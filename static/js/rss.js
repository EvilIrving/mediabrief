/* RSS subscription and task logic */
window.VTRssMethods = {
_rssReadStore() {
  try {
    const raw = localStorage.getItem('vt_rss_feeds');
    const feeds = raw ? JSON.parse(raw) : [];
    return Array.isArray(feeds) ? feeds : [];
  } catch (_) {
    return [];
  }
},

_rssWriteStore(feeds) {
  localStorage.setItem('vt_rss_feeds', JSON.stringify(feeds));
},

async _rssFetchWithTimeout(url, options = {}, ms = 35000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), ms);
  try {
    return await fetch(url, { ...options, signal: controller.signal });
  } finally {
    clearTimeout(timer);
  }
},

_rssMergeFeed(oldFeed, newFeed) {
  const oldEntries = oldFeed?.entries || [];
  const oldStatus = new Map(oldEntries.filter(e => e.processed).map(e => [e.id, e.processed]));
  const existingIds = new Set(oldEntries.map(e => e.id));
  const mergedEntries = (newFeed.entries || []).map(e => ({ ...e, processed: oldStatus.get(e.id) || e.processed }));
  for (const entry of oldEntries) {
    if (!mergedEntries.some(e => e.id === entry.id)) mergedEntries.push(entry);
  }
  return {
    ...newFeed,
    added_at: oldFeed?.added_at || newFeed.added_at,
    entries: mergedEntries,
    new_count: mergedEntries.filter(e => !e.processed && !existingIds.has(e.id)).length,
  };
},

_rssSummaries(feeds) {
  return feeds.map(f => ({
    id: f.id,
    title: f.title,
    type: f.type,
    url: f.url,
    last_checked: f.last_checked,
    last_error: f.last_error,
    entry_count: (f.entries || []).length,
    new_count: (f.entries || []).filter(e => !e.processed).length,
  }));
},

async _rssParseFeed(feedUrl) {
  const fd = new FormData();
  fd.append('feed_url', feedUrl);
  const resp = await this._rssFetchWithTimeout(`${this.apiBase}/rss/parse`, { method: 'POST', body: fd });
  if (!resp.ok) { const err = await resp.json().catch(() => ({})); throw new Error(err.detail || this.t('request_failed')); }
  const data = await resp.json();
  return data.feed;
},

async _rssSubscribe() {
  const feedUrl = this.rssFeedUrl.value.trim();
  if (!feedUrl) { this._rssShowError(this.t('rss_url_placeholder')); return; }
  this.rssAddBtn.disabled = true;
  this.rssAddBtn.innerHTML = `<span class="spinner"></span> ${this.t('adding')}`;
  this._rssHideError();
  try {
    const newFeed = await this._rssParseFeed(feedUrl);
    const feeds = this._rssReadStore();
    const idx = feeds.findIndex(f => f.id === newFeed.id || f.url === newFeed.url);
    if (idx >= 0) feeds[idx] = this._rssMergeFeed(feeds[idx], newFeed);
    else feeds.unshift(newFeed);
    this._rssWriteStore(feeds);
    this.rssFeedUrl.value = '';
    this._rssLoadFeeds();
  } catch (e) {
    this._rssShowError(this.t('subscribe_failed') + (e.name === 'AbortError' ? this.t('timeout') : e.message));
  } finally {
    this.rssAddBtn.disabled = false;
    this.rssAddBtn.innerHTML = `<i class="fas fa-plus"></i> <span>${this.t('subscribe')}</span>`;
  }
},

async _rssLoadFeeds() {
  this._rssRenderFeeds(this._rssSummaries(this._rssReadStore()));
},

