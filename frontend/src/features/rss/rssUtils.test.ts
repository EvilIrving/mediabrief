import { describe, it, expect, beforeEach } from 'vitest'
import {
  normalizeImportList,
  mergeFeedMetadata,
  feedSummaries,
  rememberFeedMeta,
  forgetFeedMeta,
} from './rssUtils'
import type { RssFeed } from '@/lib/types'

const INVALID = 'invalid'

describe('normalizeImportList', () => {
  it('accepts a bare string array', () => {
    const out = normalizeImportList(['https://a.com/feed', 'https://b.com/feed'], INVALID)
    expect(out.map((x) => x.url)).toEqual(['https://a.com/feed', 'https://b.com/feed'])
  })

  it('accepts a { feeds: [...] } wrapper', () => {
    const out = normalizeImportList({ feeds: ['https://a.com/feed'] }, INVALID)
    expect(out).toHaveLength(1)
    expect(out[0].url).toBe('https://a.com/feed')
  })

  it('preserves object presets and trims urls', () => {
    const out = normalizeImportList([{ url: '  https://a.com/feed  ', topic: 'tech' }], INVALID)
    expect(out[0]).toMatchObject({ url: 'https://a.com/feed', topic: 'tech' })
  })

  it('dedupes by url ignoring a trailing slash', () => {
    const out = normalizeImportList(
      ['https://a.com/feed', 'https://a.com/feed/', 'https://b.com/feed'],
      INVALID,
    )
    expect(out.map((x) => x.url)).toEqual(['https://a.com/feed', 'https://b.com/feed'])
  })

  it('drops items without a string url', () => {
    const out = normalizeImportList([{ topic: 'no-url' }, 42, null, 'https://ok.com'], INVALID)
    expect(out.map((x) => x.url)).toEqual(['https://ok.com'])
  })

  it('throws the provided message when not a list', () => {
    expect(() => normalizeImportList({ nope: true }, INVALID)).toThrow(INVALID)
    expect(() => normalizeImportList('string', INVALID)).toThrow(INVALID)
  })
})

describe('feedSummaries', () => {
  it('projects feeds and counts entries / new (unprocessed) entries', () => {
    const feeds: RssFeed[] = [
      {
        id: '1',
        url: 'https://a.com',
        title: 'A',
        favorite: true,
        entries: [
          { id: 'e1', processed: 'seen' },
          { id: 'e2' },
          { id: 'e3' },
        ],
      },
    ]
    const [s] = feedSummaries(feeds)
    expect(s).toMatchObject({ id: '1', title: 'A', favorite: true, entry_count: 3, new_count: 2 })
  })

  it('handles feeds with no entries', () => {
    const [s] = feedSummaries([{ id: '1', url: 'https://a.com' }])
    expect(s.entry_count).toBe(0)
    expect(s.new_count).toBe(0)
    expect(s.favorite).toBe(false)
  })
})

describe('feed metadata persistence (localStorage)', () => {
  beforeEach(() => localStorage.clear())

  it('remembers metadata and merges it into feeds missing those fields', () => {
    rememberFeedMeta('https://a.com/feed', { title: 'Remembered', topic: 'tech', region: 'us' })
    const merged = mergeFeedMetadata([{ id: '1', url: 'https://a.com/feed' }])
    expect(merged[0]).toMatchObject({ title: 'Remembered', topic: 'tech', region: 'us' })
  })

  it('normalizes the url key by trailing slash', () => {
    rememberFeedMeta('https://a.com/feed/', { title: 'T' })
    const merged = mergeFeedMetadata([{ id: '1', url: 'https://a.com/feed' }])
    expect(merged[0].title).toBe('T')
  })

  it('does not override fields already present on the feed', () => {
    rememberFeedMeta('https://a.com/feed', { title: 'Remembered' })
    const merged = mergeFeedMetadata([{ id: '1', url: 'https://a.com/feed', title: 'Original' }])
    expect(merged[0].title).toBe('Original')
  })

  it('forgets metadata', () => {
    rememberFeedMeta('https://a.com/feed', { title: 'T' })
    forgetFeedMeta('https://a.com/feed')
    const merged = mergeFeedMetadata([{ id: '1', url: 'https://a.com/feed' }])
    expect(merged[0].title).toBe('')
  })

  it('ignores blank meta values', () => {
    rememberFeedMeta('https://a.com/feed', { title: '   ', topic: '' })
    const merged = mergeFeedMetadata([{ id: '1', url: 'https://a.com/feed' }])
    expect(merged[0].title).toBe('')
    expect(merged[0].topic).toBe('')
  })
})
