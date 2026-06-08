/* IndexedDB-backed summary history */
window.VTHistoryMethods = {
_historyOpenDb() {
  if (!('indexedDB' in window)) return Promise.reject(new Error('IndexedDB is not available'));
  if (this._historyDbPromise) return this._historyDbPromise;
  this._historyDbPromise = new Promise((resolve, reject) => {
    const req = indexedDB.open('ai_transcriber_history', 1);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains('summaries')) {
        const store = db.createObjectStore('summaries', { keyPath: 'id' });
        store.createIndex('createdAt', 'createdAt');
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error || new Error(this.t('history_db_failed')));
  });
  return this._historyDbPromise;
},

async _historyTx(mode, run) {
  const db = await this._historyOpenDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction('summaries', mode);
    const store = tx.objectStore('summaries');
    let result;
    tx.oncomplete = () => resolve(result);
    tx.onerror = () => reject(tx.error || new Error('History transaction failed'));
    try { result = run(store); } catch (e) { reject(e); }
  });
},

async _historySaveSummary({ summary, videoTitle, summaryLang }) {
  const text = (summary || '').trim();
  if (!text) return;
  const now = new Date().toISOString();
  const source = this.currentSource || {};
  const title = (videoTitle || source.title || this.t('unnamed_summary')).trim();
  const item = {
    id: this.currentTaskId || `summary_${Date.now()}`,
    taskId: this.currentTaskId || '',
    title,
    sourceType: source.type || 'url',
    source: source.value || '',
    summary: text,
    summaryLang: summaryLang || this.summaryLangSel?.value || '',
    createdAt: now,
  };
  try {
    await this._historyTx('readwrite', (store) => store.add(item));
    if (this.currentPage === 'history') await this._historyLoad();
  } catch (e) {
    if (e?.name !== 'ConstraintError') console.warn('Failed to save summary history', e);
  }
},

async _historyLoad() {
  if (!this.historyList) return;
  try {
    const items = await this._historyTx('readonly', (store) => {
      const req = store.getAll();
      return new Promise((resolve, reject) => {
        req.onsuccess = () => resolve(req.result || []);
        req.onerror = () => reject(req.error);
      });
    });
    this.historyItems = (items || []).sort((a, b) => String(b.createdAt).localeCompare(String(a.createdAt)));
    this._historyRender();
  } catch (e) {
    this.historyList.innerHTML = `<div class="history-empty"><div class="history-empty-icon"><i class="fas fa-triangle-exclamation"></i></div><p>${this.t('history_load_failed')}${this._escapeHtml(e.message || String(e))}</p></div>`;
  }
},

_historyRender() {
  if (!this.historyList) return;
  const q = (this.historySearch?.value || '').trim().toLowerCase();
  const items = q ? this.historyItems.filter(item => [item.title, item.source, item.summary].join('\n').toLowerCase().includes(q)) : this.historyItems;
  if (!items.length) {
    const msg = q ? this.t('no_matches') : this.t('history_empty');
    this.historyList.innerHTML = `<div class="history-empty"><div class="history-empty-icon"><i class="fas fa-box-archive"></i></div><p>${msg}</p></div>`;
    return;
  }
  this.historyList.innerHTML = items.map(item => {
    const date = item.createdAt ? new Date(item.createdAt).toLocaleString() : '';
    const source = item.source || '';
    const sourceHtml = source && /^https?:\/\//i.test(source)
      ? `<a class="history-source" href="${this._escapeHtml(source)}" target="_blank" rel="noreferrer">${this.t('source_link')}</a>`
      : this._escapeHtml(source || item.sourceType || this.t('local_task'));
    return `
      <div class="history-item" data-history-id="${this._escapeHtml(item.id)}">
        <div class="history-head">
          <div>
            <div class="history-title">${this._escapeHtml(item.title || this.t('unnamed_summary'))}</div>
            <div class="history-meta"><span>${date}</span><span>${sourceHtml}</span></div>
          </div>
          <div class="history-actions">
            <button class="btn-sm primary" data-action="open-history" data-history-id="${this._escapeHtml(item.id)}">${this.t('view')}</button>
            <button class="btn-sm" data-action="delete-history" data-history-id="${this._escapeHtml(item.id)}">${this.t('delete')}</button>
          </div>
        </div>
        <div class="history-body"><div class="md-content">${marked.parse(item.summary || '')}</div></div>
      </div>
    `;
  }).join('');

  this.historyList.querySelectorAll('[data-action="open-history"]').forEach(btn => {
    btn.addEventListener('click', () => {
      const card = btn.closest('.history-item');
      if (!card) return;
      const open = card.classList.toggle('open');
      btn.textContent = open ? this.t('collapse') : this.t('view');
    });
  });
  this.historyList.querySelectorAll('[data-action="delete-history"]').forEach(btn => {
    btn.addEventListener('click', () => {
      if (confirm(this.t('confirm_delete_history'))) this._historyDelete(btn.dataset.historyId);
    });
  });
},

async _historyDelete(id) {
  if (!id) return;
  try {
    await this._historyTx('readwrite', (store) => store.delete(id));
    this.historyItems = this.historyItems.filter(item => item.id !== id);
    this._historyRender();
  } catch (e) {
    alert(this.t('delete_failed') + (e.message || e));
  }
}

/* ═══════════════════════════════════════════════════════════
   RSS page (subscriptions are stored in browser localStorage)
   ═══════════════════════════════════════════════════════ */
};