_rssRenderFeeds(feeds) {
  if (!feeds.length) {
    this.feedList.innerHTML = `<div class="rss-empty"><div class="rss-empty-icon"><i class="fas fa-satellite-dish"></i></div><p>${this.t('rss_empty')}</p></div>`;
    return;
  }
  this.feedList.innerHTML = feeds.map(f => {
    const lastChecked = f.last_checked ? new Date(f.last_checked).toLocaleString() : this.t('never_updated');
    const errorInfo = f.last_error ? `<span style="color:var(--error);font-size:10px;" title="${this._escapeHtml(f.last_error)}"><i class="fas fa-triangle-exclamation"></i> ${this.t('rss_refresh_failed')}</span>` : '';
    const newBadge = f.new_count > 0 ? `<span class="badge" style="background:var(--accent);">${this.t('new_count')(f.new_count)}</span>` : '';
    return `
    <div class="feed-card" data-feed-id="${f.id}">
      <div class="feed-card-header">
        <div>
          <div class="feed-card-title">
            ${this._escapeHtml(f.title)} ${newBadge}
          </div>
          <div class="feed-card-meta">
            <span class="feed-card-badge">${String(f.type || 'rss').toUpperCase()}</span>
            <span>${this.t('item_count')(f.entry_count || 0)}</span>
            <span style="font-size:10px;">${this.t('updated')} ${lastChecked}</span>
            ${errorInfo}
          </div>
        </div>
        <div style="display:flex;gap:4px;">
          <button class="feed-card-del" data-action="refresh-feed" data-feed-id="${f.id}" title="${this.t('refresh')}">
            <i class="fas fa-sync-alt"></i>
          </button>
          <button class="feed-card-del" data-action="delete-feed" data-feed-id="${f.id}" title="${this.t('delete')}">
            <i class="fas fa-trash"></i>
          </button>
        </div>
      </div>
      <div class="feed-entries" id="entries-${f.id}">
        <div style="text-align:center;padding:20px;color:var(--text-dim);">${this.t('expand_entries_hint')}</div>
      </div>
    </div>
  `}).join('');

  this.feedList.querySelectorAll('.feed-card').forEach(card => {
    card.addEventListener('click', (e) => {
      if (e.target.closest('[data-action]')) return;
      card.classList.toggle('expanded');
      const fid = card.dataset.feedId;
      if (card.classList.contains('expanded')) this._rssLoadEntries(fid);
    });
  });

  this.feedList.querySelectorAll('[data-action="delete-feed"]').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      if (confirm(this.t('confirm_delete_feed'))) this._rssDeleteFeed(btn.dataset.feedId);
    });
  });

  this.feedList.querySelectorAll('[data-action="refresh-feed"]').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      this._rssRefreshFeed(btn.dataset.feedId);
    });
  });
},

async _rssLoadEntries(feedId) {
  const container = document.getElementById('entries-' + feedId);
  if (!container) return;
  const feed = this._rssReadStore().find(f => f.id === feedId);
  if (!feed) { container.innerHTML = `<div style="text-align:center;padding:20px;color:var(--error);">${this.t('feed_missing')}</div>`; return; }
  const entries = feed.entries || [];
  container.innerHTML = entries.length ? entries.map(e => {
    const isSummarized = e.processed === 'summarized';
    const isDownloaded = e.processed === 'downloaded';
    const hasAudio = Boolean(e.enclosure_url);
    const processedClass = isSummarized || isDownloaded ? ' processed' : '';
    return `
    <div class="entry-item${processedClass}">
      <span class="entry-title" title="${this._escapeHtml(e.title)}">
        ${isSummarized ? '<i class="fas fa-file-lines"></i> ' : isDownloaded ? '<i class="fas fa-circle-down"></i> ' : ''}${this._escapeHtml(e.title)}
      </span>
      <div class="entry-actions">
        <button class="btn-sm primary" data-action="summarize" data-feed="${feedId}" data-entry="${e.id}"
          ${isSummarized ? 'disabled' : ''}>
          ${isSummarized ? this.t('summarized') : this.t('summarize')}
        </button>
        ${hasAudio ? `
        <button class="btn-sm" data-action="download-entry" data-feed="${feedId}" data-entry="${e.id}"
          ${isDownloaded ? 'disabled' : ''}>
          ${isDownloaded ? this.t('downloaded') : this.t('nav_download')}
        </button>` : ''}
      </div>
    </div>
  `}).join('') : `<div style="text-align:center;padding:20px;color:var(--text-dim);">${this.t('no_entries')}</div>`;

  container.querySelectorAll('.btn-sm:not([disabled])').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const action = btn.dataset.action;
      const fid = btn.dataset.feed;
      const eid = btn.dataset.entry;
      if (action === 'summarize') this._rssCreateTask(fid, eid, 'summarize');
      else if (action === 'download-entry') this._rssCreateTask(fid, eid, 'download');
    });
  });
},

