/* ────────────────────────────────────────────────────────────
   AI Video Transcriber · app.js
   Dual-step summary / Stage-weighted progress / Downloads / RSS
   ──────────────────────────────────────────────────────────── */

class VideoTranscriber {
  constructor() {
    this.currentTaskId  = null;
    this.eventSource    = null;
    this.apiBase        = '/api';
    this.currentLang    = 'en';
    this.currentPage    = 'transcribe';
    this.useTwoStep     = true;  // dual-step summary on by default

    /* Smart progress simulation (for transcribe page only) */
    this.sp = { enabled: false, current: 0, target: 15, lastServer: 0, interval: null, startTime: null, stage: 'preparing' };

    /* Download-only page state */
    this.dwnTaskId = null;
    this.dwnEventSource = null;
    this.dwnFormats = [];
    this.dwnSelectedFormat = 'best';

    this.i18n = {
      en: {
        title: 'AI Video Transcriber', subtitle: 'Supports automatic transcription and AI summary for 30+ platforms',
        video_url_placeholder: 'Paste YouTube, Tiktok, Bilibili or other platform video URLs...',
        start_transcription: 'Transcribe', ai_settings: 'AI Settings',
        model_base_url: 'Model API Base URL', model_base_url_placeholder: 'https://openrouter.ai/api/v1',
        api_key: 'API Key', api_key_placeholder: 'sk-...', fetch_models: 'Fetch',
        model_select: 'Model', model_default: '— use server default —',
        summary_language: 'Summary Language', processing_progress: 'Processing',
        preparing: 'Preparing…', transcript_text: 'Transcript', intelligent_summary: 'AI Summary',
        translation: 'Translation', download_transcript: 'Transcript', download_translation: 'Translation',
        download_summary: 'Summary', empty_hint: 'Paste a video URL or drop a file above and let AI do the heavy lifting.',
        footer_text: 'This tool is part of <a href="https://sipsip.ai" target="_blank" style="color:var(--accent-text);text-decoration:none;">sipsip.ai</a> — distill anything and get daily AI briefs from your favorite creators',
        processing: 'Processing…', downloading_video: 'Downloading audio…', parsing_video: 'Parsing video info…',
        transcribing_audio: 'Transcribing audio…', optimizing_transcript: 'Optimizing transcript…',
        generating_summary: 'Generating summary…', detecting_subtitles: 'Detecting subtitles…',
        subtitle_found: 'Subtitles found! Processing text…', no_subtitle: 'No subtitles found, downloading audio…',
        mode_subtitle: '⚡ Subtitle', mode_whisper: '🎙 Whisper', completed: 'Done!',
        error_invalid_url: 'Please enter a valid video URL', error_processing_failed: 'Processing failed: ',
        error_no_download: 'No file available for download', error_download_failed: 'Download failed: ',
        fetching_models: 'Fetching models…', models_loaded: (n) => `${n} models loaded`,
        models_error: 'Failed to fetch models', upload_or: 'or drop your files',
        upload_formats: '.mp3 · .mp4 · .wav · .m4a · .webm · .mkv · .ogg · .flac',
        upload_files_btn: 'Upload files', error_upload_type: 'Unsupported file type',
        error_upload_empty: 'File is empty', error_upload_size: (mb) => `File exceeds ${mb} MB limit`,
      },
      zh: {
        title: 'AI 视频转录器', subtitle: '粘贴 YouTube、TikTok 或任意公开视频链接，获取转录文本和 AI 摘要。',
        video_url_placeholder: '请输入视频链接…', start_transcription: '开始转录', ai_settings: 'AI 设置',
        model_base_url: 'Model API 地址', model_base_url_placeholder: 'https://openrouter.ai/api/v1',
        api_key: 'API Key', api_key_placeholder: 'sk-...', fetch_models: '获取',
        model_select: '模型', model_default: '— 使用服务器默认 —', summary_language: '摘要语言',
        processing_progress: '处理进度', preparing: '准备中…', transcript_text: '转录文本',
        intelligent_summary: '智能摘要', translation: '翻译', download_transcript: '转录',
        download_translation: '翻译', download_summary: '摘要',
        empty_hint: '在上方粘贴视频链接或拖放文件，让 AI 来处理一切。',
        footer_text: '本工具是 <a href="https://sipsip.ai" target="_blank" style="color:var(--accent-text);text-decoration:none;">sipsip.ai</a> 的一部分 — 提取任何内容要点并构建你自己的知识库。',
        processing: '处理中…', downloading_video: '正在下载音频…', parsing_video: '正在解析视频信息…',
        transcribing_audio: '正在转录音频…', optimizing_transcript: '正在优化转录文本…',
        generating_summary: '正在生成摘要…', detecting_subtitles: '正在检测字幕…',
        subtitle_found: '字幕获取成功！正在处理文本…', no_subtitle: '未找到字幕，正在下载音频…',
        mode_subtitle: '⚡ 字幕模式', mode_whisper: '🎙 Whisper 模式', completed: '处理完成！',
        error_invalid_url: '请输入有效的视频链接', error_processing_failed: '处理失败：',
        error_no_download: '没有可下载的文件', error_download_failed: '下载失败：',
        fetching_models: '正在获取模型列表…', models_loaded: (n) => `已加载 ${n} 个模型`,
        models_error: '获取模型失败', upload_or: '或拖放文件到此处',
        upload_formats: '.mp3 · .mp4 · .wav · .m4a · .webm · .mkv · .ogg · .flac',
        upload_files_btn: '上传文件', error_upload_type: '不支持的文件类型',
        error_upload_empty: '文件为空', error_upload_size: (mb) => `文件超过 ${mb} MB 限制`,
      }
    };

    this._initElements();
    this._bindEvents();
    this._initTheme();
    this._loadSettings();
    this._switchLang('en');
  }

