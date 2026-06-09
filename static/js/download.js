/* Download page logic */
window.VTDownloadMethods = {
_switchDwnTab(tab) {
  this.dwnTabBtns.forEach(b => {
    const active = b.dataset.dwntab === tab;
    b.style.borderBottomColor = active ? 'var(--accent)' : 'transparent';
    b.style.color = active ? 'var(--accent-text)' : 'var(--text-muted)';
  });
  this.dwnTabPanes.forEach(p => {
    p.style.display = p.id === 'dwnTab' + tab.charAt(0).toUpperCase() + tab.slice(1) ? 'block' : 'none';
  });
},

async _dwnDetectFormats() {
  const url = this.dwnUrl.value.trim();
  if (!url) { this._dwnShowError(this.t('url_required')); return; }
  this.dwnDetectBtn.disabled = true;
  this.dwnDetectBtn.innerHTML = `<span class="spinner"></span> ${this.t('detecting')}`;
  this._dwnHideError();
  this.dwnFormatsDiv.style.display = 'none';
  this.dwnCompleted.style.display = 'none';
  this.dwnProgressPanel.classList.remove('show');
  try {
    const fd = new FormData(); fd.append('url', url);
    const data = await this.api.downloadFormats(fd).catch((err) => {
      throw new Error(err.detail || this.t('request_failed'));
    });

    // Store detected data
    this._dwnData = data;
    this.dwnSelectedVideoFormat = 'bestvideo+bestaudio/best';
    this.dwnSelectedAudioFormat = 'bestaudio/best';

    // Render all three tabs
    this._dwnRenderVideoFormats();
    this._dwnRenderAudioFormats();
    this._dwnRenderSubtitleOptions();

    this.dwnFormatsDiv.style.display = 'block';
    this._switchDwnTab('video');
  } catch (e) {
    this._dwnShowError(this.t('detect_failed') + e.message);
  } finally {
    this.dwnDetectBtn.disabled = false;
    this.dwnDetectBtn.innerHTML = `<i class="fas fa-magnifying-glass"></i> <span>${this.t('detect')}</span>`;
  }
},

_dwnRenderVideoFormats() {
  const formats = this._dwnData?.video_formats || [];
  this.dwnFmtList.innerHTML = '';
  formats.forEach((f) => {
    const div = document.createElement('div');
    div.className = 'fmt-item' + (f.id === this.dwnSelectedVideoFormat ? ' selected' : '');
    const sizeStr = f.filesize ? this._dwnFormatSize(f.filesize) : '';
    div.innerHTML = `
      <div class="fmt-main">
        <span class="fmt-name">${this._escapeHtml(f.note || f.resolution || f.id)}</span>
        <span class="fmt-detail">${this._escapeHtml(f.ext || '')}${f.vcodec ? ' · ' + f.vcodec : ''}</span>
      </div>
      <span class="fmt-size">${sizeStr}</span>
    `;
    div.addEventListener('click', () => {
      this.dwnSelectedVideoFormat = f.id;
      this._dwnRenderVideoFormats();
    });
    this.dwnFmtList.appendChild(div);
  });
},

_dwnRenderAudioFormats() {
  const formats = this._dwnData?.audio_formats || [];
  this.dwnAudioFmtList.innerHTML = '';
  if (!formats.length) {
    this.dwnAudioFmtList.innerHTML = `<div class="dwn-empty">${this.t('audio_unavailable')}</div>`;
    this.dwnStartAudioBtn.disabled = true;
    return;
  }
  this.dwnStartAudioBtn.disabled = false;
  formats.forEach((f) => {
    const div = document.createElement('div');
    div.className = 'fmt-item' + (f.id === this.dwnSelectedAudioFormat ? ' selected' : '');
    const sizeStr = f.filesize ? this._dwnFormatSize(f.filesize) : '';
    div.innerHTML = `
      <div class="fmt-main">
        <span class="fmt-name">${this._escapeHtml(f.note || f.id)}</span>
        <span class="fmt-detail">${this._escapeHtml(f.ext || '')}${f.acodec ? ' · ' + f.acodec : ''}${f.abr ? ' · ' + f.abr + 'kbps' : ''}</span>
      </div>
      <span class="fmt-size">${sizeStr}</span>
    `;
    div.addEventListener('click', () => {
      this.dwnSelectedAudioFormat = f.id;
      this._dwnRenderAudioFormats();
    });
    this.dwnAudioFmtList.appendChild(div);
  });
},

_dwnRenderSubtitleOptions() {
  const subs = this._dwnData?.subtitles || {};
  const manual = subs.manual || [];
  const auto = subs.auto || [];
  const allLangs = [...new Set([...manual, ...auto])].sort();

  if (!allLangs.length) {
    this.dwnSubInfo.innerHTML = `<p style="color:var(--text-dim);"><i class="fas fa-circle-info"></i> ${this.t('no_subtitles')}</p>`;
    this.dwnSubLang.innerHTML = '';
    this.dwnStartSubBtn.disabled = true;
    return;
  }

  this.dwnStartSubBtn.disabled = false;
  const manualSet = new Set(manual);
  let info = '';
  if (manual.length) info += `<i class="fas fa-closed-captioning"></i> ${this.t('manual_subtitles')}${manual.join(', ')}<br>`;
  if (auto.length) info += `<i class="fas fa-wand-magic-sparkles"></i> ${this.t('auto_subtitles')}${auto.join(', ')}`;
  this.dwnSubInfo.innerHTML = info || this.t('subtitles_available');

  this.dwnSubLang.innerHTML = allLangs.map(l => {
    const isManual = manualSet.has(l);
    return `<option value="${l}">${l}${isManual ? ` (${this.t('manual')})` : ` (${this.t('auto')})`}</option>`;
  }).join('');

  // Default to English, then the first available subtitle.
  const preferOrder = ['en', 'en-orig', 'zh-Hans', 'zh-Hant', 'zh'];
  for (const p of preferOrder) {
    if (allLangs.includes(p)) { this.dwnSubLang.value = p; break; }
  }
},

_dwnFormatSize(bytes) {
  if (!bytes || bytes <= 0) return '';
  const units = ['B', 'KB', 'MB', 'GB'];
  let i = 0, val = bytes;
  while (val >= 1024 && i < units.length - 1) { val /= 1024; i++; }
  return val.toFixed(i > 0 ? 1 : 0) + ' ' + units[i];
},

_escapeHtml(s) { const d = document.createElement('div'); d.textContent = s; return d.innerHTML; },

async _dwnStartDownload(type) {
  const url = this.dwnUrl.value.trim();
  if (!url) return;

  this.dwnFormatsDiv.style.display = 'none';
  this.dwnCompleted.style.display = 'none';
  this.dwnProgressPanel.classList.add('show');
  this.dwnProgressStatus.textContent = '0%';
  this.dwnProgressFill.style.width = '0%';
  this.dwnStageName.textContent = '';
  this.dwnStagePct.textContent = '';

  try {
    const fd = new FormData();
    fd.append('url', url);

    let call;
    if (type === 'video') {
      fd.append('format_id', this.dwnSelectedVideoFormat);
      fd.append('filename', this._dwnData?.title || '');
      call = this.api.downloadVideo(fd);
    } else if (type === 'audio') {
      fd.append('format_id', this.dwnSelectedAudioFormat);
      fd.append('filename', this._dwnData?.title || '');
      fd.append('audio_format', this.dwnAudioContainer.value);
      call = this.api.downloadAudio(fd);
    } else if (type === 'subtitle') {
      fd.append('lang', this.dwnSubLang.value);
      fd.append('filename', this._dwnData?.title || '');
      call = this.api.downloadSubtitles(fd);
    }

    const data = await call.catch((err) => { throw new Error(err.detail || this.t('request_failed')); });
    this.dwnTaskId = data.task_id;
    this._dwnStartSSE();
  } catch (e) {
    this._dwnShowError(this.t('download_failed') + e.message);
    this.dwnProgressPanel.classList.remove('show');
  }
},

_dwnStartSSE() {
  if (!this.dwnTaskId) return;
  this._dwnStopSSE();
  this.dwnEventSource = new EventSource(this.api.streamUrl(this.dwnTaskId));
  this.dwnEventSource.onmessage = (ev) => {
    try {
      const task = JSON.parse(ev.data);
      if (task.type === 'heartbeat') return;
      const pct = this._clampPct(task.progress || 0);
      this.dwnProgressStatus.textContent = Math.round(pct) + '%';
      this.dwnProgressFill.style.width = pct + '%';
      if (task.current_stage_label) {
        const stagePct = this._clampPct(task.current_stage_progress || 0);
        this.dwnStageName.textContent = task.current_stage_label;
        this.dwnStagePct.textContent = stagePct > 0 ? Math.round(stagePct) + '%' : '';
      }
      this.dwnProgressMsg.textContent = task.message || '';
      if (task.status === 'completed') {
        this._dwnStopSSE();
        this.dwnProgressPanel.classList.remove('show');
        this.dwnCompleted.style.display = 'block';
        this.dwnFileName.textContent = task.filename || '';
        this.dwnFileLink.href = this.api.videoFileUrl(task.filename || '');
      } else if (task.status === 'error') {
        this._dwnStopSSE();
        this.dwnProgressPanel.classList.remove('show');
        this._dwnShowError(task.error || this.t('download_failed'));
      }
    } catch (_) {}
  };
  this.dwnEventSource.onerror = () => { this._dwnStopSSE(); };
},

_dwnStopSSE() { if (this.dwnEventSource) { this.dwnEventSource.close(); this.dwnEventSource = null; } },

_dwnShowError(msg) { this.dwnErrorMsg.textContent = msg; this.dwnErrorBanner.classList.add('show'); setTimeout(() => this._dwnHideError(), 8000); },

_dwnHideError() { this.dwnErrorBanner.classList.remove('show'); }

/* ═══════════════════════════════════════════════════════════
   Summary history (stored in browser IndexedDB)
   ═══════════════════════════════════════════════════════ */
};
