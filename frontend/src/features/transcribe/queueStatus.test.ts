import { describe, expect, it } from "vitest"
import { displayQueueStatus, mergeQueueItems } from "./queueStatus"
import type { QueueItem } from "@/lib/types"

function item(partial: Partial<QueueItem> & Pick<QueueItem, "id" | "status">): QueueItem {
  return {
    queue_name: "tasks",
    item_type: "process_video",
    item_key: "k",
    task_id: "t1",
    position: 0,
    created_at: "",
    started_at: "",
    completed_at: "",
    error: "",
    ...partial,
  }
}

describe("displayQueueStatus", () => {
  it("does not let a leftover task error cover a queued or processing row", () => {
    expect(displayQueueStatus(item({ id: "a", status: "queued", task_status: "error" }))).toBe("queued")
    expect(displayQueueStatus(item({ id: "a", status: "processing", task_status: "error" }))).toBe("processing")
  })

  it("keeps terminal queue status when the task agrees", () => {
    expect(displayQueueStatus(item({ id: "a", status: "error", task_status: "error" }))).toBe("error")
  })
})

describe("mergeQueueItems", () => {
  it("lets a retry snapshot replace a stuck error on the same id", () => {
    const prev = [item({ id: "a", status: "error" })]
    const incoming = [item({ id: "a", status: "processing" })]
    expect(mergeQueueItems(prev, incoming)[0].status).toBe("processing")
  })
})
