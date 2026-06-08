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
    this.partialSummaryShown = false;
    this.isProcessing = false;
    this.currentSource  = { type: 'url', value: '', title: '' };
    this.historyItems   = [];

    /* Smart progress simulation (for transcribe page only) */
    this.sp = { enabled: false, current: 0, target: 15, lastServer: 0, interval: null, startTime: null, stage: 'preparing' };

    /* Download-only page state */
    this.dwnTaskId = null;
    this.dwnEventSource = null;
    this.dwnFormats = [];
    this.dwnSelectedFormat = 'best';

    this.i18n = {
      en: {
        title: 'AI Transcriber', subtitle: 'Transcribe, summarize, save history.',
        nav_transcribe: 'Transcribe', nav_download: 'Download', nav_history: 'History',
        toggle_theme: 'Toggle theme', video_url_placeholder: 'Paste video URL...',
        start_transcription: 'Transcribe', ai_settings: 'Settings',
        model_base_url: 'Model API Base URL', model_base_url_placeholder: 'https://openrouter.ai/api/v1',
        api_key: 'API Key', api_key_placeholder: 'sk-...', fetch_models: 'Fetch',
        model_select: 'Model', model_default: 'Server default', two_step_summary: 'Two-step summary',
        summary_language: 'Language', processing_progress: 'Processing', total_progress: 'Total',
        preparing: 'Preparing…', transcript_text: 'Transcript', intelligent_summary: 'AI Summary',
        translation: 'Translation', download_transcript: 'Transcript', download_translation: 'Translation',
        download_summary: 'Summary', copy: 'Copy', copy_transcript: 'Copy transcript', copy_summary: 'Copy summary', copy_translation: 'Copy translation',
        empty_hint: 'Paste a link or upload a file.',
        footer_text: '<a class="repo-primary" href="https://github.com/EvilIrving/ai-transcriber" target="_blank">ai-transcriber</a> · Inspired by <a href="https://github.com/wendy7756/AI-Video-Transcriber" target="_blank">AI-Video-Transcriber</a>',
        processing: 'Processing…', downloading_video: 'Downloading audio…', parsing_video: 'Parsing video info…',
        transcribing_audio: 'Transcribing audio…', optimizing_transcript: 'Optimizing transcript…',
        generating_summary: 'Generating summary…', detecting_subtitles: 'Detecting subtitles…',
        subtitle_found: 'Subtitles found…', no_subtitle: 'Downloading audio…',
        mode_subtitle: 'Subtitle', mode_whisper: 'Whisper', completed: 'Done',
        error_invalid_url: 'URL required', error_processing_failed: 'Processing failed: ',
        error_no_download: 'No file available for download', error_download_failed: 'Download failed: ',
        fetching_models: 'Fetching models…', models_loaded: (n) => `${n} models loaded`,
        models_error: 'Failed to fetch models', upload_or: 'Upload file',
        upload_formats: '.mp3 · .mp4 · .wav · .m4a · .webm · .mkv · .ogg · .flac',
        upload_files_btn: 'Upload files', error_upload_type: 'Unsupported file type',
        error_upload_empty: 'File is empty', error_upload_size: (mb) => `File exceeds ${mb} MB limit`,
        download_page_title: 'Download', download_page_subtitle: 'Choose video, audio, or subtitles.',
        detect: 'Detect', video: 'Video', audio: 'Audio', subtitle_file: 'Subtitles', choose_quality: 'Choose quality:',
        choose_audio_quality: 'Choose audio quality:', output_format: 'Format:', subtitle_language: 'Subtitle language:',
        download_video_btn: 'Download video', download_audio_btn: 'Download audio', download_subtitle_btn: 'Download subtitles',
        downloading: 'Downloading', download_file: 'Download file', copyright_notice: 'Respect copyright.',
        history_page_title: 'History', history_page_subtitle: 'Search, view, delete summaries.', history_search_placeholder: 'Search history...',
        history_empty: 'No history yet.', rss_page_subtitle: 'Summarize or download feed entries.', rss_url_placeholder: 'Paste RSS URL...',
        subscribe: 'Subscribe', rss_empty: 'No subscriptions yet.',
        cancel: 'Cancel', transcript_pending: 'Transcript is still being optimized…', processing_error: 'Processing error', sse_disconnected: 'SSE disconnected', request_failed: 'Request failed', unknown_error: 'Unknown error', history_db_failed: 'Failed to open history database',
        url_required: 'URL required', detecting: 'Detecting…', detect_failed: 'Detection failed: ', audio_unavailable: 'No audio-only stream.',
        no_subtitles: 'No subtitles', manual_subtitles: 'Manual:', auto_subtitles: 'Auto:', subtitles_available: 'Subtitles available', manual: 'manual', auto: 'auto',
        download_failed: 'Download failed: ', unnamed_summary: 'Untitled summary', history_load_failed: 'Load failed: ', no_matches: 'No matches.',
        source_link: 'Source link', local_task: 'Local task', view: 'View', collapse: 'Collapse', delete: 'Delete', confirm_delete_history: 'Delete this summary?', delete_failed: 'Delete failed: ',
        adding: 'Adding…', subscribe_failed: 'Subscribe failed: ', timeout: 'request timed out', rss_refresh_failed: 'Refresh failed', new_count: (n) => `${n} new`,
        item_count: (n) => `${n} items`, updated: 'Updated:', never_updated: 'Never', refresh: 'Refresh', confirm_delete_feed: 'Delete this subscription?', expand_entries_hint: 'Click to load entries', feed_missing: 'Subscription not found', no_entries: 'No entries', summarized: 'Summarized', summarize: 'Summarize', downloaded: 'Downloaded', task_creation_failed: 'Task creation failed: ', refresh_failed: 'Refresh failed: ', found_new_items: (n) => `${n} new items`,
      },
      zh: {
        title: 'AI Transcriber', subtitle: '转录，摘要，保存历史。',
        nav_transcribe: '转录', nav_download: '下载', nav_history: '历史',
        toggle_theme: '切换主题', video_url_placeholder: '粘贴视频链接...', start_transcription: '转录', ai_settings: '设置',
        model_base_url: 'Model API 地址', model_base_url_placeholder: 'https://openrouter.ai/api/v1',
        api_key: 'API Key', api_key_placeholder: 'sk-...', fetch_models: '获取',
        model_select: '模型', model_default: '服务器默认', two_step_summary: '双步摘要', summary_language: '语言',
        processing_progress: '处理进度', total_progress: '总进度', preparing: '准备中…', transcript_text: '转录文本',
        intelligent_summary: '智能摘要', translation: '翻译', download_transcript: '转录',
        download_translation: '翻译', download_summary: '摘要', copy: '复制', copy_transcript: '复制转录文本', copy_summary: '复制摘要', copy_translation: '复制翻译',
        empty_hint: '粘贴链接或上传文件。',
        footer_text: '<a class="repo-primary" href="https://github.com/EvilIrving/ai-transcriber" target="_blank">ai-transcriber</a> · 致谢 <a href="https://github.com/wendy7756/AI-Video-Transcriber" target="_blank">AI-Video-Transcriber</a>',
        processing: '处理中…', downloading_video: '正在下载音频…', parsing_video: '正在解析视频信息…',
        transcribing_audio: '正在转录音频…', optimizing_transcript: '正在优化转录文本…',
        generating_summary: '正在生成摘要…', detecting_subtitles: '正在检测字幕…',
        subtitle_found: '已获取字幕…', no_subtitle: '下载音频…',
        mode_subtitle: '字幕', mode_whisper: 'Whisper', completed: '完成',
        error_invalid_url: '请输入有效的视频链接', error_processing_failed: '处理失败：',
        error_no_download: '没有可下载的文件', error_download_failed: '下载失败：',
        fetching_models: '正在获取模型列表…', models_loaded: (n) => `已加载 ${n} 个模型`,
        models_error: '获取模型失败', upload_or: '或拖放文件到此处',
        upload_formats: '.mp3 · .mp4 · .wav · .m4a · .webm · .mkv · .ogg · .flac',
        upload_files_btn: '上传文件', error_upload_type: '不支持的文件类型',
        error_upload_empty: '文件为空', error_upload_size: (mb) => `文件超过 ${mb} MB 限制`,
        download_page_title: '下载', download_page_subtitle: '选择视频、音频或字幕。',
        detect: '检测', video: '视频', audio: '音频', subtitle_file: '字幕', choose_quality: '选择清晰度：',
        choose_audio_quality: '选择音质：', output_format: '输出格式：', subtitle_language: '字幕语言：',
        download_video_btn: '下载视频', download_audio_btn: '下载音频', download_subtitle_btn: '下载字幕',
        downloading: '下载中', download_file: '下载文件', copyright_notice: '请遵守版权规定。',
        history_page_title: '历史', history_page_subtitle: '搜索、查看、删除摘要。', history_search_placeholder: '搜索历史...',
        history_empty: '暂无历史。', rss_page_subtitle: '订阅后可摘要或下载。', rss_url_placeholder: '粘贴 RSS 链接...',
        subscribe: '订阅', rss_empty: '暂无订阅。',
        cancel: '取消', transcript_pending: '转录文本仍在优化…', processing_error: '处理错误', sse_disconnected: 'SSE 连接中断', request_failed: '请求失败', unknown_error: '未知错误', history_db_failed: '无法打开历史数据库',
        url_required: '请输入链接', detecting: '检测中…', detect_failed: '检测失败：', audio_unavailable: '无纯音频流。',
        no_subtitles: '无字幕', manual_subtitles: '手动：', auto_subtitles: '自动：', subtitles_available: '有字幕', manual: '手动', auto: '自动',
        download_failed: '下载失败：', unnamed_summary: '未命名摘要', history_load_failed: '读取失败：', no_matches: '无匹配结果。',
        source_link: '来源链接', local_task: '本地任务', view: '查看', collapse: '收起', delete: '删除', confirm_delete_history: '确定要删除这条历史摘要吗？', delete_failed: '删除失败：',
        adding: '添加中…', subscribe_failed: '订阅失败：', timeout: '请求超时', rss_refresh_failed: '刷新失败', new_count: (n) => `${n} 新`,
        item_count: (n) => `${n} 条`, updated: '更新:', never_updated: '未更新', refresh: '刷新', confirm_delete_feed: '确定要删除此订阅吗？', expand_entries_hint: '点击展开条目列表', feed_missing: '订阅不存在', no_entries: '暂无条目', summarized: '已摘要', summarize: '摘要', downloaded: '已下载', task_creation_failed: '任务创建失败：', refresh_failed: '刷新失败: ', found_new_items: (n) => `发现 ${n} 条新内容`,
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
    this.copyTranslationBtn = document.getElementById('copyTranslation');
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
    this.dwnAudioFmtList    = document.getElementById('dwnAudioFmtList');
    this.dwnSubInfo         = document.getElementById('dwnSubInfo');
    this.dwnSubLang         = document.getElementById('dwnSubLang');
    this.dwnVideoContainer  = document.getElementById('dwnVideoContainer');
    this.dwnAudioContainer  = document.getElementById('dwnAudioContainer');
    this.dwnStartVideoBtn   = document.getElementById('dwnStartVideoBtn');
    this.dwnStartAudioBtn   = document.getElementById('dwnStartAudioBtn');
    this.dwnStartSubBtn     = document.getElementById('dwnStartSubBtn');
    this.dwnStartBtn        = document.getElementById('dwnStartBtn');
    this.dwnTabBtns         = document.querySelectorAll('.dwn-tab-btn');
    this.dwnTabPanes        = document.querySelectorAll('.dwn-tab-pane');
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

    // Summary history page
    this.historySearch      = document.getElementById('historySearch');
    this.historyList        = document.getElementById('historyList');
  }

  /* ── Events ───────────────────────────────────────────── */
  _bindEvents() {
    // Transcribe form
    this.form.addEventListener('submit', (e) => { e.preventDefault(); this._startTranscription(); });
    this.submitBtn.addEventListener('mouseenter', () => {
      if (this.isProcessing) this.submitBtn.innerHTML = `<i class="fas fa-xmark"></i> <span>${this.t('cancel')}</span>`;
    });
    this.submitBtn.addEventListener('mouseleave', () => {
      if (this.isProcessing) this.submitBtn.innerHTML = `<span class="spinner"></span> ${this.t('processing')}`;
    });
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
    this.copyScriptBtn.addEventListener('click',      () => this._copyTabContent('script'));
    this.copySummaryBtn.addEventListener('click',     () => this._copyTabContent('summary'));
    this.copyTranslationBtn.addEventListener('click', () => this._copyTabContent('translation'));
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
    this.dwnStartVideoBtn.addEventListener('click', () => this._dwnStartDownload('video'));
    this.dwnStartAudioBtn.addEventListener('click', () => this._dwnStartDownload('audio'));
    this.dwnStartSubBtn.addEventListener('click', () => this._dwnStartDownload('subtitle'));
    // Download tab switching
    this.dwnTabBtns.forEach(btn => {
      btn.addEventListener('click', () => this._switchDwnTab(btn.dataset.dwntab));
    });
    // Enter key on URL input
    this.dwnUrl.addEventListener('keydown', (e) => { if (e.key === 'Enter') this._dwnDetectFormats(); });
    // RSS page
    this.rssAddBtn.addEventListener('click', () => this._rssSubscribe());
    this.rssFeedUrl.addEventListener('keydown', (e) => { if (e.key === 'Enter') this._rssSubscribe(); });
    // Summary history page
    if (this.historySearch) this.historySearch.addEventListener('input', this._debounce(() => this._historyRender(), 120));
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
    document.querySelectorAll('[data-i18n-title]').forEach(el => {
      const v = this.t(el.dataset.i18nTitle);
      if (typeof v === 'string') el.title = v;
    });
    document.querySelectorAll('[data-i18n-aria-label]').forEach(el => {
      const v = this.t(el.dataset.i18nAriaLabel);
      if (typeof v === 'string') el.setAttribute('aria-label', v);
    });
    if (this.currentPage === 'history') this._historyRender();
    if (this.currentPage === 'rss') this._rssLoadFeeds();
    if (!this.isProcessing && this.submitBtn) this._setLoading(false);
    if (this.dwnDetectBtn && !this.dwnDetectBtn.disabled) {
      this.dwnDetectBtn.innerHTML = `<i class="fas fa-magnifying-glass"></i> <span>${this.t('detect')}</span>`;
    }
    if (this.rssAddBtn && !this.rssAddBtn.disabled) {
      this.rssAddBtn.innerHTML = `<i class="fas fa-plus"></i> <span>${this.t('subscribe')}</span>`;
    }
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
    if (page === 'history') this._historyLoad();
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
    if (this.isProcessing) { await this._cancelCurrentTask(); return; }
    const url = this.videoUrlInput.value.trim();
    if (!url) { this._showError(this.t('error_invalid_url')); return; }
    this.currentSource = { type: 'url', value: url, title: '' };
    this.partialSummaryShown = false;
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
  }
  _stopSSE() { if (this.eventSource) { this.eventSource.close(); this.eventSource = null; } }

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

  /* ── Stage-weighted Progress (dual bar) ───────────────── */
  _updateProgressFromTask(task) {
    const pct = this._clampPct(task.progress || 0);
    const stageName = task.current_stage_label || task.message || this.t('preparing');

    // Total progress
    this.progressStatus.textContent = Math.round(pct) + '%';
    this.progressFill.style.width = pct + '%';

    // Current phase, shown above the bar. Keep detailed message below the bar.
    this.progStageName.textContent = stageName;
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
  _clampPct(value) {
    const n = Number(value);
    if (!Number.isFinite(n)) return 0;
    return Math.max(0, Math.min(100, n));
  }

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

  /* ── Results ──────────────────────────────────────────── */
  _normLangTab(code) {
    if (!code) return '';
    const c = String(code).toLowerCase().trim();
    if (c.startsWith('zh')) return 'zh';
    if (c.length >= 2) return c.slice(0, 2);
    return c;
  }
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
  }
  _showPartialSummary(task) {
    this.partialSummaryShown = true;
    this.scriptContent.innerHTML = `<p style="color:var(--text-muted);font-style:italic;">${this.t('transcript_pending')}</p>`;
    this.summaryContent.innerHTML = marked.parse(task.summary);
    this.translationTabBtn.style.display = 'none';
    this.dlTranslation.style.display = 'none';
    this.resultsPanel.classList.add('show');
    this._switchResultTab('summary');
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
    this.progStageName.textContent = this.t('preparing');
    if (this.progStagePct) this.progStagePct.textContent = '';
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

  /* ── Download ─────────────────────────────────────────── */
  async _downloadFile(type) {
    if (!this.currentTaskId) { this._showError(this.t('error_no_download')); return; }
    try {
      const r = await fetch(`${this.apiBase}/task-status/${this.currentTaskId}`);
      if (!r.ok) throw new Error(this.t('request_failed'));
      const task = await r.json();
      let filename;
      if (type === 'script')      filename = task.script_path ? task.script_path.split('/').pop() : `transcript_${task.safe_title||'x'}_${task.short_id||'x'}.md`;
      else if (type === 'summary') filename = task.summary_path ? task.summary_path.split('/').pop() : `summary_${task.safe_title||'x'}_${task.short_id||'x'}.md`;
      else if (type === 'translation') filename = task.translation_path ? task.translation_path.split('/').pop() : `translation_${task.safe_title||'x'}_${task.short_id||'x'}.md`;
      else throw new Error(this.t('unknown_error'));
      const a = document.createElement('a');
      a.href = `${this.apiBase}/download/${encodeURIComponent(filename)}`;
      a.download = filename; document.body.appendChild(a); a.click(); document.body.removeChild(a);
    } catch (e) { this._showError(this.t('error_download_failed') + e.message); }
  }

  /* ── UI helpers ───────────────────────────────────────── */
  _setLoading(on) {
    this.isProcessing = on;
    this.submitBtn.disabled = false;
    this.submitBtn.classList.toggle('processing', on);
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

  _switchDwnTab(tab) {
    this.dwnTabBtns.forEach(b => {
      const active = b.dataset.dwntab === tab;
      b.style.borderBottomColor = active ? 'var(--accent)' : 'transparent';
      b.style.color = active ? 'var(--accent-text)' : 'var(--text-muted)';
    });
    this.dwnTabPanes.forEach(p => {
      p.style.display = p.id === 'dwnTab' + tab.charAt(0).toUpperCase() + tab.slice(1) ? 'block' : 'none';
    });
  }

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
      const resp = await fetch(`${this.apiBase}/download-video/formats`, { method: 'POST', body: fd });
      if (!resp.ok) { const err = await resp.json().catch(() => ({})); throw new Error(err.detail || this.t('request_failed')); }
      const data = await resp.json();

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
  }

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
  }

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
  }

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

    // 默认选英语或第一个
    const preferOrder = ['en', 'en-orig', 'zh-Hans', 'zh-Hant', 'zh'];
    for (const p of preferOrder) {
      if (allLangs.includes(p)) { this.dwnSubLang.value = p; break; }
    }
  }

  _dwnFormatSize(bytes) {
    if (!bytes || bytes <= 0) return '';
    const units = ['B', 'KB', 'MB', 'GB'];
    let i = 0, val = bytes;
    while (val >= 1024 && i < units.length - 1) { val /= 1024; i++; }
    return val.toFixed(i > 0 ? 1 : 0) + ' ' + units[i];
  }

  _escapeHtml(s) { const d = document.createElement('div'); d.textContent = s; return d.innerHTML; }

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

      let endpoint = '';
      if (type === 'video') {
        endpoint = `${this.apiBase}/download-video`;
        fd.append('format_id', this.dwnSelectedVideoFormat);
        fd.append('filename', this._dwnData?.title || '');
      } else if (type === 'audio') {
        endpoint = `${this.apiBase}/download-audio`;
        fd.append('format_id', this.dwnSelectedAudioFormat);
        fd.append('filename', this._dwnData?.title || '');
        fd.append('audio_format', this.dwnAudioContainer.value);
      } else if (type === 'subtitle') {
        endpoint = `${this.apiBase}/download-subtitles`;
        fd.append('lang', this.dwnSubLang.value);
        fd.append('filename', this._dwnData?.title || '');
      }

      const resp = await fetch(endpoint, { method: 'POST', body: fd });
      if (!resp.ok) { const err = await resp.json().catch(() => ({})); throw new Error(err.detail || this.t('request_failed')); }
      const data = await resp.json();
      this.dwnTaskId = data.task_id;
      this._dwnStartSSE();
    } catch (e) {
      this._dwnShowError(this.t('download_failed') + e.message);
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
          this.dwnFileLink.href = `${this.apiBase}/download-video/file/${encodeURIComponent(task.filename || '')}`;
        } else if (task.status === 'error') {
          this._dwnStopSSE();
          this.dwnProgressPanel.classList.remove('show');
          this._dwnShowError(task.error || this.t('download_failed'));
        }
      } catch (_) {}
    };
    this.dwnEventSource.onerror = () => { this._dwnStopSSE(); };
  }
  _dwnStopSSE() { if (this.dwnEventSource) { this.dwnEventSource.close(); this.dwnEventSource = null; } }

  _dwnShowError(msg) { this.dwnErrorMsg.textContent = msg; this.dwnErrorBanner.classList.add('show'); setTimeout(() => this._dwnHideError(), 6000); }
  _dwnHideError() { this.dwnErrorBanner.classList.remove('show'); }

  /* ═══════════════════════════════════════════════════════════
     Summary history (stored in browser IndexedDB)
     ═══════════════════════════════════════════════════════ */
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
  }

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
  }

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
  }

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
  }

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
  }

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
  _rssReadStore() {
    try {
      const raw = localStorage.getItem('vt_rss_feeds');
      const feeds = raw ? JSON.parse(raw) : [];
      return Array.isArray(feeds) ? feeds : [];
    } catch (_) {
      return [];
    }
  }

  _rssWriteStore(feeds) {
    localStorage.setItem('vt_rss_feeds', JSON.stringify(feeds));
  }

  async _rssFetchWithTimeout(url, options = {}, ms = 35000) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), ms);
    try {
      return await fetch(url, { ...options, signal: controller.signal });
    } finally {
      clearTimeout(timer);
    }
  }

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
  }

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
  }

  async _rssParseFeed(feedUrl) {
    const fd = new FormData();
    fd.append('feed_url', feedUrl);
    const resp = await this._rssFetchWithTimeout(`${this.apiBase}/rss/parse`, { method: 'POST', body: fd });
    if (!resp.ok) { const err = await resp.json().catch(() => ({})); throw new Error(err.detail || this.t('request_failed')); }
    const data = await resp.json();
    return data.feed;
  }

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
  }

  async _rssLoadFeeds() {
    this._rssRenderFeeds(this._rssSummaries(this._rssReadStore()));
  }

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
  }

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
  }

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
  }

  async _rssDeleteFeed(feedId) {
    this._rssWriteStore(this._rssReadStore().filter(f => f.id !== feedId));
    this._rssLoadFeeds();
  }

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
