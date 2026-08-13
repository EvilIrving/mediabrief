import { useMemo, useState } from "react"
import type { ReactNode } from "react"
import {
  ChevronDownRegular,
  CopyRegular,
  InfoRegular,
  WarningRegular,
} from "@fluentui/react-icons"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible"
import { useI18n } from "@/i18n/I18nContext"
import { cn, translate } from "@/lib/utils"
import type {
  AudioProfile,
  RecoveryActionCode,
  RecoveryActionResponse,
  TaskDiagnostics,
  TranscriptQualityReport,
  TranscriptionStrategy,
} from "@/lib/types"

const ACTION_REQUIRED = "action_required"

function cleanDynamicText(value: unknown, maxLength = 800): string {
  const text = String(value ?? "")
    .replace(/<[^>]*>/g, " ")
    .replace(/[\u0000-\u001f\u007f-\u009f]/g, " ")
    .replace(/\s+/g, " ")
    .trim()
  return text.length > maxLength ? `${text.slice(0, maxLength - 1)}…` : text
}

function cleanCode(value: unknown): string {
  return cleanDynamicText(value, 64).replace(/[^a-zA-Z0-9._-]/g, "")
}

function hasValues(value: unknown): boolean {
  return Boolean(value && typeof value === "object" && Object.keys(value).length)
}

export function hasTaskDiagnostics(task?: TaskDiagnostics | null): boolean {
  return Boolean(
    task?.recovery_status ||
    task?.recovery_message ||
    task?.recovery_observations?.length ||
    hasValues(task?.audio_profile) ||
    hasValues(task?.transcription_strategy) ||
    hasValues(task?.transcript_quality_report),
  )
}

function formatDuration(value?: number | null): string {
  if (value == null || !Number.isFinite(value)) return "—"
  if (value < 60) return `${value.toFixed(1)}s`
  const hours = Math.floor(value / 3600)
  const minutes = Math.floor((value % 3600) / 60)
  const seconds = Math.round(value % 60)
  return hours ? `${hours}h ${minutes}m ${seconds}s` : `${minutes}m ${seconds}s`
}

function formatPercent(value?: number | null, digits = 0): string {
  return value == null || !Number.isFinite(value) ? "—" : `${(value * 100).toFixed(digits)}%`
}

function formatAmplitude(value?: number | null): string {
  return value == null || !Number.isFinite(value) ? "—" : value.toFixed(3)
}

function copyPlainText(text: string): Promise<void> {
  if (navigator.clipboard?.writeText) return navigator.clipboard.writeText(text)
  const textarea = document.createElement("textarea")
  textarea.value = text
  textarea.style.position = "fixed"
  textarea.style.opacity = "0"
  document.body.appendChild(textarea)
  textarea.select()
  document.execCommand("copy")
  document.body.removeChild(textarea)
  return Promise.resolve()
}

type BadgeVariant = "default" | "secondary" | "destructive" | "outline" | "success"

function statusVariant(status?: string): BadgeVariant {
  if (["good", "passed", "complete", "recovered", "success"].includes(status || "")) return "success"
  if (["failed", "poor", "unusable", "cancelled", "failure"].includes(status || "")) return "destructive"
  if (["warning", "fair", ACTION_REQUIRED, "partial"].includes(status || "")) return "default"
  return "secondary"
}

function InsightBadge({ prefix, value }: { prefix: string; value?: string | null }) {
  const { t } = useI18n()
  if (!value) return null
  const code = cleanCode(value)
  const label = translate(t, `diagnostics.${prefix}.${code}`, code.replaceAll("_", " "))
  return <Badge variant={statusVariant(code)} className="font-medium normal-case tracking-normal">{label}</Badge>
}

function ReasonList({ values }: { values?: string[] }) {
  const { t } = useI18n()
  if (!values?.length) return null
  return (
    <div className="flex flex-wrap gap-1.5">
      {values.map((value, index) => {
        const code = cleanCode(value)
        return (
          <span key={`${code}-${index}`} className="rounded-md bg-[var(--surface-3)] px-2 py-1 text-[11px] leading-tight text-[var(--text-muted)]">
            {translate(t, `diagnostics.reason.${code}`, code.replaceAll("_", " "))}
          </span>
        )
      })}
    </div>
  )
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0 rounded-md border border-[var(--border-light)] bg-[var(--surface-2)] px-2.5 py-2">
      <div className="text-[10px] uppercase tracking-[.06em] text-[var(--text-dim)]">{label}</div>
      <div className="mt-0.5 truncate text-xs font-medium text-[var(--text)]" title={value}>{value}</div>
    </div>
  )
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="space-y-2 border-t border-[var(--border-light)] py-3 first:border-t-0 first:pt-1">
      <h4 className="text-xs font-semibold text-[var(--text)]">{title}</h4>
      {children}
    </section>
  )
}

