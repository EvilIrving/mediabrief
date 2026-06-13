import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { DataBarVerticalRegular, DocumentTextRegular, ArrowCircleDownRegular, MailInboxRegular, ListRegular, ArrowClockwiseRegular, RssRegular, GlobeSearchRegular, SearchRegular, StarRegular } from "@fluentui/react-icons"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Card } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { ErrorBanner } from "@/components/ErrorBanner"
import { api } from "@/lib/api"
import { useAutoDismissError } from "@/hooks/useAutoDismissError"
import { useI18n } from "@/i18n/I18nContext"
import { useSettings } from "@/context/SettingsContext"
import { feedSummaries, normalizeImportList, mergeFeedMetadata, rememberFeedMeta, forgetFeedMeta, type ImportPreset } from "./rssUtils"
import { cn } from "@/lib/utils"
import type { ApiError, QueueState, RssFeed } from "@/lib/types"

/** 从队列状态推导每一条目的前端展示状态 */
type EntryQueueStatus = "idle" | "queued" | "processing"

function sortFeeds(all: RssFeed[]): RssFeed[] {
  return [...(all || [])].sort((a, b) => {
    const favDiff = (b.favorite ? 1 : 0) - (a.favorite ? 1 : 0)
    if (favDiff) return favDiff
    return String(b.added_at || "").localeCompare(String(a.added_at || ""))
  })
}

