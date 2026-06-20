import { useState } from "react"
import { EyeRegular, EyeOffRegular } from "@fluentui/react-icons"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { useSettings } from "@/context/SettingsContext"
import { useI18n } from "@/i18n/I18nContext"

export function TtsSection() {
  const { t } = useI18n()
  const { ttsConfig, setTtsConfig } = useSettings()
  const [revealKey, setRevealKey] = useState(false)

  return (
    <div className="space-y-5">
      <h3 className="text-sm font-semibold">{t("settings_section_tts")}</h3>

      {/* API Key */}
      <div className="space-y-1.5">
        <Label className="text-xs">{t("tts_api_key")}</Label>
        <div className="relative">
          <Input
            type={revealKey ? "text" : "password"}
            value={ttsConfig.apiKey}
            onChange={(e) => setTtsConfig({ apiKey: e.target.value })}
            placeholder="sk-..."
            className="pr-9"
          />
          <button
            type="button"
            onClick={() => setRevealKey((v) => !v)}
            className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
            title={revealKey ? t("bot_hide") : t("bot_show")}
          >
            {revealKey ? <EyeOffRegular className="h-4 w-4" /> : <EyeRegular className="h-4 w-4" />}
          </button>
        </div>
      </div>

      {/* Speaker ID（不是密钥，明文输入） */}
      <div className="space-y-1.5">
        <Label className="text-xs">{t("tts_speaker")}</Label>
        <Input
          type="text"
          value={ttsConfig.speaker}
          onChange={(e) => setTtsConfig({ speaker: e.target.value })}
          placeholder="zh_female_vv_uranus_bigtts"
        />
      </div>

      {/* Resource ID */}
      <div className="space-y-1.5">
        <Label className="text-xs">{t("tts_resource_id")}</Label>
        <Input
          type="text"
          value={ttsConfig.resourceId}
          onChange={(e) => setTtsConfig({ resourceId: e.target.value })}
          placeholder="seed-tts-2.0"
        />
      </div>
    </div>
  )
}
