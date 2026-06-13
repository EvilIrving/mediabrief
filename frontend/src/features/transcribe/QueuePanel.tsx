import { ListRegular } from "@fluentui/react-icons"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { useI18n } from "@/i18n/I18nContext"
import { cn } from "@/lib/utils"
import type { QueueItem } from "@/lib/types"

const TERMINAL = new Set(["completed", "error", "cancelled"])

/** 从队列项 payload 推导可读标题（payload 形态随任务类型而异）。 */
function itemTitle(item: QueueItem): string {
  const p = (item.payload || {}) as unknown as Record<string, unknown>
  const entry = p.entry_data as { title?: string } | undefined
  return (
    (p.video_title as string) ||
    (p.original_name as string) ||
    (entry?.title) ||
    (p.url as string) ||
    item.item_key ||
    item.task_id ||
    "—"
  )
}

export function QueuePanel({
  items,
  displayedTaskId,
  onSelect,
  onCancel,
  onRemove,
  onClear,
}: {
  items: QueueItem[]
  displayedTaskId: string | null
  onSelect: (item: QueueItem) => void
  onCancel: (item: QueueItem) => void
  onRemove: (item: QueueItem) => void
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

      {items.length === 0 ? (
        <div className="queue-empty">{t("queue_empty")}</div>
      ) : (
        <div className="queue-list">
          {items.map((item) => {
            const meta = statusMeta(item.status)
            const isTerminal = TERMINAL.has(item.status)
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
                  if (selectable && (e.key === "Enter" || e.key === " ")) onSelect(item)
                }}
              >
                <span className="queue-row-title" title={itemTitle(item)}>{itemTitle(item)}</span>
                <div className="queue-row-actions" onClick={(e) => e.stopPropagation()}>
                  <Badge variant={meta.variant} className={cn("text-[10.5px]", meta.cls)}>{meta.label}</Badge>
                  {!isTerminal ? (
                    <Button
                      variant="ghost"
                      size="sm"
                      className="text-[var(--text-dim)] hover:text-[var(--error)]"
                      onClick={() => onCancel(item)}
                    >
                      {t("cancel")}
                    </Button>
                  ) : (
                    <Button
                      variant="ghost"
                      size="sm"
                      className="text-[var(--text-dim)] hover:text-[var(--error)]"
                      onClick={() => onRemove(item)}
                    >
                      {t("delete")}
                    </Button>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
