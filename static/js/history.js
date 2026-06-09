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
    this._historySelected = new Set();
    this._updateHistorySelectUI();
    this._historyRender();
  } catch (e) {
    this.historyList.innerHTML = `<div class="history-empty"><div class="history-empty-icon"><i class="fas fa-triangle-exclamation"></i></div><p>${this.t('history_load_failed')}${this._escapeHtml(e.message || String(e))}</p></div>`;
  }
},

_historyRender() {
  if (!this.historyList) return;
  const q = (this.historySearch?.value || '').trim().toLowerCase();
  const filteredBySource = this.historyItems.filter(item => this._historyMatchesSourceFilter(item));
  const items = q ? filteredBySource.filter(item => [item.title, item.source, item.summary].join('\n').toLowerCase().includes(q)) : filteredBySource;
  if (!items.length) {
    const msg = q ? this.t('no_matches') : this.t('history_empty');
    this.historyList.innerHTML = `<div class="history-empty"><div class="history-empty-icon"><i class="fas fa-box-archive"></i></div><p>${msg}</p></div>`;
    return;
  }
  const inSelect = this._historySelectMode;
  this.historyList.innerHTML = items.map(item => {
    const date = item.createdAt ? new Date(item.createdAt).toLocaleString() : '';
    const source = item.source || '';
    const sourceHtml = source && /^https?:\/\//i.test(source)
      ? `<a class="history-source" href="${this._escapeHtml(source)}" target="_blank" rel="noreferrer">${this.t('source_link')}</a>`
      : this._escapeHtml(source || item.sourceType || this.t('local_task'));
    const checked = this._historySelected.has(item.id) ? ' checked' : '';
    const checkboxHtml = inSelect
      ? `<input type="checkbox" class="history-checkbox" data-history-id="${this._escapeHtml(item.id)}"${checked}>`
      : '';
    return `
      <div class="history-item${inSelect ? ' select-mode' : ''}" data-history-id="${this._escapeHtml(item.id)}">
        <div class="history-head">
          <div class="history-head-left">
            ${checkboxHtml}
            <div>
              <div class="history-title">${this._escapeHtml(item.title || this.t('unnamed_summary'))}</div>
              <div class="history-meta"><span>${date}</span><span>${sourceHtml}</span></div>
            </div>
          </div>
          <button class="btn-sm" data-action="delete-history" data-history-id="${this._escapeHtml(item.id)}">${this.t('delete')}</button>
        </div>
        <div class="history-body"><div class="md-content">${marked.parse(item.summary || '')}</div></div>
      </div>
    `;
  }).join('');

  // Click title / head area to expand (exclusive accordion)
  this.historyList.querySelectorAll('.history-item').forEach(card => {
    const head = card.querySelector('.history-head');
    if (!head) return;
    head.addEventListener('click', (e) => {
      if (e.target.closest('[data-action]') || e.target.closest('a') || e.target.closest('.history-checkbox')) return;
      this._accordionToggle(card, this.historyList, 'open');
    });
  });
  this.historyList.querySelectorAll('[data-action="delete-history"]').forEach(btn => {
    btn.addEventListener('click', () => {
      if (confirm(this.t('confirm_delete_history'))) this._historyDelete(btn.dataset.historyId);
    });
  });

  // Checkbox toggle in select mode
  if (inSelect) {
    this.historyList.querySelectorAll('.history-checkbox').forEach(cb => {
      cb.addEventListener('click', (e) => {
        e.stopPropagation();
        const id = cb.dataset.historyId;
        if (cb.checked) this._historySelected.add(id);
        else this._historySelected.delete(id);
        this._updateHistorySelectUI();
      });
    });
  }
},


_historyMatchesSourceFilter(item) {
  const filter = this._historySourceFilter || 'all';
  if (filter === 'all') return true;
  if (filter === 'file') return item.sourceType === 'file';
  if (filter === 'rss') return item.sourceType === 'rss';
  if (filter === 'youtube') return /(^|\.)youtube\.com|youtu\.be/i.test(item.source || '');
  return true;
},

_historyVisibleItems() {
  const q = (this.historySearch?.value || '').trim().toLowerCase();
  const bySource = this.historyItems.filter(item => this._historyMatchesSourceFilter(item));
  return q ? bySource.filter(item => [item.title, item.source, item.summary].join('\n').toLowerCase().includes(q)) : bySource;
},

/* ── Select mode ───────────────────────────────────────────── */

_historyToggleSelectMode() {
  this._historySelectMode = !this._historySelectMode;
  if (!this._historySelectMode) this._historySelected.clear();
  this._updateHistorySelectUI();
  this._historyRender();
},

_updateHistorySelectUI() {
  const n = this._historySelected.size;
  if (this.historySelectBtn) {
    this.historySelectBtn.textContent = this._historySelectMode
      ? this.t('selected_count_short')(n) : this.t('select');
  }
  if (this.historyDeleteSelBar) {
    if (this._historySelectMode) {
      this.historyDeleteSelBar.style.display = 'flex';
      this.historyDeleteSelBar.innerHTML = `
        <span>${this.t('selected_count')(n)}</span>
        <button class="btn-sm" id="historySelectAll">${this.t('select_all')}</button>
        <button class="btn-sm" id="historyDeselectAll">${this.t('deselect_all')}</button>
        <button class="btn-sm primary" id="historyDeleteSelected"${n ? '' : ' disabled'}>${this.t('delete_selected')}</button>
      `;
      document.getElementById('historySelectAll').addEventListener('click', () => {
        this._historyVisibleItems().forEach(item => this._historySelected.add(item.id));
        this._updateHistorySelectUI();
        this._historyRender();
      });
      document.getElementById('historyDeselectAll').addEventListener('click', () => {
        this._historySelected.clear();
        this._updateHistorySelectUI();
        this._historyRender();
      });
      document.getElementById('historyDeleteSelected').addEventListener('click', () => {
        if (n && confirm(this.t('confirm_delete_selected')(n))) this._historyDeleteSelected();
      });
    } else {
      this.historyDeleteSelBar.style.display = 'none';
    }
  }
},

async _historyDeleteSelected() {
  const ids = [...this._historySelected];
  if (!ids.length) return;
  try {
    await this._historyTx('readwrite', (store) => {
      for (const id of ids) store.delete(id);
    });
    this.historyItems = this.historyItems.filter(item => !this._historySelected.has(item.id));
    this._historySelected.clear();
    this._updateHistorySelectUI();
    this._historyRender();
  } catch (e) {
    alert(this.t('delete_failed') + (e.message || e));
  }
},

async _historyDelete(id) {
  if (!id) return;
  try {
    await this._historyTx('readwrite', (store) => store.delete(id));
    this.historyItems = this.historyItems.filter(item => item.id !== id);
    this._historySelected.delete(id);
    this._updateHistorySelectUI();
    this._historyRender();
  } catch (e) {
    alert(this.t('delete_failed') + (e.message || e));
  }
}

/* ═══════════════════════════════════════════════════════════
   RSS page methods live in rss.js
   ═══════════════════════════════════════════════════════════ */
};
