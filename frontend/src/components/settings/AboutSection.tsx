import { useEffect, useState } from "react"
import { Button } from "@/components/ui/button"
import { useI18n } from "@/i18n/I18nContext"
import { api } from "@/lib/api"
import { DOWNLOAD_PAGE_URL, PRIVACY_PAGE_URL, openExternal } from "@/lib/links"

export function AboutSection() {
  const { t } = useI18n()
  const [version, setVersion] = useState<string>("")
  const [dataDir, setDataDir] = useState<string>("")

  useEffect(() => {
    let cancelled = false
    void api.diagnostics().then((data) => {
      if (cancelled) return
      setVersion(data.app_version || "")
      setDataDir(data.data_dir || "")
    }).catch(() => {
      if (!cancelled) setVersion("")
    })
    return () => { cancelled = true }
  }, [])

  return (
    <div className="space-y-4">
      <h3 className="text-sm font-semibold">{t("settings_section_about")}</h3>
      <p className="text-sm text-[var(--text)]">
        {t("about_version")}: {version || "—"}
      </p>
      <p className="text-xs leading-relaxed text-[var(--text-muted)]">{t("about_updates_hint")}</p>
      <div className="flex flex-wrap gap-2">
        <Button type="button" variant="outline" size="sm" onClick={() => openExternal(DOWNLOAD_PAGE_URL)}>
          {t("about_check_updates")}
        </Button>
        <Button type="button" variant="outline" size="sm" onClick={() => openExternal(PRIVACY_PAGE_URL)}>
          {t("about_privacy")}
        </Button>
      </div>
      {dataDir && (
        <div className="space-y-1">
          <p className="text-xs text-[var(--text-muted)]">{t("about_data_dir")}</p>
          <p className="break-all rounded-md border border-[var(--border-color)] bg-[var(--surface-2)] px-2 py-1.5 text-xs text-[var(--text)]" data-selectable>
            {dataDir}
          </p>
        </div>
      )}
    </div>
  )
}
