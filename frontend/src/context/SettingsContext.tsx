import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { api } from '@/lib/api'
import type { AppBotPlatformConfig, AppSettingsPayload, ModelInfo, TtsConfig } from '@/lib/types'
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
  whisperModel: string
  hfEndpoint: string
  browserCookiesAutoDetect: boolean
  fetchStatus: FetchStatus
  whisperReady: boolean
  whisperError: string | null
  configured: boolean
  setBaseUrl: (v: string) => void
  setApiKey: (v: string) => void
  setModel: (v: string) => void
  setSummaryLang: (v: string) => void
  setTwoStep: (v: boolean) => void
  setWhisperModel: (v: string) => void
  setHfEndpoint: (v: string) => void
  setBrowserCookiesAutoDetect: (v: boolean) => void
  /* Bot 集成配置：长期持久化到后端 SQLite，localStorage 仅作缓存/迁移兜底。 */
  botConfigs: Record<string, AppBotPlatformConfig>
  setBotConfig: (platform: string, patch: Partial<AppBotPlatformConfig>) => void
  /* 把启用的 Bot 配置 + 当前 LLM 配置一并下发后端。 */
  pushBotConfigs: () => ReturnType<typeof api.botsConfigure>
  /* TTS 语音合成配置：长期持久化到后端 SQLite。 */
  ttsConfig: TtsConfig
  setTtsConfig: (patch: Partial<TtsConfig>) => void
  ttsConfigured: boolean
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
  apiKeyConfigured?: boolean
  model?: string
  summaryLang?: string
  useTwoStep?: boolean
  models?: ModelInfo[]
  whisperModel?: string
  hfEndpoint?: string
  browserCookiesAutoDetect?: boolean
  botConfigs?: Record<string, AppBotPlatformConfig>
  ttsConfig?: TtsConfig
}

const DEFAULT_TTS: TtsConfig = { enabled: false, apiKey: '', speaker: '', resourceId: 'seed-tts-2.0' }

function loadPersisted(): Persisted {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return raw ? (JSON.parse(raw) as Persisted) : {}
  } catch {
    return {}
  }
}

function hasAnySettings(s: Partial<AppSettingsPayload | Persisted>): boolean {
  return Boolean(
    s.baseUrl || s.apiKey || s.model || s.whisperModel || s.hfEndpoint ||
    s.browserCookiesAutoDetect || Object.keys(s.botConfigs || {}).length ||
    (s.ttsConfig && (s.ttsConfig.apiKey || s.ttsConfig.enabled || s.ttsConfig.speaker))
  )
}

function fromPersisted(p: Persisted): AppSettingsPayload {
  return {
    baseUrl: p.baseUrl || '',
    apiKey: p.apiKey || '',
    apiKeyConfigured: Boolean(p.apiKey || p.apiKeyConfigured),
    model: p.model || '',
    summaryLang: p.summaryLang || 'en',
    useTwoStep: p.useTwoStep !== undefined ? p.useTwoStep : true,
    models: p.models || [],
    whisperModel: p.whisperModel || 'base',
    hfEndpoint: p.hfEndpoint || '',
    browserCookiesAutoDetect: Boolean(p.browserCookiesAutoDetect),
    botConfigs: p.botConfigs || {},
    ttsConfig: { ...DEFAULT_TTS, ...(p.ttsConfig || {}) },
  }
}

