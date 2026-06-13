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
  connecting: true, stageName: '', mode: '', modeLabel: '', statusText: '0%',
  pct: 0, subtitleMode: false, detail: '', artifacts: [], stages: [],
}

const EMPTY_RESULTS: ResultsState = {
  scriptHtml: '', summaryHtml: '', translationHtml: '', showTranslation: false, activeTab: 'script',
}

const ALLOWED_UPLOAD_EXTS = new Set([
  '.txt', '.md', '.mp3', '.mp4', '.wav', '.m4a', '.webm', '.mkv', '.ogg', '.flac',
])
const UPLOAD_MAX_MB = 500

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

  // ── 当前查看任务的详情视图 ──
  const [phase, setPhase] = useState<'empty' | 'progress' | 'results'>('empty')
  const [progress, setProgress] = useState<ProgressState>(EMPTY_PROGRESS)
  const [results, setResults] = useState<ResultsState>(EMPTY_RESULTS)
  const [error, setError] = useState('')

  const queueEsRef = useRef<EventSource | null>(null)
  const taskEsRef = useRef<EventSource | null>(null)
  const detailIdRef = useRef<string | null>(null)
  const partialShownRef = useRef(false)

  const displayedId = selectedTaskId ?? processing?.task_id ?? null

  const showError = useCallback((m: string) => setError(m), [])
  const dismissError = useCallback(() => setError(''), [])

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
    const stageName = task.current_stage_label || task.message || ''
    const stageDetail = task.current_stage_detail || task.message || stageName
    setProgress((p) => ({
      ...p,
      connecting: false,
      statusText: task.progress_label || (pct ? `${Math.round(pct)}%` : ''),
      pct,
      stageName,
      detail: stageDetail,
      artifacts: Array.isArray(task.result_items) ? task.result_items : [],
      stages: Array.isArray(task.stage_items) ? task.stage_items : [],
      mode: task.mode === 'subtitle' ? 'subtitle' : task.mode === 'whisper' ? 'whisper' : p.mode,
      modeLabel: task.mode === 'subtitle' || task.mode === 'whisper' ? task.mode_label || '' : p.modeLabel,
      subtitleMode: task.mode === 'subtitle' ? true : task.mode === 'whisper' ? false : p.subtitleMode,
    }))
  }, [])

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
        if (taskEsRef.current) { taskEsRef.current.close(); taskEsRef.current = null }
        // 钉住已完成项，使其离开 processing 后仍保持展示。
        if (task.task_id) setSelectedTaskId(task.task_id)
        showResults(task, partialShownRef.current ? 'summary' : 'script')
      } else if (task.status === 'error') {
        if (taskEsRef.current) { taskEsRef.current.close(); taskEsRef.current = null }
        if (task.task_id) setSelectedTaskId(task.task_id)
        showError(task.error || (t('processing_error') as string))
      } else if (task.status === 'cancelled') {
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
      setItems(Array.isArray(s.items) ? s.items : [])
      setProcessing(s.processing || null)
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
  }, [])

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
        if (task?.status === 'completed') {
          showResults(task, partialShownRef.current ? 'summary' : 'script')
          return
        }
      } catch { /* fall through */ }
    }
  }, [displayedId, showResults])

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
      setSelectedTaskId(null) // 跟随处理中
      return true
    } catch (err) {
      showError((t('error_processing_failed') as string) + ((err as ApiError).detail || (t('request_failed') as string)))
      return false
    }
  }, [buildFormData, showError, t])

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
      setSelectedTaskId(null)
      return true
    } catch (err) {
      showError((t('error_processing_failed') as string) + ((err as ApiError).detail || (t('request_failed') as string)))
      return false
    }
  }, [buildFormData, showError, t])

  // ── 选择 / 跟随 ──
  const selectItem = useCallback((item: QueueItem) => {
    if (!item.task_id) return
    setSelectedTaskId(item.task_id)
  }, [])

  const followLive = useCallback(() => setSelectedTaskId(null), [])

  // ── 队列项操作 ──
  const cancelItem = useCallback(async (item: QueueItem) => {
    try {
      await api.queueCancel(item.id, 'tasks')
    } catch (err) {
      showError((t('error_processing_failed') as string) + ((err as ApiError).detail || ''))
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
    try {
      await api.queueClear('tasks')
    } catch { /* ignore */ }
  }, [])

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
    items, processing, displayedTaskId: displayedId, isProcessing: Boolean(processing),
    // 详情视图
    phase, progress, results, error,
    // 操作
    enqueueUrl, enqueueFile, selectItem, followLive,
    cancelItem, removeItem, clearCompleted,
    retryTranscription, exportContent, setActiveTab, dismissError,
  }
}
