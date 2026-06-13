import { useEffect, useRef, useState } from "react"
import { useLocation } from "react-router-dom"
import { ArrowUploadRegular, LinkRegular } from "@fluentui/react-icons"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { ErrorBanner } from "@/components/ErrorBanner"
import { useI18n } from "@/i18n/I18nContext"
import { useTaskHandoff } from "@/context/TaskHandoff"
import { useTranscribe } from "./useTranscribe"
import { SettingsBar } from "./SettingsBar"
import { ProgressPanel } from "./ProgressPanel"
import { ResultsPanel } from "./ResultsPanel"

const UPLOAD_ACCEPT = ".txt,.mp3,.mp4,.m4a,.wav,.webm,.mkv,.ogg,.flac"

export function TranscribePage() {
  const { t } = useI18n()
  const tr = useTranscribe()
  const { take } = useTaskHandoff()
  const location = useLocation()
  const [url, setUrl] = useState("")
  const [dragover, setDragover] = useState(false)
  const [cancelHover, setCancelHover] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (location.pathname !== "/transcribe") return
    const pending = take()
    if (pending) {
      tr.adoptRssTask(pending.taskId, pending.source)
      return
    }
    void tr.recoverActiveTask()
  }, [location.pathname, take, tr.adoptRssTask, tr.recoverActiveTask])

  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    void tr.startTranscription(url)
  }

  const onFiles = (files: FileList | null) => {
    if (files && files[0]) void tr.startFileUpload(files[0])
  }

  const isProcessing = tr.isProcessing

  return (
    <div>
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
            />
          </div>
          <Button
            type="submit"
            variant={isProcessing && cancelHover ? "destructive" : "default"}
            size="sm"
            className={`shrink-0 w-[140px] ${isProcessing && cancelHover ? "bg-[var(--error)] hover:bg-[var(--error)] text-white" : ""}`}
            onMouseEnter={() => isProcessing && setCancelHover(true)}
            onMouseLeave={() => setCancelHover(false)}
          >
            {isProcessing && !cancelHover && <span className="spinner" />}
            {isProcessing && cancelHover ? t("cancel") : isProcessing ? t("processing") : t("start_transcription")}
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
            if (!isProcessing) setDragover(true)
          }}
          onDragLeave={() => setDragover(false)}
          onDrop={(e) => {
            e.preventDefault()
            setDragover(false)
            if (!isProcessing) onFiles(e.dataTransfer.files)
          }}
          style={isProcessing ? { pointerEvents: "none", opacity: 0.65 } : undefined}
        >
          <p className="upload-or">{t("upload_or")}</p>
          <p className="upload-formats">{t("upload_formats")}</p>
          <Button
            type="button"
            variant="outline"
            disabled={isProcessing}
            className="gap-2"
          >
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

      <div className="result-panel">
        {tr.phase === "empty" && (
          <div className="empty-state">
            <span className="es-icon">
              <LinkRegular className="h-9 w-9 text-[var(--text-dim)]" />
            </span>
            <span className="es-text">{t("empty_hint")}</span>
          </div>
        )}
        {tr.phase === "progress" && <ProgressPanel progress={tr.progress} onCancel={() => void tr.cancelTask()} />}
        {tr.phase === "results" && (
          <ResultsPanel
            results={tr.results}
            isProcessing={isProcessing}
            onTab={tr.setActiveTab}
            onExport={() => void tr.exportContent()}
            onRetry={() => void tr.retryTranscription()}
          />
        )}
      </div>
    </div>
  )
}
