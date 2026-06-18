import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '@/lib/api'
import { renderMarkdown } from '@/lib/markdown'
import type { ApiError, QueueItem, QueueState, ResultItem, StageItem, TaskPayload } from '@/lib/types'
import { useI18n } from '@/i18n/I18nContext'
import { useSettings } from '@/context/SettingsContext'
import { clampPct, translate } from '@/lib/utils'

export type ResultTab = 'script' | 'summary' | 'translation'

export interface ProgressState {
  connecting: boolean
  stageName: string
  currentStageKey: string
  mode: '' | 'subtitle' | 'whisper'
  modeLabel: string
  statusText: string
  pct: number
  subtitleMode: boolean
  detail: string
  artifacts: ResultItem[]
  stages: StageItem[]
}

export interface ResultsState {
  scriptHtml: string
  summaryHtml: string
  translationHtml: string
  showTranslation: boolean
  activeTab: ResultTab
}

const EMPTY_PROGRESS: ProgressState = {
  connecting: true, stageName: '', currentStageKey: '', mode: '', modeLabel: '', statusText: '0%',
  pct: 0, subtitleMode: false, detail: '', artifacts: [], stages: [],
}

const EMPTY_RESULTS: ResultsState = {
  scriptHtml: '', summaryHtml: '', translationHtml: '', showTranslation: false, activeTab: 'script',
}

const ALLOWED_UPLOAD_EXTS = new Set([
  '.txt', '.md', '.mp3', '.mp4', '.wav', '.m4a', '.webm', '.mkv', '.ogg', '.flac',
])
const UPLOAD_MAX_MB = 500
const TERMINAL_STATUSES = new Set<QueueItem['status']>(['completed', 'error', 'cancelled'])

// 队列快照可能乱序到达：同一队列项只能前进，不能从 processing 回退到 queued。
const STATUS_RANK: Record<string, number> = {
  queued: 0, processing: 1, completed: 2, error: 2, cancelled: 2,
}
const statusRank = (s?: string): number => STATUS_RANK[s ?? ''] ?? 0

function normLangTab(code?: string): string {
  if (!code) return ''
  const c = String(code).toLowerCase().trim()
  if (c.startsWith('zh')) return 'zh'
  if (c.length >= 2) return c.slice(0, 2)
  return c
}

const tr = translate

function resolveTaskError(t: (key: string) => unknown, task: TaskPayload): string {
  if (task.error_code) {
    const translated = tr(t, `error.${task.error_code}`)
    if (translated) return translated
  }
  if (task.message?.startsWith('error.')) {
    const translated = tr(t, task.message)
    if (translated) return translated
  }
  return task.error || tr(t, 'processing_error', 'Processing error')
}

function displayStatus(item: QueueItem): QueueItem['status'] {
  const taskStatus = item.task_status
  if (taskStatus === 'completed' || taskStatus === 'error' || taskStatus === 'cancelled' || taskStatus === 'processing') {
    return taskStatus
  }
  return item.status
}

function normalizeQueueItem(item: QueueItem): QueueItem {
  const status = displayStatus(item)
  return status === item.status ? item : { ...item, status }
}

function queueItemToTask(item: QueueItem): TaskPayload {
  return {
    task_id: item.task_id,
    status: item.task_status || item.status,
    progress: item.progress,
    progress_key: item.progress_key,
    progress_step_current: item.progress_step_current,
    progress_step_total: item.progress_step_total,
    current_stage: item.current_stage,
    mode: item.mode,
    stage_items: item.stage_items,
    result_items: item.result_items,
    error: item.error,
  }
}

/**
 * 单源模型：
 * - 队列 SSE（/queue/stream/tasks）驱动列表、唯一 processing 项和轻量进度。
 * - 详情正文（script/summary/translation）一律按需 GET /api/task/{id}。
 * - 下载页不复用这里的队列流，独立轮询 /task-status/{id}。
 */
