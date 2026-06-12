import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '@/lib/api'
import { renderMarkdown } from '@/lib/markdown'
import { historyAdd } from '@/lib/db'
import type { ApiError, ResultItem, SourceDescriptor, StageItem, TaskPayload } from '@/lib/types'
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

const SP_SPEEDS: Record<string, number> = {
  subtitle: 0.5, parsing: 0.3, downloading: 0.18, transcribing: 0.14, optimizing: 0.22, summarizing: 0.28,
}

export function useTranscribe() {
  const { t } = useI18n()
  const { twoStep, appendModelFields } = useSettings()

  const [phase, setPhase] = useState<'empty' | 'progress' | 'results'>('empty')
  const [isProcessing, setIsProcessing] = useState(false)
  const [progress, setProgress] = useState<ProgressState>(EMPTY_PROGRESS)
  const [results, setResults] = useState<ResultsState>({
    scriptHtml: '', summaryHtml: '', translationHtml: '', showTranslation: false, activeTab: 'script',
  })
  const [error, setError] = useState('')

  const taskIdRef = useRef<string | null>(null)
  const sourceRef = useRef<SourceDescriptor>({ type: 'url', value: '', title: '' })
  const esRef = useRef<EventSource | null>(null)
  const partialShownRef = useRef(false)

  /* ── Smart progress simulation ── */
  const sp = useRef({ enabled: false, current: 0, target: 15, stage: 'preparing', interval: 0 as number | 0 })

  const showError = useCallback((m: string) => setError(m), [])

  const initSP = useCallback(() => {
    sp.current.enabled = false
    sp.current.current = 0
    sp.current.target = 15
    sp.current.stage = 'preparing'
  }, [])

  const stopSP = useCallback(() => {
    if (sp.current.interval) {
      clearInterval(sp.current.interval)
      sp.current.interval = 0
    }
    sp.current.enabled = false
  }, [])

  const startSP = useCallback(() => {
    if (sp.current.interval) clearInterval(sp.current.interval)
    sp.current.enabled = true
    sp.current.interval = window.setInterval(() => {
      const s = sp.current
      if (!s.enabled || s.current >= s.target) return
      let inc = SP_SPEEDS[s.stage] || 0.2
      const remaining = s.target - s.current
      if (remaining < 5) inc *= 0.3
      const next = Math.min(s.current + inc, s.target)
      if (next > s.current) {
        s.current = next
        const pct = clampPct(next)
        setProgress((p) => ({ ...p, statusText: Math.round(pct) + '%', pct }))
      }
    }, 500)
  }, [])

  const stopSSE = useCallback(() => {
    if (esRef.current) {
      esRef.current.close()
      esRef.current = null
    }
  }, [])

  const showResults = useCallback(
    (task: TaskPayload, preferredTab: ResultTab) => {
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
      /* Persist summary to history (best-effort). */
      const text = (task.summary || '').trim()
      if (text) {
        const source = sourceRef.current
        const title = (task.video_title || source.title || (t('unnamed_summary') as string)).trim()
        const item = {
          id: taskIdRef.current || `summary_${Date.now()}`,
          taskId: taskIdRef.current || '',
          title,
          sourceType: source.type || 'url',
          source: source.value || '',
          summary: text,
          summaryLang: task.summary_language || '',
          createdAt: new Date().toISOString(),
        }
        historyAdd(item).catch((e: { name?: string }) => {
          if (e?.name !== 'ConstraintError') console.warn('Failed to save summary history', e)
        })
      }
    },
    [t],
  )

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
    stopSP()
    const pct = clampPct(task.progress || 0)
    const stageName = task.current_stage_label || task.message || ''
    const stageDetail = task.current_stage_detail || task.message || stageName
    setProgress((p) => ({
      ...p,
      connecting: false,
      statusText: task.progress_label || '',
      pct,
      stageName,
      detail: stageDetail,
      artifacts: Array.isArray(task.result_items) ? task.result_items : [],
      stages: Array.isArray(task.stage_items) ? task.stage_items : [],
      mode: task.mode === 'subtitle' ? 'subtitle' : task.mode === 'whisper' ? 'whisper' : p.mode,
      modeLabel: task.mode === 'subtitle' || task.mode === 'whisper' ? task.mode_label || '' : p.modeLabel,
      subtitleMode: task.mode === 'subtitle' ? true : task.mode === 'whisper' ? false : p.subtitleMode,
    }))
  }, [stopSP])

  const startSSE = useCallback(() => {
    const taskId = taskIdRef.current
    if (!taskId) return
    stopSSE()
    const es = new EventSource(api.streamUrl(taskId))
    esRef.current = es
    es.onmessage = (ev) => {
      try {
        const task = JSON.parse(ev.data) as TaskPayload
        if (task.type === 'heartbeat') return
        updateProgressFromTask(task)
        if (task.status === 'processing' && task.summary && !partialShownRef.current) {
          showPartialSummary(task)
        }
        if (task.status === 'completed') {
          stopSP(); stopSSE(); setIsProcessing(false)
          showResults(task, partialShownRef.current ? 'summary' : 'script')
        } else if (task.status === 'error') {
          stopSP(); stopSSE(); setIsProcessing(false); setPhase('empty')
          showError(task.error || (t('processing_error') as string))
        } else if (task.status === 'cancelled') {
          stopSP(); stopSSE(); setIsProcessing(false); setPhase('empty')
          partialShownRef.current = false
        }
      } catch {
        /* ignore malformed frames */
      }
    }
    es.onerror = async () => {
      stopSSE()
      try {
        if (taskIdRef.current) {
          const task = await api.taskStatus(taskIdRef.current)
          if (task?.status === 'completed') {
            stopSP(); setIsProcessing(false)
            showResults(task, partialShownRef.current ? 'summary' : 'script')
            return
          }
        }
      } catch {
        /* fall through to error */
      }
      showError((t('error_processing_failed') as string) + (t('sse_disconnected') as string))
      setIsProcessing(false)
    }
  }, [showError, showPartialSummary, showResults, stopSP, stopSSE, t, updateProgressFromTask])

  const beginProgress = useCallback(() => {
    setError('')
    setProgress(EMPTY_PROGRESS)
    setPhase('progress')
    setIsProcessing(true)
    initSP()
    startSP()
  }, [initSP, startSP])

  const buildFormData = useCallback(
    (url: string): FormData => {
      const fd = new FormData()
      fd.append('url', url || '')
      appendModelFields(fd)
      return fd
    },
    [appendModelFields],
  )

  const startTranscription = useCallback(
    async (url: string) => {
      if (isProcessing) {
        await cancelTask()
        return
      }
      const trimmed = url.trim()
      if (!trimmed) {
        showError(t('error_invalid_url') as string)
        return
      }
      sourceRef.current = { type: 'url', value: trimmed, title: '' }
      partialShownRef.current = false
      beginProgress()
      try {
        const data = await api.processVideo(buildFormData(trimmed))
        taskIdRef.current = data.task_id
        startSSE()
      } catch (err) {
        showError((t('error_processing_failed') as string) + ((err as ApiError).detail || (t('request_failed') as string)))
        setIsProcessing(false)
        setPhase('empty')
      }
    },
    [beginProgress, buildFormData, isProcessing, showError, startSSE, t],
  )

  const startFileUpload = useCallback(
    async (file: File) => {
      if (isProcessing) return
      const parts = (file.name || '').split('.')
      const ext = parts.length > 1 ? '.' + (parts.pop() as string).toLowerCase() : ''
      if (!ALLOWED_UPLOAD_EXTS.has(ext)) {
        showError(t('error_upload_type') as string)
        return
      }
      if (!file.size) {
        showError(t('error_upload_empty') as string)
        return
      }
      if (file.size > UPLOAD_MAX_MB * 1024 * 1024) {
        showError((t('error_upload_size') as (mb: number) => string)(UPLOAD_MAX_MB))
        return
      }
      sourceRef.current = { type: 'file', value: file.name || '', title: file.name || '' }
      partialShownRef.current = false
      beginProgress()
      try {
        const fd = buildFormData('')
        fd.append('file', file, file.name)
        const data = await api.processVideo(fd)
        taskIdRef.current = data.task_id
        startSSE()
      } catch (err) {
        showError((t('error_processing_failed') as string) + ((err as ApiError).detail || (t('request_failed') as string)))
        setIsProcessing(false)
        setPhase('empty')
      }
    },
    [beginProgress, buildFormData, isProcessing, showError, startSSE, t],
  )

  const cancelTask = useCallback(async () => {
    const taskId = taskIdRef.current
    if (!taskId) {
      setIsProcessing(false)
      setPhase('empty')
      return
    }
    taskIdRef.current = null
    stopSP()
    try {
      await api.deleteTask(taskId)
    } catch {
      /* ignore */
    }
    stopSSE()
    setIsProcessing(false)
    setPhase('empty')
    partialShownRef.current = false
  }, [stopSP, stopSSE])

  const retryTranscription = useCallback(async () => {
    if (!taskIdRef.current) {
      showError(t('processing_error') as string)
      return
    }
    if (isProcessing) return
    beginProgress()
    try {
      const fd = buildFormData('')
      fd.append('use_two_step', twoStep ? 'true' : 'false')
      const data = await api.retry(taskIdRef.current, fd)
      taskIdRef.current = data.task_id
      partialShownRef.current = false
      startSSE()
    } catch (err) {
      showError((t('error_processing_failed') as string) + ((err as ApiError).detail || (t('request_failed') as string)))
      setIsProcessing(false)
      setPhase('empty')
    }
  }, [beginProgress, buildFormData, isProcessing, showError, startSSE, t, twoStep])

  /* RSS page hands off a created task to the transcribe view. */
  const adoptRssTask = useCallback(
    (taskId: string, source: SourceDescriptor) => {
      sourceRef.current = source
      taskIdRef.current = taskId
      partialShownRef.current = false
      beginProgress()
      startSSE()
    },
    [beginProgress, startSSE],
  )

  const setActiveTab = useCallback((tab: ResultTab) => {
    setResults((r) => ({ ...r, activeTab: tab }))
  }, [])

  const exportContent = useCallback(async () => {
    if (!taskIdRef.current) {
      showError(t('error_no_download') as string)
      return
    }
    const typeMap: Record<ResultTab, string> = { script: 'transcript', summary: 'summary', translation: 'translation' }
    const content_type = typeMap[results.activeTab] || 'transcript'
    try {
      const fd = new FormData()
      fd.append('task_id', taskIdRef.current)
      fd.append('content_type', content_type)
      fd.append('export_format', 'markdown')
      fd.append('include_timestamps', 'false')
      fd.append('include_header', 'false')
      const resp = await fetch('/api/export', { method: 'POST', body: fd })
      if (!resp.ok) {
        let detail = ''
        try {
          detail = (await resp.json()).detail || ''
        } catch {
          /* ignore */
        }
        throw new Error(detail || resp.statusText)
      }
      const blob = await resp.blob()
      const disposition = resp.headers.get('Content-Disposition')
      let filename: string | null = null
      if (disposition) {
        const m = disposition.match(/filename\*=UTF-8''([^;]+)/i)
        if (m) {
          try {
            filename = decodeURIComponent(m[1])
          } catch {
            filename = m[1]
          }
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
  }, [results.activeTab, showError, t])

  /* Cleanup on unmount. */
  useEffect(() => () => {
    stopSP()
    stopSSE()
  }, [stopSP, stopSSE])

  return {
    phase, isProcessing, progress, results, error,
    startTranscription, startFileUpload, cancelTask, retryTranscription,
    adoptRssTask, setActiveTab, exportContent, dismissError: () => setError(''),
  }
}
