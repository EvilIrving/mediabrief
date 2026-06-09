/* RSS subscription and task logic */
window.VTRssMethods = {
_rssOpenDb() {
  if (!('indexedDB' in window)) return Promise.reject(new Error('IndexedDB is not available'));
  if (this._rssDbPromise) return this._rssDbPromise;
  this._rssDbPromise = new Promise((resolve, reject) => {
    const req = indexedDB.open('ai_transcriber_rss', 1);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains('feeds')) {
        const store = db.createObjectStore('feeds', { keyPath: 'id' });
        store.createIndex('url', 'url', { unique: false });
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error || new Error('Failed to open RSS database'));
  });
  return this._rssDbPromise;
},


async _rssReadStore() {
  const db = await this._rssOpenDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction('feeds', 'readonly');
    const req = tx.objectStore('feeds').getAll();
    req.onsuccess = () => resolve((req.result || []).sort((a, b) => String(b.added_at || '').localeCompare(String(a.added_at || ''))));
    req.onerror = () => reject(req.error || new Error('RSS read failed'));
  });
},

async _rssWriteStore(feeds) {
  const db = await this._rssOpenDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction('feeds', 'readwrite');
    const store = tx.objectStore('feeds');
    store.clear();
    (feeds || []).forEach(feed => { if (feed?.id) store.put(feed); });
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error || new Error('RSS write failed'));
  });
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
    const feeds = await this._rssReadStore();
    const idx = feeds.findIndex(f => f.id === newFeed.id || f.url === newFeed.url);
    if (idx >= 0) feeds[idx] = this._rssMergeFeed(feeds[idx], newFeed);
    else { (newFeed.entries || []).forEach(e => { if (!e.processed) e.processed = 'seen'; }); feeds.unshift(newFeed); }
    await this._rssWriteStore(feeds);
    this.rssFeedUrl.value = '';
    await this._rssLoadFeeds();
  } catch (e) {
    this._rssShowError(this.t('subscribe_failed') + (e.name === 'AbortError' ? this.t('timeout') : e.message));
  } finally {
    this.rssAddBtn.disabled = false;
    this.rssAddBtn.innerHTML = `<i class="fas fa-plus"></i> <span>${this.t('subscribe')}</span>`;
  }
},

_rssNormalizeImportList(data) {
  const list = Array.isArray(data) ? data : data?.feeds;
  if (!Array.isArray(list)) throw new Error(this.t('rss_json_invalid'));
  const seen = new Set();
  return list
    .map(item => (typeof item === 'string' ? { url: item } : item))
    .filter(item => item && typeof item.url === 'string')
    .map(item => ({ ...item, url: item.url.trim() }))
    .filter(item => {
      if (!item.url || seen.has(item.url.replace(/\/$/, ''))) return false;
      seen.add(item.url.replace(/\/$/, ''));
      return true;
    });
},

async _rssImportFeedList(feedList, btn) {
  const normalized = this._rssNormalizeImportList(feedList);
  const existing = await this._rssReadStore();
  const existingUrls = new Set(existing.map(f => (f.url || '').replace(/\/$/, '')));
  const pending = normalized.filter(f => !existingUrls.has(f.url.replace(/\/$/, '')));
  const total = pending.length;
  let feeds = existing;
  let done = 0;
  let imported = 0;
  let failed = 0;
  const failedItems = [];

  console.info('[RSS import] start', {
    inputCount: Array.isArray(feedList) ? feedList.length : feedList?.feeds?.length,
    normalizedCount: normalized.length,
    existingCount: existing.length,
    pendingCount: pending.length,
  });

  if (!total) {
    console.info('[RSS import] nothing to import');
    this._rssShowError(this.t('imported_json_feeds')(0, 0));
    return;
  }

  const parseWithRetry = async (preset, tries = 3) => {
    let lastError;
    for (let attempt = 1; attempt <= tries; attempt += 1) {
      console.info(`[RSS import] parsing ${done + 1}/${total}, attempt ${attempt}/${tries}`, preset.title || preset.url, preset.url);
      try {
        const feed = await this._rssParseFeed(preset.url);
        console.info('[RSS import] parsed', preset.title || preset.url, { title: feed.title, entries: feed.entries?.length || 0 });
        return feed;
      } catch (e) {
        lastError = e;
        console.warn(`[RSS import] parse failed, attempt ${attempt}/${tries}`, preset.title || preset.url, e);
        if (attempt < tries) await new Promise(resolve => setTimeout(resolve, 800 * attempt));
      }
    }
    throw lastError;
  };

  while (pending.length) {
    const preset = pending.shift();
    try {
      const newFeed = await parseWithRetry(preset);
      feeds = await this._rssReadStore();
      const idx = feeds.findIndex(f => f.id === newFeed.id || f.url === newFeed.url);
      if (idx >= 0) {
        feeds[idx] = this._rssMergeFeed(feeds[idx], newFeed);
        console.info('[RSS import] merged existing feed', newFeed.title, newFeed.url);
      } else {
        (newFeed.entries || []).forEach(e => { if (!e.processed) e.processed = 'seen'; });
        feeds.unshift(newFeed);
        console.info('[RSS import] added feed', newFeed.title, newFeed.url);
      }
      await this._rssWriteStore(feeds);
      imported += 1;
    } catch (e) {
      failed += 1;
      failedItems.push(`${preset.title || preset.url}: ${e.message || e}`);
      console.error('[RSS import] final failure', preset.title || preset.url, preset.url, e);
    } finally {
      done += 1;
      if (btn) btn.innerHTML = `<span class="spinner"></span> ${this.t('importing_json_feeds')(done, total)}`;
      await this._rssLoadFeeds();
    }
  }

  console.info('[RSS import] done', { imported, failed, failedItems });
  if (failedItems.length) console.warn('RSS import failures:', failedItems);
  this._rssShowError(this.t('imported_json_feeds')(imported, failed));
},