async _rssCreateTask(feedId, entryId, action) {
  try {
    const feed = this._rssReadStore().find(f => f.id === feedId);
    const entry = feed?.entries?.find(e => e.id === entryId);
    if (!entry) throw new Error(this.t('feed_missing'));

    const fd = new FormData();
    fd.append('feed_id', feedId);
    fd.append('entry_id', entryId);
    fd.append('entry_json', JSON.stringify(entry));
    fd.append('action', action);
    fd.append('summary_language', this.summaryLangSel.value);
    const apiKey = this.apiKeyInput.value.trim();
    const baseUrl = this.modelBaseUrl.value.trim().replace(/\/$/, '');
    const modelId = this.modelSelect.value;
    if (apiKey)  fd.append('api_key', apiKey);
    if (baseUrl) fd.append('model_base_url', baseUrl);
    if (modelId) fd.append('model_id', modelId);

    const resp = await fetch(`${this.apiBase}/rss/create-task`, { method: 'POST', body: fd });
    if (!resp.ok) { const err = await resp.json().catch(() => ({})); throw new Error(err.detail || this.t('request_failed')); }
    const data = await resp.json();

    entry.processed = action === 'download' ? 'downloaded' : 'summarized';
    this._rssWriteStore(this._rssReadStore().map(f => f.id === feedId ? feed : f));

    this.currentSource = { type: 'rss', value: entry.link || entry.enclosure_url || '', title: entry.title || feed.title || '' };
    this._switchPage('transcribe');
    this.currentTaskId = data.task_id;
    this._showProgressTranscribe();
    this._initSP();
    this._startSSE();
    this._setLoading(true);
  } catch (e) {
    this._rssShowError(this.t('task_creation_failed') + e.message);
  }
},

async _rssDeleteFeed(feedId) {
  this._rssWriteStore(this._rssReadStore().filter(f => f.id !== feedId));
  this._rssLoadFeeds();
},

async _rssRefreshFeed(feedId) {
  const card = this.feedList.querySelector(`[data-feed-id="${feedId}"]`);
  const refreshBtn = card?.querySelector('[data-action="refresh-feed"] i');
  const feeds = this._rssReadStore();
  const idx = feeds.findIndex(f => f.id === feedId);
  if (idx < 0) return;
  if (refreshBtn) refreshBtn.className = 'fas fa-spinner fa-spin';
  try {
    const parsed = await this._rssParseFeed(feeds[idx].url);
    const merged = this._rssMergeFeed(feeds[idx], parsed);
    feeds[idx] = merged;
    this._rssWriteStore(feeds);
    this._rssLoadFeeds();
    if (card?.classList.contains('expanded')) this._rssLoadEntries(feedId);
    if (merged.new_count > 0) {
      this._rssShowError(this.t('found_new_items')(merged.new_count));
      setTimeout(() => this._rssHideError(), 3000);
    }
  } catch (e) {
    feeds[idx].last_error = e.name === 'AbortError' ? this.t('timeout') : e.message;
    this._rssWriteStore(feeds);
    this._rssShowError(this.t('refresh_failed') + feeds[idx].last_error);
  } finally {
    if (refreshBtn) refreshBtn.className = 'fas fa-sync-alt';
  }
},

_rssShowError(msg) { this.rssErrorMsg.textContent = msg; this.rssErrorBanner.classList.add('show'); setTimeout(() => this._rssHideError(), 6000); },


};