  /* ── Elements ─────────────────────────────────────────── */
  _initElements() {
    // Transcribe page
    this.form               = document.getElementById('videoForm');
    this.videoUrlInput      = document.getElementById('videoUrl');
    this.submitBtn          = document.getElementById('submitBtn');
    this.summaryLangSel     = document.getElementById('summaryLanguage');
    this.errorBanner        = document.getElementById('errorBanner');
    this.errorMsg           = document.getElementById('errorMsg');
    this.emptyState         = document.getElementById('emptyState');
    this.progressPanel      = document.getElementById('progressPanel');
    this.modeBadge          = document.getElementById('modeBadge');
    this.progressStatus     = document.getElementById('progressStatus');
    this.progressFill       = document.getElementById('progressFill');
    this.progressMessage    = document.getElementById('progressMessage');
    this.progStageName      = document.getElementById('progStageName');
    this.progStagePct       = document.getElementById('progStagePct');
    this.resultsPanel       = document.getElementById('resultsPanel');
    this.scriptContent      = document.getElementById('scriptContent');
    this.summaryContent     = document.getElementById('summaryContent');
    this.translationContent = document.getElementById('translationContent');
    this.dlScript           = document.getElementById('downloadScript');
    this.dlTranslation      = document.getElementById('downloadTranslation');
    this.dlSummary          = document.getElementById('downloadSummary');
    this.copyScriptBtn      = document.getElementById('copyScript');
    this.copySummaryBtn     = document.getElementById('copySummary');
    this.translationTabBtn  = document.getElementById('translationTabBtn');
    this.tabBtns            = document.querySelectorAll('#pageTranscribe .tab-btn');
    this.tabPanes           = document.querySelectorAll('#pageTranscribe .tab-pane');
    // Settings
    this.settingsToggle     = document.getElementById('settingsToggle');
    this.settingsBody       = document.getElementById('settingsBody');
    this.modelBaseUrl       = document.getElementById('modelBaseUrl');
    this.apiKeyInput        = document.getElementById('apiKeyInput');
    this.fetchModelsBtn     = document.getElementById('fetchModelsBtn');
    this.fetchStatus        = document.getElementById('fetchStatus');
    this.modelSelect        = document.getElementById('modelSelect');
    this.fetchIcon          = document.getElementById('fetchIcon');
    this.twoStepToggle      = document.getElementById('twoStepToggle');
    // Upload
    this.uploadZone         = document.getElementById('uploadZone');
    this.uploadPickBtn      = document.getElementById('uploadPickBtn');
    this.fileInput          = document.getElementById('fileInput');
    this.uploadMaxMb        = 200;
    this._allowedUploadExts = new Set(['.txt', '.mp3', '.mp4', '.m4a', '.wav', '.webm', '.mkv', '.ogg', '.flac']);
    // Theme/lang
    this.themeToggle        = document.getElementById('themeToggle');
    this.themeIcon          = document.getElementById('themeIcon');
    this.langToggle         = document.getElementById('langToggle');
    this.langText           = document.getElementById('langText');
    // Page nav
    this.tabNavBtns         = document.querySelectorAll('.tab-nav-btn');
    this.pagePanels         = document.querySelectorAll('.page-panel');

    // Download page
    this.dwnUrl             = document.getElementById('dwnUrl');
    this.dwnDetectBtn       = document.getElementById('dwnDetectBtn');
    this.dwnFormatsDiv      = document.getElementById('dwnFormats');
    this.dwnFmtList         = document.getElementById('dwnFmtList');
    this.dwnStartBtn        = document.getElementById('dwnStartBtn');
    this.dwnProgressPanel   = document.getElementById('dwnProgressPanel');
    this.dwnProgressStatus  = document.getElementById('dwnProgressStatus');
    this.dwnProgressFill    = document.getElementById('dwnProgressFill');
    this.dwnProgressMsg     = document.getElementById('dwnProgressMsg');
    this.dwnStageName       = document.getElementById('dwnStageName');
    this.dwnStagePct        = document.getElementById('dwnStagePct');
    this.dwnCompleted       = document.getElementById('dwnCompleted');
    this.dwnFileName        = document.getElementById('dwnFileName');
    this.dwnFileLink        = document.getElementById('dwnFileLink');
    this.dwnErrorBanner     = document.getElementById('dwnErrorBanner');
    this.dwnErrorMsg        = document.getElementById('dwnErrorMsg');

    // RSS page
    this.rssFeedUrl         = document.getElementById('rssFeedUrl');
    this.rssAddBtn          = document.getElementById('rssAddBtn');
    this.feedList           = document.getElementById('feedList');
    this.rssErrorBanner     = document.getElementById('rssErrorBanner');
    this.rssErrorMsg        = document.getElementById('rssErrorMsg');
  }

