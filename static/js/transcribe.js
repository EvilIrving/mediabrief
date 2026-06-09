/* Transcription task flow and result rendering */
window.VTTranscribeMethods = {
async _startTranscription() {
  if (this.isProcessing) { await this._cancelCurrentTask(); return; }
  const url = this.videoUrlInput.value.trim();
  if (!url) { this._showError(this.t('error_invalid_url')); return; }
  this.currentSource = { type: 'url', value: url, title: '' };
  this.partialSummaryShown = false;
  this._setLoading(true); this._hideResults(); this._showProgressTranscribe();
  try {
    const fd = this._buildFormData(url);
    const resp = await fetch(`${this.apiBase}/process-video`, { method: 'POST', body: fd });
    if (!resp.ok) { const err = await resp.json().catch(() => ({})); throw new Error(err.detail || this.t('request_failed')); }
    const data = await resp.json();
    this.currentTaskId = data.task_id;
    this._initSP(); this._startSSE(); this._saveSettings();
  } catch (err) {
    this._showError(this.t('error_processing_failed') + err.message);
    this._setLoading(false); this._hideProgressTranscribe();
  }
},

async _startFileUpload(file) {
  if (this.isProcessing) return;
  const parts = (file.name || '').split('.');
  const ext = parts.length > 1 ? ('.' + parts.pop().toLowerCase()) : '';
  if (!this._allowedUploadExts.has(ext)) { this._showError(this.t('error_upload_type')); return; }
  if (!file.size) { this._showError(this.t('error_upload_empty')); return; }
  const maxB = this.uploadMaxMb * 1024 * 1024;
  if (file.size > maxB) { this._showError(this.t('error_upload_size')(this.uploadMaxMb)); return; }
  this.currentSource = { type: 'file', value: file.name || '', title: file.name || '' };
  this.partialSummaryShown = false;
  this._setLoading(true); this._hideResults(); this._showProgressTranscribe();
  try {
    const fd = this._buildFormData(''); fd.append('file', file, file.name);
    const resp = await fetch(`${this.apiBase}/process-video`, { method: 'POST', body: fd });
    if (!resp.ok) { const err = await resp.json().catch(() => ({})); throw new Error(err.detail || this.t('request_failed')); }
    const data = await resp.json();
    this.currentTaskId = data.task_id;
    this._initSP(); this._startSSE(); this._saveSettings();
  } catch (err) {
    this._showError(this.t('error_processing_failed') + err.message);
    this._setLoading(false); this._hideProgressTranscribe();
  }
},

_buildFormData(url) {
  const fd = new FormData();
  fd.append('url', url || '');
  fd.append('summary_language', this.summaryLangSel.value);
  const apiKey = this.apiKeyInput.value.trim();
  const baseUrl = this.modelBaseUrl.value.trim().replace(/\/$/, '');
  const modelId = this.modelSelect.value;
  if (apiKey)  fd.append('api_key', apiKey);
  if (baseUrl) fd.append('model_base_url', baseUrl);
  if (modelId) fd.append('model_id', modelId);
  return fd;
}

/* ── SSE ──────────────────────────────────────────────── */,

_startSSE() {
  if (!this.currentTaskId) return;
  this._stopSSE();
  this.eventSource = new EventSource(`${this.apiBase}/task-stream/${this.currentTaskId}`);
  this.eventSource.onmessage = (ev) => {
    try {
      const task = JSON.parse(ev.data);
      if (task.type === 'heartbeat') return;
      this._updateProgressFromTask(task);
      if (task.status === 'processing' && task.summary && !this.partialSummaryShown) {
        this._showPartialSummary(task);
      }
      if (task.status === 'completed') {
        this._stopSP(); this._stopSSE(); this._setLoading(false); this._hideProgressTranscribe();
        this._showResults(task.script, task.summary, task.video_title, task.translation, task.detected_language, task.summary_language, this.partialSummaryShown ? 'summary' : 'script');
      } else if (task.status === 'error') {
        this._stopSP(); this._stopSSE(); this._setLoading(false); this._hideProgressTranscribe();
        this._showError(task.error || this.t('processing_error'));
      }
    } catch (_) {}
  };
  this.eventSource.onerror = async () => {
    this._stopSSE();
    try {
      if (this.currentTaskId) {
        const r = await fetch(`${this.apiBase}/task-status/${this.currentTaskId}`);
        if (r.ok) {
          const task = await r.json();
          if (task?.status === 'completed') {
            this._stopSP(); this._setLoading(false); this._hideProgressTranscribe();
            this._showResults(task.script, task.summary, task.video_title, task.translation, task.detected_language, task.summary_language, this.partialSummaryShown ? 'summary' : 'script');
            return;
          }
        }
      }
    } catch (_) {}
    this._showError(this.t('error_processing_failed') + this.t('sse_disconnected'));
    this._setLoading(false);
  };
},

_stopSSE() { if (this.eventSource) { this.eventSource.close(); this.eventSource = null; } },

async _cancelCurrentTask() {
  if (!this.currentTaskId) {
    this._setLoading(false);
    this._hideProgressTranscribe();
    return;
  }
  const taskId = this.currentTaskId;
  this._stopSP();
  this._stopSSE();
  this.currentTaskId = null;
  this._setLoading(false);
  this._hideProgressTranscribe();
  this.progressMessage.textContent = '';
  try {
    await fetch(`${this.apiBase}/task/${encodeURIComponent(taskId)}`, { method: 'DELETE' });
  } catch (_) {}
}

/* ── Stage-weighted Progress (dual bar) ───────────────── */,

_updateProgressFromTask(task) {
  const pct = this._clampPct(task.progress || 0);
  const stageName = task.current_stage_label || task.message || '';
  const stageDetail = task.current_stage_detail || task.message || stageName;

  // The bar is secondary. The stage chain below is the source of truth.
  this.progressStatus.textContent = this._formatTaskProgress(task, pct);
  this.progressFill.style.width = pct + '%';

  this.progStageName.textContent = stageName;
  if (this.progStageDetail) this.progStageDetail.textContent = stageDetail;
  this.progressMessage.textContent = task.message || '';
  this._renderResultAvailability(task);
  this._renderStageChain(task);

  // Mode badge
  if (task.mode === 'subtitle') {
    this.modeBadge.textContent = task.mode_label || '';
    this.modeBadge.className = 'mode-badge subtitle';
    this.progressFill.classList.add('subtitle-mode');
  } else if (task.mode === 'whisper') {
    this.modeBadge.textContent = task.mode_label || '';
    this.modeBadge.className = 'mode-badge whisper';
    this.progressFill.classList.remove('subtitle-mode');
  }

  this._stopSP(); // disable smart progress simulation when we have real stage data
},

_formatTaskProgress(task, pct) {
  if (task?.progress_label) return task.progress_label;
  return '';
},

_renderResultAvailability(task) {
  if (!this.progArtifacts) return;
  const items = Array.isArray(task?.result_items) ? task.result_items : [];
  this.progArtifacts.innerHTML = items.map(item => {
    const cls = item.state === 'ready' ? 'ready' : 'waiting';
    const icon = item.key === 'summary' ? 'fa-file-lines' : 'fa-align-left';
    return `<span class="artifact-pill ${cls}" data-artifact="${this._escapeHtml(item.key || '')}"><i class="fas ${icon}"></i> ${this._escapeHtml(item.label || '')} · ${this._escapeHtml(item.state_label || '')}</span>`;
  }).join('');
},

_renderStageChain(task) {
  if (!this.progStageList) return;
  const stages = Array.isArray(task?.stage_items) ? task.stage_items : [];
  if (!stages.length) {
    this.progStageList.innerHTML = '';
    return;
  }
  this.progStageList.innerHTML = stages.map((stage) => {
    const state = stage.state || 'pending';
    const title = stage.detail || stage.label || stage.name;
    return `<span class="prog-step ${this._escapeHtml(state)}" title="${this._escapeHtml(title)}"><span class="prog-step-dot"></span><span>${this._escapeHtml(stage.name || '')}</span></span>`;
  }).join('');
}

/* ── Smart Progress (fallback for legacy tasks) ───────── */,

_initSP() {
  this.sp.enabled = false; this.sp.current = 0; this.sp.target = 15;
  this.sp.lastServer = 0; this.sp.startTime = Date.now(); this.sp.stage = 'preparing';
},

_startSP() {
  if (this.sp.interval) clearInterval(this.sp.interval);
  this.sp.enabled = true; this.sp.startTime = this.sp.startTime || Date.now();
  this.sp.interval = setInterval(() => this._tickSP(), 500);
},

_stopSP() { if (this.sp.interval) { clearInterval(this.sp.interval); this.sp.interval = null; } this.sp.enabled = false; },

_clampPct(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return 0;
  return Math.max(0, Math.min(100, n));
},

_tickSP() {
  if (!this.sp.enabled || this.sp.current >= this.sp.target) return;
  const speeds = { subtitle: .5, parsing: .3, downloading: .18, transcribing: .14, optimizing: .22, summarizing: .28 };
  let inc = speeds[this.sp.stage] || .2;
  const remaining = this.sp.target - this.sp.current;
  if (remaining < 5) inc *= .3;
  const next = Math.min(this.sp.current + inc, this.sp.target);
  if (next > this.sp.current) {
    this.sp.current = next;
    const pct = this._clampPct(next);
    this.progressStatus.textContent = Math.round(pct) + '%';
    this.progressFill.style.width = pct + '%';
  }
}

/* ── Results ──────────────────────────────────────────── */,

_normLangTab(code) {
  if (!code) return '';
  const c = String(code).toLowerCase().trim();
  if (c.startsWith('zh')) return 'zh';
  if (c.length >= 2) return c.slice(0, 2);
  return c;
},

_showResults(script, summary, videoTitle, translation, detectedLang, summaryLang, preferredTab = 'script') {
  this.scriptContent.innerHTML  = script    ? marked.parse(script)  : '';
  this.summaryContent.innerHTML = summary   ? marked.parse(summary) : '';
  const d = this._normLangTab(detectedLang);
  const s = this._normLangTab(summaryLang);
  const showTrans = Boolean(translation) && d && s && d !== s;
  if (showTrans) {
    this.translationContent.innerHTML = marked.parse(translation);
    this.translationTabBtn.style.display = 'inline-block';
    this.dlTranslation.style.display = 'inline-flex';
  } else {
    this.translationTabBtn.style.display = 'none';
    this.dlTranslation.style.display = 'none';
  }
  this.resultsPanel.classList.add('show');
  this._switchResultTab(preferredTab);
  this.resultsPanel.scrollIntoView({ behavior: 'smooth', block: 'start' });
  this._historySaveSummary({ summary, videoTitle, summaryLang });
},

_showPartialSummary(task) {
  this.partialSummaryShown = true;
  this.scriptContent.innerHTML = `<p style="color:var(--text-muted);font-style:italic;">${this.t('transcript_pending')}</p>`;
  this.summaryContent.innerHTML = marked.parse(task.summary);
  this.translationTabBtn.style.display = 'none';
  this.dlTranslation.style.display = 'none';
  this.resultsPanel.classList.add('show');
  this._switchResultTab('summary');
  this.resultsPanel.scrollIntoView({ behavior: 'smooth', block: 'start' });
},

_hideResults() { this.resultsPanel.classList.remove('show'); },

_switchResultTab(name) {
  this.tabBtns.forEach(b => b.classList.toggle('active', b.dataset.tab === name));
  this.tabPanes.forEach(p => p.classList.toggle('active', p.id === `${name}Tab`));
},

_showProgressTranscribe() {
  this.emptyState.style.display = 'none';
  this.resultsPanel.classList.remove('show');
  this.progressPanel.classList.add('show');
  this.progStageName.textContent = '';
  if (this.progStagePct) this.progStagePct.textContent = '';
  if (this.modeBadge) { this.modeBadge.style.display = 'none'; this.modeBadge.className = 'mode-badge'; }
  if (this.progressFill) { this.progressFill.classList.remove('subtitle-mode'); this.progressFill.style.width = '0%'; }
  if (this.progStageDetail) this.progStageDetail.textContent = '';
  if (this.progArtifacts) this.progArtifacts.innerHTML = '';
  if (this.progStageList) this.progStageList.innerHTML = '';
  this.progressStatus.textContent = '';
},

_hideProgressTranscribe() { this.progressPanel.classList.remove('show'); },

/* ── Copy to clipboard ──────────────────────────────── */

/* ── Retry ──────────────────────────────────────────── */

async _retryTranscription() {
  if (!this.currentTaskId) { this._showError(this.t('processing_error')); return; }
  if (this.isProcessing) return;

  this._setLoading(true);
  this._showProgressTranscribe();
  this.progStageName.textContent = '';
  this.progressMessage.textContent = '';

  try {
    const fd = this._buildFormData('');
    // 追加 two_step 开关
    fd.append('use_two_step', this.useTwoStep ? 'true' : 'false');

    const resp = await fetch(`${this.apiBase}/retry/${encodeURIComponent(this.currentTaskId)}`, {
      method: 'POST',
      body: fd,
    });
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      throw new Error(err.detail || this.t('request_failed'));
    }
    const data = await resp.json();
    this.currentTaskId = data.task_id;
    this.partialSummaryShown = false;
    this._initSP();
    this._startSSE();
    this._saveSettings();
  } catch (err) {
    this._showError(this.t('error_processing_failed') + err.message);
    this._setLoading(false);
    this._hideProgressTranscribe();
  }
}
};
