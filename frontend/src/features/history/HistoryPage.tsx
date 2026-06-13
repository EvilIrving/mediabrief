import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { useLocation } from "react-router-dom"
import { ArchiveRegular, BookOpenRegular, ArrowUpRightRegular, SearchRegular } from "@fluentui/react-icons"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Card } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import { ScrollArea } from "@/components/ui/scroll-area"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { cn } from "@/lib/utils"
import { Markdown } from "@/components/Markdown"
import { api } from "@/lib/api"
import type { HistoryItem } from "@/lib/types"
import { useI18n } from "@/i18n/I18nContext"

type SourceFilter = string

const PLATFORM_PATTERNS: [RegExp, string][] = [
  [/(^|\.)youtube\.com|youtu\.be/i, "YouTube"],
  [/(^|\.)bilibili\.com/i, "Bilibili"],
  [/(^|\.)vimeo\.com/i, "Vimeo"],
  [/(^|\.)twitch\.tv/i, "Twitch"],
  [/(^|\.)nicovideo\.jp/i, "Niconico"],
  [/(^|\.)dailymotion\.com/i, "Dailymotion"],
  [/(^|\.)tiktok\.com/i, "TikTok"],
  [/(^|\.)xiaohongshu\.com/i, "小红书"],
  [/(^|\.)ixigua\.com/i, "西瓜视频"],
]

function sourceCategory(item: HistoryItem): string {
  if (item.source_type === "file") return "file"
  if (item.source_type === "rss") return "rss"
  const src = item.source_value || item.url || ""
  for (const [re, label] of PLATFORM_PATTERNS) {
    if (re.test(src)) return label
  }
  try {
    return new URL(src).hostname.replace(/^www\./, "")
  } catch {
    return "url"
  }
}

function sourceFilterLabel(cat: string): string {
  if (cat === "file") return "filter_local_upload"
  if (cat === "rss") return "RSS"
  return cat
}

function matchesSource(item: HistoryItem, filter: SourceFilter): boolean {
  if (filter === "all") return true
  return sourceCategory(item) === filter
}