  /* ── Events ───────────────────────────────────────────── */
  _bindEvents() {
    // Transcribe form
    this.form.addEventListener('submit', (e) => { e.preventDefault(); this._startTranscription(); });
    // Lang
    this.langToggle.addEventListener('click', () => { this._switchLang(this.currentLang === 'en' ? 'zh' : 'en'); });
    // Theme
    this.themeToggle.addEventListener('click', () => this._toggleTheme());
    // Settings
    this.settingsToggle.addEventListener('click', () => {
      const open = this.settingsBody.classList.toggle('open');
      this.settingsToggle.classList.toggle('open', open);
    });
    this.fetchModelsBtn.addEventListener('click', () => this._fetchModels());
    const debouncedFetch = this._debounce(() => {
      if (this.modelBaseUrl.value.trim() && this.apiKeyInput.value.trim()) this._fetchModels();
    }, 900);
    this.modelBaseUrl.addEventListener('input', debouncedFetch);
    this.apiKeyInput.addEventListener('input', debouncedFetch);
    [this.modelBaseUrl, this.apiKeyInput, this.modelSelect, this.summaryLangSel, this.twoStepToggle].forEach(el => {
      el.addEventListener('change', () => this._saveSettings());
    });
    // Two-step toggle
    this.twoStepToggle.addEventListener('change', () => {
      this.useTwoStep = this.twoStepToggle.checked;
      this._saveSettings();
    });
    // Tabs
    this.tabBtns.forEach(btn => { btn.addEventListener('click', () => this._switchResultTab(btn.dataset.tab)); });
    // Downloads
    this.dlScript.addEventListener('click',      () => this._downloadFile('script'));
    this.dlTranslation.addEventListener('click', () => this._downloadFile('translation'));
    this.dlSummary.addEventListener('click',     () => this._downloadFile('summary'));
    // Copy buttons
    this.copyScriptBtn.addEventListener('click',  () => this._copyTabContent('script'));
    this.copySummaryBtn.addEventListener('click', () => this._copyTabContent('summary'));
    // Upload
    if (this.uploadPickBtn && this.fileInput && this.uploadZone) {
      this.uploadPickBtn.addEventListener('click', (e) => { e.stopPropagation(); this.fileInput.click(); });
      this.uploadZone.addEventListener('click', (e) => {
        if (e.target === this.uploadPickBtn || this.uploadPickBtn.contains(e.target)) return;
        this.fileInput.click();
      });
      this.fileInput.addEventListener('change', () => {
        const f = this.fileInput.files && this.fileInput.files[0];
        this.fileInput.value = '';
        if (f) this._startFileUpload(f);
      });
      ['dragenter', 'dragover'].forEach((ev) => {
        this.uploadZone.addEventListener(ev, (e) => { e.preventDefault(); this.uploadZone.classList.add('dragover'); });
      });
      this.uploadZone.addEventListener('dragleave', (e) => { if (!this.uploadZone.contains(e.relatedTarget)) this.uploadZone.classList.remove('dragover'); });
      this.uploadZone.addEventListener('drop', (e) => {
        e.preventDefault(); this.uploadZone.classList.remove('dragover');
        const f = e.dataTransfer.files && e.dataTransfer.files[0];
        if (f) this._startFileUpload(f);
      });
    }
    // Page nav tabs
    this.tabNavBtns.forEach(btn => { btn.addEventListener('click', () => this._switchPage(btn.dataset.page)); });
    // Download page
    this.dwnDetectBtn.addEventListener('click', () => this._dwnDetectFormats());
    this.dwnStartBtn.addEventListener('click', () => this._dwnStartDownload());
    // RSS page
    this.rssAddBtn.addEventListener('click', () => this._rssSubscribe());
    this.rssFeedUrl.addEventListener('keydown', (e) => { if (e.key === 'Enter') this._rssSubscribe(); });
  }

