import { useRef, useState } from "react"
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs"
import { Button } from "@/components/ui/button"
import { CopyRegular, ArrowDownloadRegular, ArrowClockwiseRegular, CheckmarkCircleRegular, PlayRegular, PauseRegular } from "@fluentui/react-icons"
import { TelegramIcon } from "@/components/icons/TelegramIcon"
import { cn } from "@/lib/utils"
import { useI18n } from "@/i18n/I18nContext"
import { api } from "@/lib/api"
import type { ResultsState, ResultTab } from "./useTranscribe"

interface Props {
  results: ResultsState
  isProcessing: boolean
  onTab: (tab: ResultTab) => void
  onExport: () => void
  onRetry: () => void
  onSendTelegram: () => Promise<boolean>
  sendingTelegram: boolean
  taskType?: string
  downloadFilename?: string
  fileSize?: number
  playSummary: () => void
  ttsLoading: boolean
  ttsPlaying: boolean
  ttsConfigured: boolean
}

function formatFileSize(bytes: number): string {
  if (bytes <= 0) return ''
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`
}

function DownloadResultCard({ filename, downloadUrl, fileSize }: { filename: string; downloadUrl: string; fileSize?: number }) {
  const { t } = useI18n()
  const sizeStr = fileSize ? formatFileSize(fileSize) : ''
  return (
    <div className="dwn-completed show">
      <CheckmarkCircleRegular className="inline h-5 w-5 mr-1.5" />
      <p className="dwn-completed-file">{filename}{sizeStr && <span className="text-[var(--text-dim)] text-sm ml-2">({sizeStr})</span>}</p>
      <Button variant="default" size="sm" asChild>
        <a href={downloadUrl} download={filename}>{t("download_file")}</a>
      </Button>
    </div>
  )
}

export function ResultsPanel({ results, isProcessing, onTab, onExport, onRetry, onSendTelegram, sendingTelegram, taskType, downloadFilename, fileSize, playSummary, ttsLoading, ttsPlaying, ttsConfigured }: Props) {
  const { t } = useI18n()
  const scriptRef = useRef<HTMLDivElement>(null)
  const summaryRef = useRef<HTMLDivElement>(null)
  const translationRef = useRef<HTMLDivElement>(null)
  const [copied, setCopied] = useState(false)
  const [sent, setSent] = useState(false)

  if (taskType === "download_only") {
    const downloadUrl = downloadFilename ? api.videoFileUrl(downloadFilename) : "#"
    return (
      <div className="result-panel-inner">
        <DownloadResultCard filename={downloadFilename || ""} downloadUrl={downloadUrl} fileSize={fileSize} />
      </div>
    )
  }

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
            {results.activeTab === "summary" && (
              <Button
                variant="ghost"
                size="icon-sm"
                disabled={ttsLoading || !ttsConfigured}
                onClick={playSummary}
                title={ttsConfigured ? t("play_summary_audio") : t("tts_config_required")}
              >
                {ttsLoading ? (
                  <span className="inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-current border-t-transparent" />
                ) : ttsPlaying ? (
                  <PauseRegular className="h-3.5 w-3.5" />
                ) : (
                  <PlayRegular className="h-3.5 w-3.5" />
                )}
              </Button>
            )}
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