export function HistoryPage() {
  const { t } = useI18n()
  const [items, setItems] = useState<HistoryItem[]>([])
  const [loadError, setLoadError] = useState("")
  const [search, setSearch] = useState("")
  const [sourceFilter, setSourceFilter] = useState<SourceFilter>("all")
  const [activeId, setActiveId] = useState("")
  const [selectMode, setSelectMode] = useState(false)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [pendingDelete, setPendingDelete] = useState<string | null>(null)
  const [confirmSelected, setConfirmSelected] = useState(false)
  // 详情页摘要/转录稿切换。转录稿全文不在列表里，点开按需拉取并缓存。
  const [detailTab, setDetailTab] = useState<"summary" | "transcript">("summary")
  const [transcripts, setTranscripts] = useState<Record<string, string>>({})
  const [transcriptLoading, setTranscriptLoading] = useState(false)

  const location = useLocation()
  const isActive = location.pathname === '/history'
  const prevActive = useRef(isActive)

  const load = useCallback(async () => {
    try {
      const { items: all } = await api.historyList({ limit: 200 })
      setItems(all || [])
      setLoadError("")
    } catch (e) {
      setLoadError(t("history_load_failed") + ((e as Error).message || String(e)))
    }
  }, [t])

  // 仅在 History 页签激活时刷新（首次挂载 + 每次切到此页签）
  useEffect(() => {
    if (isActive) {
      void load()
    }
    prevActive.current = isActive
  }, [isActive, load])

  const visible = useMemo(() => {
    const q = search.trim().toLowerCase()
    const bySource = items.filter((i) => matchesSource(i, sourceFilter))
    return q
      ? bySource.filter((i) =>
          [i.video_title, i.source_value, i.url, i.summary]
            .join("\n")
            .toLowerCase()
            .includes(q),
        )
      : bySource
  }, [items, search, sourceFilter])

  const sourceFilters = useMemo(() => {
    const seen = new Set<string>()
    const cats: string[] = []
    for (const cat of ["file", "rss"]) {
      if (items.some((i) => sourceCategory(i) === cat)) {
        seen.add(cat)
        cats.push(cat)
      }
    }
    for (const [, label] of PLATFORM_PATTERNS) {
      if (!seen.has(label) && items.some((i) => sourceCategory(i) === label)) {
        seen.add(label)
        cats.push(label)
      }
    }
    for (const item of items) {
      const cat = sourceCategory(item)
      if (!seen.has(cat)) {
        seen.add(cat)
        cats.push(cat)
      }
    }
    return cats
  }, [items])

  const effectiveActive = visible.some((i) => i.task_id === activeId) ? activeId : visible[0]?.task_id || ""
  const activeItem = visible.find((i) => i.task_id === effectiveActive)

  // 切换详情项时回到摘要标签。
  useEffect(() => { setDetailTab("summary") }, [effectiveActive])

  const loadTranscript = useCallback(async (taskId: string) => {
    if (transcripts[taskId] !== undefined) return // 已缓存
    setTranscriptLoading(true)
    try {
      const r = await api.taskTranscript(taskId)
      setTranscripts((p) => ({ ...p, [taskId]: r.script || "" }))
    } catch {
      setTranscripts((p) => ({ ...p, [taskId]: "" }))
    } finally {
      setTranscriptLoading(false)
    }
  }, [transcripts])

  // 切到转录稿标签时按需拉取全文。
  useEffect(() => {
    if (detailTab === "transcript" && effectiveActive) void loadTranscript(effectiveActive)
  }, [detailTab, effectiveActive, loadTranscript])

  const removeOne = async (id: string) => {
    try {
      await api.historyDelete(id)
      setItems((prev) => prev.filter((i) => i.task_id !== id))
      setSelected((prev) => { const next = new Set(prev); next.delete(id); return next })
    } catch (e) {
      alert(t("delete_failed") + ((e as Error).message || e))
    } finally { setPendingDelete(null) }
  }

  const removeSelected = async () => {
    const ids = [...selected]
    if (!ids.length) return
    try {
      await api.historyDeleteMany(ids)
      setItems((prev) => prev.filter((i) => !selected.has(i.task_id)))
      setSelected(new Set())
    } catch (e) {
      alert(t("delete_failed") + ((e as Error).message || e))
    } finally { setConfirmSelected(false) }
  }

  const toggleSelected = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id); else next.add(id)
      return next
    })
  }

  const isLink = (item: HistoryItem) => /^https?:\/\//i.test(item.source_value || item.url || "")

  return (
    <div className="list-page">
      <div className="page-topbar">
        <div className="page-topbar-left">
          <h1 className="page-topbar-title">{t("history_page_title")}</h1>
          <span className="page-topbar-sub">{t("history_page_subtitle")}</span>
        </div>
      </div>

      <div className="history-toolbar">
        <div className="url-wrap history-search">
          <SearchRegular className="url-icon h-4 w-4" />
          <Input
            type="search"
            className="url-input"
            placeholder={t("history_search_placeholder")}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <Button
          variant={selectMode ? "secondary" : "outline"}
          size="sm"
          onClick={() => {
            setSelectMode((m) => !m)
            if (selectMode) setSelected(new Set())
          }}
        >
          {selectMode ? (t("selected_count_short") as (n: number) => string)(selected.size) : t("select")}
        </Button>
      </div>

      <div className="history-filter-row">
        <Button
          variant={sourceFilter === "all" ? "secondary" : "ghost"}
          size="sm"
          className={cn(sourceFilter === "all" && "bg-[rgba(var(--accent-rgb),.12)] text-[var(--accent-text)] border-[var(--accent-dim)]")}
          onClick={() => setSourceFilter("all")}
        >
          {t("filter_all")}
        </Button>
        {sourceFilters.map((cat) => {
          const label = sourceFilterLabel(cat)
          const display = label.startsWith("filter_") ? t(label) : label
          return (
            <Button
              key={cat}
              variant={sourceFilter === cat ? "secondary" : "ghost"}
              size="sm"
              className={cn(sourceFilter === cat && "bg-[rgba(var(--accent-rgb),.12)] text-[var(--accent-text)] border-[var(--accent-dim)]")}
              onClick={() => setSourceFilter(cat)}
            >
              {display}
            </Button>
          )
        })}
      </div>

      {selectMode && (
        <div className="history-delete-sel-bar show">
          <span>{(t("selected_count") as (n: number) => string)(selected.size)}</span>
          <Button variant="outline" size="sm" onClick={() => setSelected(new Set(visible.map((i) => i.task_id)))}>
            {t("select_all")}
          </Button>
          <Button variant="outline" size="sm" onClick={() => setSelected(new Set())}>
            {t("deselect_all")}
          </Button>
          <Button variant="destructive" size="sm" disabled={!selected.size} onClick={() => setConfirmSelected(true)}>
            {t("delete_selected")}
          </Button>
        </div>
      )}

      <div className="split-page">
        <ScrollArea className="split-list">
          <div className="history-list">
            {!visible.length ? (
              <div className="history-empty">
                <ArchiveRegular />
                <p>{loadError || (search ? t("no_matches") : t("history_empty"))}</p>
              </div>
            ) : (
              visible.map((item) => {
                const date = item.created_at ? new Date(item.created_at).toLocaleString() : ""
                return (
                  <Card
                    key={item.task_id}
                    className={cn(
                      "cursor-pointer p-3 transition-colors",
                      item.task_id === effectiveActive && "border-[var(--accent)] bg-[rgba(var(--accent-rgb),.06)]",
                    )}
                    onClick={() => setActiveId(item.task_id)}
                  >
                    <div className="flex justify-between gap-3 items-start">
                      <div className="flex gap-2 items-start flex-1 min-w-0">
                        {selectMode && (
                          <Checkbox
                            checked={selected.has(item.task_id)}
                            className="mt-0.5"
                            onClick={(e) => e.stopPropagation()}
                            onCheckedChange={() => toggleSelected(item.task_id)}
                          />
                        )}
                        <div className="min-w-0">
                          <div className="text-sm font-semibold leading-snug break-words">
                            {item.video_title || t("unnamed_summary")}
                          </div>
                          <div className="history-meta">
                            <span>{date}</span>
                            {isLink(item) ? (
                              <a
                                className="history-source inline-flex items-center gap-0.5"
                                href={item.source_value || item.url}
                                target="_blank"
                                rel="noreferrer"
                                onClick={(e) => e.stopPropagation()}
                              >
                                <ArrowUpRightRegular className="h-2.5 w-2.5" />
                                {t("source_link")}
                              </a>
                            ) : (
                              <span>{item.source_value || item.source_type || t("local_task")}</span>
                            )}
                          </div>
                        </div>
                      </div>
                      {pendingDelete === item.task_id ? (
                        <Button
                          variant="ghost"
                          size="sm"
                          className="shrink-0 text-[var(--error)] border border-[var(--error)] hover:bg-[var(--error)] hover:text-white"
                          onClick={(e) => { e.stopPropagation(); void removeOne(item.task_id) }}
                          onBlur={() => setPendingDelete(null)}
                          autoFocus
                        >
                          {t("confirm_delete")}
                        </Button>
                      ) : (
                        <Button
                          variant="ghost"
                          size="sm"
                          className="shrink-0 text-[var(--text-dim)] hover:text-[var(--error)]"
                          onClick={(e) => { e.stopPropagation(); setPendingDelete(item.task_id) }}
                        >
                          {t("delete")}
                        </Button>
                      )}
                    </div>
                  </Card>
                )
              })
            )}
          </div>
        </ScrollArea>

        <div className="split-detail">
          {activeItem ? (
            <ScrollArea className="h-full">
              <div className="detail-head">
                <div className="detail-meta">
                  <span>{activeItem.created_at ? new Date(activeItem.created_at).toLocaleString() : ""}</span>
                  <span>
                    {isLink(activeItem) ? (
                      <a className="history-source inline-flex items-center gap-0.5" href={activeItem.source_value || activeItem.url} target="_blank" rel="noreferrer">
                        <ArrowUpRightRegular className="h-2.5 w-2.5" />
                        {t("source_link")}
                      </a>
                    ) : (
                      activeItem.source_value || activeItem.source_type || t("local_task")
                    )}
                  </span>
                </div>
              </div>
              {activeItem.has_transcript && (
                <div className="history-filter-row" style={{ marginBottom: 8 }}>
                  <Button
                    variant={detailTab === "summary" ? "secondary" : "ghost"}
                    size="sm"
                    onClick={() => setDetailTab("summary")}
                  >
                    {t("intelligent_summary")}
                  </Button>
                  <Button
                    variant={detailTab === "transcript" ? "secondary" : "ghost"}
                    size="sm"
                    onClick={() => setDetailTab("transcript")}
                  >
                    {t("transcript_text")}
                  </Button>
                </div>
              )}
              {detailTab === "transcript" ? (
                transcriptLoading && transcripts[effectiveActive] === undefined ? (
                  <p className="muted-note">{t("preparing")}</p>
                ) : (
                  <Markdown source={transcripts[effectiveActive] || ""} />
                )
              ) : (
                <Markdown source={activeItem.summary || ""} />
              )}
            </ScrollArea>
          ) : (
            <div className="detail-empty">
              <BookOpenRegular />
              <p>{t("history_detail_empty")}</p>
            </div>
          )}
        </div>
      </div>

      <AlertDialog open={confirmSelected} onOpenChange={setConfirmSelected}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t("delete_selected")}</AlertDialogTitle>
            <AlertDialogDescription>
              {(t("confirm_delete_selected") as (n: number) => string)(selected.size)}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t("cancel")}</AlertDialogCancel>
            <AlertDialogAction
              className="bg-[var(--error)] hover:bg-[var(--error)] hover:opacity-90"
              onClick={() => void removeSelected()}
            >
              {t("delete")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}