export function RssPage() {
  const { t } = useI18n()
  const { appendModelFields } = useSettings()
  const { msg: error, show: showError, hide: hideError } = useAutoDismissError()

  const [feeds, setFeeds] = useState<RssFeed[]>([])
  const [feedUrl, setFeedUrl] = useState("")
  const [search, setSearch] = useState("")
  const [topicFilter, setTopicFilter] = useState("all")
  const [regionFilter, setRegionFilter] = useState("all")
  const [activeFeedId, setActiveFeedId] = useState("")
  const [addBusy, setAddBusy] = useState(false)
  const [importLabel, setImportLabel] = useState("")
  const [pendingDeleteFeed, setPendingDeleteFeed] = useState<string | null>(null)
  const [refreshingId, setRefreshingId] = useState("")

  // 后端管理的队列状态（通过 SSE 实时同步）
  const [qState, setQState] = useState<QueueState>({ queue_name: "tasks", items: [], processing: null, pending_count: 0 })
  const esRef = useRef<EventSource | null>(null)
  const lastCompletedRef = useRef(0) // 用于检测新完成项 → 刷新 feeds

  const jsonInputRef = useRef<HTMLInputElement>(null)

  // ── Feed 数据 ────────────────────────────────────────────────

  const loadFeeds = useCallback(async () => {
    try {
      const { feeds: all } = await api.rssFeeds()
      setFeeds(sortFeeds(mergeFeedMetadata(all || [])))
    } catch {
      setFeeds([])
    }
  }, [])

  const loadFeedsSilent = useCallback(async () => {
    try {
      const { feeds: all } = await api.rssFeeds()
      setFeeds(sortFeeds(mergeFeedMetadata(all || [])))
    } catch { }
  }, [])

  // ── 队列 SSE 订阅 ────────────────────────────────────────────

  const startQueueSSE = useCallback(() => {
    if (esRef.current) esRef.current.close()
    const es = new EventSource(api.queueStreamUrl("tasks"))
    esRef.current = es
    es.onmessage = (ev) => {
      try {
        const state = JSON.parse(ev.data) as QueueState
        if ((state as any).type === "heartbeat") return
        setQState(state)
        // 检测到新完成项 → 刷新 feeds（标记已处理）
        const completed = state.items.filter((i) => i.status === "completed").length
        if (completed > lastCompletedRef.current) {
          lastCompletedRef.current = completed
          void loadFeedsSilent()
        }
      } catch { /* ignore malformed frames */ }
    }
    es.onerror = () => {
      // SSE 断连后自动重连（浏览器行为），不额外处理
    }
  }, [loadFeedsSilent])

  const syncQueueState = useCallback(async () => {
    try {
      const state = await api.queueState("tasks")
      setQState(state)
      lastCompletedRef.current = state.items.filter((i) => i.status === "completed").length
    } catch {
      /* ignore */
    }
  }, [])

  useEffect(() => {
    void loadFeeds()
    void syncQueueState()
    startQueueSSE()
    return () => {
      if (esRef.current) { esRef.current.close(); esRef.current = null }
    }
  }, [loadFeeds, startQueueSSE, syncQueueState])

  // ── 队列状态 → 条目前端映射 ──────────────────────────────────

  const entryQueueMap = useMemo(() => {
    const map: Record<string, EntryQueueStatus> = {}
    for (const item of qState.items) {
      const key = `${item.payload?.feed_id}:${item.payload?.entry_id}`
      if (item.status === "processing") map[key] = "processing"
      else if (item.status === "queued") map[key] = "queued"
    }
    return map
  }, [qState])

  // ── 衍生数据 ─────────────────────────────────────────────────

  const summaries = useMemo(() => feedSummaries(feeds), [feeds])
  const topicOptions = useMemo(() => {
    const seen = new Set<string>()
    const items: string[] = []
    for (const feed of summaries) {
      const value = (feed.topic || "").trim()
      if (value && !seen.has(value)) {
        seen.add(value)
        items.push(value)
      }
    }
    return items
  }, [summaries])
  const regionOptions = useMemo(() => {
    const seen = new Set<string>()
    const items: string[] = []
    for (const feed of summaries) {
      const value = (feed.region || "").trim()
      if (value && !seen.has(value)) {
        seen.add(value)
        items.push(value)
      }
    }
    return items
  }, [summaries])
  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    const byText = q
      ? summaries.filter((f) => [f.title, f.topic, f.region, f.type].join("\n").toLowerCase().includes(q))
      : summaries
    return byText.filter((f) => {
      const topicOk = topicFilter === "all" || (f.topic || "") === topicFilter
      const regionOk = regionFilter === "all" || (f.region || "") === regionFilter
      return topicOk && regionOk
    })
  }, [summaries, search, topicFilter, regionFilter])

  const effectiveActive = filtered.some((f) => f.id === activeFeedId) ? activeFeedId : filtered[0]?.id || ""
  const activeFeed = feeds.find((f) => f.id === effectiveActive)

  const totalEntries = summaries.reduce((s, f) => s + f.entry_count, 0)
  const totalNew = summaries.reduce((s, f) => s + f.new_count, 0)

  // ── 入队 ─────────────────────────────────────────────────────

  const enqueueTask = useCallback(async (feedId: string, entryId: string, action: "summarize" | "download") => {
    const key = `${feedId}:${entryId}`
    if (entryQueueMap[key]) return // 已在队列中

    try {
      const feed = feeds.find((f) => f.id === feedId)
      const entry = feed?.entries?.find((e) => e.id === entryId)
      if (!feed || !entry) { showError(t("feed_missing") as string); return }

      const fd = new FormData()
      fd.append("feed_id", feedId)
      fd.append("entry_id", entryId)
      fd.append("entry_json", JSON.stringify(entry))
      fd.append("action", action)
      appendModelFields(fd)

      const result = await api.rssEnqueue(fd)
      if (result.duplicate) return // 幂等：已在队列中
    } catch (err) {
      showError(t("task_creation_failed") + ((err as ApiError).detail || (err as Error).message || ""))
    }
  }, [entryQueueMap, feeds, appendModelFields, showError, t])

  // ── Feed 操作 ─────────────────────────────────────────────────

  const subscribe = async () => {
    const url = feedUrl.trim()
    if (!url) { showError(t("rss_url_placeholder")); return }
    setAddBusy(true)
    hideError()
    try {
      const fd = new FormData()
      fd.append("feed_url", url)
      await api.rssSubscribe(fd)
      await loadFeeds()
      setFeedUrl("")
    } catch (e) {
      showError(t("subscribe_failed") + ((e as ApiError).detail || (e as Error).message || ""))
    } finally { setAddBusy(false) }
  }

  const importJson = async (file: File) => {
    setImportLabel(t("adding") as string)
    hideError()
    try {
      const raw = await file.text()
      const data = JSON.parse(raw)
      const normalized = normalizeImportList(data, t("rss_json_invalid") as string)
      if (!normalized.length) {
        showError((t("imported_json_feeds") as (a: number, b: number) => string)(0, 0))
        return
      }
      let done = 0, imported = 0, failed = 0
      const total = normalized.length
      for (const preset of normalized) {
        try {
          const fd = new FormData()
          fd.append("feed_url", preset.url)
          await api.rssSubscribe(fd)
          rememberFeedMeta(preset.url, { title: preset.title, topic: preset.topic, region: preset.region })
          imported++
        } catch { failed++ }
        finally { done++; setImportLabel((t("importing_json_feeds") as (a: number, b: number) => string)(done, total)) }
      }
      await loadFeeds()
      showError((t("imported_json_feeds") as (a: number, b: number) => string)(imported, failed))
    } catch (e) {
      showError(t("rss_import_failed") + (e as Error).message)
    } finally {
      setImportLabel("")
      if (jsonInputRef.current) jsonInputRef.current.value = ""
    }
  }

  const refreshFeed = async (id: string) => {
    setRefreshingId(id)
    try {
      await api.rssRefreshFeed(id)
      await loadFeeds()
    } catch (e) {
      showError(t("refresh_failed") + ((e as ApiError).detail || (e as Error).message || ""))
    } finally { setRefreshingId("") }
  }

  const toggleFavorite = async (id: string) => {
    try {
      const { favorite } = await api.rssToggleFavorite(id)
      setFeeds((prev) => prev.map((f) => f.id === id ? { ...f, favorite } : f))
    } catch { /* ignore */ }
  }

  const deleteFeed = async (id: string) => {
    const feed = feeds.find((f) => f.id === id)
    try {
      await api.rssDeleteFeed(id)
      if (feed?.url) forgetFeedMeta(feed.url)
      setFeeds((prev) => prev.filter((f) => f.id !== id))
      if (activeFeedId === id) setActiveFeedId("")
    } catch { /* ignore */ }
    setPendingDeleteFeed(null)
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

      {/* 队列状态栏（有排队/处理中任务时显示） */}
      {(qState.pending_count > 0 || qState.processing) && (
        <div className="rss-summary-bar" style={{ background: "var(--accent-dim-bg)", justifyContent: "flex-start", gap: 8 }}>
          <span style={{ fontSize: 13 }}>
            {qState.processing
              ? `${t("processing") || "处理中"}…`
              : (t("queue_pending") as (n: number) => string)(qState.pending_count)}
          </span>
        </div>
      )}

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
        <Button variant="default" size="sm" className="shrink-0" disabled={addBusy} loading={addBusy} onClick={() => void subscribe()}>
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
        <>
          <div className="history-filter-row rss-filter-row">
            <span className="self-center text-[10px] font-semibold uppercase tracking-[0.08em] text-[var(--text-dim)]">
              {t("rss_topic")}
            </span>
            <Button
              variant={topicFilter === "all" ? "secondary" : "ghost"}
              size="sm"
              className={cn(topicFilter === "all" && "bg-[rgba(var(--accent-rgb),.12)] text-[var(--accent-text)] border-[var(--accent-dim)]")}
              onClick={() => setTopicFilter("all")}
            >
              {t("filter_all")}
            </Button>
            {topicOptions.map((topic) => (
              <Button
                key={topic}
                variant={topicFilter === topic ? "secondary" : "ghost"}
                size="sm"
                className={cn(topicFilter === topic && "bg-[rgba(var(--accent-rgb),.12)] text-[var(--accent-text)] border-[var(--accent-dim)]")}
                onClick={() => setTopicFilter(topic)}
              >
                {topic}
              </Button>
            ))}
          </div>
          <div className="history-filter-row rss-filter-row">
            <span className="self-center text-[10px] font-semibold uppercase tracking-[0.08em] text-[var(--text-dim)]">
              {t("rss_region")}
            </span>
            <Button
              variant={regionFilter === "all" ? "secondary" : "ghost"}
              size="sm"
              className={cn(regionFilter === "all" && "bg-[rgba(var(--accent-rgb),.12)] text-[var(--accent-text)] border-[var(--accent-dim)]")}
              onClick={() => setRegionFilter("all")}
            >
              {t("filter_all")}
            </Button>
            {regionOptions.map((region) => (
              <Button
                key={region}
                variant={regionFilter === region ? "secondary" : "ghost"}
                size="sm"
                className={cn(regionFilter === region && "bg-[rgba(var(--accent-rgb),.12)] text-[var(--accent-text)] border-[var(--accent-dim)]")}
                onClick={() => setRegionFilter(region)}
              >
                {region}
              </Button>
            ))}
          </div>
        </>
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
                      <p className="feed-card-title">
                        <span>{f.title}</span>
                        <span className="feed-card-count">{(t("item_count") as (n: number) => string)(f.entry_count)}</span>
                        {f.new_count > 0 && (
                          <Badge variant="new">{(t("new_count") as (n: number) => string)(f.new_count)}</Badge>
                        )}
                      </p>
                      <div className="feed-card-meta">
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
                          className="text-[var(--error)] border border-[var(--error)] hover:bg-[var(--error)] hover:text-white"
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
                          className="text-[var(--text-dim)] hover:text-[var(--error)]"
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
                  const entryKey = `${activeFeed.id}:${e.id}`
                  const queueStatus = entryQueueMap[entryKey] || "idle"
                  const isQueued = queueStatus === "queued"
                  const isProcessing = queueStatus === "processing"
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
                        <Button
                          variant="primary-sm"
                          disabled={isQueued || isProcessing}
                          loading={isProcessing}
                          onClick={() => void enqueueTask(activeFeed.id, e.id, "summarize")}
                        >
                          {isQueued ? "⏳" : isSummarized ? t("resummarize") : t("summarize")}
                        </Button>
                        {hasAudio && (
                          <Button
                            variant="outline"
                            size="sm"
                            disabled={isQueued || isProcessing}
                            onClick={() => void enqueueTask(activeFeed.id, e.id, "download")}
                          >
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
