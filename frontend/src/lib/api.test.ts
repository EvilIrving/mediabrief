import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { api } from './api'
import type { ApiError } from './types'

function jsonResponse(body: unknown, ok = true, status = 200): Response {
  return {
    ok,
    status,
    json: async () => body,
  } as unknown as Response
}

describe('VTApiClient (api singleton)', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('issues a GET to the right /api path and returns parsed JSON', async () => {
    const fetchMock = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValue(jsonResponse({ status: 'done' }))
    const out = await api.taskStatus('abc-123')
    expect(out).toEqual({ status: 'done' })
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/task-status/abc-123')
    expect((init as RequestInit).method).toBe('GET')
  })

  it('POSTs FormData for processVideo', async () => {
    const fetchMock = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValue(jsonResponse({ task_id: 't1' }))
    const fd = new FormData()
    fd.set('url', 'https://x.com')
    const out = await api.processVideo(fd)
    expect(out).toEqual({ task_id: 't1' })
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/process-video')
    expect((init as RequestInit).method).toBe('POST')
    expect((init as RequestInit).body).toBe(fd)
  })

  it('maps an HTTP error body to Error with .detail and .status', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      jsonResponse({ detail: 'API Key 无效' }, false, 401),
    )
    await expect(api.taskStatus('x')).rejects.toMatchObject({
      message: 'API Key 无效',
      detail: 'API Key 无效',
      status: 401,
    })
  })

  it('falls back to "HTTP <status>" when error body has no detail', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(jsonResponse({}, false, 500))
    try {
      await api.taskStatus('x')
      throw new Error('should have thrown')
    } catch (e) {
      const err = e as ApiError
      expect(err.message).toBe('HTTP 500')
      expect(err.status).toBe(500)
    }
  })

  it('encodes path params in URL builders', () => {
    expect(api.mdFileUrl('a b/c.md')).toBe('/api/download/a%20b%2Fc.md')
    expect(api.videoFileUrl('x y.mp4')).toBe('/api/download-video/file/x%20y.mp4')
  })

  it('DELETE task uses the DELETE method and encoded id', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(jsonResponse({}))
    await api.deleteTask('id/with slash')
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/task/id%2Fwith%20slash')
    expect((init as RequestInit).method).toBe('DELETE')
  })
})
