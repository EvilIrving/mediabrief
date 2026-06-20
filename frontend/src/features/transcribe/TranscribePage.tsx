import { useRef, useState } from "react"
import { ArrowUploadRegular, LinkRegular } from "@fluentui/react-icons"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { ErrorBanner } from "@/components/ErrorBanner"
import { useI18n } from "@/i18n/I18nContext"
import { useTranscribe } from "./useTranscribe"
import { SettingsBar } from "./SettingsBar"
import { ProgressPanel } from "./ProgressPanel"
import { ResultsPanel } from "./ResultsPanel"
import { QueuePanel } from "./QueuePanel"

const UPLOAD_ACCEPT = ".txt,.mp3,.mp4,.m4a,.wav,.webm,.mkv,.ogg,.flac"

export function TranscribePage() {
  const { t } = useI18n()
  const tr = useTranscribe()
  const [url, setUrl] = useState("")
  const [dragover, setDragover] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)

  const doSubmit = async () => {
    const ok = await tr.enqueueUrl(url)
    if (ok) setUrl("")
  }

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    void doSubmit()
  }

  const onFiles = (files: FileList | null) => {
    if (files && files[0]) void tr.enqueueFile(files[0])
  }

  // 取消当前正在查看的处理中任务（若它是一个队列项）。
  const cancelDisplayed = () => {
    const item = tr.items.find((i) => i.task_id === tr.displayedTaskId)
    if (item) void tr.cancelItem(item)
  }
  const hasDetail = tr.phase !== "empty"

  return (
    <div className={`transcribe-page${hasDetail ? " transcribe-page-detail" : ""}`}>
      <div className="transcribe-list">
        <div className="page-topbar">
          <div className="page-topbar-left">
            <h1 className="page-topbar-title">{t("title")}</h1>
            <span className="page-topbar-sub">{t("subtitle")}</span>
          </div>
        </div>

        <form onSubmit={submit} autoComplete="off" noValidate>
          <div className="input-row">
            <div className="url-wrap">
              <LinkRegular className="url-icon h-4 w-4" />
              <Input
                type="url"
                className="url-input"
                placeholder={t("video_url_placeholder")}
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                onKeyDown={(e) => {
                  if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
                    e.preventDefault()
                    void doSubmit()
                  }
                }}
              />
            </div>
            <Button type="submit" variant="default" size="sm" className="shrink-0 w-[140px]">
              {t("start_transcription")}
            </Button>
          </div>
        </form>

        <div className="upload-section">
          <div
            className={`upload-zone${dragover ? " dragover" : ""}`}
            tabIndex={0}
            role="button"
            aria-label={t("upload_files_btn")}
            onClick={() => fileRef.current?.click()}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") fileRef.current?.click()
            }}
            onDragOver={(e) => {
              e.preventDefault()
              setDragover(true)
            }}
            onDragLeave={() => setDragover(false)}
            onDrop={(e) => {
              e.preventDefault()
              setDragover(false)
              onFiles(e.dataTransfer.files)
            }}
          >
            <p className="upload-or">{t("upload_or")}</p>
            <p className="upload-formats">{t("upload_formats")}</p>
            <Button type="button" variant="outline" className="gap-2">
              <ArrowUploadRegular className="h-3.5 w-3.5" />
              {t("upload_files_btn")}
            </Button>
          </div>
          <input
            ref={fileRef}
            type="file"
            accept={UPLOAD_ACCEPT}
            hidden
            onChange={(e) => onFiles(e.target.files)}
          />
        </div>

        <ErrorBanner msg={tr.error} />

        <SettingsBar />

        <QueuePanel
          items={tr.items}
          displayedTaskId={tr.displayedTaskId}
          cancellingIds={tr.cancellingIds}
          onSelect={tr.selectItem}
          onCancel={tr.cancelItem}
          onRemove={tr.removeItem}
          onRetry={tr.retryItem}
          onClear={tr.clearCompleted}
        />
      </div>

      {hasDetail && (
        <div className="transcribe-detail">
          <div className="result-panel">
            {tr.phase === "progress" && <ProgressPanel progress={tr.progress} onCancel={cancelDisplayed} />}
            {tr.phase === "results" && (
              <ResultsPanel
                results={tr.results}
                isProcessing={tr.isProcessing}
                onTab={tr.setActiveTab}
                onExport={() => void tr.exportContent()}
                onRetry={() => void tr.retryTranscription()}
                onSendTelegram={tr.sendToTelegram}
                sendingTelegram={tr.sendingTelegram}
                taskType={tr.taskType}
                downloadFilename={tr.downloadFilename}
                fileSize={tr.fileSize}
                playSummary={tr.playSummary}
                ttsLoading={tr.ttsLoading}
                ttsPlaying={tr.ttsPlaying}
                ttsConfigured={tr.ttsConfigured}
              />
            )}
          </div>
        </div>
      )}
    </div>
  )
}
