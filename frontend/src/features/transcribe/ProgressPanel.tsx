import { Icon } from '@/components/IconSprite'
import { useI18n } from '@/i18n/I18nContext'
import type { ProgressState } from './useTranscribe'

export function ProgressPanel({ progress }: { progress: ProgressState }) {
  const { t } = useI18n()
  return (
    <div className="progress-panel show">
      <div className="prog-top">
        <div className="prog-top-left">
          <span className="prog-current">
            {progress.connecting ? (
              <>
                <span className="connecting-dots"><span /><span /><span /></span>
                {t('connecting')}
              </>
            ) : (
              progress.stageName
            )}
          </span>
          {progress.mode && (
            <span className={`mode-badge ${progress.mode}`}>{progress.modeLabel}</span>
          )}
        </div>
        <span className="prog-total">{progress.statusText}</span>
      </div>
      <div className="prog-bar">
        <div
          className={`prog-fill${progress.subtitleMode ? ' subtitle-mode' : ''}`}
          style={{ width: `${progress.pct}%` }}
        />
      </div>
      {progress.detail && <div className="prog-detail">{progress.detail}</div>}
      {progress.artifacts.length > 0 && (
        <div className="prog-artifacts">
          {progress.artifacts.map((item, i) => (
            <span
              key={i}
              className={`artifact-pill ${item.state === 'ready' ? 'ready' : 'waiting'}`}
              data-artifact={item.key || ''}
            >
              <Icon name={item.key === 'summary' ? 'i-file-lines' : 'i-align-left'} />
              {' '}
              {item.label || ''} · {item.state_label || ''}
            </span>
          ))}
        </div>
      )}
      {progress.stages.length > 0 && (
        <div className="prog-steps">
          {progress.stages.map((stage, i) => (
            <span
              key={i}
              className={`prog-step ${stage.state || 'pending'}`}
              title={stage.detail || stage.label || stage.name || ''}
            >
              <span className="prog-step-dot" />
              <span>{stage.name || ''}</span>
            </span>
          ))}
        </div>
      )}
    </div>
  )
}
