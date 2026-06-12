import { useEffect, useMemo, useState } from 'react'
import { Icon } from '@/components/IconSprite'
import { Markdown } from '@/components/Markdown'
import { historyDelete, historyDeleteMany, historyGetAll } from '@/lib/db'
import type { HistoryItem } from '@/lib/types'
import { useI18n } from '@/i18n/I18nContext'

type SourceFilter = 'all' | 'youtube' | 'file' | 'rss'

function matchesSource(item: HistoryItem, filter: SourceFilter): boolean {
  if (filter === 'all') return true
  if (filter === 'file') return item.sourceType === 'file'
  if (filter === 'rss') return item.sourceType === 'rss'
  if (filter === 'youtube') return /(^|\.)youtube\.com|youtu\.be/i.test(item.source || '')
  return true
}

export function HistoryPage() {
  const { t } = useI18n()
  const [items, setItems] = useState<HistoryItem[]>([])
  const [loadError, setLoadError] = useState('')
  const [search, setSearch] = useState('')
  const [sourceFilter, setSourceFilter] = useState<SourceFilter>('all')
  const [activeId, setActiveId] = useState('')
  const [selectMode, setSelectMode] = useState(false)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [pendingDelete, setPendingDelete] = useState<string | null>(null)
  const [confirmSelected, setConfirmSelected] = useState(false)

  const load = async () => {
    try {
      const all = await historyGetAll()
      all.sort((a, b) => String(b.createdAt).localeCompare(String(a.createdAt)))
      setItems(all)
      setLoadError('')
    } catch (e) {
      setLoadError(t('history_load_failed') + ((e as Error).message || String(e)))
    }
  }

  useEffect(() => { void load() }, [])

  const visible = useMemo(() => {
    const q = search.trim().toLowerCase()
    const bySource = items.filter((i) => matchesSource(i, sourceFilter))
    return q
      ? bySource.filter((i) => [i.title, i.source, i.summary].join('\n').toLowerCase().includes(q))
      : bySource
  }, [items, search, sourceFilter])

  /* Keep an active selection in sync with the visible list. */
  const effectiveActive = visible.some((i) => i.id === activeId)
    ? activeId
    : visible[0]?.id || ''
  const activeItem = visible.find((i) => i.id === effectiveActive)

  const removeOne = async (id: string) => {
    try {
      await historyDelete(id)
      setItems((prev) => prev.filter((i) => i.id !== id))
      setSelected((prev) => {
        const next = new Set(prev)
        next.delete(id)
        return next
      })
    } catch (e) {
      alert(t('delete_failed') + ((e as Error).message || e))
    } finally {
      setPendingDelete(null)
    }
  }

  const removeSelected = async () => {
    const ids = [...selected]
    if (!ids.length) return
    try {
      await historyDeleteMany(ids)
      setItems((prev) => prev.filter((i) => !selected.has(i.id)))
      setSelected(new Set())
    } catch (e) {
      alert(t('delete_failed') + ((e as Error).message || e))
    } finally {
      setConfirmSelected(false)
    }
  }

  const toggleSelected = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  return (
    <div className="list-page">
      <div className="page-topbar">
        <div className="page-topbar-left">
          <h1 className="page-topbar-title">{t('history_page_title')}</h1>
          <span className="page-topbar-sub">{t('history_page_subtitle')}</span>
        </div>
      </div>

      <div className="history-toolbar">
        <div className="url-wrap history-search">
          <Icon name="i-magnifying-glass" className="icon url-icon" />
          <input
            type="search"
            className="url-input"
            placeholder={t('history_search_placeholder')}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <button
          className="btn-sm"
          onClick={() => {
            setSelectMode((m) => !m)
            if (selectMode) setSelected(new Set())
          }}
        >
          {selectMode ? (t('selected_count_short') as (n: number) => string)(selected.size) : t('select')}
        </button>
      </div>

      <div className="history-filter-row">
        {(['all', 'youtube', 'file', 'rss'] as SourceFilter[]).map((f) => (
          <button
            key={f}
            className={`history-filter${sourceFilter === f ? ' active' : ''}`}
            onClick={() => setSourceFilter(f)}
          >
            {f === 'all' ? t('filter_all') : f === 'file' ? t('filter_local_upload') : f === 'youtube' ? 'YouTube' : 'RSS'}
          </button>
        ))}
      </div>

      {selectMode && (
        <div className="history-delete-sel-bar show">
          <span>{(t('selected_count') as (n: number) => string)(selected.size)}</span>
          <button className="btn-sm" onClick={() => setSelected(new Set(visible.map((i) => i.id)))}>{t('select_all')}</button>
          <button className="btn-sm" onClick={() => setSelected(new Set())}>{t('deselect_all')}</button>
          {confirmSelected ? (
            <span className="inline-confirm">
              <span className="inline-confirm-message">{(t('confirm_delete_selected') as (n: number) => string)(selected.size)}</span>
              <button className="btn-sm danger" onClick={() => void removeSelected()}>{t('delete')}</button>
              <button className="btn-sm" onClick={() => setConfirmSelected(false)}>{t('cancel')}</button>
            </span>
          ) : (
            <button className="btn-sm primary" disabled={!selected.size} onClick={() => setConfirmSelected(true)}>
              {t('delete_selected')}
            </button>
          )}
        </div>
      )}

      <div className="split-page">
        <div className="history-list split-list">
          {!visible.length ? (
            <div className="history-empty">
              <div className="history-empty-icon"><Icon name="i-box-archive" /></div>
              <p>{loadError || (search ? t('no_matches') : t('history_empty'))}</p>
            </div>
          ) : (
            visible.map((item) => {
              const date = item.createdAt ? new Date(item.createdAt).toLocaleString() : ''
              const isLink = /^https?:\/\//i.test(item.source || '')
              return (
                <div
                  key={item.id}
                  className={`history-item${selectMode ? ' select-mode' : ''}${item.id === effectiveActive ? ' active' : ''}`}
                  onClick={() => setActiveId(item.id)}
                >
                  <div className="history-head">
                    <div className="history-head-left">
                      {selectMode && (
                        <input
                          type="checkbox"
                          className="history-checkbox"
                          checked={selected.has(item.id)}
                          onClick={(e) => e.stopPropagation()}
                          onChange={() => toggleSelected(item.id)}
                        />
                      )}
                      <div>
                        <div className="history-title">{item.title || t('unnamed_summary')}</div>
                        <div className="history-meta">
                          <span>{date}</span>
                          <span>
                            {isLink ? (
                              <a className="history-source" href={item.source} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()}>
                                {t('source_link')}
                              </a>
                            ) : (
                              item.source || item.sourceType || t('local_task')
                            )}
                          </span>
                        </div>
                      </div>
                    </div>
                    {pendingDelete === item.id ? (
                      <span className="inline-confirm" onClick={(e) => e.stopPropagation()}>
                        <span className="inline-confirm-message">{t('confirm_delete_history')}</span>
                        <button className="btn-sm danger" onClick={() => void removeOne(item.id)}>{t('delete')}</button>
                        <button className="btn-sm" onClick={() => setPendingDelete(null)}>{t('cancel')}</button>
                      </span>
                    ) : (
                      <button
                        className="btn-sm"
                        onClick={(e) => { e.stopPropagation(); setPendingDelete(item.id) }}
                      >
                        {t('delete')}
                      </button>
                    )}
                  </div>
                </div>
              )
            })
          )}
        </div>

        <div className="split-detail">
          {activeItem ? (
            <>
              <div className="detail-head">
                <div className="detail-meta">
                  <span>{activeItem.createdAt ? new Date(activeItem.createdAt).toLocaleString() : ''}</span>
                  <span>
                    {/^https?:\/\//i.test(activeItem.source || '') ? (
                      <a className="history-source" href={activeItem.source} target="_blank" rel="noreferrer">{t('source_link')}</a>
                    ) : (
                      activeItem.source || activeItem.sourceType || t('local_task')
                    )}
                  </span>
                </div>
              </div>
              <Markdown source={activeItem.summary || ''} />
            </>
          ) : (
            <div className="detail-empty">
              <Icon name="i-book-open" />
              <p>{t('history_detail_empty')}</p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
