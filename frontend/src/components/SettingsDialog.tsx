import { useEffect, useState } from "react"
import {
  SettingsRegular,
  MicRegular,
  BotRegular,
  InfoRegular,
} from "@fluentui/react-icons"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import { useI18n } from "@/i18n/I18nContext"
import { useSettings } from "@/context/SettingsContext"
import type { SettingsSection } from "@/components/settings/types"
import { TranscriptionSection } from "@/components/settings/TranscriptionSection"
import { IntegrationsSection } from "@/components/settings/IntegrationsSection"
import { AboutSection } from "@/components/settings/AboutSection"

/* ── Section registry ──────────────────────────────────────────
   Each settings section is a self-contained component under
   components/settings/. To add a future config area, append an
   entry here — the sidebar and the content pane are both driven
   off this list. */
const SECTIONS: SettingsSection[] = [
  {
    id: "transcription",
    labelKey: "settings_section_transcription",
    icon: <MicRegular className="h-4 w-4" />,
    render: () => <TranscriptionSection />,
  },
  {
    id: "integrations",
    labelKey: "settings_section_integrations",
    icon: <BotRegular className="h-4 w-4" />,
    render: () => <IntegrationsSection />,
  },
  {
    id: "about",
    labelKey: "settings_section_about",
    icon: <InfoRegular className="h-4 w-4" />,
    render: () => <AboutSection />,
  },
]
const RELEASE_SECTIONS = SECTIONS.filter((item) => item.id !== "transcription")

export function SettingsDialog() {
  const { t } = useI18n()
  const { releaseConfigured } = useSettings()
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(SECTIONS[0].id)
  const sections = releaseConfigured ? RELEASE_SECTIONS : SECTIONS
  const section = sections.find((s) => s.id === active) ?? sections[0]

  useEffect(() => {
    if (!sections.some((item) => item.id === active)) setActive(sections[0].id)
  }, [active, sections])

  // 由全局快捷键 Cmd/Ctrl+, 触发打开（见 lib/desktop.ts）。
  useEffect(() => {
    const open = () => setOpen(true)
    window.addEventListener("open-settings", open)
    return () => window.removeEventListener("open-settings", open)
  }, [])

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="ghost" size="icon" title={t("settings_gear")}>
          <SettingsRegular className="h-4 w-4" />
        </Button>
      </DialogTrigger>
      <DialogContent className="max-w-[min(60vw,900px)] gap-0 overflow-hidden p-0">
        <div className="flex h-[80vh] max-h-[700px]">
          {/* ── Left sidebar ── */}
          <aside className="w-44 shrink-0 border-r border-border bg-muted/30 p-3">
            <DialogHeader className="px-2 pb-3 pt-1">
              <DialogTitle className="text-sm font-semibold">
                {t("settings_title")}
              </DialogTitle>
            </DialogHeader>
            <nav className="space-y-0.5">
              {sections.map((s) => (
                <button
                  key={s.id}
                  type="button"
                  onClick={() => setActive(s.id)}
                  className={`flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm transition-colors ${
                    s.id === active
                      ? "bg-accent text-accent-foreground"
                      : "text-muted-foreground hover:bg-accent/50"
                  }`}
                >
                  {s.icon}
                  <span>{t(s.labelKey)}</span>
                </button>
              ))}
            </nav>
          </aside>

          {/* ── Right content ── */}
          <div className="flex-1 overflow-y-auto p-5">{section.render()}</div>
        </div>
      </DialogContent>
    </Dialog>
  )
}
