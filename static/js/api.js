/* ────────────────────────────────────────────────────────────
   AI Video Transcriber · api.js
   Network layer: the single place that knows about server
   endpoints. UI mixins call these methods instead of fetch().

   Conventions:
   - On HTTP success, returns the parsed JSON body.
   - On HTTP error, throws an Error whose `.message` is the server
     `detail` (or `HTTP <status>`), and which also carries
     `.detail` (server detail or undefined) and `.status`.
     Callers that need a localized fallback use `err.detail || t(...)`.
   - Network/abort failures reject as usual (e.g. AbortError),
     so timeout handling at call sites is preserved.
   ──────────────────────────────────────────────────────────── */
class VTApiClient {
  constructor(base) { this.base = base || '/api'; }

  async _request(method, path, body, opts = {}) {
    const init = { method, ...opts };
    if (body !== undefined) init.body = body;
    const resp = await fetch(`${this.base}${path}`, init);
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      const e = new Error(err.detail || `HTTP ${resp.status}`);
      e.detail = err.detail;
      e.status = resp.status;
      throw e;
    }
    return resp.json();
  }

  /* ── URL builders (for EventSource / <a download>) ────── */
  streamUrl(taskId)        { return `${this.base}/task-stream/${taskId}`; }
  mdFileUrl(filename)      { return `${this.base}/download/${encodeURIComponent(filename)}`; }
  videoFileUrl(filename)   { return `${this.base}/download-video/file/${encodeURIComponent(filename)}`; }

  /* ── Transcribe / task ────────────────────────────────── */
  processVideo(fd)         { return this._request('POST', '/process-video', fd); }
  retry(taskId, fd)        { return this._request('POST', `/retry/${encodeURIComponent(taskId)}`, fd); }
  taskStatus(taskId)       { return this._request('GET', `/task-status/${taskId}`); }
  deleteTask(taskId)       { return this._request('DELETE', `/task/${encodeURIComponent(taskId)}`); }

  /* ── Models ───────────────────────────────────────────── */
  fetchModels(fd)          { return this._request('POST', '/models', fd); }

  /* ── Download-only page ───────────────────────────────── */
  downloadFormats(fd)      { return this._request('POST', '/download-video/formats', fd); }
  downloadVideo(fd)        { return this._request('POST', '/download-video', fd); }
  downloadAudio(fd)        { return this._request('POST', '/download-audio', fd); }
  downloadSubtitles(fd)    { return this._request('POST', '/download-subtitles', fd); }

  /* ── Retry / regenerate ───────────────────────────────── */
  regenerateSummary(taskId, fd) {
    return this._request('POST', `/regenerate-summary/${encodeURIComponent(taskId)}`, fd);
  }

  /* ── RSS ──────────────────────────────────────────────── */
  rssParse(fd, signal)     { return this._request('POST', '/rss/parse', fd, signal ? { signal } : {}); }
  rssCreateTask(fd)        { return this._request('POST', '/rss/create-task', fd); }
}

window.VTApiClient = VTApiClient;
