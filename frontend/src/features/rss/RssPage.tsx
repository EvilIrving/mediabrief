import { useEffect, useMemo, useRef, useState } from "react"
import { useNavigate } from "react-router-dom"
import { DataBarVerticalRegular, DocumentTextRegular, ArrowCircleDownRegular, MailInboxRegular, ListRegular, ArrowClockwiseRegular, RssRegular, GlobeSearchRegular, SearchRegular, StarRegular } from "@fluentui/react-icons"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Card } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { ErrorBanner } from "@/components/ErrorBanner"
import { api } from "@/lib/api"
import { rssReadStore, rssWriteStore } from "@/lib/db"
import type { ApiError, RssFeed } from "@/lib/types"
import { useAutoDismissError } from "@/hooks/useAutoDismissError"
import { useI18n } from "@/i18n/I18nContext"
import { useSettings } from "@/context/SettingsContext"
import { useTaskHandoff } from "@/context/TaskHandoff"
import { feedSummaries, mergeFeed, normalizeImportList, parseFeed, type ImportPreset } from "./rssUtils"
import { cn } from "@/lib/utils"

export function RssPage() {
  const { t } = useI18n()
  const navigate = useNavigate()
  const { appendModelFields } = useSettings()
  const { set: setHandoff } = useTaskHandoff()
  const { msg: error, show: showError, hide: hideError } = useAutoDismissError()

  const [feeds, setFeeds] = useState<RssFeed[]>([])
  const [feedUrl, setFeedUrl] = useState("")
  const [search, setSearch] = useState("")
  const [activeFeedId, setActiveFeedId] = useState("")
  const [addBusy, setAddBusy] = useState(false)
  const [importLabel, setImportLabel] = useState("")
  const [pendingDeleteFeed, setPendingDeleteFeed] = useState<string | null>(null)
  const [refreshingId, setRefreshingId] = useState("")
  const [creatingTask, setCreatingTask] = useState(false)
  const jsonInputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    rssReadStore().then(setFeeds).catch(() => setFeeds([]))
  }, [])

  const persist = async (next: RssFeed[]) => {
    setFeeds(next)
    await rssWriteStore(next)
  }

  const summaries = useMemo(() => feedSummaries(feeds), [feeds])
  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    return q ? summaries.filter((f) => (f.title || "").toLowerCase().includes(q)) : summaries
  }, [summaries, search])

  const effectiveActive = filtered.some((f) => f.id === activeFeedId) ? activeFeedId : filtered[0]?.id || ""
  const activeFeed = feeds.find((f) => f.id === effectiveActive)

  const totalEntries = summaries.reduce((s, f) => s + f.entry_count, 0)
  const totalNew = summaries.reduce((s, f) => s + f.new_count, 0)

  const subscribe = async () => {
    const url = feedUrl.trim()
    if (!url) {
      showError(t("rss_url_placeholder"))
      return
    }
    setAddBusy(true)
    hideError()
    try {
      const newFeed = await parseFeed(url, t("request_failed") as string)
      const current = await rssReadStore()
      const idx = current.findIndex((f) => f.id === newFeed.id || f.url === newFeed.url)
      if (idx >= 0) current[idx] = mergeFeed(current[idx], newFeed)
      else {
        ;(newFeed.entries || []).forEach((e) => { if (!e.processed) e.processed = "seen" })
        current.unshift(newFeed)
      }
      await persist(current)
      setFeedUrl("")
    } catch (e) {
      const err = e as { name?: string; message?: string }
      showError(t("subscribe_failed") + (err.name === "AbortError" ? (t("timeout") as string) : err.message))
    } finally {
      setAddBusy(false)
    }
  }

  const importJson = async (file: File) => {
    setImportLabel(t("adding") as string)
    hideError()
    try {
      const raw = await file.text()
      const data = JSON.parse(raw)
      const normalized = normalizeImportList(data, t("rss_json_invalid") as string)
      let current = await rssReadStore()
      const existingUrls = new Set(current.map((f) => (f.url || "").replace(/\/$/, "")))
      const pending = normalized.filter((f) => !existingUrls.has(f.url.replace(/\/$/, "")))
      const total = pending.length
      if (!total) {
        showError((t("imported_json_feeds") as (a: number, b: number) => string)(0, 0))
        return
      }
      let done = 0, imported = 0, failed = 0
      const parseWithRetry = async (preset: ImportPreset, tries = 3): Promise<RssFeed> => {
        let lastError: unknown
        for (let attempt = 1; attempt <= tries; attempt++) {
          try { return await parseFeed(preset.url, t("request_failed") as string) }
          catch (e) { lastError = e; if (attempt < tries) await new Promise((r) => setTimeout(r, 800 * attempt)) }
        }
        throw lastError
      }
      for (const preset of pending) {
        try {
          const newFeed = await parseWithRetry(preset)
          current = await rssReadStore()
          const idx = current.findIndex((f) => f.id === newFeed.id || f.url === newFeed.url)
          if (idx >= 0) current[idx] = mergeFeed(current[idx], newFeed)
          else {
            ;(newFeed.entries || []).forEach((e) => { if (!e.processed) e.processed = "seen" })
            current.unshift(newFeed)
          }
          await persist(current)
          imported++
        } catch { failed++ }
        finally { done++; setImportLabel((t("importing_json_feeds") as (a: number, b: number) => string)(done, total)) }
      }
      showError((t("imported_json_feeds") as (a: number, b: number) => string)(imported, failed))
    } catch (e) {
      showError(t("rss_import_failed") + (e as Error).message)
    } finally {
      setImportLabel("")
      if (jsonInputRef.current) jsonInputRef.current.value = ""
    }
  }

  const refreshFeed = async (id: string) => {
    const current = await rssReadStore()
    const idx = current.findIndex((f) => f.id === id)
    if (idx < 0) return
    setRefreshingId(id)
    try {
      const parsed = await parseFeed(current[idx].url, t("request_failed") as string)
      const merged = mergeFeed(current[idx], parsed)
      current[idx] = merged
      await persist(current)
      if (merged.new_count && merged.new_count > 0) {
        showError((t("found_new_items") as (n: number) => string)(merged.new_count))
      }
    } catch (e) {
      const err = e as { name?: string; message?: string }
      current[idx].last_error = err.name === "AbortError" ? (t("timeout") as string) : err.message
      await persist([...current])
      showError(t("refresh_failed") + current[idx].last_error)
    } finally { setRefreshingId("") }
  }

  const toggleFavorite = async (id: string) => {
    const current = await rssReadStore()
    const feed = current.find((f) => f.id === id)
    if (!feed) return
    feed.favorite = !feed.favorite
    await persist([...current])
  }

  const deleteFeed = async (id: string) => {
    const current = await rssReadStore()
    await persist(current.filter((f) => f.id !== id))
    if (activeFeedId === id) setActiveFeedId("")
    setPendingDeleteFeed(null)
  }

  const createTask = async (feedId: string, entryId: string, action: "summarize" | "download") => {
    if (creatingTask) return
    setCreatingTask(true)
    try {
      const current = await rssReadStore()
      const feed = current.find((f) => f.id === feedId)
      const entry = feed?.entries?.find((e) => e.id === entryId)
      if (!feed || !entry) throw new Error(t("feed_missing") as string)
      const fd = new FormData()
      fd.append("feed_id", feedId)
      fd.append("entry_id", entryId)
      fd.append("entry_json", JSON.stringify(entry))
      fd.append("action", action)
      appendModelFields(fd)
      const data = await api.rssCreateTask(fd).catch((err: ApiError) => {
        throw new Error(err.detail || (t("request_failed") as string))
      })
      entry.processed = action === "download" ? "downloaded" : "summarized"
      await persist([...current])
      setHandoff({
        taskId: data.task_id,
        source: { type: "rss", value: entry.link || entry.enclosure_url || "", title: entry.title || feed.title || "" },
      })
      navigate("/transcribe")
    } catch (e) {
      showError(t("task_creation_failed") + (e as Error).message)
    } finally { setCreatingTask(false) }
  }

  const activeEntries = useMemo(() => {
    if (!activeFeed) return []
    return (activeFeed.entries || []).slice().sort((a, b) => (b.published || "").localeCompare(a.published || ""))
  }, [activeFeed])

  return (
    <div className="list-page">
      <div className="page-topbar">
        <div className="page-topbar-left">
          <h1 className="page-topbar-title">RSS</h1>
          <span className="page-topbar-sub">{t("rss_page_subtitle")}</span>
        </div>
        <div className="page-topbar-actions">
          <Button variant="outline" size="sm" asChild>
            <a href={`${import.meta.env.BASE_URL}rss_feeds_template.json`} download>{t("download_json_template")}</a>
          </Button>
          <Button
            variant="primary-sm"
            disabled={!!importLabel}
            loading={!!importLabel}
            onClick={() => jsonInputRef.current?.click()}
          >
            {importLabel || t("import_json_feeds")}
          </Button>
          <input
            ref={jsonInputRef}
            type="file"
            accept="application/json,.json"
            hidden
            onChange={(e) => { const f = e.target.files?.[0]; if (f) void importJson(f) }}
          />
        </div>
      </div>

      <ErrorBanner msg={error} />

      <div className="rss-add-row">
        <div className="url-wrap">
          <RssRegular className="url-icon h-4 w-4" />
          <Input
            type="url"
            className="url-input"
            placeholder={t("rss_url_placeholder")}
            value={feedUrl}
            onChange={(e) => setFeedUrl(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") void subscribe() }}
          />
        </div>
        <Button variant="default" size="lg" className="h-10 shrink-0" disabled={addBusy} loading={addBusy} onClick={() => void subscribe()}>
          {addBusy ? t("adding") : t("subscribe")}
        </Button>
      </div>

      {summaries.length > 0 && (
        <div className="rss-summary-bar">
          <DataBarVerticalRegular className="h-3.5 w-3.5 text-[var(--accent-dim)]" />
          <span>{(t("rss_total") as (a: number, b: number, c: number) => string)(summaries.length, totalEntries, totalNew)}</span>
        </div>
      )}

      {summaries.length > 0 && (
        <div className="rss-search-row">
          <div className="url-wrap">
            <SearchRegular className="url-icon h-4 w-4" />
            <Input
              type="search"
              className="url-input"
              placeholder={t("rss_search_placeholder")}
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              autoComplete="off"
            />
          </div>
        </div>
      )}

      <div className="split-page">
        <div className="feed-list split-list">
          {!summaries.length ? (
            <div className="rss-empty">
              <GlobeSearchRegular />
              <p>{t("rss_empty")}</p>
            </div>
          ) : !filtered.length ? (
            <div className="rss-empty">
              <SearchRegular />
              <p>{t("rss_no_match")}</p>
            </div>
          ) : (
            filtered.map((f) => {
              const lastChecked = f.last_checked ? new Date(f.last_checked).toLocaleString() : (t("never_updated") as string)
              return (
                <Card
                  key={f.id}
                  className={cn("cursor-pointer p-3", f.id === effectiveActive && "border-[var(--accent)] bg-[rgba(var(--accent-rgb),.06)]")}
                  onClick={() => setActiveFeedId(f.id)}
                >
                  <div className="flex justify-between items-start gap-2">
                    <div className="min-w-0 flex-1">
                      <div className="feed-card-title">
                        {f.title}{" "}
                        {f.new_count > 0 && (
                          <Badge variant="new">{(t("new_count") as (n: number) => string)(f.new_count)}</Badge>
                        )}
                      </div>
                      <div className="feed-card-meta">
                        <Badge variant="feed">{String(f.type || "rss").toUpperCase()}</Badge>
                        <span>{(t("item_count") as (n: number) => string)(f.entry_count)}</span>
                        <span className="text-[10px]">{t("updated")} {lastChecked}</span>
                        {f.last_error && (
                          <span className="feed-card-error" title={f.last_error}>{t("rss_refresh_failed")}</span>
                        )}
                      </div>
                    </div>
                    <div className="feed-card-actions" onClick={(e) => e.stopPropagation()}>
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        className={cn("h-7 w-7", f.favorite && "text-[var(--star)]")}
                        title={f.favorite ? (t("unfavorite") as string) : (t("favorite") as string)}
                        onClick={() => void toggleFavorite(f.id)}
                      >
                        <StarRegular className="h-3.5 w-3.5" fill={f.favorite ? "currentColor" : "none"} />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        className="h-7 w-7"
                        disabled={refreshingId === f.id}
                        loading={refreshingId === f.id}
                        onClick={() => void refreshFeed(f.id)}
                      >
                        {refreshingId !== f.id && <ArrowClockwiseRegular className="h-3.5 w-3.5" />}
                      </Button>
                      {pendingDeleteFeed === f.id ? (
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-6 px-2 text-xs text-[var(--error)] border border-[var(--error)] hover:bg-[var(--error)] hover:text-white"
                          onClick={() => void deleteFeed(f.id)}
                          onBlur={() => setPendingDeleteFeed(null)}
                          autoFocus
                        >
                          {t("confirm_delete")}
                        </Button>
                      ) : (
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-6 px-2 text-xs text-[var(--text-dim)] hover:text-[var(--error)]"
                          onClick={() => setPendingDeleteFeed(f.id)}
                        >
                          {t("delete")}
                        </Button>
                      )}
                    </div>
                  </div>
                </Card>
              )
            })
          )}
        </div>

        <div className="split-detail rss-entry-pane">
          {!activeFeed ? (
            <div className="detail-empty">
              <ListRegular />
              <p>{t("rss_entry_empty")}</p>
            </div>
          ) : (
            <>
              <div className="detail-head">
                <div className="detail-title">{activeFeed.title || "RSS"}</div>
                <div className="detail-meta">
                  <Badge variant="feed">{String(activeFeed.type || "rss").toUpperCase()}</Badge>
                  <span>{(t("item_count") as (n: number) => string)(activeEntries.length)}</span>
                  <span>{t("updated")} {activeFeed.last_checked ? new Date(activeFeed.last_checked).toLocaleString() : (t("never_updated") as string)}</span>
                </div>
              </div>
              {activeEntries.length ? (
                activeEntries.map((e) => {
                  const isSummarized = e.processed === "summarized"
                  const isDownloaded = e.processed === "downloaded"
                  const hasAudio = Boolean(e.enclosure_url)
                  return (
                    <div className="entry-item" key={e.id}>
                      <span className="entry-title" title={e.title}>
                        {isSummarized && <DocumentTextRegular className="inline h-3 w-3 mr-1 text-[var(--text-dim)]" />}
                        {!isSummarized && isDownloaded && <ArrowCircleDownRegular className="inline h-3 w-3 mr-1 text-[var(--text-dim)]" />}
                        {e.title}
                      </span>
                      <div className="entry-actions">
                        <Button variant="primary-sm" disabled={creatingTask} loading={creatingTask} onClick={() => void createTask(activeFeed.id, e.id, "summarize")}>
                          {isSummarized ? t("resummarize") : t("summarize")}
                        </Button>
                        {hasAudio && (
                          <Button variant="outline" size="sm" disabled={creatingTask} onClick={() => void createTask(activeFeed.id, e.id, "download")}>
                            {isDownloaded ? t("redownload") : t("nav_download")}
                          </Button>
                        )}
                      </div>
                    </div>
                  )
                })
              ) : (
                <div className="detail-empty">
                  <MailInboxRegular />
                  <p>{t("no_entries")}</p>
                </div>
              )}
            </>
          )}
        </div>
      </div>

    </div>
  )
}
