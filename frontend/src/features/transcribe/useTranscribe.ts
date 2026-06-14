import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '@/lib/api'
import { renderMarkdown } from '@/lib/markdown'
import type { ApiError, QueueItem, QueueState, ResultItem, StageItem, TaskPayload } from '@/lib/types'
import { useI18n } from '@/i18n/I18nContext'
import { useSettings } from '@/context/SettingsContext'

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

// 队列状态优先级（单调性守卫用）：快照只能让某项前进，不能后退。
// REST 快照与队列 SSE 各自捕获不同时刻的 DB 状态、到达顺序不保证，晚到的
// queued 快照不得覆盖已到的 processing。终态由 terminalTaskStatusRef 单独兜住。
const STATUS_RANK: Record<string, number> = {
  queued: 0, processing: 1, completed: 2, error: 2, cancelled: 2,
}
const statusRank = (s?: string): number => STATUS_RANK[s ?? ''] ?? 0

function clampPct(value: unknown): number {
  const n = Number(value)
  if (!Number.isFinite(n)) return 0
  return Math.max(0, Math.min(100, n))
}

function normLangTab(code?: string): string {
  if (!code) return ''
  const c = String(code).toLowerCase().trim()
  if (c.startsWith('zh')) return 'zh'
  if (c.length >= 2) return c.slice(0, 2)
  return c
}

function tr(t: (key: string) => unknown, key: string, fallback = ''): string {
  if (!key) return fallback
  const value = t(key)
  return typeof value === 'string' && value !== key ? value : fallback
}

function resolveTaskError(t: (key: string) => unknown, task: TaskPayload): string {
  if (task.error_code) {
    const translated = tr(t, `error.${task.error_code}`)
    if (translated) return translated
  }
  if (task.message?.startsWith('error.')) {
    const translated = tr(t, task.message)
    if (translated) return translated
  }
  return tr(t, 'processing_error', 'Processing error')
}

/**
 * 统一队列模型：
 * - 队列 SSE（/queue/stream/tasks）驱动整张列表的成员与状态（live 刷新）。
 * - 任务 SSE（/task-stream/{id}）驱动「当前查看任务」的实时进度与结果。
 *   serial 策略下同一时刻只有一个任务在跑，故只需一条任务 SSE。
 * - 「当前查看任务」= 用户手动选中的项；未选中时自动跟随正在处理的项。
 */
