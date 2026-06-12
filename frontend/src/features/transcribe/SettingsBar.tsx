import { useState } from "react"
import { ErrorBanner } from "@/components/ErrorBanner"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Switch } from "@/components/ui/switch"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible"
import { ChevronDownRegular } from "@fluentui/react-icons"
import { cn } from "@/lib/utils"
import { useI18n } from "@/i18n/I18nContext"
import { useSettings } from "@/context/SettingsContext"

const SUMMARY_LANGS = [
  { value: "en", label: "English" },
  { value: "zh", label: "中文（简体）" },
  { value: "es", label: "Español" },
  { value: "fr", label: "Français" },
  { value: "de", label: "Deutsch" },
  { value: "it", label: "Italiano" },
  { value: "pt", label: "Português" },
  { value: "ru", label: "Русский" },
  { value: "ja", label: "日本語" },
  { value: "ko", label: "한국어" },
  { value: "ar", label: "العربية" },
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
    : (t("model_select_placeholder") as string)
  const statusText = configured ? modelLabel : (t("not_configured") as string)

  return (
    <>
      {!configured && <ErrorBanner msg={t("onboarding_setup")} notice />}

      <div className="settings-row">
        {/* Summary language */}
        <div className="inline-lang">
          <Label htmlFor="summaryLanguage" className="inline-lang-label">
            {t("summary_language")}
          </Label>
          <Select value={summaryLang} onValueChange={setSummaryLang}>
            <SelectTrigger id="summaryLanguage" className="w-[140px] h-8 text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {SUMMARY_LANGS.map((l) => (
                <SelectItem key={l.value} value={l.value}>
                  {l.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        {/* Model select */}
        <div className="settings-inline-model">
          <Label htmlFor="modelSelect" className="inline-lang-label">
            {t("model_select")}
          </Label>
          <Select value={model} onValueChange={setModel}>
            <SelectTrigger id="modelSelect" className="max-w-[240px] h-8 text-xs">
              <SelectValue placeholder={t("model_select_placeholder")} />
            </SelectTrigger>
            <SelectContent>
              {models.map((m) => (
                <SelectItem key={m.id} value={m.id}>
                  {m.name || m.id}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        {/* Whisper status */}
        {!whisperReady && (
          <span className="settings-status" title="Whisper">
            <span>{whisperError ? "⚠ Whisper" : (t("model_loading") as string)}</span>
          </span>
        )}

        {/* Configured status pill */}
        <span className={cn("settings-status", configured && "configured")}>
          <span>{statusText}</span>
        </span>

        {/* Settings toggle */}
        <Collapsible open={open} onOpenChange={setOpen}>
          <CollapsibleTrigger asChild>
            <Button variant="outline" size="sm" className="gap-1.5 text-xs">
              <ChevronDownRegular
                className={cn("h-3 w-3 transition-transform duration-200", open && "rotate-180")}
              />
              {t("ai_settings")}
            </Button>
          </CollapsibleTrigger>
        </Collapsible>
      </div>

      {/* Collapsible settings panel */}
      <Collapsible open={open} onOpenChange={setOpen}>
        <CollapsibleContent className="overflow-hidden data-[state=open]:animate-in data-[state=open]:slide-in-from-top-2 data-[state=closed]:animate-out data-[state=closed]:slide-out-to-top-2 mt-2.5">
          <div className="rounded-lg border border-[var(--border-color)] bg-[var(--surface)] p-4">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div className="sm:col-span-2">
                <Label className="s-label">{t("model_base_url")}</Label>
                <Input
                  type="url"
                  placeholder={t("model_base_url_placeholder")}
                  autoComplete="off"
                  value={baseUrl}
                  onChange={(e) => setBaseUrl(e.target.value)}
                  className="h-9 text-sm"
                />
              </div>
              <div>
                <Label className="s-label">{t("api_key")}</Label>
                <div className="key-row">
                  <Input
                    type="password"
                    placeholder={t("api_key_placeholder")}
                    autoComplete="new-password"
                    value={apiKey}
                    onChange={(e) => setApiKey(e.target.value)}
                    className="h-9 text-sm"
                  />
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => void fetchModels(false)}
                    className="h-9 text-xs shrink-0"
                  >
                    {t("fetch_models")}
                  </Button>
                </div>
                {fetchStatus.msg && (
                  <div
                    className={cn(
                      "fetch-status text-xs mt-1",
                      fetchStatus.cls === "ok" && "fetch-status ok",
                      fetchStatus.cls === "err" && "fetch-status err"
                    )}
                  >
                    {fetchStatus.msg}
                  </div>
                )}
              </div>
            </div>

            <div className="setting-row divider">
              <span className="setting-label">{t("two_step_summary")}</span>
              <Switch checked={twoStep} onCheckedChange={setTwoStep} />
            </div>
          </div>
        </CollapsibleContent>
      </Collapsible>
    </>
  )
}
