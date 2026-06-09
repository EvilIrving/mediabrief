/* UI utilities, settings, theme, copy/download helpers */
window.VTUiMethods = {
_initTheme() {
  const saved = localStorage.getItem('vt_theme');
  if (saved === 'light' || saved === 'dark') {
    document.documentElement.setAttribute('data-theme', saved);
    this._updateThemeIcon(saved);
    return;
  }
  if (window.matchMedia('(prefers-color-scheme: light)').matches) {
    document.documentElement.setAttribute('data-theme', 'light');
    this._updateThemeIcon('light');
  }
  window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', (e) => {
    if (!localStorage.getItem('vt_theme')) {
      const t = e.matches ? 'dark' : 'light';
      document.documentElement.setAttribute('data-theme', t);
      this._updateThemeIcon(t);
    }
  });
},

_toggleTheme() {
  const cur = document.documentElement.getAttribute('data-theme');
  const nxt = cur === 'light' ? 'dark' : 'light';
  document.documentElement.setAttribute('data-theme', nxt);
  localStorage.setItem('vt_theme', nxt);
  this._updateThemeIcon(nxt);
},

_updateThemeIcon(theme) {
  if (!this.themeIcon) return;
  this.themeIcon.className = theme === 'light' ? 'fas fa-moon' : 'fas fa-sun';
}

/* ── Page switching ───────────────────────────────────── */,

_switchPage(page) {
  this.currentPage = page;
  document.body.classList.toggle('list-page-active', page === 'rss' || page === 'history');
  this.tabNavBtns.forEach(b => b.classList.toggle('active', b.dataset.page === page));
  this.pagePanels.forEach(p => p.classList.toggle('active', p.id === 'page' + page.charAt(0).toUpperCase() + page.slice(1)));
  if (page === 'rss') this._rssLoadFeeds();
  if (page === 'history') this._historyLoad();
}

/* ── Settings persistence ─────────────────────────────── */,

_saveSettings() {
  const s = {
    baseUrl: this.modelBaseUrl.value, apiKey: this.apiKeyInput.value,
    model: this.modelSelect.value, summaryLang: this.summaryLangSel.value,
    useTwoStep: this.twoStepToggle.checked,
  };
  try { localStorage.setItem('vt_settings', JSON.stringify(s)); } catch (_) {}
},

_loadSettings() {
  try {
    const raw = localStorage.getItem('vt_settings');
    if (!raw) return;
    const s = JSON.parse(raw);
    if (s.baseUrl)     this.modelBaseUrl.value = s.baseUrl;
    if (s.apiKey)      this.apiKeyInput.value  = s.apiKey;
    if (s.summaryLang) this.summaryLangSel.value = s.summaryLang;
    if (s.useTwoStep !== undefined) {
      this.useTwoStep = s.useTwoStep;
      this.twoStepToggle.checked = s.useTwoStep;
    }
    this._savedModel = s.model || '';
    if (s.baseUrl || s.apiKey) {
      this.settingsBody.classList.add('open');
      this.settingsToggle.classList.add('open');
      if (s.baseUrl && s.apiKey) setTimeout(() => this._fetchModels(true), 400);
    }
  } catch (_) {}
}

/* ── Fetch models ─────────────────────────────────────── */,

async _fetchModels(silent = false) {
  const baseUrl = this.modelBaseUrl.value.trim().replace(/\/$/, '');
  const apiKey  = this.apiKeyInput.value.trim();
  if (!baseUrl || !apiKey) { if (!silent) this._setFetchStatus('err', this.t('api_url_required')); return; }
  this.fetchModelsBtn.disabled = true;
  this.fetchIcon.className = 'fas fa-spinner fa-spin';
  if (!silent) this._setFetchStatus('', this.t('fetching_models'));
  try {
    const fd = new FormData(); fd.append('base_url', baseUrl); fd.append('api_key', apiKey);
    const data = await this.api.fetchModels(fd);
    const models = data.data || data.models || [];
    this.modelSelect.innerHTML = `<option value="">${this.t('model_default')}</option>`;
    models.forEach(m => {
      const opt = document.createElement('option'); opt.value = m.id; opt.textContent = m.name || m.id;
      this.modelSelect.appendChild(opt);
    });
    if (this._savedModel) { this.modelSelect.value = this._savedModel; this._savedModel = ''; }
    this._setFetchStatus('ok', typeof this.t('models_loaded') === 'function' ? this.t('models_loaded')(models.length) : `${models.length} models`);
  } catch (e) {
    this._setFetchStatus('err', this.t('models_error') + ': ' + e.message);
  } finally {
    this.fetchModelsBtn.disabled = false; this.fetchIcon.className = 'fas fa-sync-alt';
  }
},