export function useTranscribe() {
  const { t } = useI18n()
  const { twoStep, appendModelFields } = useSettings()

  // ── 队列列表状态 ──
  const [items, setItems] = useState<QueueItem[]>([])
  const [processing, setProcessing] = useState<QueueItem | null>(null)
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null) // null => 跟随处理中
  const [cancellingIds, setCancellingIds] = useState<Set<string>>(new Set()) // 正在等待后端确认取消的队列项 id

  // ── 当前查看任务的详情视图 ──
  const [phase, setPhase] = useState<'empty' | 'progress' | 'results'>('empty')
  const [progress, setProgress] = useState<ProgressState>(EMPTY_PROGRESS)
  const [results, setResults] = useState<ResultsState>(EMPTY_RESULTS)
  const [error, setError] = useState('')

  const queueEsRef = useRef<EventSource | null>(null)
  const taskEsRef = useRef<EventSource | null>(null)
  const detailIdRef = useRef<string | null>(null)
  const partialShownRef = useRef(false)
  const terminalTaskStatusRef = useRef<Record<string, QueueItem['status']>>({})

  const displayedId = selectedTaskId ?? processing?.task_id ?? null

  const showError = useCallback((m: string) => setError(m), [])
  const dismissError = useCallback(() => setError(''), [])

  const applyQueueState = useCallback((s: QueueState) => {
    const terminalStatuses = terminalTaskStatusRef.current
    const incoming = (Array.isArray(s.items) ? s.items : []).map((item) => {
      const terminalStatus = terminalStatuses[item.task_id]
      return terminalStatus && item.status !== terminalStatus
        ? { ...item, status: terminalStatus }
        : item
    })
    const nextProcessing = s.processing?.task_id && terminalStatuses[s.processing.task_id]
      ? null
      : s.processing || null
    // 单调性守卫：用上一帧同一项的状态兜底，不让晚到的旧快照把 processing 降回 queued。
    setItems((prev) => {
      const prevByTask = new Map(prev.map((it) => [it.task_id, it]))
      return incoming.map((item) => {
        const before = prevByTask.get(item.task_id)
        return before && statusRank(before.status) > statusRank(item.status)
          ? { ...item, status: before.status }
          : item
      })
    })
    setProcessing(nextProcessing)
  }, [])

  const refreshQueueState = useCallback(async () => {
    try {
      applyQueueState(await api.queueState('tasks'))
    } catch { /* 队列同步是兜底，失败时保留当前 UI 状态。 */ }
  }, [applyQueueState])

  const markQueueItemTerminal = useCallback((taskId: string | undefined, status: QueueItem['status']) => {
    if (!taskId) return
    terminalTaskStatusRef.current[taskId] = status
    setItems((prev) => prev.map((item) => (
      item.task_id === taskId ? { ...item, status } : item
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
    // Resolve progress text
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

  // 用 ref 持有最新的消息处理逻辑，使详情 SSE 的 effect 只依赖 displayedId
  // （避免回调身份变化导致反复重连）。ref 在 effect 里更新，不在 render 期写入。
  const onTaskMessageRef = useRef<(task: TaskPayload) => void>(() => {})
  useEffect(() => {
    onTaskMessageRef.current = (task: TaskPayload) => {
      updateProgressFromTask(task)
      if (task.status === 'processing' && task.summary && !partialShownRef.current) {
        showPartialSummary(task)
      }
      if (task.status === 'completed') {
        markQueueItemTerminal(task.task_id, 'completed')
        void refreshQueueState()
        if (taskEsRef.current) { taskEsRef.current.close(); taskEsRef.current = null }
        // 钉住已完成项，使其离开 processing 后仍保持展示。
        if (task.task_id) setSelectedTaskId(task.task_id)
        showResults(task, partialShownRef.current ? 'summary' : 'script')
      } else if (task.status === 'error') {
        markQueueItemTerminal(task.task_id, 'error')
        void refreshQueueState()
        if (taskEsRef.current) { taskEsRef.current.close(); taskEsRef.current = null }
        if (task.task_id) setSelectedTaskId(task.task_id)
        setPhase('empty')
        showError(resolveTaskError(t, task))
      } else if (task.status === 'cancelled') {
        markQueueItemTerminal(task.task_id, 'cancelled')
        void refreshQueueState()
        if (taskEsRef.current) { taskEsRef.current.close(); taskEsRef.current = null }
        detailIdRef.current = null
        setSelectedTaskId(null)
        partialShownRef.current = false
      }
    }
  })

  // ── 队列 SSE：驱动整张列表 ──
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

  // ── 详情任务 SSE：跟随 displayedId ──
  useEffect(() => {
    if (!displayedId) {
      if (taskEsRef.current) { taskEsRef.current.close(); taskEsRef.current = null }
      detailIdRef.current = null
      setPhase('empty')
      return
    }
    if (displayedId === detailIdRef.current) return

    if (taskEsRef.current) { taskEsRef.current.close(); taskEsRef.current = null }
    detailIdRef.current = displayedId
    partialShownRef.current = false
    setProgress(EMPTY_PROGRESS)
    setResults(EMPTY_RESULTS)
    setError('')
    setPhase('progress')

    const es = new EventSource(api.streamUrl(displayedId))
    taskEsRef.current = es
    es.onmessage = (ev) => {
      try {
        const task = JSON.parse(ev.data) as TaskPayload
        if (task.type === 'heartbeat') return
        onTaskMessageRef.current(task)
      } catch { /* ignore */ }
    }
    es.onerror = async () => {
      // 断连兜底：拉一次最终状态，若已完成则直接展示。
      if (taskEsRef.current) { taskEsRef.current.close(); taskEsRef.current = null }
      try {
        const task = await api.taskStatus(displayedId)
        if (['completed', 'error', 'cancelled'].includes(task?.status || '')) {
          onTaskMessageRef.current(task)
          return
        }
      } catch { /* fall through */ }
    }
  }, [displayedId, showResults])

  useEffect(() => {
    if (!displayedId || terminalTaskStatusRef.current[displayedId]) return
    const timer = window.setInterval(async () => {
      if (terminalTaskStatusRef.current[displayedId]) {
        window.clearInterval(timer)
        return
      }
      try {
        const task = await api.taskStatus(displayedId)
        if (['completed', 'error', 'cancelled'].includes(task?.status || '')) {
          onTaskMessageRef.current(task)
        }
      } catch { /* SSE 仍是主路径，轮询只做静默兜底。 */ }
    }, 5000)
    return () => window.clearInterval(timer)
  }, [displayedId])

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
      // 入队后主动拉取队列状态，弥补 SSE 连接延迟/代理缓冲等导致的失序
      void refreshQueueState()
      setSelectedTaskId(null) // 跟随处理中
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
      // 入队后主动拉取队列状态，弥补 SSE 连接延迟/代理缓冲等导致的失序
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
  // 取消处理中的任务时后端会等 pipeline 真正停掉（Whisper 段边界）才返回，可能耗时，
  // 故标记「取消中」让 UI 给出反馈、并防止重复点击。
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
        if (taskEsRef.current) { taskEsRef.current.close(); taskEsRef.current = null }
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
      if (data.task_id) setSelectedTaskId(data.task_id)
    } catch (err) {
      showError((t('error_processing_failed') as string) + ((err as ApiError).detail || (t('request_failed') as string)))
    }
  }, [buildFormData, displayedId, showError, t, twoStep])

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

  // 卸载清理。
  useEffect(() => () => {
    if (queueEsRef.current) queueEsRef.current.close()
    if (taskEsRef.current) taskEsRef.current.close()
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
  }
}
