import { api } from '@/lib/api'
import type { RssEntry, RssFeed, RssFeedSummary } from '@/lib/types'

/* Merge a freshly parsed feed with the stored one, preserving processed
   state and favorites, and computing the new-entry count. Ported from
   the original _rssMergeFeed. */
export function mergeFeed(oldFeed: RssFeed | undefined, newFeed: RssFeed): RssFeed {
  const oldEntries = oldFeed?.entries || []
  const oldStatus = new Map(oldEntries.filter((e) => e.processed).map((e) => [e.id, e.processed]))
  const existingIds = new Set(oldEntries.map((e) => e.id))
  const mergedEntries: RssEntry[] = (newFeed.entries || []).map((e) => ({
    ...e,
    processed: oldStatus.get(e.id) || e.processed,
  }))
  for (const entry of oldEntries) {
    if (!mergedEntries.some((e) => e.id === entry.id)) mergedEntries.push(entry)
  }
  mergedEntries.sort((a, b) => (b.published || '').localeCompare(a.published || ''))
  return {
    ...newFeed,
    added_at: oldFeed?.added_at || newFeed.added_at,
    favorite: Boolean(oldFeed?.favorite),
    entries: mergedEntries,
    new_count: mergedEntries.filter((e) => !e.processed && !existingIds.has(e.id)).length,
  }
}

export function feedSummaries(feeds: RssFeed[]): RssFeedSummary[] {
  return feeds.map((f) => ({
    id: f.id,
    title: f.title,
    favorite: Boolean(f.favorite),
    type: f.type,
    url: f.url,
    last_checked: f.last_checked,
    last_error: f.last_error,
    entry_count: (f.entries || []).length,
    new_count: (f.entries || []).filter((e) => !e.processed).length,
  }))
}

export interface ImportPreset {
  url: string
  title?: string
  [k: string]: unknown
}

export function normalizeImportList(data: unknown, invalidMsg: string): ImportPreset[] {
  const list = Array.isArray(data) ? data : (data as { feeds?: unknown })?.feeds
  if (!Array.isArray(list)) throw new Error(invalidMsg)
  const seen = new Set<string>()
  return list
    .map((item) => (typeof item === 'string' ? { url: item } : item))
    .filter((item): item is ImportPreset => !!item && typeof (item as ImportPreset).url === 'string')
    .map((item) => ({ ...item, url: item.url.trim() }))
    .filter((item) => {
      const key = item.url.replace(/\/$/, '')
      if (!item.url || seen.has(key)) return false
      seen.add(key)
      return true
    })
}

/* Parse a feed with a 35s timeout, matching the original _rssParseFeed. */
export async function parseFeed(feedUrl: string, requestFailedMsg: string): Promise<RssFeed> {
  const fd = new FormData()
  fd.append('feed_url', feedUrl)
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), 35000)
  try {
    const data = await api.rssParse(fd, controller.signal).catch((err: { name?: string; detail?: string }) => {
      if (err.name === 'AbortError') throw err
      throw new Error(err.detail || requestFailedMsg)
    })
    return data.feed
  } finally {
    clearTimeout(timer)
  }
}