export function useTranscribe() {
  const { t } = useI18n()
  const { twoStep, appendModelFields } = useSettings()

  // ── 队列列表状态 ──
  const [items, setItems] = useState<QueueItem[]>([])
  const [processing, setProcessing] = useState<QueueItem | null>(null)
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null) // null => 跟随处理中
  const [cancellingIds, setCancellingIds] = useState<Set<string>>(new Set())

  // ── 当前查看任务的详情视图 ──
  const [phase, setPhase] = useState<'empty' | 'progress' | 'results'>('empty')
  const [progress, setProgress] = useState<ProgressState>(EMPTY_PROGRESS)
  const [results, setResults] = useState<ResultsState>(EMPTY_RESULTS)
  const [error, setError] = useState('')

  const queueEsRef = useRef<EventSource | null>(null)
  const detailIdRef = useRef<string | null>(null)
  const partialShownRef = useRef(false)
  const detailRequestSeqRef = useRef(0)

  const displayedId = selectedTaskId ?? processing?.task_id ?? null

  const showError = useCallback((m: string) => setError(m), [])
  const dismissError = useCallback(() => setError(''), [])

  const applyQueueState = useCallback((s: QueueState) => {
    const incoming = (Array.isArray(s.items) ? s.items : []).map(normalizeQueueItem)
    const rawProcessing = s.processing ? normalizeQueueItem(s.processing) : null
    const nextProcessing = rawProcessing && !TERMINAL_STATUSES.has(rawProcessing.status) ? rawProcessing : null

    setItems((prev) => {
      const prevById = new Map(prev.map((it) => [it.id, it]))
      return incoming.map((item) => {
        const before = prevById.get(item.id)
        return before && statusRank(before.status) > statusRank(item.status) ? before : item
      })
    })
    setProcessing(nextProcessing)
  }, [])

  const refreshQueueState = useCallback(async () => {
    try {
      applyQueueState(await api.queueState('tasks'))
    } catch { /* 队列同步是兜底，失败时保留当前 UI 状态。 */ }
  }, [applyQueueState])

  const markProcessingTerminal = useCallback((taskId: string | undefined, status: QueueItem['status']) => {
    if (!taskId) return
    setItems((prev) => prev.map((item) => (
      item.task_id === taskId && item.status === 'processing' ? { ...item, status } : item
    )))
    setProcessing((current) => current?.task_id === taskId ? null : current)
  }, [])

  // ── 结果渲染 ──
  const showResults = useCallback((task: TaskPayload, preferredTab: ResultTab) => {
    const d = normLangTab(task.detected_language)
    const s = normLangTab(task.summary_language)
    const showTranslation = Boolean(task.translation) && !!d && !!s && d !== s
    setResults({
      scriptHtml: renderMarkdown(task.script),
      summaryHtml: renderMarkdown(task.summary),
      translationHtml: showTranslation ? renderMarkdown(task.translation) : '',
      showTranslation,
      activeTab: preferredTab,
    })
    setPhase('results')
  }, [])

  const showPartialSummary = useCallback((task: TaskPayload) => {
    partialShownRef.current = true
    setResults({
      scriptHtml: `<p class="muted-note">${t('transcript_pending')}</p>`,
      summaryHtml: renderMarkdown(task.summary),
      translationHtml: '',
      showTranslation: false,
      activeTab: 'summary',
    })
    setPhase('results')
  }, [t])

  const updateProgressFromTask = useCallback((task: TaskPayload) => {
    const pct = clampPct(task.progress || 0)
    const stageKey = task.current_stage || ''
    const stageName = stageKey ? tr(t, `stage.${stageKey}.label`, stageKey) : ''
    const stageDetail = stageKey ? tr(t, `stage.${stageKey}.detail`) : ''
    let statusText = ''
    const pk = task.progress_key || ''
    if (pk === 'step' && task.progress_step_current && task.progress_step_total) {
      const formatter = t('progress_step')
      statusText = typeof formatter === 'function'
        ? formatter(task.progress_step_current, task.progress_step_total)
        : `Step ${task.progress_step_current}/${task.progress_step_total}`
    } else if (pk) {
      statusText = tr(t, `progress.${pk}`)
    } else if (pct) {
      statusText = `${Math.round(pct)}%`
    }
    setProgress((p) => ({
      ...p,
      connecting: false,
      statusText,
      pct,
      stageName,
      currentStageKey: stageKey,
      detail: stageDetail,
      artifacts: Array.isArray(task.result_items) ? task.result_items : [],
      stages: Array.isArray(task.stage_items) ? task.stage_items : [],
      mode: task.mode === 'subtitle' ? 'subtitle' : task.mode === 'whisper' ? 'whisper' : p.mode,
      modeLabel: task.mode ? tr(t, `mode.${task.mode}`, task.mode) : p.modeLabel,
      subtitleMode: task.mode === 'subtitle' ? true : task.mode === 'whisper' ? false : p.subtitleMode,
    }))
  }, [t])

  const applyTaskDetail = useCallback((task: TaskPayload, preferredTab: ResultTab = 'summary') => {
    updateProgressFromTask(task)
    if (task.status === 'completed') {
      markProcessingTerminal(task.task_id, 'completed')
      if (task.task_id) setSelectedTaskId(task.task_id)
      showResults(task, partialShownRef.current ? 'summary' : preferredTab)
    } else if (task.status === 'error') {
      markProcessingTerminal(task.task_id, 'error')
      if (task.task_id) setSelectedTaskId(task.task_id)
      setPhase('empty')
      showError(resolveTaskError(t, task))
    } else if (task.status === 'cancelled') {
      markProcessingTerminal(task.task_id, 'cancelled')
      detailIdRef.current = null
      setSelectedTaskId(null)
      partialShownRef.current = false
      setPhase('empty')
    } else if (task.script) {
      showResults(task, preferredTab)
    } else if (task.summary) {
      showPartialSummary(task)
    } else {
      setPhase('progress')
    }
  }, [markProcessingTerminal, showError, showPartialSummary, showResults, t, updateProgressFromTask])

  const fetchTaskDetail = useCallback(async (taskId: string, preferredTab: ResultTab = 'summary') => {
    const seq = ++detailRequestSeqRef.current
    try {
      const task = await api.taskDetail(taskId)
      if (seq !== detailRequestSeqRef.current || detailIdRef.current !== taskId) return
      applyTaskDetail(task, preferredTab)
    } catch (err) {
      if (detailIdRef.current === taskId) {
        showError((err as ApiError).detail || (t('request_failed') as string))
      }
    }
  }, [applyTaskDetail, showError, t])

  // ── 队列 SSE：唯一实时状态源 ──
  useEffect(() => {
    let stopped = false
    const apply = (s: QueueState) => {
      if (stopped) return
      applyQueueState(s)
    }
    api.queueState('tasks').then(apply).catch(() => {})
    const es = new EventSource(api.queueStreamUrl('tasks'))
    queueEsRef.current = es
    es.onmessage = (ev) => {
      try {
        const data = JSON.parse(ev.data)
        if (data?.type === 'heartbeat') return
        apply(data as QueueState)
      } catch { /* ignore malformed frames */ }
    }
    return () => {
      stopped = true
      es.close()
      queueEsRef.current = null
    }
  }, [applyQueueState])

  // ── 详情 REST：切换查看任务时拉一次完整正文 ──
  useEffect(() => {
    if (!displayedId) {
      detailIdRef.current = null
      partialShownRef.current = false
      setPhase('empty')
      return
    }
    if (displayedId === detailIdRef.current) return

    const keepDetailMounted = phase !== 'empty'
    detailIdRef.current = displayedId
    partialShownRef.current = false
    setError('')
    if (!keepDetailMounted) {
      setProgress(EMPTY_PROGRESS)
      setResults(EMPTY_RESULTS)
      setPhase('progress')
    } else if (phase === 'progress') {
      setProgress(EMPTY_PROGRESS)
    }
    void fetchTaskDetail(displayedId)
  }, [displayedId, fetchTaskDetail, phase])

  // ── 运行中详情：队列 processing 项负责进度；ready/终态翻转时按需拉正文 ──
  useEffect(() => {
    if (!displayedId || !processing || processing.task_id !== displayedId) return
    updateProgressFromTask(queueItemToTask(processing))

    const status = processing.task_status || processing.status
    if (status === 'completed') {
      setSelectedTaskId(displayedId)
      void fetchTaskDetail(displayedId, 'summary')
      return
    }
    if (status === 'error' || status === 'cancelled') {
      setSelectedTaskId(displayedId)
      void fetchTaskDetail(displayedId)
      return
    }
    if (processing.transcript_ready) {
      void fetchTaskDetail(displayedId, 'summary')
    } else if (processing.summary_ready && !partialShownRef.current) {
      void fetchTaskDetail(displayedId, 'summary')
    }
  }, [displayedId, fetchTaskDetail, processing, updateProgressFromTask])

  // ── 提交：仅入队，列表由队列 SSE 自动反映 ──
  const buildFormData = useCallback((url: string): FormData => {
    const fd = new FormData()
    fd.append('url', url || '')
    appendModelFields(fd)
    return fd
  }, [appendModelFields])

  const enqueueUrl = useCallback(async (url: string) => {
    const trimmed = url.trim()
    if (!trimmed) {
      showError(t('error_invalid_url') as string)
      return false
    }
    try {
      await api.processVideo(buildFormData(trimmed))
      void refreshQueueState()
      setSelectedTaskId(null)
      return true
    } catch (err) {
      showError((t('error_processing_failed') as string) + ((err as ApiError).detail || (t('request_failed') as string)))
      return false
    }
  }, [buildFormData, refreshQueueState, showError, t])

  const enqueueFile = useCallback(async (file: File) => {
    const parts = (file.name || '').split('.')
    const ext = parts.length > 1 ? '.' + (parts.pop() as string).toLowerCase() : ''
    if (!ALLOWED_UPLOAD_EXTS.has(ext)) {
      showError(t('error_upload_type') as string)
      return false
    }
    if (!file.size) {
      showError(t('error_upload_empty') as string)
      return false
    }
    if (file.size > UPLOAD_MAX_MB * 1024 * 1024) {
      showError((t('error_upload_size') as (mb: number) => string)(UPLOAD_MAX_MB))
      return false
    }
    try {
      const fd = buildFormData('')
      fd.append('file', file, file.name)
      await api.processVideo(fd)
      void refreshQueueState()
      setSelectedTaskId(null)
      return true
    } catch (err) {
      showError((t('error_processing_failed') as string) + ((err as ApiError).detail || (t('request_failed') as string)))
      return false
    }
  }, [buildFormData, refreshQueueState, showError, t])

  // ── 选择 / 跟随 ──
  const selectItem = useCallback((item: QueueItem) => {
    if (!item.task_id) return
    setSelectedTaskId(item.task_id)
  }, [])

  const followLive = useCallback(() => setSelectedTaskId(null), [])

  // ── 队列项操作 ──
  const cancelItem = useCallback(async (item: QueueItem) => {
    setCancellingIds((prev) => (prev.has(item.id) ? prev : new Set(prev).add(item.id)))
    try {
      await api.queueCancel(item.id, 'tasks')
    } catch (err) {
      showError((t('error_processing_failed') as string) + ((err as ApiError).detail || ''))
    } finally {
      setCancellingIds((prev) => {
        if (!prev.has(item.id)) return prev
        const next = new Set(prev)
        next.delete(item.id)
        return next
      })
    }
    if (selectedTaskId && selectedTaskId === item.task_id) setSelectedTaskId(null)
  }, [selectedTaskId, showError, t])

  const removeItem = useCallback(async (item: QueueItem) => {
    try {
      await api.queueRemoveItem(item.id, 'tasks')
    } catch { /* ignore */ }
    if (selectedTaskId && selectedTaskId === item.task_id) setSelectedTaskId(null)
  }, [selectedTaskId])

  const clearCompleted = useCallback(async () => {
    const shouldResetDetail = Boolean(
      selectedTaskId && items.some((item) => item.task_id === selectedTaskId && TERMINAL_STATUSES.has(item.status))
    )
    try {
      await api.queueClear('tasks')
      if (shouldResetDetail) {
        detailIdRef.current = null
        partialShownRef.current = false
        setSelectedTaskId(null)
        setProgress(EMPTY_PROGRESS)
        setResults(EMPTY_RESULTS)
        setError('')
        setPhase('empty')
      }
      void refreshQueueState()
    } catch { /* ignore */ }
  }, [items, refreshQueueState, selectedTaskId])

  // ── 重试 / 导出 / 切页 ──
  const retryTranscription = useCallback(async () => {
    if (!displayedId) {
      showError(t('processing_error') as string)
      return
    }
    try {
      const fd = buildFormData('')
      fd.append('use_two_step', twoStep ? 'true' : 'false')
      const data = await api.retry(displayedId, fd)
      const nextTaskId = data.task_id || displayedId
      detailIdRef.current = nextTaskId
      partialShownRef.current = false
      setProgress(EMPTY_PROGRESS)
      setResults(EMPTY_RESULTS)
      setError('')
      setPhase('progress')
      if (data.task_id) setSelectedTaskId(data.task_id)
      void refreshQueueState()
    } catch (err) {
      showError((t('error_processing_failed') as string) + ((err as ApiError).detail || (t('request_failed') as string)))
    }
  }, [buildFormData, displayedId, refreshQueueState, showError, t, twoStep])

  const setActiveTab = useCallback((tab: ResultTab) => {
    setResults((r) => ({ ...r, activeTab: tab }))
  }, [])

  const exportContent = useCallback(async () => {
    if (!displayedId) {
      showError(t('error_no_download') as string)
      return
    }
    const typeMap: Record<ResultTab, string> = { script: 'transcript', summary: 'summary', translation: 'translation' }
    const content_type = typeMap[results.activeTab] || 'transcript'
    try {
      const fd = new FormData()
      fd.append('task_id', displayedId)
      fd.append('content_type', content_type)
      fd.append('export_format', 'markdown')
      fd.append('include_timestamps', 'false')
      fd.append('include_header', 'false')
      const resp = await fetch('/api/export', { method: 'POST', body: fd })
      if (!resp.ok) {
        let detail = ''
        try { detail = (await resp.json()).detail || '' } catch { /* ignore */ }
        throw new Error(detail || resp.statusText)
      }
      const blob = await resp.blob()
      const disposition = resp.headers.get('Content-Disposition')
      let filename: string | null = null
      if (disposition) {
        const m = disposition.match(/filename\*=UTF-8''([^;]+)/i)
        if (m) {
          try { filename = decodeURIComponent(m[1]) } catch { filename = m[1] }
        } else {
          const m2 = disposition.match(/filename="?([^";]+)"?/i)
          if (m2) filename = m2[1]
        }
      }
      if (!filename) filename = 'export.md'
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = filename
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)
    } catch (e) {
      showError((t('export_error') as string) + (e as Error).message)
    }
  }, [displayedId, results.activeTab, showError, t])

  const [sendingTelegram, setSendingTelegram] = useState(false)

  const sendToTelegram = useCallback(async () => {
    if (!displayedId) {
      showError(t('error_no_download') as string)
      return false
    }
    const typeMap: Record<ResultTab, string> = { script: 'transcript', summary: 'summary', translation: 'translation' }
    const content_type = typeMap[results.activeTab] || 'transcript'
    setSendingTelegram(true)
    try {
      await api.botsSendTelegram(displayedId, content_type)
      return true
    } catch (e) {
      showError((t('bot_send_error') as string) + (e as Error).message)
      return false
    } finally {
      setSendingTelegram(false)
    }
  }, [displayedId, results.activeTab, showError, t])

  useEffect(() => () => {
    if (queueEsRef.current) queueEsRef.current.close()
  }, [])

  return {
    // 队列列表
    items, processing, displayedTaskId: displayedId, isProcessing: Boolean(processing), cancellingIds,
    // 详情视图
    phase, progress, results, error,
    // 操作
    enqueueUrl, enqueueFile, selectItem, followLive,
    cancelItem, removeItem, clearCompleted,
    retryTranscription, exportContent, setActiveTab, dismissError,
    sendToTelegram, sendingTelegram,
  }
}