_setFetchStatus(cls, msg) { this.fetchStatus.className = 'fetch-status' + (cls ? ` ${cls}` : ''); this.fetchStatus.textContent = msg; }

/* ── Transcription ────────────────────────────────────── */,

async _copyTabContent(type) {
  let el, btn;
  if (type === 'script') { el = this.scriptContent; btn = this.copyScriptBtn; }
  else if (type === 'summary') { el = this.summaryContent; btn = this.copySummaryBtn; }
  else if (type === 'translation') { el = this.translationContent; btn = this.copyTranslationBtn; }
  else return;
  if (!el || !el.textContent.trim()) return;

  try {
    await navigator.clipboard.writeText(el.textContent.trim());
    btn.classList.add('copied');
    const icon = btn.querySelector('i');
    if (icon) icon.className = 'fas fa-check';
    setTimeout(() => {
      btn.classList.remove('copied');
      if (icon) icon.className = 'fas fa-copy';
    }, 1500);
  } catch (e) {
    // Fallback for non-HTTPS
    const ta = document.createElement('textarea');
    ta.value = el.textContent; ta.style.position = 'fixed'; ta.style.opacity = '0';
    document.body.appendChild(ta); ta.select();
    document.execCommand('copy'); document.body.removeChild(ta);
  }
}

/* ── Download ─────────────────────────────────────────── */,

async _downloadFile(type) {
  if (!this.currentTaskId) { this._showError(this.t('error_no_download')); return; }
  try {
    const task = await this.api.taskStatus(this.currentTaskId)
      .catch(() => { throw new Error(this.t('request_failed')); });
    let filename;
    if (type === 'script')      filename = task.script_path ? task.script_path.split('/').pop() : `transcript_${task.safe_title||'x'}_${task.short_id||'x'}.md`;
    else if (type === 'summary') filename = task.summary_path ? task.summary_path.split('/').pop() : `summary_${task.safe_title||'x'}_${task.short_id||'x'}.md`;
    else if (type === 'translation') filename = task.translation_path ? task.translation_path.split('/').pop() : `translation_${task.safe_title||'x'}_${task.short_id||'x'}.md`;
    else throw new Error(this.t('unknown_error'));
    const a = document.createElement('a');
    a.href = this.api.mdFileUrl(filename);
    a.download = filename; document.body.appendChild(a); a.click(); document.body.removeChild(a);
  } catch (e) { this._showError(this.t('error_download_failed') + e.message); }
}

/* ── UI helpers ───────────────────────────────────────── */,

_setLoading(on) {
  this.isProcessing = on;
  this.submitBtn.disabled = false;
  this.submitBtn.classList.toggle('processing', on);
  this.submitBtn.innerHTML = on ? `<span class="spinner"></span> ${this.t('processing')}` : `<i class="fas fa-search"></i> <span>${this.t('start_transcription')}</span>`;
  if (this.uploadPickBtn) this.uploadPickBtn.disabled = on;
  if (this.uploadZone) { this.uploadZone.style.pointerEvents = on ? 'none' : ''; this.uploadZone.style.opacity = on ? '0.65' : ''; this.uploadZone.tabIndex = on ? -1 : 0; }
  if (this.fileInput) this.fileInput.disabled = on;
  if (this.retryScriptBtn) this.retryScriptBtn.disabled = on;
  if (this.retrySummaryBtn) this.retrySummaryBtn.disabled = on;
  if (this.retryTranslationBtn) this.retryTranslationBtn.disabled = on;
},

_showError(msg) {
  this.errorMsg.textContent = msg; this.errorBanner.classList.add('show');
  this.errorBanner.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  setTimeout(() => this._hideError(), 6000);
},

_hideError() { this.errorBanner.classList.remove('show'); },

_debounce(fn, ms) { let t; return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); }; },

// Shared exclusive accordion: closes siblings, toggles target. Returns true if opened.
_accordionToggle(card, container, openClass) {
  const wasOpen = card.classList.contains(openClass);
  container.querySelectorAll(`.${openClass}`).forEach(c => c.classList.remove(openClass));
  if (!wasOpen) card.classList.add(openClass);
  return !wasOpen;
},

/* ═══════════════════════════════════════════════════════════
   Download-only page
   ═══════════════════════════════════════════════════════ */
};
