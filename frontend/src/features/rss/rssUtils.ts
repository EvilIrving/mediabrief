import type { RssFeed, RssFeedSummary } from '@/lib/types'

/* ── 工具函数 ────────────────────────────────────────────
   所有 RSS 数据管理（解析、合并、去重、持久化）由后端负责。
   前端仅做展示相关的变换。 */

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


