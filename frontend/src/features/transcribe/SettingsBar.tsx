import { useState } from 'react'
import { ErrorBanner } from '@/components/ErrorBanner'
import { useI18n } from '@/i18n/I18nContext'
import { useSettings } from '@/context/SettingsContext'

const SUMMARY_LANGS: { value: string; label: string }[] = [
  { value: 'en', label: 'English' },
  { value: 'zh', label: '中文（简体）' },
  { value: 'es', label: 'Español' },
  { value: 'fr', label: 'Français' },
  { value: 'de', label: 'Deutsch' },
  { value: 'it', label: 'Italiano' },
  { value: 'pt', label: 'Português' },
  { value: 'ru', label: 'Русский' },
  { value: 'ja', label: '日本語' },
  { value: 'ko', label: '한국어' },
  { value: 'ar', label: 'العربية' },
]

export function SettingsBar() {
  const { t } = useI18n()
  const {
    baseUrl, apiKey, model, summaryLang, twoStep, models, fetchStatus,
    whisperReady, whisperError, configured,
    setBaseUrl, setApiKey, setModel, setSummaryLang, setTwoStep, fetchModels,
  } = useSettings()
  const [open, setOpen] = useState(!configured)

  const modelLabel = model
    ? models.find((m) => m.id === model)?.name || model
    : (t('model_select_placeholder') as string)
  const statusText = configured ? modelLabel : (t('not_configured') as string)

  return (
    <>
      {!configured && <ErrorBanner msg={t('onboarding_setup')} notice />}

      <div className="settings-row">
        <div className="inline-lang">
          <label className="inline-lang-label" htmlFor="summaryLanguage">{t('summary_language')}</label>
          <select
            id="summaryLanguage"
            className="inline-lang-select"
            value={summaryLang}
            onChange={(e) => setSummaryLang(e.target.value)}
          >
            {SUMMARY_LANGS.map((l) => (
              <option key={l.value} value={l.value}>{l.label}</option>
            ))}
          </select>
        </div>
        <div className="settings-inline-model">
          <label className="inline-lang-label" htmlFor="modelSelect">{t('model_select')}</label>
          <select
            id="modelSelect"
            className="s-select"
            value={model}
            onChange={(e) => setModel(e.target.value)}
          >
            <option value="" disabled>{t('model_select_placeholder')}</option>
            {models.map((m) => (
              <option key={m.id} value={m.id}>{m.name || m.id}</option>
            ))}
          </select>
        </div>
        {!whisperReady && (
          <span className="settings-status" title="Whisper">
            <span>{whisperError ? '⚠ Whisper' : (t('model_loading') as string)}</span>
          </span>
        )}
        <span className={`settings-status${configured ? ' configured' : ''}`}>
          <span>{statusText}</span>
        </span>
        <button className="settings-toggle" onClick={() => setOpen((o) => !o)}>
          <span>{t('ai_settings')}</span>
        </button>
      </div>

      <div className={`settings-body${open ? ' open' : ''}`}>
        <div className="settings-card">
          <div className="settings-grid">
            <div className="span2">
              <label className="s-label">{t('model_base_url')}</label>
              <input
                className="s-input"
                type="url"
                placeholder={t('model_base_url_placeholder')}
                autoComplete="off"
                value={baseUrl}
                onChange={(e) => setBaseUrl(e.target.value)}
              />
            </div>
            <div>
              <label className="s-label">{t('api_key')}</label>
              <div className="key-row">
                <input
                  className="s-input"
                  type="password"
                  placeholder={t('api_key_placeholder')}
                  autoComplete="new-password"
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                />
                <button className="btn-fetch" type="button" onClick={() => void fetchModels(false)}>
                  <span>{t('fetch_models')}</span>
                </button>
              </div>
              <div className={`fetch-status${fetchStatus.cls ? ' ' + fetchStatus.cls : ''}`}>
                {fetchStatus.msg}
              </div>
            </div>
          </div>
          <div className="setting-row divider">
            <span className="setting-label">{t('two_step_summary')}</span>
            <label className="toggle-switch">
              <input type="checkbox" checked={twoStep} onChange={(e) => setTwoStep(e.target.checked)} />
              <span className="toggle-slider" />
            </label>
          </div>
        </div>
      </div>
    </>
  )
}
