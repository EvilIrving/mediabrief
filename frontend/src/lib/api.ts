/* ────────────────────────────────────────────────────────────
   Network layer: the single place that knows about server
   endpoints. Ported 1:1 from the original static/js/api.js,
   now typed. Hooks call these methods instead of fetch().

   Conventions:
   - On HTTP success, returns the parsed JSON body.
   - On HTTP error, throws an Error whose `.message` is the server
     `detail` (or `HTTP <status>`), and which also carries
     `.detail` and `.status`.
   - Network/abort failures reject as usual (e.g. AbortError).
   ──────────────────────────────────────────────────────────── */
import type {
  ApiError,
  BotsConfigureBody,
  BotsStatusResponse,
  DownloadFormatsResponse,
  HistoryItem,
  ModelsResponse,
  QueueEnqueueResponse,
  QueueItem,
  QueueItemsResponse,
  QueueState,
  QueueStats,
  WhisperModelInfo,
  RssFeed,
  RssParseResponse,
  TaskCreateResponse,
  TaskPayload,
  TranscriptResponse,
} from './types'

class VTApiClient {
  base: string

  constructor(base?: string) {
    this.base = base || '/api'
  }

  private async _request<T>(
    method: string,
    path: string,
    body?: BodyInit,
    opts: RequestInit = {},
  ): Promise<T> {
    const init: RequestInit = { method, ...opts }
    if (body !== undefined) init.body = body
    const resp = await fetch(`${this.base}${path}`, init)
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}))
      const e = new Error(err.detail || `HTTP ${resp.status}`) as ApiError
      e.detail = err.detail
      e.status = resp.status
      throw e
    }
    return resp.json() as Promise<T>
  }

  /* ── URL builders (for EventSource / <a download>) ────── */
  mdFileUrl(filename: string) { return `${this.base}/download/${encodeURIComponent(filename)}` }
  videoFileUrl(filename: string) { return `${this.base}/download-video/file/${encodeURIComponent(filename)}` }

  /* ── Transcribe / task ────────────────────────────────── */
  processVideo(fd: FormData) { return this._request<TaskCreateResponse>('POST', '/process-video', fd) }
  retry(taskId: string, fd: FormData) { return this._request<TaskCreateResponse>('POST', `/retry/${encodeURIComponent(taskId)}`, fd) }
  taskStatus(taskId: string) { return this._request<TaskPayload>('GET', `/task-status/${taskId}`) }
  taskDetail(taskId: string) { return this._request<TaskPayload>('GET', `/task/${encodeURIComponent(taskId)}`) }
  deleteTask(taskId: string) { return this._request<unknown>('DELETE', `/task/${encodeURIComponent(taskId)}`) }

  /* ── Models ───────────────────────────────────────────── */
  fetchModels(fd: FormData) { return this._request<ModelsResponse>('POST', '/models', fd) }

  /* ── Whisper (ASR) models: list + download ────────────── */
  whisperModels() {
    return this._request<{ data: WhisperModelInfo[]; default: string }>('GET', '/whisper-models')
  }
  whisperModelDownload(size: string, hfEndpoint?: string) {
    const fd = new FormData()
    fd.append('size', size)
    if (hfEndpoint && hfEndpoint.trim()) fd.append('hf_endpoint', hfEndpoint.trim())
    return this._request<{ size: string; downloaded: boolean }>('POST', '/whisper-models/download', fd)
  }

  /* ── Download-only page ───────────────────────────────── */
  downloadFormats(fd: FormData) { return this._request<DownloadFormatsResponse>('POST', '/download-video/formats', fd) }
  downloadVideo(fd: FormData) { return this._request<TaskCreateResponse>('POST', '/download-video', fd) }
  downloadAudio(fd: FormData) { return this._request<TaskCreateResponse>('POST', '/download-audio', fd) }
  downloadSubtitles(fd: FormData) { return this._request<TaskCreateResponse>('POST', '/download-subtitles', fd) }

  /* ── Active tasks / history ─────────────────────────── */
  activeTasks() { return this._request<{tasks: TaskPayload[]}>('GET', '/active-tasks') }
  historyList(params?: { search?: string; source_type?: string; limit?: number }) {
    const qs = new URLSearchParams()
    if (params?.search) qs.set('search', params.search)
    if (params?.source_type) qs.set('source_type', params.source_type)
    if (params?.limit) qs.set('limit', String(params.limit))
    const q = qs.toString()
    return this._request<{items: HistoryItem[]}>('GET', `/history${q ? '?' + q : ''}`)
  }
  taskTranscript(taskId: string) { return this._request<TranscriptResponse>('GET', `/task/${encodeURIComponent(taskId)}/transcript`) }
  historyDelete(taskId: string) { return this._request<unknown>('DELETE', `/history/${encodeURIComponent(taskId)}`) }
  historyDeleteMany(taskIds: string[]) {
    const fd = new FormData()
    taskIds.forEach((id, i) => fd.append('task_ids', id))
    return this._request<unknown>('POST', '/history/delete', fd)
  }

  /* ── Retry / regenerate ───────────────────────────────── */
  regenerateSummary(taskId: string, fd: FormData) {
    return this._request<TaskCreateResponse>('POST', `/regenerate-summary/${encodeURIComponent(taskId)}`, fd)
  }


  rssParse(fd: FormData, signal?: AbortSignal) { return this._request<RssParseResponse>('POST', '/rss/parse', fd, signal ? { signal } : {}) }
  rssCreateTask(fd: FormData) { return this._request<TaskCreateResponse>('POST', '/rss/create-task', fd) }
  rssSubscribe(fd: FormData) { return this._request<{feed: RssFeed}>('POST', '/rss/subscribe', fd) }
  rssFeeds() { return this._request<{feeds: RssFeed[]}>('GET', '/rss/feeds?full=true') }
  rssDeleteFeed(feedId: string) { return this._request<unknown>('DELETE', `/rss/feed/${encodeURIComponent(feedId)}`) }
  rssRefreshFeed(feedId: string) { return this._request<unknown>('POST', `/rss/refresh/${encodeURIComponent(feedId)}`) }
  rssToggleFavorite(feedId: string) { return this._request<{favorite: boolean}>('PUT', `/rss/feed/${encodeURIComponent(feedId)}/favorite`) }
  rssEnqueue(fd: FormData) { return this._request<QueueEnqueueResponse>('POST', '/rss/enqueue', fd) }

  /* ── Task queue ────────────────────────────────────── */
  queueState(queueName = 'tasks') { return this._request<QueueState>('GET', `/queue/state?queue_name=${encodeURIComponent(queueName)}`) }
  queueStreamUrl(queueName = 'tasks') { return `${this.base}/queue/stream/${encodeURIComponent(queueName)}` }
  queueClear(queueName = 'tasks') { return this._request<{cleared: number}>('POST', `/queue/clear?queue_name=${encodeURIComponent(queueName)}`) }
  queueStats(queueName = 'tasks') { return this._request<QueueStats>('GET', `/queue/${encodeURIComponent(queueName)}/stats`) }
  queueItems(queueName = 'tasks', params?: { status?: string; limit?: number; offset?: number }) {
    const qs = new URLSearchParams()
    if (params?.status) qs.set('status', params.status)
    if (params?.limit) qs.set('limit', String(params.limit))
    if (params?.offset) qs.set('offset', String(params.offset))
    const q = qs.toString()
    return this._request<QueueItemsResponse>('GET', `/queue/${encodeURIComponent(queueName)}/items${q ? '?' + q : ''}`)
  }
  queueItemDetail(itemId: string) { return this._request<QueueItem>('GET', `/queue/item/${encodeURIComponent(itemId)}`) }
  // 取消一项：杀掉运行中的下载/ffmpeg/Whisper 并删除记录。
  queueCancel(itemId: string, queueName = 'tasks') {
    return this._request<{message: string}>('POST', `/queue/item/${encodeURIComponent(itemId)}/cancel?queue_name=${encodeURIComponent(queueName)}`)
  }
  queueRemoveItem(itemId: string, queueName = 'tasks') {
    return this._request<{message: string}>('DELETE', `/queue/item/${encodeURIComponent(itemId)}?queue_name=${encodeURIComponent(queueName)}`)
  }

  /* ── Bot integration ──────────────────────────────────── */
  botsConfigure(body: BotsConfigureBody) {
    return this._request<BotsStatusResponse>('POST', '/bots/configure', JSON.stringify(body), {
      headers: { 'Content-Type': 'application/json' },
    })
  }
  botsStatus() { return this._request<BotsStatusResponse>('GET', '/bots/status') }
  botsTest(platform: string, token: string, extras: Record<string, unknown> = {}) {
    return this._request<{ ok: boolean; bot_name: string }>('POST', '/bots/test', JSON.stringify({ platform, token, extras }), {
      headers: { 'Content-Type': 'application/json' },
    })
  }
  botsSendTelegram(taskId: string, contentType: string) {
    return this._request<{ ok: boolean }>('POST', '/bots/telegram/send', JSON.stringify({ task_id: taskId, content_type: contentType }), {
      headers: { 'Content-Type': 'application/json' },
    })
  }

  /* ── Model status (no detail wrapping) ────────────────── */
  async modelStatus(): Promise<{ whisper_ready: boolean; whisper_error: string | null } | null> {
    try {
      const resp = await fetch(`${this.base}/model-status`)
      if (!resp.ok) return null
      return resp.json()
    } catch {
      return null
    }
  }
}

export const api = new VTApiClient('/api')
export type { VTApiClient }
