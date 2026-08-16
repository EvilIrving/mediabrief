import { useEffect, useMemo, useRef, useState } from "react"
import { LinkRegular, CheckmarkCircleRegular } from "@fluentui/react-icons"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs"
import { ScrollArea } from "@/components/ui/scroll-area"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { ErrorBanner } from "@/components/ErrorBanner"
import { api } from "@/lib/api"
import type { ApiError, DownloadFormatsResponse, MediaFormat, TaskPayload } from "@/lib/types"
import { useAutoDismissError } from "@/hooks/useAutoDismissError"
import { useI18n } from "@/i18n/I18nContext"
import { useSettings } from "@/context/SettingsContext"
import { cn, clampPct, translate } from "@/lib/utils"
import { presentFormats, type FormatHint } from "./downloadFormats"

type DwnTab = "video" | "audio" | "subtitle"

const HINT_KEYS: Record<FormatHint, string> = {
  compatible: "fmt_hint_compatible",
  smaller: "fmt_hint_smaller",
}

export function DownloadPage() {
  const { t } = useI18n()
  const { browserCookiesAutoDetect } = useSettings()
  const { msg: error, show: showError, hide: hideError } = useAutoDismissError()

  const [url, setUrl] = useState("")
  const [detecting, setDetecting] = useState(false)
  const [data, setData] = useState<DownloadFormatsResponse | null>(null)
  const [tab, setTab] = useState<DwnTab>("video")
  const [videoFmt, setVideoFmt] = useState("bestvideo+bestaudio/best")
  const [audioFmt, setAudioFmt] = useState("bestaudio/best")
  const [audioContainer, setAudioContainer] = useState("m4a")
  const [subLang, setSubLang] = useState("")
  const [phase, setPhase] = useState<"formats" | "fallback" | "progress" | "completed" | "none">("none")
  const [fallbackWarning, setFallbackWarning] = useState("")
  const [progress, setProgress] = useState({ pct: 0, stageName: "", msg: "" })
  const [completed, setCompleted] = useState({ filename: "", fileUrl: "#" })

  const pollTimerRef = useRef<number | null>(null)
  const taskIdRef = useRef<string | null>(null)

  const tr = (key: string, fallback = '') => translate(t, key, fallback)

  const stopPolling = () => {
    if (pollTimerRef.current !== null) {
      window.clearTimeout(pollTimerRef.current)
      pollTimerRef.current = null
    }
  }
  useEffect(() => () => stopPolling(), [])

  const videoFormats = data?.video_formats || []
  const audioFormats = data?.audio_formats || []
  const subLangs = useMemo(() => {
    const subs = data?.subtitles || {}
    return [...new Set([...(subs.manual || []), ...(subs.auto || [])])].sort()
  }, [data])
  const manualSet = useMemo(() => new Set(data?.subtitles?.manual || []), [data])

  const detect = async () => {
    const trimmed = url.trim()
    if (!trimmed) {
      showError(t("url_required"))
      return
    }
    setDetecting(true)
    hideError()
    setData(null)
    setPhase("none")
    try {
      const fd = new FormData()
      fd.append("url", trimmed)
      if (browserCookiesAutoDetect) fd.append("auto_detect_browser_cookies", "true")
      const resp = await api.downloadFormats(fd).catch((err: ApiError) => {
        throw new Error(err.detail || (t("request_failed") as string))
      })
      setData(resp)
      setVideoFmt("bestvideo+bestaudio/best")
      setAudioFmt("bestaudio/best")
      const subs = resp.subtitles || {}
      const all = [...new Set([...(subs.manual || []), ...(subs.auto || [])])].sort()
      const prefer = ["en", "en-orig", "zh-Hans", "zh-Hant", "zh"]
      setSubLang(prefer.find((p) => all.includes(p)) || all[0] || "")
      setTab("video")
      setPhase("formats")
    } catch (e) {
      setFallbackWarning((e as Error).message || "")
      setPhase("fallback")
    } finally {
      setDetecting(false)
    }
  }

  const startDownload = async (type: DwnTab) => {
    const trimmed = url.trim()
    if (!trimmed) return
    setPhase("progress")
    setProgress({ pct: 0, stageName: "", msg: "" })
    try {
      const fd = new FormData()
      fd.append("url", trimmed)
      if (browserCookiesAutoDetect) fd.append("auto_detect_browser_cookies", "true")
      let call: Promise<{ task_id: string }>
      if (type === "video") {
        fd.append("format_id", videoFmt)
        fd.append("filename", data?.title || "")
        call = api.downloadVideo(fd)
      } else if (type === "audio") {
        fd.append("format_id", audioFmt)
        fd.append("filename", data?.title || "")
        fd.append("audio_format", audioContainer)
        call = api.downloadAudio(fd)
      } else {
        fd.append("lang", subLang)
        fd.append("filename", data?.title || "")
        call = api.downloadSubtitles(fd)
      }
      const resp = await call.catch((err: ApiError) => {
        throw new Error(err.detail || (t("request_failed") as string))
      })
      taskIdRef.current = resp.task_id
      startPolling()
    } catch (e) {
      showError(t("download_failed") + (e as Error).message)
      setPhase("none")
    }
  }

  const applyDownloadTask = (task: TaskPayload) => {
    const pct = clampPct(task.progress || 0)
    const stageKey = task.current_stage || ''
    const stageLabel = stageKey ? tr(`stage.${stageKey}.label`, tr(`stage.${stageKey}.name`, stageKey)) : ''
    setProgress({
      pct,
      stageName: stageLabel || '',
      msg: task.message ? tr(task.message) : '',
    })
    if (task.status === "completed") {
      stopPolling()
      setCompleted({
        filename: task.filename || "",
        fileUrl: api.videoFileUrl(task.filename || ""),
      })
      setPhase("completed")
    } else if (task.status === "error") {
      stopPolling()
      showError(task.error_code ? tr(`error.${task.error_code}`, t("download_failed") as string) : task.error || (t("download_failed") as string))
      setPhase("none")
    }
  }

  const startPolling = () => {
    const taskId = taskIdRef.current
    if (!taskId) return
    stopPolling()

    const tick = async () => {
      try {
        const task = await api.taskStatus(taskId)
        applyDownloadTask(task)
        if (task.status !== "completed" && task.status !== "error" && task.status !== "cancelled") {
          pollTimerRef.current = window.setTimeout(tick, 1500)
        }
      } catch (e) {
        pollTimerRef.current = window.setTimeout(tick, 2000)
      }
    }
    void tick()
  }

  return (
    <div>
      <div className="page-topbar">
        <div className="page-topbar-left">
          <h1 className="page-topbar-title">{t("download_page_title")}</h1>
          <span className="page-topbar-sub">{t("download_page_subtitle")}</span>
        </div>
      </div>

      <ErrorBanner msg={error} />

      <form
        onSubmit={(e) => {
          e.preventDefault()
          if (!detecting) void detect()
        }}
        autoComplete="off"
        noValidate
      >
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
            variant="default"
            size="sm"
            className="shrink-0"
            disabled={detecting}
            loading={detecting}
          >
            {detecting ? t("detecting") : t("detect")}
          </Button>
        </div>
      </form>

      {phase === "fallback" && (
        <div className="rounded-lg border border-[var(--warning-border,#d4a017)] bg-[var(--warning-bg,rgba(212,160,23,0.06))] p-4 mt-4">
          <p className="text-sm text-[var(--text-dim)] mb-1">{t("formats_unavailable")}</p>
          {fallbackWarning && <p className="text-xs text-[var(--text-dim)] opacity-70 mb-3">{fallbackWarning}</p>}
          <div className="flex flex-col gap-2">
            <Button className="w-full justify-center" onClick={() => void startDownload("video")}>
              {t("direct_download_video_btn")}
            </Button>
            <Button variant="secondary" className="w-full justify-center" onClick={() => void startDownload("audio")}>
              {t("direct_download_audio_btn")}
            </Button>
            <Button variant="secondary" className="w-full justify-center" onClick={() => void startDownload("subtitle")}>
              {t("direct_download_subtitle_btn")}
            </Button>
          </div>
        </div>
      )}

      {phase === "formats" && data && (
        <Tabs value={tab} onValueChange={(v) => setTab(v as DwnTab)}>
          <TabsList>
            <TabsTrigger value="video">{t("video")}</TabsTrigger>
            <TabsTrigger value="audio">{t("audio")}</TabsTrigger>
            <TabsTrigger value="subtitle">{t("subtitle_file")}</TabsTrigger>
          </TabsList>

          <TabsContent value="video">
            <p className="dwn-field-note">{t("choose_quality")}</p>
            <FormatList formats={videoFormats} selected={videoFmt} onSelect={setVideoFmt} kind="video" t={t} />
            <Button className="w-full justify-center mt-3" onClick={() => void startDownload("video")}>
              {t("download_video_btn")}
            </Button>
          </TabsContent>

          <TabsContent value="audio">
            <p className="dwn-field-note">{t("choose_audio_quality")}</p>
            {audioFormats.length ? (
              <FormatList formats={audioFormats} selected={audioFmt} onSelect={setAudioFmt} kind="audio" t={t} />
            ) : (
              <div className="rounded-lg border border-[var(--border-color)] p-8 text-center text-sm text-[var(--text-dim)]">
                {t("audio_unavailable")}
              </div>
            )}
            <div className="dwn-inline-field mt-3">
              <span>{t("output_format")}</span>
              <Select value={audioContainer} onValueChange={setAudioContainer}>
                <SelectTrigger className="w-[140px]">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="m4a">m4a (AAC)</SelectItem>
                  <SelectItem value="mp3">mp3</SelectItem>
                  <SelectItem value="opus">opus</SelectItem>
                  <SelectItem value="flac">flac</SelectItem>
                  <SelectItem value="wav">wav</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <Button
              className="w-full justify-center mt-3"
              disabled={!audioFormats.length}
              onClick={() => void startDownload("audio")}
            >
              {t("download_audio_btn")}
            </Button>
          </TabsContent>

          <TabsContent value="subtitle">
            {subLangs.length ? (
              <>
                <div className="dwn-sub-info">
                  {(data.subtitles?.manual?.length ?? 0) > 0 && (
                    <span>{t("manual_subtitles")}{data.subtitles!.manual!.join(", ")}</span>
                  )}
                  {(data.subtitles?.auto?.length ?? 0) > 0 && (
                    <span>{t("auto_subtitles")}{data.subtitles!.auto!.join(", ")}</span>
                  )}
                </div>
                <div className="dwn-subtitle-row">
                  <span>{t("subtitle_language")}</span>
                  <Select value={subLang} onValueChange={setSubLang}>
                    <SelectTrigger className="flex-1">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {subLangs.map((l) => (
                        <SelectItem key={l} value={l}>
                          {l}{manualSet.has(l) ? ` (${t("manual")})` : ` (${t("auto")})`}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <Button className="w-full justify-center mt-3" onClick={() => void startDownload("subtitle")}>
                  {t("download_subtitle_btn")}
                </Button>
              </>
            ) : (
              <p className="dwn-sub-empty">{t("no_subtitles")}</p>
            )}
          </TabsContent>
        </Tabs>
      )}

      {phase === "progress" && (
        <div className="progress-panel show">
          <div className="prog-top">
            <div className="prog-top-left">
              <span>{t("downloading")}</span>
            </div>
            <span>{Math.round(progress.pct)}%</span>
          </div>
          <div className="prog-bar">
            <div className="prog-fill" style={{ width: `${progress.pct}%` }} />
          </div>
        </div>
      )}

      {phase === "completed" && (
        <div className="dwn-completed show">
          <p className="dwn-completed-title">
            <CheckmarkCircleRegular className="inline h-5 w-5 mr-1.5" />
            {t("completed")}
          </p>
          <p className="dwn-completed-file">{completed.filename}</p>
          <Button variant="default" size="sm" asChild>
            <a href={completed.fileUrl}>{t("download_file")}</a>
          </Button>
        </div>
      )}

      <p className="inline-info">{t("copyright_notice")}</p>
    </div>
  )
}

function FormatList({
  formats,
  selected,
  onSelect,
  kind,
  t,
}: {
  formats: MediaFormat[]
  selected: string
  onSelect: (id: string) => void
  kind: "video" | "audio"
  t: (key: string) => unknown
}) {
  const rows = presentFormats(formats, kind)
  return (
    <ScrollArea className="fmt-scroll max-h-[300px] rounded-lg border border-[var(--border-color)]">
      {rows.map((row) => {
        const hint = row.hint ? String(t(HINT_KEYS[row.hint])) : ""
        const title = row.isAuto
          ? String(t(kind === "video" ? "fmt_best_video" : "fmt_best_audio"))
          : [row.title, hint].filter(Boolean).join(" ")
        return (
          <div
            key={row.id}
            className={cn(
              "fmt-item",
              row.id === selected && "selected"
            )}
            onClick={() => onSelect(row.id)}
          >
            <div className="fmt-main">
              <span className="fmt-name">{title}</span>
            </div>
            <span className="fmt-size">{row.sizeLabel}</span>
          </div>
        )
      })}
    </ScrollArea>
  )
}