function RecoveryDetails({ diagnostics }: { diagnostics: TaskDiagnostics }) {
  const { t } = useI18n()
  const observations = diagnostics.recovery_observations || []
  if (!diagnostics.recovery_status && !diagnostics.recovery_message && !observations.length) return null
  return (
    <Section title={t("diagnostics_recovery_title")}>
      <div className="flex flex-wrap items-center gap-2">
        <InsightBadge prefix="recovery" value={diagnostics.recovery_status} />
        {diagnostics.recovery_code && <code className="text-[11px] text-[var(--text-dim)]">{cleanCode(diagnostics.recovery_code)}</code>}
      </div>
      {diagnostics.recovery_message && (
        <p className="text-xs leading-relaxed text-[var(--text-muted)]">{cleanDynamicText(diagnostics.recovery_message)}</p>
      )}
      {observations.length > 0 && (
        <ol className="space-y-1.5">
          {observations.map((item, index) => {
            const action = cleanCode(item.action)
            const actionLabel = translate(t, `diagnostics.recovery_action.${action}`, action.replaceAll("_", " "))
            return (
              <li key={`${action}-${index}`} className="flex gap-2 text-xs leading-relaxed">
                <span className="mt-[2px] text-[10px] tabular-nums text-[var(--text-dim)]">{index + 1}</span>
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <span className="font-medium text-[var(--text)]">{actionLabel}</span>
                    <InsightBadge prefix="observation" value={item.status} />
                    {item.code && <code className="text-[10px] text-[var(--text-dim)]">{cleanCode(item.code)}</code>}
                  </div>
                  {item.summary && <p className="mt-0.5 text-[var(--text-muted)]">{cleanDynamicText(item.summary)}</p>}
                </div>
              </li>
            )
          })}
        </ol>
      )}
    </Section>
  )
}

function AudioDetails({ profile }: { profile: AudioProfile }) {
  const { t } = useI18n()
  const format = [cleanDynamicText(profile.container, 30), cleanDynamicText(profile.codec, 30)].filter(Boolean).join(" · ") || "—"
  const volume = profile.low_volume == null
    ? formatAmplitude(profile.rms_amplitude)
    : `${formatAmplitude(profile.rms_amplitude)} · ${t(profile.low_volume ? "diagnostics_low" : "diagnostics_normal")}`
  return (
    <Section title={t("diagnostics_audio_title")}>
      <div className="flex flex-wrap gap-2">
        <InsightBadge prefix="audio_status" value={profile.analysis_status} />
        <InsightBadge prefix="audio_grade" value={profile.quality_grade} />
      </div>
      <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-3">
        <Metric label={t("diagnostics_format")} value={format} />
        <Metric label={t("diagnostics_duration")} value={formatDuration(profile.duration_seconds)} />
        <Metric label={t("diagnostics_speech")} value={formatPercent(profile.speech_ratio)} />
        <Metric label={t("diagnostics_silence")} value={formatPercent(profile.silence_ratio)} />
        <Metric label={t("diagnostics_volume")} value={volume} />
        <Metric label={t("diagnostics_clipping")} value={formatPercent(profile.clipping_ratio, 2)} />
      </div>
      <ReasonList values={[...(profile.reason_codes || []), ...(profile.integrity_flags || []).map((flag) => `integrity_${flag}`)]} />
      {profile.analysis_error && (
        <p className="text-xs leading-relaxed text-[var(--text-muted)]">{cleanDynamicText(profile.analysis_error)}</p>
      )}
    </Section>
  )
}

