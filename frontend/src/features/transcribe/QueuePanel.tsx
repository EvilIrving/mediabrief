import { ListRegular, ArrowCircleDownRegular } from "@fluentui/react-icons"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { useI18n } from "@/i18n/I18nContext"
import { cn } from "@/lib/utils"
import type { QueueItem } from "@/lib/types"

const TERMINAL = new Set(["completed", "error", "cancelled"])

function itemTitle(item: QueueItem): string {
  return item.source_label || item.item_key || item.task_id || "—"
}

export function QueuePanel({
  items,
  displayedTaskId,
  cancellingIds,
  onSelect,
  onCancel,
  onRemove,
  onRetry,
  onClear,
}: {
  items: QueueItem[]
  displayedTaskId: string | null
  cancellingIds: Set<string>
  onSelect: (item: QueueItem) => void
  onCancel: (item: QueueItem) => void
  onRemove: (item: QueueItem) => void
  onRetry: (item: QueueItem) => void
  onClear: () => void
}) {
  const { t } = useI18n()

  const statusMeta = (status: string): { label: string; variant: "secondary" | "success" | "default"; cls?: string } => {
    switch (status) {
      case "processing": return { label: t("processing") as string, variant: "default" }
      case "completed": return { label: t("completed") as string, variant: "success" }
      case "error": return { label: t("q_error") as string, variant: "secondary", cls: "text-[var(--error)]" }
      case "cancelled": return { label: t("q_cancelled") as string, variant: "secondary" }
      default: return { label: t("q_queued") as string, variant: "secondary" }
    }
  }

  const hasTerminal = items.some((i) => TERMINAL.has(i.status))

  return (
    <div className="queue-panel">
      <div className="queue-head">
        <span className="queue-title">
          <ListRegular className="h-4 w-4" />
          {t("queue_title")}
          {items.length > 0 && <span className="queue-count">{items.length}</span>}
        </span>
        {hasTerminal && (
          <Button variant="ghost" size="sm" onClick={onClear}>
            {t("queue_clear_done")}
          </Button>
        )}
      </div>

      <div className="queue-body">
        {items.length === 0 ? (
          <div className="queue-empty">{t("queue_empty")}</div>
        ) : (
          <div className="queue-list">
            {items.map((item) => {
              const meta = statusMeta(item.status)
              const isTerminal = TERMINAL.has(item.status)
              const cancelling = cancellingIds.has(item.id)
              const selectable = Boolean(item.task_id)
              const active = selectable && item.task_id === displayedTaskId
              return (
                <div
                  key={item.id}
                  className={cn("queue-row", active && "queue-row-active", selectable && "queue-row-selectable")}
                  onClick={() => selectable && onSelect(item)}
                  role={selectable ? "button" : undefined}
                  tabIndex={selectable ? 0 : undefined}
                  onKeyDown={(e) => {
                    if (selectable && (e.key === "Enter" || e.key === " ")) {
                      e.preventDefault()  // 阻止 Space 滚动页面
                      onSelect(item)
                    } else if (e.key === "ArrowDown") {
                      e.preventDefault()
                      ;(e.currentTarget.nextElementSibling as HTMLElement | null)?.focus()
                    } else if (e.key === "ArrowUp") {
                      e.preventDefault()
                      ;(e.currentTarget.previousElementSibling as HTMLElement | null)?.focus()
                    } else if (e.key === "Delete" || e.key === "Backspace") {
                      e.preventDefault()
                      if (isTerminal) onRemove(item)
                      else if (!cancelling) onCancel(item)
                    }
                  }}
                >
                  <span className="queue-row-title" title={itemTitle(item)}>{item.task_type === "download_only" && <ArrowCircleDownRegular className="h-3 w-3 mr-1 text-[var(--text-dim)]" />}{itemTitle(item)}</span>
                  <div className="queue-row-actions" onClick={(e) => e.stopPropagation()}>
                    {item.status !== 'error' && (
                      <Badge variant={meta.variant} className={cn("text-[10.5px]", meta.cls)}>{meta.label}</Badge>
                    )}
                    {!isTerminal ? (
                      <Button
                        variant="ghost"
                        size="sm"
                        className="text-[var(--text-dim)] hover:text-[var(--error)]"
                        disabled={cancelling}
                        onClick={() => onCancel(item)}
                      >
                        {cancelling ? t("q_cancelling") : t("cancel")}
                      </Button>
                    ) : (
                      <>
                        {item.status === 'error' && (
                          <Button
                            variant="ghost"
                            size="sm"
                            className="text-[var(--text-dim)] hover:text-[var(--accent)]"
                            onClick={() => onRetry(item)}
                          >
                            {t("retry")}
                          </Button>
                        )}
                        <Button
                          variant="ghost"
                          size="sm"
                          className="text-[var(--text-dim)] hover:text-[var(--error)]"
                          onClick={() => onRemove(item)}
                        >
                          {t("delete")}
                        </Button>
                      </>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}
