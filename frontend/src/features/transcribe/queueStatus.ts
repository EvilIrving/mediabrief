import type { QueueItem } from "@/lib/types"

const TERMINAL = new Set(["completed", "error", "cancelled"])

export const QUEUE_STATUS_RANK: Record<string, number> = {
  queued: 0, processing: 1, completed: 2, error: 2, cancelled: 2,
}

export function queueStatusRank(status?: string): number {
  return QUEUE_STATUS_RANK[status ?? ""] ?? 0
}

export function displayQueueStatus(item: QueueItem): QueueItem["status"] {
  // 排队/运行中以队列行为准。tasks 表可能还留着上一轮 error，
  // 盖上去会让 Retry 一直显示，再点就 409。
  if (item.status === "queued" || item.status === "processing") {
    return item.status
  }
  const taskStatus = item.task_status
  if (taskStatus === "completed" || taskStatus === "error" || taskStatus === "cancelled" || taskStatus === "processing") {
    return taskStatus
  }
  return item.status
}

export function normalizeQueueItem(item: QueueItem): QueueItem {
  const status = displayQueueStatus(item)
  return status === item.status ? item : { ...item, status }
}

export function mergeQueueItems(prev: QueueItem[], incoming: QueueItem[]): QueueItem[] {
  const prevById = new Map(prev.map((it) => [it.id, it]))
  return incoming.map((item) => {
    const before = prevById.get(item.id)
    if (!before) return item
    // 同一队列项被重试后 id 会变；同一 id 上，终态 residual 不能压过 queued/processing。
    if (TERMINAL.has(before.status) && (item.status === "queued" || item.status === "processing")) {
      return item
    }
    return queueStatusRank(before.status) > queueStatusRank(item.status) ? before : item
  })
}