function StrategyDetails({ strategy }: { strategy: TranscriptionStrategy }) {
  const { t } = useI18n()
  const language = strategy.language || translate(t, `diagnostics.language_mode.${cleanCode(strategy.language_mode)}`, t("diagnostics_auto") as string)
  return (
    <Section title={t("diagnostics_strategy_title")}>
      <div className="flex flex-wrap gap-2">
        <InsightBadge prefix="strategy" value={strategy.profile} />
        {strategy.model_id && <Badge variant="outline" className="font-mono font-normal">{cleanDynamicText(strategy.model_id, 80)}</Badge>}
      </div>
      <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-3">
        <Metric label={t("diagnostics_language")} value={cleanDynamicText(language, 40)} />
        <Metric label={t("diagnostics_chunk")} value={formatDuration(strategy.chunk_seconds)} />
        <Metric label={t("diagnostics_overlap")} value={formatDuration(strategy.overlap_seconds)} />
        <Metric label={t("diagnostics_volume_normalization")} value={t(strategy.normalize_volume ? "diagnostics_enabled" : "diagnostics_disabled")} />
        <Metric label={t("diagnostics_vad_profile")} value={cleanCode(strategy.vad_profile) || "—"} />
        <Metric label={t("diagnostics_retry_budget")} value={String(strategy.max_segment_retries ?? 0)} />
      </div>
      <ReasonList values={strategy.reason_codes} />
    </Section>
  )
}

function rangeText(start?: number, end?: number): string {
  return `${formatDuration(start)}–${formatDuration(end)}`
}

function QualityDetails({ report }: { report: TranscriptQualityReport }) {
  const { t } = useI18n()
  const findings = report.findings || []
  const retries = report.retry_records || []
  return (
    <Section title={t("diagnostics_quality_title")}>
      <div className="flex flex-wrap gap-2">
        <InsightBadge prefix="quality" value={report.evaluation_status} />
        {retries.length > 0 && <Badge variant="outline">{(t("diagnostics_retries") as (n: number) => string)(retries.length)}</Badge>}
      </div>
      <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-3">
        <Metric label={t("diagnostics_coverage")} value={formatPercent(report.coverage_ratio)} />
        <Metric label={t("diagnostics_segments")} value={report.segment_count == null ? "—" : String(report.segment_count)} />
        <Metric label={t("diagnostics_suspicious_ranges")} value={String(report.suspicious_ranges?.length || 0)} />
      </div>
      {findings.length > 0 ? (
        <ul className="space-y-1.5">
          {findings.map((finding, index) => {
            const code = cleanCode(finding.code)
            return (
              <li key={`${code}-${index}`} className="text-xs leading-relaxed text-[var(--text-muted)]">
                <span className="font-medium text-[var(--text)]">{translate(t, `diagnostics.finding.${code}`, code.replaceAll("_", " "))}</span>
                {finding.ranges?.length ? ` · ${finding.ranges.map((range) => rangeText(range.start_seconds, range.end_seconds)).join(", ")}` : ""}
              </li>
            )
          })}
        </ul>
      ) : report.evaluation_status === "passed" ? (
        <p className="text-xs text-[var(--text-muted)]">{t("diagnostics_quality_no_warnings")}</p>
      ) : null}
      {retries.map((retry, index) => (
        <p key={index} className="text-xs leading-relaxed text-[var(--text-muted)]">
          {(t("diagnostics_retry_record") as (range: string, selected: string) => string)(
            rangeText(retry.time_range?.start_seconds, retry.time_range?.end_seconds),
            translate(t, `diagnostics.selection.${cleanCode(retry.selected)}`, cleanCode(retry.selected)),
          )}
        </p>
      ))}
    </Section>
  )
}

const USER_ACTIONS: RecoveryActionCode[] = [
  "enable_browser_session",
  "login_then_retry",
  "requeue_continue",
  "abort",
  "copy_sanitized_diagnostic",
]

function recommendedAction(value?: string): RecoveryActionCode | undefined {
  if (value === "retry_later") return "requeue_continue"
  return USER_ACTIONS.includes(value as RecoveryActionCode) ? value as RecoveryActionCode : undefined
}

