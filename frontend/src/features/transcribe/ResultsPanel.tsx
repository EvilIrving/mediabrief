import { useRef, useState } from 'react'
import { useI18n } from '@/i18n/I18nContext'
import type { ResultsState, ResultTab } from './useTranscribe'

interface Props {
  results: ResultsState
  isProcessing: boolean
  onTab: (tab: ResultTab) => void
  onExport: () => void
  onRetry: () => void
}

export function ResultsPanel({ results, isProcessing, onTab, onExport, onRetry }: Props) {
  const { t } = useI18n()
  const scriptRef = useRef<HTMLDivElement>(null)
  const summaryRef = useRef<HTMLDivElement>(null)
  const translationRef = useRef<HTMLDivElement>(null)
  const [copied, setCopied] = useState(false)

  const activeRef =
    results.activeTab === 'script' ? scriptRef
    : results.activeTab === 'summary' ? summaryRef
    : translationRef

  const copy = async () => {
    const el = activeRef.current
    const text = el?.textContent?.trim()
    if (!text) return
    try {
      await navigator.clipboard.writeText(text)
    } catch {
      const ta = document.createElement('textarea')
      ta.value = text
      ta.style.position = 'fixed'
      ta.style.opacity = '0'
      document.body.appendChild(ta)
      ta.select()
      document.execCommand('copy')
      document.body.removeChild(ta)
    }
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  const tabBtn = (tab: ResultTab, label: string, hidden = false) =>
    hidden ? null : (
      <button
        className={`tab-btn${results.activeTab === tab ? ' active' : ''}`}
        onClick={() => onTab(tab)}
      >
        <span>{label}</span>
      </button>
    )

  return (
    <div className="results-panel show">
      <div className="tab-bar">
        {tabBtn('script', t('transcript_text'))}
        {tabBtn('summary', t('intelligent_summary'))}
        {tabBtn('translation', t('translation'), !results.showTranslation)}
        <div className="tab-actions">
          <button className="btn-dl" onClick={onExport}>
            <span>{t('export_button')}</span>
          </button>
          {results.activeTab === 'script' && (
            <button className="btn-dl" title={t('retry')} disabled={isProcessing} onClick={onRetry}>
              <span>{t('retry')}</span>
            </button>
          )}
          <button className={`btn-dl${copied ? ' copied' : ''}`} onClick={copy}>
            <span>{copied ? t('completed') : t('copy')}</span>
          </button>
        </div>
      </div>
      <div className={`tab-pane${results.activeTab === 'script' ? ' active' : ''}`}>
        <div className="tab-pane-scroll">
          <div className="md-content" ref={scriptRef} dangerouslySetInnerHTML={{ __html: results.scriptHtml }} />
        </div>
      </div>
      <div className={`tab-pane${results.activeTab === 'summary' ? ' active' : ''}`}>
        <div className="tab-pane-scroll">
          <div className="md-content" ref={summaryRef} dangerouslySetInnerHTML={{ __html: results.summaryHtml }} />
        </div>
      </div>
      <div className={`tab-pane${results.activeTab === 'translation' ? ' active' : ''}`}>
        <div className="tab-pane-scroll">
          <div className="md-content" ref={translationRef} dangerouslySetInnerHTML={{ __html: results.translationHtml }} />
        </div>
      </div>
    </div>
  )
}