  /* ── i18n ─────────────────────────────────────────────── */
  t(key) { return this.i18n[this.currentLang][key] || this.i18n['en'][key] || key; }
  _switchLang(lang) {
    this.currentLang = lang;
    this.langText.textContent = lang === 'en' ? 'English' : '中文';
    document.documentElement.lang = lang === 'zh' ? 'zh-CN' : 'en';
    document.title = this.t('title');
    document.querySelectorAll('[data-i18n]').forEach(el => {
      const v = this.t(el.dataset.i18n);
      if (typeof v === 'string') {
        if (el.dataset.i18n === 'footer_text') el.innerHTML = v;
        else el.textContent = v;
      }
    });
    document.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
      const v = this.t(el.dataset.i18nPlaceholder);
      if (typeof v === 'string') el.placeholder = v;
    });
  }

  /* ── Theme ─────────────────────────────────────────────── */
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
  }
  _toggleTheme() {
    const cur = document.documentElement.getAttribute('data-theme');
    const nxt = cur === 'light' ? 'dark' : 'light';
    document.documentElement.setAttribute('data-theme', nxt);
    localStorage.setItem('vt_theme', nxt);
    this._updateThemeIcon(nxt);
  }
  _updateThemeIcon(theme) {
    if (!this.themeIcon) return;
    this.themeIcon.className = theme === 'light' ? 'fas fa-moon' : 'fas fa-sun';
  }

  /* ── Page switching ───────────────────────────────────── */
  _switchPage(page) {
    this.currentPage = page;
    this.tabNavBtns.forEach(b => b.classList.toggle('active', b.dataset.page === page));
    this.pagePanels.forEach(p => p.classList.toggle('active', p.id === 'page' + page.charAt(0).toUpperCase() + page.slice(1)));
    if (page === 'rss') this._rssLoadFeeds();
  }

  /* ── Settings persistence ─────────────────────────────── */
  _saveSettings() {
    const s = {
      baseUrl: this.modelBaseUrl.value, apiKey: this.apiKeyInput.value,
      model: this.modelSelect.value, summaryLang: this.summaryLangSel.value,
      useTwoStep: this.twoStepToggle.checked,
    };
    try { localStorage.setItem('vt_settings', JSON.stringify(s)); } catch (_) {}
  }
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

  /* ── Fetch models ─────────────────────────────────────── */
  async _fetchModels(silent = false) {
    const baseUrl = this.modelBaseUrl.value.trim().replace(/\/$/, '');
    const apiKey  = this.apiKeyInput.value.trim();
    if (!baseUrl || !apiKey) { if (!silent) this._setFetchStatus('err', this.t('api_key') + ' & URL required'); return; }
    this.fetchModelsBtn.disabled = true;
    this.fetchIcon.className = 'fas fa-spinner fa-spin';
    if (!silent) this._setFetchStatus('', this.t('fetching_models'));
    try {
      const fd = new FormData(); fd.append('base_url', baseUrl); fd.append('api_key', apiKey);
      const resp = await fetch(`${this.apiBase}/models`, { method: 'POST', body: fd });
      if (!resp.ok) { const err = await resp.json().catch(() => ({})); throw new Error(err.detail || `HTTP ${resp.status}`); }
      const data = await resp.json();
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
  }
  _setFetchStatus(cls, msg) { this.fetchStatus.className = 'fetch-status' + (cls ? ` ${cls}` : ''); this.fetchStatus.textContent = msg; }

  /* ── Transcription ────────────────────────────────────── */
  async _startTranscription() {
    if (this.submitBtn.disabled) return;
    const url = this.videoUrlInput.value.trim();
    if (!url) { this._showError(this.t('error_invalid_url')); return; }
    this._setLoading(true); this._hideResults(); this._showProgressTranscribe();
    try {
      const fd = this._buildFormData(url);
      const resp = await fetch(`${this.apiBase}/process-video`, { method: 'POST', body: fd });
      if (!resp.ok) { const err = await resp.json().catch(() => ({})); throw new Error(err.detail || 'Request failed'); }
      const data = await resp.json();
      this.currentTaskId = data.task_id;
      this._initSP(); this._startSSE(); this._saveSettings();
    } catch (err) {
      this._showError(this.t('error_processing_failed') + err.message);
      this._setLoading(false); this._hideProgressTranscribe();
    }
  }

  async _startFileUpload(file) {
    if (this.submitBtn.disabled) return;
    const parts = (file.name || '').split('.');
    const ext = parts.length > 1 ? ('.' + parts.pop().toLowerCase()) : '';
    if (!this._allowedUploadExts.has(ext)) { this._showError(this.t('error_upload_type')); return; }
    if (!file.size) { this._showError(this.t('error_upload_empty')); return; }
    const maxB = this.uploadMaxMb * 1024 * 1024;
    if (file.size > maxB) { this._showError(this.t('error_upload_size')(this.uploadMaxMb)); return; }
    this._setLoading(true); this._hideResults(); this._showProgressTranscribe();
    try {
      const fd = this._buildFormData(''); fd.append('file', file, file.name);
      const resp = await fetch(`${this.apiBase}/process-video`, { method: 'POST', body: fd });
      if (!resp.ok) { const err = await resp.json().catch(() => ({})); throw new Error(err.detail || 'Request failed'); }
      const data = await resp.json();
      this.currentTaskId = data.task_id;
      this._initSP(); this._startSSE(); this._saveSettings();
    } catch (err) {
      this._showError(this.t('error_processing_failed') + err.message);
      this._setLoading(false); this._hideProgressTranscribe();
    }
  }

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

  /* ── SSE ──────────────────────────────────────────────── */
  _startSSE() {
    if (!this.currentTaskId) return;
    this._stopSSE();
    this.eventSource = new EventSource(`${this.apiBase}/task-stream/${this.currentTaskId}`);
    this.eventSource.onmessage = (ev) => {
      try {
        const task = JSON.parse(ev.data);
        if (task.type === 'heartbeat') return;
        this._updateProgressFromTask(task);
        if (task.status === 'completed') {
          this._stopSP(); this._stopSSE(); this._setLoading(false); this._hideProgressTranscribe();
          this._showResults(task.script, task.summary, task.video_title, task.translation, task.detected_language, task.summary_language);
        } else if (task.status === 'error') {
          this._stopSP(); this._stopSSE(); this._setLoading(false); this._hideProgressTranscribe();
          this._showError(task.error || 'Processing error');
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
              this._showResults(task.script, task.summary, task.video_title, task.translation, task.detected_language, task.summary_language);
              return;
            }
          }
        }
      } catch (_) {}
      this._showError(this.t('error_processing_failed') + 'SSE disconnected');
      this._setLoading(false);
    };
  }
  _stopSSE() { if (this.eventSource) { this.eventSource.close(); this.eventSource = null; } }

  /* ── Stage-weighted Progress (dual bar) ───────────────── */
  _updateProgressFromTask(task) {
    const pct = task.progress || 0;
    const stageName = task.current_stage_label || task.message || '';
    const stagePct = task.current_stage_progress || 0;

    // Total bar
    this.progressStatus.textContent = Math.round(pct) + '%';
    this.progressFill.style.width = pct + '%';

    // Stage row
    if (stageName) {
      this.progStageName.textContent = stageName;
      this.progStagePct.textContent = stagePct > 0 ? Math.round(stagePct) + '%' : '';
    }

    // Message
    this.progressMessage.textContent = task.message || '';

    // Mode badge
    if (task.mode === 'subtitle') {
      this.modeBadge.textContent = this.t('mode_subtitle');
      this.modeBadge.className = 'mode-badge subtitle';
      this.progressFill.classList.add('subtitle-mode');
    } else if (task.mode === 'whisper') {
      this.modeBadge.textContent = this.t('mode_whisper');
      this.modeBadge.className = 'mode-badge whisper';
      this.progressFill.classList.remove('subtitle-mode');
    }

    this._stopSP(); // disable smart progress simulation when we have real stage data
  }

  /* ── Smart Progress (fallback for legacy tasks) ───────── */
  _initSP() {
    this.sp.enabled = false; this.sp.current = 0; this.sp.target = 15;
    this.sp.lastServer = 0; this.sp.startTime = Date.now(); this.sp.stage = 'preparing';
  }
  _startSP() {
    if (this.sp.interval) clearInterval(this.sp.interval);
    this.sp.enabled = true; this.sp.startTime = this.sp.startTime || Date.now();
    this.sp.interval = setInterval(() => this._tickSP(), 500);
  }
  _stopSP() { if (this.sp.interval) { clearInterval(this.sp.interval); this.sp.interval = null; } this.sp.enabled = false; }
  _tickSP() {
    if (!this.sp.enabled || this.sp.current >= this.sp.target) return;
    const speeds = { subtitle: .5, parsing: .3, downloading: .18, transcribing: .14, optimizing: .22, summarizing: .28 };
    let inc = speeds[this.sp.stage] || .2;
    const remaining = this.sp.target - this.sp.current;
    if (remaining < 5) inc *= .3;
    const next = Math.min(this.sp.current + inc, this.sp.target);
    if (next > this.sp.current) {
      this.sp.current = next;
      this.progressStatus.textContent = Math.round(next) + '%';
      this.progressFill.style.width = next + '%';
    }
  }

  /* ── Results ──────────────────────────────────────────── */
  _normLangTab(code) {
    if (!code) return '';
    const c = String(code).toLowerCase().trim();
    if (c.startsWith('zh')) return 'zh';
    if (c.length >= 2) return c.slice(0, 2);
    return c;
  }
  _showResults(script, summary, videoTitle, translation, detectedLang, summaryLang) {
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
    this._switchResultTab('script');
    this.resultsPanel.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }
  _hideResults() { this.resultsPanel.classList.remove('show'); }
  _switchResultTab(name) {
    this.tabBtns.forEach(b => b.classList.toggle('active', b.dataset.tab === name));
    this.tabPanes.forEach(p => p.classList.toggle('active', p.id === `${name}Tab`));
  }
  _showProgressTranscribe() {
    this.emptyState.style.display = 'none';
    this.resultsPanel.classList.remove('show');
    this.progressPanel.classList.add('show');
    this.progStageName.textContent = '';
    this.progStagePct.textContent = '';
    if (this.modeBadge) { this.modeBadge.style.display = 'none'; this.modeBadge.className = 'mode-badge'; }
    if (this.progressFill) { this.progressFill.classList.remove('subtitle-mode'); this.progressFill.style.width = '0%'; }
    this.progressStatus.textContent = '0%';
  }
  _hideProgressTranscribe() { this.progressPanel.classList.remove('show'); }

  /* ── Copy to clipboard ──────────────────────────────── */
  async _copyTabContent(type) {
    let el, btn;
    if (type === 'script') { el = this.scriptContent; btn = this.copyScriptBtn; }
    else if (type === 'summary') { el = this.summaryContent; btn = this.copySummaryBtn; }
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

  /* ── Download ─────────────────────────────────────────── */
  async _downloadFile(type) {
    if (!this.currentTaskId) { this._showError(this.t('error_no_download')); return; }
    try {
      const r = await fetch(`${this.apiBase}/task-status/${this.currentTaskId}`);
      if (!r.ok) throw new Error('Failed');
      const task = await r.json();
      let filename;
      if (type === 'script')      filename = task.script_path ? task.script_path.split('/').pop() : `transcript_${task.safe_title||'x'}_${task.short_id||'x'}.md`;
      else if (type === 'summary') filename = task.summary_path ? task.summary_path.split('/').pop() : `summary_${task.safe_title||'x'}_${task.short_id||'x'}.md`;
      else if (type === 'translation') filename = task.translation_path ? task.translation_path.split('/').pop() : `translation_${task.safe_title||'x'}_${task.short_id||'x'}.md`;
      else throw new Error('Unknown');
      const a = document.createElement('a');
      a.href = `${this.apiBase}/download/${encodeURIComponent(filename)}`;
      a.download = filename; document.body.appendChild(a); a.click(); document.body.removeChild(a);
    } catch (e) { this._showError(this.t('error_download_failed') + e.message); }
  }

  /* ── UI helpers ───────────────────────────────────────── */
  _setLoading(on) {
    this.submitBtn.disabled = on;
    this.submitBtn.innerHTML = on ? `<span class="spinner"></span> ${this.t('processing')}` : `<i class="fas fa-search"></i> <span>${this.t('start_transcription')}</span>`;
    if (this.uploadPickBtn) this.uploadPickBtn.disabled = on;
    if (this.uploadZone) { this.uploadZone.style.pointerEvents = on ? 'none' : ''; this.uploadZone.style.opacity = on ? '0.65' : ''; this.uploadZone.tabIndex = on ? -1 : 0; }
    if (this.fileInput) this.fileInput.disabled = on;
  }
  _showError(msg) {
    this.errorMsg.textContent = msg; this.errorBanner.classList.add('show');
    this.errorBanner.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    setTimeout(() => this._hideError(), 6000);
  }
  _hideError() { this.errorBanner.classList.remove('show'); }
  _debounce(fn, ms) { let t; return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); }; }

  /* ═══════════════════════════════════════════════════════════
     Download-only page
     ═══════════════════════════════════════════════════════ */
  async _dwnDetectFormats() {
    const url = this.dwnUrl.value.trim();
    if (!url) { this._dwnShowError('Please enter a URL'); return; }
    this.dwnDetectBtn.disabled = true;
    this.dwnDetectBtn.innerHTML = '<span class="spinner"></span> Detecting…';
    this._dwnHideError();
    this.dwnFormatsDiv.style.display = 'none';
    this.dwnCompleted.style.display = 'none';
    try {
      const fd = new FormData(); fd.append('url', url);
      const resp = await fetch(`${this.apiBase}/download-video/formats`, { method: 'POST', body: fd });
      if (!resp.ok) { const err = await resp.json().catch(() => ({})); throw new Error(err.detail || 'Failed'); }
      const data = await resp.json();
      this.dwnFormats = data.formats || [];
      this.dwnSelectedFormat = 'best';
      this._dwnRenderFormats();
      this.dwnFormatsDiv.style.display = 'block';
    } catch (e) {
      this._dwnShowError('Detection failed: ' + e.message);
    } finally {
      this.dwnDetectBtn.disabled = false;
      this.dwnDetectBtn.innerHTML = '<i class="fas fa-search"></i> <span>Detect</span>';
    }
  }

  _dwnRenderFormats() {
    this.dwnFmtList.innerHTML = '';
    this.dwnFormats.forEach((f, i) => {
      const div = document.createElement('div');
      div.className = 'fmt-item' + (f.id === this.dwnSelectedFormat ? ' selected' : '');
      const sizeStr = f.filesize ? this._dwnFormatSize(f.filesize) : '';
      div.innerHTML = `
        <div class="fmt-main">
          <span class="fmt-name">${this._escapeHtml(f.resolution || f.note || f.id)}</span>
          <span class="fmt-detail">${this._escapeHtml(f.ext || '')}</span>
        </div>
        <span class="fmt-size">${sizeStr}</span>
      `;
      div.addEventListener('click', () => {
        this.dwnSelectedFormat = f.id;
        this._dwnRenderFormats();
      });
      this.dwnFmtList.appendChild(div);
    });
  }

  _dwnFormatSize(bytes) {
    if (!bytes || bytes <= 0) return '';
    const units = ['B', 'KB', 'MB', 'GB'];
    let i = 0, val = bytes;
    while (val >= 1024 && i < units.length - 1) { val /= 1024; i++; }
    return val.toFixed(i > 0 ? 1 : 0) + ' ' + units[i];
  }

  _escapeHtml(s) { const d = document.createElement('div'); d.textContent = s; return d.innerHTML; }

  async _dwnStartDownload() {
    const url = this.dwnUrl.value.trim();
    if (!url || !this.dwnSelectedFormat) return;
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
      fd.append('format_id', this.dwnSelectedFormat);
      const resp = await fetch(`${this.apiBase}/download-video`, { method: 'POST', body: fd });
      if (!resp.ok) { const err = await resp.json().catch(() => ({})); throw new Error(err.detail || 'Failed'); }
      const data = await resp.json();
      this.dwnTaskId = data.task_id;
      this._dwnStartSSE();
    } catch (e) {
      this._dwnShowError('Download failed: ' + e.message);
      this.dwnProgressPanel.classList.remove('show');
    }
  }

  _dwnStartSSE() {
    if (!this.dwnTaskId) return;
    this._dwnStopSSE();
    this.dwnEventSource = new EventSource(`${this.apiBase}/task-stream/${this.dwnTaskId}`);
    this.dwnEventSource.onmessage = (ev) => {
      try {
        const task = JSON.parse(ev.data);
        if (task.type === 'heartbeat') return;
        const pct = task.progress || 0;
        this.dwnProgressStatus.textContent = Math.round(pct) + '%';
        this.dwnProgressFill.style.width = pct + '%';
        if (task.current_stage_label) {
          this.dwnStageName.textContent = task.current_stage_label;
          this.dwnStagePct.textContent = task.current_stage_progress > 0 ? Math.round(task.current_stage_progress) + '%' : '';
        }
        this.dwnProgressMsg.textContent = task.message || '';
        if (task.status === 'completed') {
          this._dwnStopSSE();
          this.dwnProgressPanel.classList.remove('show');
          this.dwnCompleted.style.display = 'block';
          this.dwnFileName.textContent = task.filename || '';
          this.dwnFileLink.href = `${this.apiBase}/download-video/file/${encodeURIComponent(task.filename || '')}`;
        } else if (task.status === 'error') {
          this._dwnStopSSE();
          this.dwnProgressPanel.classList.remove('show');
          this._dwnShowError(task.error || 'Download failed');
        }
      } catch (_) {}
    };
    this.dwnEventSource.onerror = () => { this._dwnStopSSE(); };
  }
  _dwnStopSSE() { if (this.dwnEventSource) { this.dwnEventSource.close(); this.dwnEventSource = null; } }

  _dwnShowError(msg) { this.dwnErrorMsg.textContent = msg; this.dwnErrorBanner.classList.add('show'); setTimeout(() => this._dwnHideError(), 6000); }
  _dwnHideError() { this.dwnErrorBanner.classList.remove('show'); }

  /* ═══════════════════════════════════════════════════════════
     RSS page
     ═══════════════════════════════════════════════════════ */
  async _rssSubscribe() {
    const feedUrl = this.rssFeedUrl.value.trim();
    if (!feedUrl) { this._rssShowError('Please enter an RSS feed URL'); return; }
    this.rssAddBtn.disabled = true;
    this.rssAddBtn.innerHTML = '<span class="spinner"></span> Adding…';
    this._rssHideError();
    try {
      const fd = new FormData(); fd.append('feed_url', feedUrl);
      const resp = await fetch(`${this.apiBase}/rss/subscribe`, { method: 'POST', body: fd });
      if (!resp.ok) { const err = await resp.json().catch(() => ({})); throw new Error(err.detail || 'Failed'); }
      this.rssFeedUrl.value = '';
      this._rssLoadFeeds();
    } catch (e) {
      this._rssShowError('Subscribe failed: ' + e.message);
    } finally {
      this.rssAddBtn.disabled = false;
      this.rssAddBtn.innerHTML = '<i class="fas fa-plus"></i> <span>Subscribe</span>';
    }
  }

  async _rssLoadFeeds() {
    try {
      const resp = await fetch(`${this.apiBase}/rss/feeds`);
      if (!resp.ok) return;
      const data = await resp.json();
      const feeds = data.feeds || [];
      this._rssRenderFeeds(feeds);
    } catch (e) {
      console.warn('RSS load error:', e);
    }
  }

  _rssRenderFeeds(feeds) {
    if (!feeds.length) {
      this.feedList.innerHTML = '<div class="rss-empty"><div class="rss-empty-icon">📡</div><p>No subscriptions yet. Add an RSS feed URL above.</p></div>';
      return;
    }
    this.feedList.innerHTML = feeds.map(f => {
      const lastChecked = f.last_checked ? new Date(f.last_checked).toLocaleString() : '—';
      const errorInfo = f.last_error ? `<span style="color:var(--error);font-size:10px;" title="${this._escapeHtml(f.last_error)}">⚠️ 上次刷新失败</span>` : '';
      const newBadge = f.new_count > 0 ? `<span class="badge" style="background:var(--accent);">${f.new_count} 新</span>` : '';
      return `
      <div class="feed-card" data-feed-id="${f.id}">
        <div class="feed-card-header">
          <div>
            <div class="feed-card-title">
              ${this._escapeHtml(f.title)} ${newBadge}
            </div>
            <div class="feed-card-meta">
              <span class="feed-card-badge">${f.type.toUpperCase()}</span>
              <span>${f.entry_count || 0} 条</span>
              <span style="font-size:10px;">更新: ${lastChecked}</span>
              ${errorInfo}
            </div>
          </div>
          <div style="display:flex;gap:4px;">
            <button class="feed-card-del" data-action="refresh-feed" data-feed-id="${f.id}" title="刷新">
              <i class="fas fa-sync-alt"></i>
            </button>
            <button class="feed-card-del" data-action="delete-feed" data-feed-id="${f.id}" title="删除">
              <i class="fas fa-trash"></i>
            </button>
          </div>
        </div>
        <div class="feed-entries" id="entries-${f.id}">
          <div style="text-align:center;padding:20px;color:var(--text-dim);">点击展开条目列表</div>
        </div>
      </div>
    `}).join('');

    // Bind feed card click to expand
    this.feedList.querySelectorAll('.feed-card').forEach(card => {
      card.addEventListener('click', (e) => {
        // 不拦截按钮点击
        if (e.target.closest('[data-action]')) return;
        card.classList.toggle('expanded');
        const fid = card.dataset.feedId;
        if (card.classList.contains('expanded')) {
          this._rssLoadEntries(fid);
        }
      });
    });

    // Bind delete
    this.feedList.querySelectorAll('[data-action="delete-feed"]').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        if (confirm('确定要删除此订阅吗？')) {
          this._rssDeleteFeed(btn.dataset.feedId);
        }
      });
    });

    // Bind refresh
    this.feedList.querySelectorAll('[data-action="refresh-feed"]').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const fid = btn.dataset.feedId;
        this._rssRefreshFeed(fid);
      });
    });
  }

  async _rssLoadEntries(feedId) {
    const container = document.getElementById('entries-' + feedId);
    if (!container) return;
    container.innerHTML = '<div style="text-align:center;padding:20px;color:var(--text-muted);"><span class="spinner spinner-dark"></span> 加载中…</div>';
    try {
      const resp = await fetch(`${this.apiBase}/rss/entries/${feedId}`);
      if (!resp.ok) { container.innerHTML = '<div style="text-align:center;padding:20px;color:var(--error);">加载失败</div>'; return; }
      const data = await resp.json();
      const entries = data.entries || [];
      container.innerHTML = entries.length ? entries.map(e => {
        const isSummarized = e.processed === 'summarized';
        const isDownloaded = e.processed === 'downloaded';
        const hasAudio = Boolean(e.enclosure_url);
        const processedClass = isSummarized || isDownloaded ? ' processed' : '';
        return `
        <div class="entry-item${processedClass}">
          <span class="entry-title" title="${this._escapeHtml(e.title)}">
            ${isSummarized ? '📝 ' : isDownloaded ? '📥 ' : ''}${this._escapeHtml(e.title)}
          </span>
          <div class="entry-actions">
            <button class="btn-sm primary" data-action="summarize" data-feed="${feedId}" data-entry="${e.id}"
              ${isSummarized ? 'disabled' : ''}>
              ${isSummarized ? '已摘要' : '摘要'}
            </button>
            ${hasAudio ? `
            <button class="btn-sm" data-action="download-entry" data-feed="${feedId}" data-entry="${e.id}"
              ${isDownloaded ? 'disabled' : ''}>
              ${isDownloaded ? '已下载' : '下载'}
            </button>` : ''}
          </div>
        </div>
      `}).join('') : '<div style="text-align:center;padding:20px;color:var(--text-dim);">暂无条目</div>';

      // Bind entry actions
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
    } catch (e) {
      container.innerHTML = '<div style="text-align:center;padding:20px;color:var(--error);">加载失败</div>';
    }
  }

  async _rssCreateTask(feedId, entryId, action) {
    try {
      const fd = new FormData();
      fd.append('feed_id', feedId);
      fd.append('entry_id', entryId);
      fd.append('action', action);
      fd.append('summary_language', this.summaryLangSel.value);
      const apiKey = this.apiKeyInput.value.trim();
      const baseUrl = this.modelBaseUrl.value.trim().replace(/\/$/, '');
      const modelId = this.modelSelect.value;
      if (apiKey)  fd.append('api_key', apiKey);
      if (baseUrl) fd.append('model_base_url', baseUrl);
      if (modelId) fd.append('model_id', modelId);

      const resp = await fetch(`${this.apiBase}/rss/create-task`, { method: 'POST', body: fd });
      if (!resp.ok) { const err = await resp.json().catch(() => ({})); throw new Error(err.detail || 'Failed'); }
      const data = await resp.json();

      // Switch to transcribe page and watch this task
      this._switchPage('transcribe');
      this.currentTaskId = data.task_id;
      this._showProgressTranscribe();
      this._initSP();
      this._startSSE();
      this._setLoading(true);
    } catch (e) {
      this._rssShowError('Task creation failed: ' + e.message);
    }
  }

  async _rssDeleteFeed(feedId) {
    try {
      await fetch(`${this.apiBase}/rss/feed/${feedId}`, { method: 'DELETE' });
      this._rssLoadFeeds();
    } catch (e) {
      console.warn('RSS delete error:', e);
    }
  }

  async _rssRefreshFeed(feedId) {
    const card = this.feedList.querySelector(`[data-feed-id="${feedId}"]`);
    const refreshBtn = card?.querySelector('[data-action="refresh-feed"] i');
    if (refreshBtn) refreshBtn.className = 'fas fa-spinner fa-spin';
    try {
      const resp = await fetch(`${this.apiBase}/rss/refresh/${feedId}`, { method: 'POST' });
      if (!resp.ok) { const err = await resp.json().catch(() => ({})); throw new Error(err.detail || '刷新失败'); }
      const result = await resp.json();
      this._rssLoadFeeds();
      // 如果当前展开状态，重新加载条目
      if (card?.classList.contains('expanded')) {
        this._rssLoadEntries(feedId);
      }
      if (result.new_count > 0) {
        this._rssShowError(`✅ 发现 ${result.new_count} 条新内容`);
        setTimeout(() => this._rssHideError(), 3000);
      }
    } catch (e) {
      this._rssShowError('刷新失败: ' + e.message);
    } finally {
      if (refreshBtn) refreshBtn.className = 'fas fa-sync-alt';
    }
  }

  _rssShowError(msg) { this.rssErrorMsg.textContent = msg; this.rssErrorBanner.classList.add('show'); setTimeout(() => this._rssHideError(), 6000); }
  _rssHideError() { this.rssErrorBanner.classList.remove('show'); }
}

/* ── Boot ──────────────────────────────────────────────── */
document.addEventListener('DOMContentLoaded', () => {
  window.vt = new VideoTranscriber();
});
window.addEventListener('beforeunload', () => {
  if (window.vt) {
    window.vt._stopSSE();
    window.vt._dwnStopSSE();
  }
});
