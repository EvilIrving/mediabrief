import { useRef, useState } from "react"
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs"
import { Button } from "@/components/ui/button"
import { CopyRegular, ArrowDownloadRegular, ArrowClockwiseRegular } from "@fluentui/react-icons"
import { TelegramIcon } from "@/components/icons/TelegramIcon"
import { cn } from "@/lib/utils"
import { useI18n } from "@/i18n/I18nContext"
import type { ResultsState, ResultTab } from "./useTranscribe"

interface Props {
  results: ResultsState
  isProcessing: boolean
  onTab: (tab: ResultTab) => void
  onExport: () => void
  onRetry: () => void
  onSendTelegram: () => Promise<boolean>
  sendingTelegram: boolean
}

export function ResultsPanel({ results, isProcessing, onTab, onExport, onRetry, onSendTelegram, sendingTelegram }: Props) {
  const { t } = useI18n()
  const scriptRef = useRef<HTMLDivElement>(null)
  const summaryRef = useRef<HTMLDivElement>(null)
  const translationRef = useRef<HTMLDivElement>(null)
  const [copied, setCopied] = useState(false)
  const [sent, setSent] = useState(false)

  const sendTelegram = async () => {
    const ok = await onSendTelegram()
    if (ok) {
      setSent(true)
      setTimeout(() => setSent(false), 1500)
    }
  }

  const activeRef =
    results.activeTab === "script"
      ? scriptRef
      : results.activeTab === "summary"
        ? summaryRef
        : translationRef

  const copy = async () => {
    const el = activeRef.current
    const text = el?.textContent?.trim()
    if (!text) return
    try {
      await navigator.clipboard.writeText(text)
    } catch {
      const ta = document.createElement("textarea")
      ta.value = text
      ta.style.position = "fixed"
      ta.style.opacity = "0"
      document.body.appendChild(ta)
      ta.select()
      document.execCommand("copy")
      document.body.removeChild(ta)
    }
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  const tabs = [
    { value: "summary" as ResultTab, label: t("intelligent_summary"), hidden: false },
    { value: "script" as ResultTab, label: t("transcript_text"), hidden: false },
    {
      value: "translation" as ResultTab,
      label: t("translation"),
      hidden: !results.showTranslation,
    },
  ].filter((t) => !t.hidden)

  return (
    <div className="result-panel-inner">
      <Tabs
        value={results.activeTab}
        onValueChange={(v) => onTab(v as ResultTab)}
        className="result-tabs w-full"
      >
        <div className="result-tabs-head flex items-center px-4 pt-3 gap-2 flex-wrap">
          <TabsList className="border-b-0">
            {tabs.map((tab) => (
              <TabsTrigger key={tab.value} value={tab.value}>
                {tab.label}
              </TabsTrigger>
            ))}
          </TabsList>
          <div className="ml-auto flex items-center gap-1.5 pb-2">
            <Button
              variant="ghost"
              size="icon-sm"
              disabled={sendingTelegram}
              onClick={sendTelegram}
              title={t("send_telegram_button")}
              className={cn(sent && "text-[var(--success)]")}
            >
              {sent ? (
                <span className="text-xs font-medium text-[var(--success)]">{t("send_telegram_sent")}</span>
              ) : (
                <TelegramIcon className="h-3.5 w-3.5" />
              )}
            </Button>
            <Button
              variant="ghost"
              size="icon-sm"
              onClick={onExport}
              title={t("export_button")}
            >
              <ArrowDownloadRegular className="h-3.5 w-3.5" />
            </Button>
            {results.activeTab === "script" && (
              <Button
                variant="ghost"
                size="icon-sm"
                disabled={isProcessing}
                onClick={onRetry}
                title={t("retry")}
              >
                <ArrowClockwiseRegular className="h-3.5 w-3.5" />
              </Button>
            )}
            <Button
              variant="ghost"
              size="icon-sm"
              onClick={copy}
              title={t("copy")}
              className={cn(copied && "text-[var(--success)]")}
            >
              {copied ? (
                <span className="text-xs font-medium text-[var(--success)]">{t("completed")}</span>
              ) : (
                <CopyRegular className="h-3.5 w-3.5" />
              )}
            </Button>
          </div>
        </div>

        <TabsContent value="summary" className="result-content-pane mt-0 px-5 pb-6">
          <div
            className="md-content py-4"
            ref={summaryRef}
            dangerouslySetInnerHTML={{ __html: results.summaryHtml }}
          />
        </TabsContent>
        <TabsContent value="script" className="result-content-pane mt-0 px-5 pb-6">
          <div
            className="md-content py-4"
            ref={scriptRef}
            dangerouslySetInnerHTML={{ __html: results.scriptHtml }}
          />
        </TabsContent>
        <TabsContent value="translation" className="result-content-pane mt-0 px-5 pb-6">
          <div
            className="md-content py-4"
            ref={translationRef}
            dangerouslySetInnerHTML={{ __html: results.translationHtml }}
          />
        </TabsContent>
      </Tabs>
    </div>
  )
}