export function SettingsProvider({ children }: { children: ReactNode }) {
  const { t } = useI18n()
  const persisted = useRef<Persisted>(loadPersisted())
  const initial = fromPersisted(persisted.current)

  const [baseUrl, setBaseUrl] = useState(initial.baseUrl)
  const [apiKey, setApiKey] = useState(initial.apiKey)
  const [apiKeyConfigured, setApiKeyConfigured] = useState(Boolean(initial.apiKey || initial.apiKeyConfigured))
  const [model, setModel] = useState(initial.model)
  const [summaryLang, setSummaryLang] = useState(initial.summaryLang)
  const [twoStep, setTwoStep] = useState(initial.useTwoStep)
  const [models, setModels] = useState<ModelInfo[]>(initial.models)
  const [whisperModel, setWhisperModel] = useState(initial.whisperModel)
  const [hfEndpoint, setHfEndpoint] = useState(initial.hfEndpoint)
  const [browserCookiesAutoDetect, setBrowserCookiesAutoDetect] = useState(Boolean(initial.browserCookiesAutoDetect))
  const [botConfigs, setBotConfigs] = useState<Record<string, AppBotPlatformConfig>>(initial.botConfigs)
  const [ttsConfig, setTtsConfigState] = useState<TtsConfig>(initial.ttsConfig)
  const [fetchStatus, setFetchStatus] = useState<FetchStatus>({ cls: '', msg: '' })
  const [whisperReady, setWhisperReady] = useState(false)
  const [whisperError, setWhisperError] = useState<string | null>(null)
  const [serverSettingsReady, setServerSettingsReady] = useState(false)

  const configured = Boolean((apiKey.trim() || apiKeyConfigured) && baseUrl.trim() && model.trim())
  const ttsConfigured = Boolean(ttsConfig.enabled && (ttsConfig.apiKey.trim() || ttsConfig.apiKeyConfigured) && ttsConfig.speaker.trim())

  const buildSettingsPayload = useCallback((): AppSettingsPayload => ({
    baseUrl,
    apiKey,
    apiKeyConfigured: Boolean(apiKey.trim() || apiKeyConfigured),
    model,
    summaryLang,
    useTwoStep: twoStep,
    models,
    whisperModel,
    hfEndpoint,
    browserCookiesAutoDetect,
    botConfigs,
    ttsConfig,
  }), [baseUrl, apiKey, apiKeyConfigured, model, summaryLang, twoStep, models, whisperModel, hfEndpoint, browserCookiesAutoDetect, botConfigs, ttsConfig])

  const setTtsConfig = useCallback((patch: Partial<TtsConfig>) => {
    setTtsConfigState((prev) => ({ ...prev, ...patch }))
  }, [])

  /* 后端是长期来源；localStorage 保留缓存与旧版本迁移能力。 */
  useEffect(() => {
    const s = buildSettingsPayload()
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(s))
    } catch {
      /* ignore */
    }
  }, [buildSettingsPayload])

  useEffect(() => {
    let cancelled = false
    const loadServerSettings = async () => {
      try {
        const data = await api.settings()
        if (cancelled) return
        if (hasAnySettings(data)) {
          setBaseUrl(data.baseUrl || '')
          // GET /api/settings 不返回明文 secret。若本地还有旧 key，保留它用于兼容。
          setApiKey((current) => data.apiKey || current)
          setApiKeyConfigured(Boolean(data.apiKeyConfigured || data.apiKey))
          setModel(data.model || '')
          setSummaryLang(data.summaryLang || 'en')
          setTwoStep(data.useTwoStep !== undefined ? data.useTwoStep : true)
          setModels(data.models || [])
          setWhisperModel(data.whisperModel || 'base')
          setHfEndpoint(data.hfEndpoint || '')
          setBrowserCookiesAutoDetect(Boolean(data.browserCookiesAutoDetect))
          setBotConfigs(data.botConfigs || {})
          setTtsConfigState({ ...DEFAULT_TTS, ...(data.ttsConfig || {}) })
        } else if (hasAnySettings(persisted.current)) {
          const migrated = await api.saveSettings(fromPersisted(persisted.current))
          if (cancelled) return
          setApiKeyConfigured(Boolean(migrated.apiKeyConfigured || persisted.current.apiKey))
          setBotConfigs((prev) => ({ ...prev, ...(migrated.botConfigs || {}) }))
          setTtsConfigState((prev) => ({ ...prev, ...(migrated.ttsConfig || {}) }))
        }
      } catch {
        /* 后端不可用时继续使用 localStorage 缓存，稍后由自动保存重试。 */
      } finally {
        if (!cancelled) setServerSettingsReady(true)
      }
    }
    void loadServerSettings()
    return () => { cancelled = true }
  }, [])

  useEffect(() => {
    if (!serverSettingsReady) return
    const id = window.setTimeout(() => {
      void api.saveSettings(buildSettingsPayload()).catch(() => {})
    }, 500)
    return () => window.clearTimeout(id)
  }, [serverSettingsReady, buildSettingsPayload])

  const fetchModels = useCallback(
    async (silent = false) => {
      const url = baseUrl.trim().replace(/\/$/, '')
      const key = apiKey.trim()
      if (!url || (!key && !apiKeyConfigured)) {
        if (!silent) setFetchStatus({ cls: 'err', msg: t('api_url_required') })
        return
      }
      if (!silent) setFetchStatus({ cls: '', msg: t('fetching_models') })
      try {
        const fd = new FormData()
        fd.append('base_url', url)
        if (key) fd.append('api_key', key)
        const data = await api.fetchModels(fd)
        const list = data.data || data.models || []
        setModels(list)
        /* Re-select previously saved model, otherwise default to the first. */
        const saved = persisted.current.model || model
        if (saved && list.some((m) => m.id === saved)) {
          setModel(saved)
          persisted.current.model = ''
        } else if (list.length > 0 && !model) {
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
    [baseUrl, apiKey, apiKeyConfigured, model, t],
  )

  /* On first mount, if a model provider was persisted/restored, fetch models. */
  const didAutoFetch = useRef(false)
  useEffect(() => {
    if (didAutoFetch.current || !serverSettingsReady) return
    didAutoFetch.current = true
    if (baseUrl && (apiKey || apiKeyConfigured)) {
      const id = setTimeout(() => void fetchModels(true), 400)
      return () => clearTimeout(id)
    }
  }, [serverSettingsReady, baseUrl, apiKey, apiKeyConfigured, fetchModels])

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

  const setBotConfig = useCallback((platform: string, patch: Partial<AppBotPlatformConfig>) => {
    setBotConfigs((prev) => {
      const current = prev[platform] || { enabled: false, token: '' }
      return { ...prev, [platform]: { ...current, ...patch } }
    })
  }, [])

  const pushBotConfigs = useCallback(() => {
    return api.botsConfigure({
      bots: botConfigs,
      llm: {
        api_key: apiKey.trim(),
        base_url: baseUrl.trim().replace(/\/$/, ''),
        model: model,
        summary_language: summaryLang,
        whisper_model: whisperModel,
      },
    })
  }, [botConfigs, apiKey, baseUrl, model, summaryLang, whisperModel])

  /* 旧版本只靠浏览器保存 Bot 配置；首次打开时下发一次，完成迁移并启动 Bot。 */
  const didPushBots = useRef(false)
  useEffect(() => {
    if (didPushBots.current || !serverSettingsReady) return
    const hasEnabled = Object.values(botConfigs || {}).some((b) => b?.enabled)
    if (!hasEnabled) return
    didPushBots.current = true
    const id = setTimeout(() => void pushBotConfigs().catch(() => {}), 600)
    return () => clearTimeout(id)
  }, [serverSettingsReady, botConfigs, pushBotConfigs])

  const appendModelFields = useCallback(
    (fd: FormData) => {
      fd.append('summary_language', summaryLang)
      const key = apiKey.trim()
      const url = baseUrl.trim().replace(/\/$/, '')
      // 若 key 已在后端保存，允许不传明文；后端会从 app_settings 补齐。
      if (key) fd.append('api_key', key)
      if (url) fd.append('model_base_url', url)
      if (model) fd.append('model_id', model)
      if (whisperModel) fd.append('whisper_model', whisperModel)
      if (browserCookiesAutoDetect) fd.append('auto_detect_browser_cookies', 'true')
    },
    [summaryLang, apiKey, baseUrl, model, whisperModel, browserCookiesAutoDetect],
  )

  return (
    <SettingsContext.Provider
      value={{
        baseUrl, apiKey, model, summaryLang, twoStep, models, whisperModel, hfEndpoint, browserCookiesAutoDetect, fetchStatus,
        whisperReady, whisperError, configured,
        setBaseUrl, setApiKey, setModel, setSummaryLang, setTwoStep, setWhisperModel, setHfEndpoint, setBrowserCookiesAutoDetect,
        botConfigs, setBotConfig, pushBotConfigs,
        ttsConfig, setTtsConfig, ttsConfigured,
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
