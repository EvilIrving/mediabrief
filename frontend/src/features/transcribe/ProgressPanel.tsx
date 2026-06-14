import { DocumentTextRegular, TextAlignLeftRegular } from "@fluentui/react-icons"
import { Badge } from "@/components/ui/badge"
import { useI18n } from "@/i18n/I18nContext"
import type { ProgressState } from "./useTranscribe"

export function ProgressPanel({ progress, onCancel }: { progress: ProgressState; onCancel?: () => void }) {
  const { t } = useI18n()

  const tr = (key: string, fallback = '') => {
    if (!key) return fallback
    const value = t(key)
    return typeof value === 'string' && value !== key ? value : fallback
  }
  const stageLabel = (key: string) => tr(`stage.${key}.name`, key)
  const stageDetail = (key: string) => tr(`stage.${key}.detail`)

  return (
    <div className="progress-panel show">
      <div className="prog-top">
        <div className="prog-top-left">
          <span className="prog-current">
            {progress.connecting ? (
              <>
                <span className="connecting-dots">
                  <span /><span /><span />
                </span>
                {t("connecting")}
              </>
            ) : (
              progress.stageName
            )}
          </span>
          {progress.mode && (
            <Badge
              variant={progress.mode === "subtitle" ? "success" : "secondary"}
              className="text-[10.5px] font-semibold tracking-wider"
            >
              {progress.modeLabel}
            </Badge>
          )}
        </div>
        <div className="prog-top-right">
          <span className="prog-total">{progress.statusText}</span>
          {onCancel && (
            <button
              type="button"
              className="prog-cancel-btn"
              onClick={onCancel}
              title={t("cancel") as string}
            >
              {t("cancel")}
            </button>
          )}
        </div>
      </div>
      <div className="prog-bar">
        <div
          className={`prog-fill${progress.subtitleMode ? " subtitle-mode" : ""}`}
          style={{ width: `${progress.pct}%` }}
        />
      </div>
      {progress.detail && <div className="prog-detail">{progress.detail}</div>}
      {progress.artifacts.length > 0 && (
        <div className="prog-artifacts">
          {progress.artifacts.map((item, i) => (
            <Badge
              key={i}
              variant={item.state === "ready" ? "success" : "secondary"}
              className="rounded-full gap-1.5 px-2.5 py-1.5 text-xs"
            >
              {item.key === "summary" ? (
                <DocumentTextRegular className="h-3 w-3" />
              ) : (
                <TextAlignLeftRegular className="h-3 w-3" />
              )}
              {tr(`result.${item.key || ''}`, item.key || '')} &middot; {tr(`result_state.${item.state || ''}`, item.state || '')}
            </Badge>
          ))}
        </div>
      )}
      {progress.stages.length > 0 && (
        <div className="prog-steps">
          {progress.stages.map((stage, i) => (
            <span
              key={i}
              className={`prog-step ${stage.state || "pending"}`}
              title={stageDetail(stage.name || '')}
            >
              <span className="prog-step-dot" />
              <span>{stageLabel(stage.name || '')}</span>
            </span>
          ))}
        </div>
      )}
    </div>
  )
}
