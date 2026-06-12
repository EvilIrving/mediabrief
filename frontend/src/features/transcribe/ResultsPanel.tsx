import { useRef, useState } from "react"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs"
import { Button } from "@/components/ui/button"
import { CopyRegular, ArrowDownloadRegular, ArrowClockwiseRegular } from "@fluentui/react-icons"
import { cn } from "@/lib/utils"
import { useI18n } from "@/i18n/I18nContext"
import type { ResultsState, ResultTab } from "./useTranscribe"

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
    { value: "script" as ResultTab, label: t("transcript_text"), hidden: false },
    { value: "summary" as ResultTab, label: t("intelligent_summary"), hidden: false },
    {
      value: "translation" as ResultTab,
      label: t("translation"),
      hidden: !results.showTranslation,
    },
  ].filter((t) => !t.hidden)

  return (
    <div className="px-0">
      <Tabs
        value={results.activeTab}
        onValueChange={(v) => onTab(v as ResultTab)}
        className="w-full"
      >
        <div className="flex items-center border-b border-[var(--border-color)] px-4 pt-3 gap-2 flex-wrap">
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

        <TabsContent value="script" className="mt-0 px-5 pb-6">
          <ScrollArea className="h-[520px]">
            <div
              className="md-content py-4"
              ref={scriptRef}
              dangerouslySetInnerHTML={{ __html: results.scriptHtml }}
            />
          </ScrollArea>
        </TabsContent>
        <TabsContent value="summary" className="mt-0 px-5 pb-6">
          <ScrollArea className="h-[520px]">
            <div
              className="md-content py-4"
              ref={summaryRef}
              dangerouslySetInnerHTML={{ __html: results.summaryHtml }}
            />
          </ScrollArea>
        </TabsContent>
        <TabsContent value="translation" className="mt-0 px-5 pb-6">
          <ScrollArea className="h-[520px]">
            <div
              className="md-content py-4"
              ref={translationRef}
              dangerouslySetInnerHTML={{ __html: results.translationHtml }}
            />
          </ScrollArea>
        </TabsContent>
      </Tabs>
    </div>
  )
}
