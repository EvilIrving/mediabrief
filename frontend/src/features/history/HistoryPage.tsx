import { useEffect, useMemo, useState } from "react"
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
import { historyDelete, historyDeleteMany, historyGetAll } from "@/lib/db"
import type { HistoryItem } from "@/lib/types"
import { useI18n } from "@/i18n/I18nContext"

type SourceFilter = string

// Recognized platforms — regex → label. Order defines filter button order.
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
  if (item.sourceType === "file") return "file"
  if (item.sourceType === "rss") return "rss"
  const src = item.source || ""
  for (const [re, label] of PLATFORM_PATTERNS) {
    if (re.test(src)) return label
  }
  // Unknown URL — try extracting hostname as fallback label
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

  const load = async () => {
    try {
      const all = await historyGetAll()
      all.sort((a, b) => String(b.createdAt).localeCompare(String(a.createdAt)))
      setItems(all)
      setLoadError("")
    } catch (e) {
      setLoadError(t("history_load_failed") + ((e as Error).message || String(e)))
    }
  }

  useEffect(() => { void load() }, [])

  const visible = useMemo(() => {
    const q = search.trim().toLowerCase()
    const bySource = items.filter((i) => matchesSource(i, sourceFilter))
    return q
      ? bySource.filter((i) => [i.title, i.source, i.summary].join("\n").toLowerCase().includes(q))
      : bySource
  }, [items, search, sourceFilter])

  // Sort categories: file / rss first, then recognized platforms, then other hosts
  const sourceFilters = useMemo(() => {
    const seen = new Set<string>()
    const cats: string[] = []
    // Ordered built-in categories
    for (const cat of ["file", "rss"]) {
      if (items.some((i) => sourceCategory(i) === cat)) {
        seen.add(cat)
        cats.push(cat)
      }
    }
    // Platform categories in defined order
    for (const [, label] of PLATFORM_PATTERNS) {
      if (!seen.has(label) && items.some((i) => sourceCategory(i) === label)) {
        seen.add(label)
        cats.push(label)
      }
    }
    // Remaining unknown hosts
    for (const item of items) {
      const cat = sourceCategory(item)
      if (!seen.has(cat)) {
        seen.add(cat)
        cats.push(cat)
      }
    }
    return cats
  }, [items])

  const effectiveActive = visible.some((i) => i.id === activeId) ? activeId : visible[0]?.id || ""
  const activeItem = visible.find((i) => i.id === effectiveActive)

  const removeOne = async (id: string) => {
    try {
      await historyDelete(id)
      setItems((prev) => prev.filter((i) => i.id !== id))
      setSelected((prev) => { const next = new Set(prev); next.delete(id); return next })
    } catch (e) {
      alert(t("delete_failed") + ((e as Error).message || e))
    } finally { setPendingDelete(null) }
  }

  const removeSelected = async () => {
    const ids = [...selected]
    if (!ids.length) return
    try {
      await historyDeleteMany(ids)
      setItems((prev) => prev.filter((i) => !selected.has(i.id)))
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

  return (
    <div className="list-page">
      <div className="page-topbar">
        <div className="page-topbar-left">
          <h1 className="page-topbar-title">{t("history_page_title")}</h1>
          <span className="page-topbar-sub">{t("history_page_subtitle")}</span>
        </div>
      </div>

      {/* Toolbar */}
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

      {/* Filter row */}
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

      {/* Bulk delete bar */}
      {selectMode && (
        <div className="history-delete-sel-bar show">
          <span>{(t("selected_count") as (n: number) => string)(selected.size)}</span>
          <Button variant="outline" size="sm" onClick={() => setSelected(new Set(visible.map((i) => i.id)))}>
            {t("select_all")}
          </Button>
          <Button variant="outline" size="sm" onClick={() => setSelected(new Set())}>
            {t("deselect_all")}
          </Button>
          <Button
            variant="destructive"
            size="sm"
            disabled={!selected.size}
            onClick={() => setConfirmSelected(true)}
          >
            {t("delete_selected")}
          </Button>
        </div>
      )}

      <div className="split-page">
        {/* Item list */}
        <ScrollArea className="split-list">
          <div className="history-list">
            {!visible.length ? (
              <div className="history-empty">
                <ArchiveRegular />
                <p>{loadError || (search ? t("no_matches") : t("history_empty"))}</p>
              </div>
            ) : (
              visible.map((item) => {
                const date = item.createdAt ? new Date(item.createdAt).toLocaleString() : ""
                const isLink = /^https?:\/\//i.test(item.source || "")
                return (
                  <Card
                    key={item.id}
                    className={cn(
                      "cursor-pointer p-3 transition-colors",
                      item.id === effectiveActive && "border-[var(--accent)] bg-[rgba(var(--accent-rgb),.06)]"
                    )}
                    onClick={() => setActiveId(item.id)}
                  >
                    <div className="flex justify-between gap-3 items-start">
                      <div className="flex gap-2 items-start flex-1 min-w-0">
                        {selectMode && (
                          <Checkbox
                            checked={selected.has(item.id)}
                            className="mt-0.5"
                            onClick={(e) => e.stopPropagation()}
                            onCheckedChange={() => toggleSelected(item.id)}
                          />
                        )}
                        <div className="min-w-0">
                          <div className="text-sm font-semibold leading-snug break-words">
                            {item.title || t("unnamed_summary")}
                          </div>
                          <div className="history-meta">
                            <span>{date}</span>
                            {isLink ? (
                              <a
                                className="history-source inline-flex items-center gap-0.5"
                                href={item.source}
                                target="_blank"
                                rel="noreferrer"
                                onClick={(e) => e.stopPropagation()}
                              >
                              <ArrowUpRightRegular className="h-2.5 w-2.5" />
                                {t("source_link")}
                              </a>
                            ) : (
                              <span>{item.source || item.sourceType || t("local_task")}</span>
                            )}
                          </div>
                        </div>
                      </div>
                      {pendingDelete === item.id ? (
                        <Button
                          variant="ghost"
                          size="sm"
                          className="shrink-0 h-6 px-2 text-xs text-[var(--error)] border border-[var(--error)] hover:bg-[var(--error)] hover:text-white"
                          onClick={(e) => { e.stopPropagation(); void removeOne(item.id) }}
                          onBlur={() => setPendingDelete(null)}
                          autoFocus
                        >
                          {t("confirm_delete")}
                        </Button>
                      ) : (
                        <Button
                          variant="ghost"
                          size="sm"
                          className="shrink-0 h-6 px-2 text-xs text-[var(--text-dim)] hover:text-[var(--error)]"
                          onClick={(e) => { e.stopPropagation(); setPendingDelete(item.id) }}
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

        {/* Detail panel */}
        <div className="split-detail">
          {activeItem ? (
            <ScrollArea className="h-full">
              <div className="detail-head">
                <div className="detail-meta">
                  <span>{activeItem.createdAt ? new Date(activeItem.createdAt).toLocaleString() : ""}</span>
                  <span>
                    {/^https?:\/\//i.test(activeItem.source || "") ? (
                      <a className="history-source inline-flex items-center gap-0.5" href={activeItem.source} target="_blank" rel="noreferrer">
                        <ArrowUpRightRegular className="h-2.5 w-2.5" />
                        {t("source_link")}
                      </a>
                    ) : (
                      activeItem.source || activeItem.sourceType || t("local_task")
                    )}
                  </span>
                </div>
              </div>
              <Markdown source={activeItem.summary || ""} />
            </ScrollArea>
          ) : (
            <div className="detail-empty">
              <BookOpenRegular />
              <p>{t("history_detail_empty")}</p>
            </div>
          )}
        </div>
      </div>

      {/* Bulk delete dialog */}
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
