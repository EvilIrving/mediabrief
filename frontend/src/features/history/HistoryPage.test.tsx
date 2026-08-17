import { render, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { I18nProvider } from '@/i18n/I18nContext'
import { HistoryPage } from './HistoryPage'

const TITLE = 'Models, Harnesses, and Multi-Agent Systems'

const historyItem = {
  task_id: 't1',
  video_title: TITLE,
  source_type: 'url',
  source_value: 'https://example.com/episode',
  url: 'https://example.com/episode',
  summary: `# ${TITLE}\n\n## Context and Purpose\n\nThis episode clarifies core concepts.`,
  summary_language: 'en',
  created_at: '2026-08-12T12:10:51',
  updated_at: '2026-08-12T12:10:51',
  has_transcript: false,
}

function jsonResponse(body: unknown): Response {
  return {
    ok: true,
    status: 200,
    json: async () => body,
  } as unknown as Response
}

function renderHistory() {
  return render(
    <I18nProvider>
      <MemoryRouter initialEntries={['/history']}>
        <HistoryPage />
      </MemoryRouter>
    </I18nProvider>,
  )
}

describe('HistoryPage detail header', () => {
  beforeEach(() => {
    Element.prototype.scrollIntoView = vi.fn()
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
      const url = String(input)
      if (url.includes('/api/history')) return jsonResponse({ items: [historyItem] })
      throw new Error(`unexpected fetch: ${url}`)
    })
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('puts the title in the top bar above the source link and omits it from the body', async () => {
    renderHistory()
    await waitFor(() => {
      expect(document.querySelector('.detail-title')).toHaveTextContent(TITLE)
    })

    const head = document.querySelector('.detail-head')
    expect(head?.children[0]).toHaveClass('detail-title')
    expect(head?.children[1]).toHaveClass('detail-meta')
    expect(head?.querySelector('.history-source')).toHaveTextContent('Source link')

    const body = document.querySelector('.split-detail .md-content')
    expect(body?.querySelector('h1')).toBeNull()
    expect(body).toHaveTextContent('Context and Purpose')
    expect(body).toHaveTextContent('This episode clarifies core concepts.')
    expect(body?.textContent).not.toContain(TITLE)
  })
})
