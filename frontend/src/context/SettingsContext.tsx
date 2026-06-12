import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { api } from '@/lib/api'
import type { ModelInfo } from '@/lib/types'
import { useI18n } from '@/i18n/I18nContext'

export interface FetchStatus {
  cls: '' | 'ok' | 'err'
  msg: string
}

interface SettingsValue {
  baseUrl: string
  apiKey: string
  model: string
  summaryLang: string
  twoStep: boolean
  models: ModelInfo[]
  fetchStatus: FetchStatus
  whisperReady: boolean
  whisperError: string | null
  configured: boolean
  setBaseUrl: (v: string) => void
  setApiKey: (v: string) => void
  setModel: (v: string) => void
  setSummaryLang: (v: string) => void
  setTwoStep: (v: boolean) => void
  fetchModels: (silent?: boolean) => Promise<void>
  refreshInterfaceStatus: () => Promise<void>
  /* Appends the standard model/auth fields to a FormData, matching
     the original _buildFormData / _rssCreateTask behavior. */
  appendModelFields: (fd: FormData) => void
}

const SettingsContext = createContext<SettingsValue | null>(null)

const STORAGE_KEY = 'vt_settings'

interface Persisted {
  baseUrl?: string
  apiKey?: string
  model?: string
  summaryLang?: string
  useTwoStep?: boolean
  models?: ModelInfo[]
}

function loadPersisted(): Persisted {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return raw ? (JSON.parse(raw) as Persisted) : {}
  } catch {
    return {}
  }
}

export function SettingsProvider({ children }: { children: ReactNode }) {
  const { t } = useI18n()
  const persisted = useRef<Persisted>(loadPersisted())

  const [baseUrl, setBaseUrl] = useState(persisted.current.baseUrl || '')
  const [apiKey, setApiKey] = useState(persisted.current.apiKey || '')
  const [model, setModel] = useState(persisted.current.model || '')
  const [summaryLang, setSummaryLang] = useState(persisted.current.summaryLang || 'en')
  const [twoStep, setTwoStep] = useState(
    persisted.current.useTwoStep !== undefined ? persisted.current.useTwoStep : true,
  )
  const [models, setModels] = useState<ModelInfo[]>(persisted.current.models || [])
  const [fetchStatus, setFetchStatus] = useState<FetchStatus>({ cls: '', msg: '' })
  const [whisperReady, setWhisperReady] = useState(false)
  const [whisperError, setWhisperError] = useState<string | null>(null)

  const configured = Boolean(apiKey.trim() && baseUrl.trim())

  /* Persist settings whenever they change. */
  useEffect(() => {
    const s: Persisted = { baseUrl, apiKey, model, summaryLang, useTwoStep: twoStep, models }
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(s))
    } catch {
      /* ignore */
    }
  }, [baseUrl, apiKey, model, summaryLang, twoStep, models])

  const fetchModels = useCallback(
    async (silent = false) => {
      const url = baseUrl.trim().replace(/\/$/, '')
      const key = apiKey.trim()
      if (!url || !key) {
        if (!silent) setFetchStatus({ cls: 'err', msg: t('api_url_required') })
        return
      }
      if (!silent) setFetchStatus({ cls: '', msg: t('fetching_models') })
      try {
        const fd = new FormData()
        fd.append('base_url', url)
        fd.append('api_key', key)
        const data = await api.fetchModels(fd)
        const list = data.data || data.models || []
        setModels(list)
        /* Re-select previously saved model, otherwise default to the first. */
        const saved = persisted.current.model
        if (saved && list.some((m) => m.id === saved)) {
          setModel(saved)
          persisted.current.model = ''
        } else if (list.length > 0) {
          setModel(list[0].id)
        }
        const loaded = t('models_loaded')
        setFetchStatus({
          cls: 'ok',
          msg: typeof loaded === 'function' ? loaded(list.length) : `${list.length} models`,
        })
      } catch (e) {
        setFetchStatus({ cls: 'err', msg: t('models_error') + ': ' + (e as Error).message })
      }
    },
    [baseUrl, apiKey, t],
  )

  /* On first mount, if both base URL and key were persisted, fetch models. */
  const didAutoFetch = useRef(false)
  useEffect(() => {
    if (didAutoFetch.current) return
    didAutoFetch.current = true
    if (persisted.current.baseUrl && persisted.current.apiKey) {
      const id = setTimeout(() => void fetchModels(true), 400)
      return () => clearTimeout(id)
    }
  }, [fetchModels])

  const refreshWhisperStatus = useCallback(async () => {
    const data = await api.modelStatus()
    if (!data) return false
    setWhisperReady(data.whisper_ready)
    setWhisperError(data.whisper_error)
    return data.whisper_ready
  }, [])

  const refreshInterfaceStatus = useCallback(async () => {
    await Promise.all([
      configured ? fetchModels(true) : Promise.resolve(),
      refreshWhisperStatus(),
    ])
  }, [configured, fetchModels, refreshWhisperStatus])

  /* Whisper model status polling (stops once ready). */
  useEffect(() => {
    let timer: number | undefined
    let cancelled = false
    const poll = async () => {
      const ready = await refreshWhisperStatus()
      if (cancelled) return
      if (ready && timer) {
        clearInterval(timer)
        timer = undefined
      }
    }
    void poll()
    timer = window.setInterval(poll, 15000)
    return () => {
      cancelled = true
      if (timer) clearInterval(timer)
    }
  }, [refreshWhisperStatus])

  const appendModelFields = useCallback(
    (fd: FormData) => {
      fd.append('summary_language', summaryLang)
      const key = apiKey.trim()
      const url = baseUrl.trim().replace(/\/$/, '')
      if (key) fd.append('api_key', key)
      if (url) fd.append('model_base_url', url)
      if (model) fd.append('model_id', model)
    },
    [summaryLang, apiKey, baseUrl, model],
  )

  return (
    <SettingsContext.Provider
      value={{
        baseUrl, apiKey, model, summaryLang, twoStep, models, fetchStatus,
        whisperReady, whisperError, configured,
        setBaseUrl, setApiKey, setModel, setSummaryLang, setTwoStep,
        fetchModels, refreshInterfaceStatus, appendModelFields,
      }}
    >
      {children}
    </SettingsContext.Provider>
  )
}

export function useSettings(): SettingsValue {
  const ctx = useContext(SettingsContext)
  if (!ctx) throw new Error('useSettings must be used within SettingsProvider')
  return ctx
}
