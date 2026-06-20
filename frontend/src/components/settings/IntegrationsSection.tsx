import { useCallback, useEffect, useState } from "react"
import {
  EyeRegular,
  EyeOffRegular,
  CheckmarkCircleRegular,
  WarningRegular,
} from "@fluentui/react-icons"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Switch } from "@/components/ui/switch"
import { api } from "@/lib/api"
import type { BotRuntimeStatus, BotPlatformConfig } from "@/lib/types"
import { useSettings } from "@/context/SettingsContext"
import { useI18n } from "@/i18n/I18nContext"

/* ── 集成设置：Bot 平台 + TTS，共用一个保存按钮 ──────────────── */
export function IntegrationsSection() {
  const { t } = useI18n()
  const { botConfigs, setBotConfig, pushBotConfigs, configured, ttsConfig, setTtsConfig } = useSettings()
  const [statuses, setStatuses] = useState<Record<string, BotRuntimeStatus>>({})
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [revealTtsKey, setRevealTtsKey] = useState(false)

  const refreshStatus = useCallback(async () => {
    try {
      const data = await api.botsStatus()
      setStatuses(data.bots)
    } catch {
      /* 后端未连上时静默 */
    }
  }, [])

  useEffect(() => {
    void refreshStatus()
  }, [refreshStatus])

  const handleSave = useCallback(async () => {
    setError(null)
    setSaved(false)
    setSaving(true)
    try {
      const data = await pushBotConfigs()
      setStatuses(data.bots)
      setSaved(true)
      setTimeout(() => setSaved(false), 2500)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setSaving(false)
    }
  }, [pushBotConfigs])

  const tg = botConfigs.telegram || { enabled: false, token: "", extras: {} }
  const tgChatId = String(tg.extras?.chat_id ?? "")
  const slack = botConfigs.slack || { enabled: false, token: "", extras: {} }
  const slackAppToken = String(slack.extras?.app_token ?? "")

  return (
    <div className="space-y-2.5">
      {!configured && (
        <div className="flex items-center gap-1.5 rounded-md border border-border bg-muted/40 px-2.5 py-1.5 text-xs text-muted-foreground">
          <WarningRegular className="h-3.5 w-3.5 shrink-0" />
          <span>{t("bots_needs_llm")}</span>
        </div>
      )}

      <PlatformCard
        platform="telegram"
        title="Telegram"
        status={statuses.telegram}
        config={tg}
        onChange={(patch) => setBotConfig("telegram", patch)}
        tokenLabel={t("bot_token_label")}
        tokenPlaceholder="123456:ABC-DEF..."
        tokenHint={t("bot_telegram_hint")}
        extraFields={[
          {
            key: "chat_id",
            label: t("bot_telegram_chat_id"),
            value: tgChatId,
            placeholder: "123456789",
          },
        ]}
      />

      <PlatformCard
        platform="slack"
        title="Slack"
        status={statuses.slack}
        config={slack}
        onChange={(patch) => setBotConfig("slack", patch)}
        tokenLabel={t("bot_slack_bot_token")}
        tokenPlaceholder="xoxb-..."
        tokenHint={t("bot_slack_hint")}
        extraFields={[
          {
            key: "app_token",
            label: t("bot_slack_app_token"),
            value: slackAppToken,
            placeholder: "xapp-...",
          },
        ]}
      />

      <div className="rounded-lg border border-border p-3">
        <div className="flex items-center justify-between">
          <span className="text-sm font-medium">{t("settings_section_tts")}</span>
          <Switch
            checked={ttsConfig.enabled}
            onCheckedChange={(v) => setTtsConfig({ enabled: v })}
          />
        </div>

        {ttsConfig.enabled && (
          <div className="grid grid-cols-2 gap-2 mt-2">
            <div>
              <Label className="text-xs">{t("tts_api_key")}</Label>
              <div className="relative mt-1">
                <Input
                  type={revealTtsKey ? "text" : "password"}
                  value={ttsConfig.apiKey}
                  onChange={(e) => setTtsConfig({ apiKey: e.target.value })}
                  placeholder="sk-..."
                  className="pr-9"
                />
                <button
                  type="button"
                  onClick={() => setRevealTtsKey((v) => !v)}
                  className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                  title={revealTtsKey ? t("bot_hide") : t("bot_show")}
                >
                  {revealTtsKey ? <EyeOffRegular className="h-4 w-4" /> : <EyeRegular className="h-4 w-4" />}
                </button>
              </div>
            </div>
            <div>
              <Label className="text-xs">{t("tts_speaker")}</Label>
              <Input
                type="text"
                value={ttsConfig.speaker}
                onChange={(e) => setTtsConfig({ speaker: e.target.value })}
                placeholder="zh_female_vv_uranus_bigtts"
                className="mt-1"
              />
            </div>
            <div>
              <Label className="text-xs">{t("tts_resource_id")}</Label>
              <Input
                type="text"
                value={ttsConfig.resourceId}
                onChange={(e) => setTtsConfig({ resourceId: e.target.value })}
                placeholder="seed-tts-2.0"
                className="mt-1"
              />
            </div>
          </div>
        )}
      </div>

      <div className="flex items-center gap-2.5">
        <Button onClick={handleSave} disabled={saving} size="sm">
          {saving ? t("bot_saving") : t("bot_save")}
        </Button>
        {saved && (
          <span className="flex items-center gap-1 text-xs text-[var(--accent)]">
            <CheckmarkCircleRegular className="h-4 w-4" />
            {t("bot_saved")}
          </span>
        )}
        {error && <span className="text-xs text-destructive">{error}</span>}
      </div>
    </div>
  )
}