export function TaskInsightsPanel({
  diagnostics,
  taskId,
  onRecoveryAction,
}: {
  diagnostics: TaskDiagnostics
  taskId?: string | null
  onRecoveryAction?: (action: RecoveryActionCode) => Promise<RecoveryActionResponse>
}) {
  const { t } = useI18n()
  const actionRequired = diagnostics.recovery_status === ACTION_REQUIRED
  const [open, setOpen] = useState(actionRequired)
  const [busyAction, setBusyAction] = useState<RecoveryActionCode | null>(null)
  const [feedback, setFeedback] = useState("")
  const suggested = recommendedAction(diagnostics.recovery_user_action)

  const summaryBadges = useMemo(() => [
    diagnostics.recovery_status && { prefix: "recovery", value: diagnostics.recovery_status },
    diagnostics.audio_profile?.quality_grade && { prefix: "audio_grade", value: diagnostics.audio_profile.quality_grade },
    diagnostics.transcription_strategy?.profile && { prefix: "strategy", value: diagnostics.transcription_strategy.profile },
    diagnostics.transcript_quality_report?.evaluation_status && { prefix: "quality", value: diagnostics.transcript_quality_report.evaluation_status },
  ].filter(Boolean) as { prefix: string; value: string }[], [diagnostics])

  if (!hasTaskDiagnostics(diagnostics)) return null

  const runAction = async (action: RecoveryActionCode) => {
    if (!onRecoveryAction || !taskId || busyAction) return
    setBusyAction(action)
    setFeedback("")
    try {
      const result = await onRecoveryAction(action)
      if (action === "copy_sanitized_diagnostic" && result.diagnostic) {
        await copyPlainText(cleanDynamicText(result.diagnostic, 4_000))
        setFeedback(t("diagnostics_copied"))
      } else {
        setFeedback(cleanDynamicText(result.message) || t("diagnostics_action_applied"))
      }
    } catch (error) {
      setFeedback(cleanDynamicText((error as Error).message) || t("request_failed"))
    } finally {
      setBusyAction(null)
    }
  }

  return (
    <div className="shrink-0 border-b border-[var(--border-light)] bg-[var(--surface-2)]">
      {actionRequired && (
        <div className="m-3 rounded-lg border border-[rgba(var(--error-rgb),.3)] bg-[rgba(var(--error-rgb),.06)] p-3">
          <div className="flex gap-2.5">
            <WarningRegular className="mt-0.5 h-4 w-4 shrink-0 text-[var(--error)]" />
            <div className="min-w-0 flex-1">
              <div className="text-sm font-semibold text-[var(--text)]">{t("diagnostics_action_required")}</div>
              {diagnostics.recovery_message && (
                <p className="mt-1 text-xs leading-relaxed text-[var(--text-muted)]">{cleanDynamicText(diagnostics.recovery_message)}</p>
              )}
              {onRecoveryAction && taskId && (
                <div className="mt-3 flex flex-wrap gap-1.5">
                  {USER_ACTIONS.map((action) => (
                    <Button
                      key={action}
                      variant={action === "abort" ? "outline" : action === suggested ? "default" : "secondary"}
                      size="sm"
                      loading={busyAction === action}
                      disabled={Boolean(busyAction)}
                      onClick={() => void runAction(action)}
                    >
                      {action === "copy_sanitized_diagnostic" && <CopyRegular />}
                      {t(`diagnostics.user_action.${action}`)}
                    </Button>
                  ))}
                </div>
              )}
              {feedback && <p className="mt-2 text-xs text-[var(--text-muted)]" role="status">{feedback}</p>}
            </div>
          </div>
        </div>
      )}

      <Collapsible open={open} onOpenChange={setOpen}>
        <CollapsibleTrigger asChild>
          <button type="button" className="flex w-full items-center gap-2 px-4 py-2.5 text-left hover:bg-[var(--surface-3)]">
            <InfoRegular className="h-4 w-4 shrink-0 text-[var(--text-dim)]" />
            <span className="shrink-0 text-xs font-semibold text-[var(--text)]">{t("diagnostics_title")}</span>
            <div className="flex min-w-0 flex-1 flex-wrap gap-1.5">
              {summaryBadges.map((item) => <InsightBadge key={`${item.prefix}-${item.value}`} {...item} />)}
            </div>
            <ChevronDownRegular className={cn("h-4 w-4 shrink-0 text-[var(--text-dim)] transition-transform", open && "rotate-180")} />
          </button>
        </CollapsibleTrigger>
        <CollapsibleContent>
          <div className="max-h-[48vh] overflow-y-auto px-4 pb-3">
            <RecoveryDetails diagnostics={diagnostics} />
            {diagnostics.audio_profile && <AudioDetails profile={diagnostics.audio_profile} />}
            {diagnostics.transcription_strategy && <StrategyDetails strategy={diagnostics.transcription_strategy} />}
            {diagnostics.transcript_quality_report && <QualityDetails report={diagnostics.transcript_quality_report} />}
          </div>
        </CollapsibleContent>
      </Collapsible>
    </div>
  )
}
