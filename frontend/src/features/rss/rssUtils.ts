import type { RssFeed, RssFeedSummary } from '@/lib/types'

/* ── 工具函数 ────────────────────────────────────────────
   所有 RSS 数据管理（解析、合并、去重、持久化）由后端负责。
   前端仅做展示相关的变换。 */

const RSS_META_STORAGE_KEY = 'vt_rss_meta_v1'

export interface ImportPreset {
  url: string
  title?: string
  topic?: string
  region?: string
  [k: string]: unknown
}

export interface RssFeedMeta {
  title?: string
  topic?: string
  region?: string
}

type RssMetaMap = Record<string, RssFeedMeta>

function normalizeKey(url: string): string {
  return url.trim().replace(/\/$/, '')
}

function cleanMeta(meta: RssFeedMeta): RssFeedMeta {
  const out: RssFeedMeta = {}
  if (meta.title?.trim()) out.title = meta.title.trim()
  if (meta.topic?.trim()) out.topic = meta.topic.trim()
  if (meta.region?.trim()) out.region = meta.region.trim()
  return out
}

function readMetaMap(): RssMetaMap {
  try {
    const raw = localStorage.getItem(RSS_META_STORAGE_KEY)
    const parsed = raw ? JSON.parse(raw) : {}
    return parsed && typeof parsed === 'object' ? (parsed as RssMetaMap) : {}
  } catch {
    return {}
  }
}

function writeMetaMap(map: RssMetaMap) {
  try {
    localStorage.setItem(RSS_META_STORAGE_KEY, JSON.stringify(map))
  } catch {
    /* ignore */
  }
}

export function rememberFeedMeta(url: string, meta: RssFeedMeta) {
  const key = normalizeKey(url)
  if (!key) return
  const current = readMetaMap()
  const next = { ...current, [key]: { ...(current[key] || {}), ...cleanMeta(meta) } }
  writeMetaMap(next)
}

export function forgetFeedMeta(url: string) {
  const key = normalizeKey(url)
  if (!key) return
  const current = readMetaMap()
  if (!current[key]) return
  delete current[key]
  writeMetaMap(current)
}

export function mergeFeedMetadata(feeds: RssFeed[]): RssFeed[] {
  const metaMap = readMetaMap()
  return feeds.map((feed) => {
    const meta = metaMap[normalizeKey(feed.url)] || {}
    return {
      ...feed,
      title: feed.title || meta.title || '',
      topic: feed.topic || meta.topic || '',
      region: feed.region || meta.region || '',
    }
  })
}

export function feedSummaries(feeds: RssFeed[]): RssFeedSummary[] {
  return feeds.map((f) => ({
    id: f.id,
    title: f.title,
    topic: f.topic,
    region: f.region,
    favorite: Boolean(f.favorite),
    type: f.type,
    url: f.url,
    last_checked: f.last_checked,
    last_error: f.last_error,
    entry_count: (f.entries || []).length,
    new_count: (f.entries || []).filter((e) => !e.processed).length,
  }))
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