interface ExtraField {
  key: string
  label: string
  value: string
  placeholder: string
}

interface PlatformCardProps {
  platform: string
  title: string
  status?: BotRuntimeStatus
  config: BotPlatformConfig
  onChange: (patch: Partial<BotPlatformConfig>) => void
  tokenLabel: string
  tokenPlaceholder: string
  tokenHint: string
  extraFields?: ExtraField[]
}

function PlatformCard({
  platform,
  title,
  status,
  config,
  onChange,
  tokenLabel,
  tokenPlaceholder,
  tokenHint,
  extraFields = [],
}: PlatformCardProps) {
  const { t } = useI18n()
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<string | null>(null)
  const [testError, setTestError] = useState<string | null>(null)

  const setExtra = useCallback(
    (key: string, value: string) => {
      onChange({ extras: { ...(config.extras || {}), [key]: value } })
    },
    [config.extras, onChange],
  )

  const handleTest = useCallback(async () => {
    setTestError(null)
    setTestResult(null)
    setTesting(true)
    try {
      const data = await api.botsTest(platform, config.token, config.extras || {})
      setTestResult(data.bot_name)
    } catch (e) {
      setTestError((e as Error).message)
    } finally {
      setTesting(false)
    }
  }, [platform, config.token, config.extras])

  const testDisabled = testing || !config.token.trim()
  const opened = config.enabled

  return (
    <div className="space-y-2.5 rounded-lg border border-border p-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium">{title}</span>
          <StatusDot status={status?.status} />
          <span className="text-xs text-muted-foreground">{statusLabel(status, t)}</span>
        </div>
        <Switch checked={config.enabled} onCheckedChange={(v) => onChange({ enabled: v })} />
      </div>

      {opened && (
        <>
          {/* Token + extra fields 一行两列 */}
          <div className="grid grid-cols-2 gap-2.5">
            <SecretInput
              label={tokenLabel}
              value={config.token}
              placeholder={tokenPlaceholder}
              onChange={(v) => onChange({ token: v })}
            />
            {extraFields.map((f) => (
              <SecretInput
                key={f.key}
                label={f.label}
                value={f.value}
                placeholder={f.placeholder}
                onChange={(v) => setExtra(f.key, v)}
              />
            ))}
            {extraFields.length % 2 === 1 && <div />}
          </div>

          <div className="flex items-center gap-2.5">
            <Button variant="outline" size="sm" disabled={testDisabled} onClick={handleTest}>
              {testing ? t("bot_testing") : t("bot_test")}
            </Button>
            {testResult && (
              <span className="text-xs text-[var(--accent)]">{t("bot_test_ok")} {testResult}</span>
            )}
            {testError && <span className="text-xs text-destructive">{testError}</span>}
          </div>

          <p className="text-xs text-muted-foreground">{tokenHint}</p>
        </>
      )}
    </div>
  )
}

function SecretInput({
  label,
  value,
  placeholder,
  onChange,
}: {
  label: string
  value: string
  placeholder: string
  onChange: (v: string) => void
}) {
  const { t } = useI18n()
  const [reveal, setReveal] = useState(false)
  return (
    <div className="space-y-1">
      <Label className="text-xs">{label}</Label>
      <div className="relative">
        <Input
          type={reveal ? "text" : "password"}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          className="pr-9"
        />
        <button
          type="button"
          onClick={() => setReveal((v) => !v)}
          className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
          title={reveal ? t("bot_hide") : t("bot_show")}
        >
          {reveal ? <EyeOffRegular className="h-4 w-4" /> : <EyeRegular className="h-4 w-4" />}
        </button>
      </div>
    </div>
  )
}

function StatusDot({ status }: { status?: BotRuntimeStatus["status"] }) {
  const color =
    status === "running"
      ? "bg-[var(--accent)]"
      : status === "error"
        ? "bg-destructive"
        : status === "starting"
          ? "bg-amber-500"
          : "bg-muted-foreground/40"
  return <span className={`inline-block h-2 w-2 rounded-full ${color}`} />
}

function statusLabel(status: BotRuntimeStatus | undefined, t: ReturnType<typeof useI18n>["t"]): string {
  if (!status) return t("bot_status_stopped")
  switch (status.status) {
    case "running":
      return status.bot_name ? `@${status.bot_name}` : t("bot_status_running")
    case "error":
      return status.last_error || status.message || t("bot_status_error")
    case "starting":
      return t("bot_status_starting")
    default:
      return t("bot_status_stopped")
  }
}