async _rssImportJsonFile(file) {
  if (!file) return;
  console.info('[RSS import] file selected', { name: file.name, size: file.size, type: file.type });
  const btn = this.rssImportJsonBtn;
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = `<span class="spinner"></span> ${this.t('adding')}`;
  }
  this._rssHideError();
  try {
    const raw = await file.text();
    console.info('[RSS import] file read', { bytes: raw.length });
    const data = JSON.parse(raw);
    console.info('[RSS import] json parsed', { isArray: Array.isArray(data), feedCount: Array.isArray(data) ? data.length : data?.feeds?.length });
    await this._rssImportFeedList(data, btn);
  } catch (e) {
    console.error('[RSS import] import aborted', e);
    this._rssShowError(this.t('rss_import_failed') + e.message);
  } finally {
    if (this.rssJsonFileInput) this.rssJsonFileInput.value = '';
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = `<i class="fas fa-file-import"></i> <span>${this.t('import_json_feeds')}</span>`;
    }
    await this._rssLoadFeeds();
  }
},

async _rssLoadFeeds() {
  this._rssFeeds = this._rssSummaries(await this._rssReadStore());
  this._rssFilterFeeds();
  if (this.rssSearchInput) this.rssSearchInput.value = '';
  if (this.rssSearchRow) this.rssSearchRow.style.display = this._rssFeeds.length ? 'block' : 'none';
},

_rssFilterFeeds() {
  const q = (this.rssSearchInput?.value || '').trim().toLowerCase();
  const filtered = q ? this._rssFeeds.filter(f => (f.title || '').toLowerCase().includes(q)) : this._rssFeeds;
  this._rssRenderFeeds(filtered);
},

_rssRenderFeeds(feeds) {
  const fullFeeds = this._rssFeeds || feeds;
  if (!fullFeeds.length) {
    this.feedList.innerHTML = `<div class="rss-empty"><div class="rss-empty-icon"><i class="fas fa-satellite-dish"></i></div><p>${this.t('rss_empty')}</p></div>`;
    if (this.rssSummaryBar) this.rssSummaryBar.style.display = 'none';
    if (this.rssSearchRow) this.rssSearchRow.style.display = 'none';
    return;
  }
  if (this.rssSearchRow) this.rssSearchRow.style.display = 'block';
  if (this.rssSummaryBar) {
    const totalEntries = fullFeeds.reduce((s, f) => s + (f.entry_count || 0), 0);
    const totalNew = fullFeeds.reduce((s, f) => s + (f.new_count || 0), 0);
    this.rssSummaryBar.style.display = 'flex';
    this.rssSummaryText.textContent = `${this.t('rss_total')(fullFeeds.length, totalEntries, totalNew)}`;
  }
  if (!feeds.length) {
    this.feedList.innerHTML = `<div class="rss-empty"><div class="rss-empty-icon"><i class="fas fa-search"></i></div><p>${this.t('rss_no_match')}</p></div>`;
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
      const wasExpanded = card.classList.contains('expanded');
      this.feedList.querySelectorAll('.feed-card.expanded').forEach(c => c.classList.remove('expanded'));
      if (!wasExpanded) {
        card.classList.add('expanded');
        const fid = card.dataset.feedId;
        this._rssLoadEntries(fid);
      }
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
  const feed = (await this._rssReadStore()).find(f => f.id === feedId);
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
    const feed = (await this._rssReadStore()).find(f => f.id === feedId);
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
    await this._rssWriteStore((await this._rssReadStore()).map(f => f.id === feedId ? feed : f));

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
  await this._rssWriteStore((await this._rssReadStore()).filter(f => f.id !== feedId));
  await this._rssLoadFeeds();
},

async _rssRefreshFeed(feedId) {
  const card = this.feedList.querySelector(`[data-feed-id="${feedId}"]`);
  const refreshBtn = card?.querySelector('[data-action="refresh-feed"] i');
  const feeds = await this._rssReadStore();
  const idx = feeds.findIndex(f => f.id === feedId);
  if (idx < 0) return;
  if (refreshBtn) refreshBtn.className = 'fas fa-spinner fa-spin';
  try {
    const parsed = await this._rssParseFeed(feeds[idx].url);
    const merged = this._rssMergeFeed(feeds[idx], parsed);
    feeds[idx] = merged;
    await this._rssWriteStore(feeds);
    await this._rssLoadFeeds();
    if (card?.classList.contains('expanded')) await this._rssLoadEntries(feedId);
    if (merged.new_count > 0) {
      this._rssShowError(this.t('found_new_items')(merged.new_count));
      setTimeout(() => this._rssHideError(), 3000);
    }
  } catch (e) {
    feeds[idx].last_error = e.name === 'AbortError' ? this.t('timeout') : e.message;
    await this._rssWriteStore(feeds);
    this._rssShowError(this.t('refresh_failed') + feeds[idx].last_error);
  } finally {
    if (refreshBtn) refreshBtn.className = 'fas fa-sync-alt';
  }
},

_rssShowError(msg) { this.rssErrorMsg.textContent = msg; this.rssErrorBanner.classList.add('show'); setTimeout(() => this._rssHideError(), 6000); },

_rssHideError() {
  if (this.rssErrorBanner) this.rssErrorBanner.classList.remove('show');
  if (this.rssErrorMsg) this.rssErrorMsg.textContent = '';
},

};
