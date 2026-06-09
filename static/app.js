/* ────────────────────────────────────────────────────────────
   AI Video Transcriber · app.js
   Main entry: wires modules together and boots the app.
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

    this.i18n = window.VT_I18N || {};
    this.languages = window.VT_LANGUAGES || [];

    this._initElements();
    this._bindEvents();
    this._initTheme();
    this._loadSettings();
    const savedLang = localStorage.getItem('vt_ui_lang');
    this._switchLang(this.i18n[savedLang] ? savedLang : 'en');
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
    this.progStageDetail    = document.getElementById('progStageDetail');
    this.progArtifacts      = document.getElementById('progArtifacts');
    this.progStageList      = document.getElementById('progStageList');
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
    this.retryScriptBtn      = document.getElementById('retryScript');
    this.retrySummaryBtn     = document.getElementById('retrySummary');
    this.retryTranslationBtn = document.getElementById('retryTranslation');
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
    this.langSelect         = document.getElementById('uiLanguageSelect');
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
    this.rssImportJsonBtn   = document.getElementById('rssImportJsonBtn');
    this.rssJsonFileInput   = document.getElementById('rssJsonFileInput');
    this.feedList           = document.getElementById('feedList');
    this.rssErrorBanner     = document.getElementById('rssErrorBanner');
    this.rssErrorMsg        = document.getElementById('rssErrorMsg');
    this.rssSummaryBar      = document.getElementById('rssSummaryBar');
    this.rssSummaryText     = document.getElementById('rssSummaryText');
    this.rssSearchInput     = document.getElementById('rssSearchInput');
    this.rssSearchRow       = document.getElementById('rssSearchRow');

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
    if (this.langSelect) this.langSelect.addEventListener('change', () => this._switchLang(this.langSelect.value));
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
    // Retry buttons
    this.retryScriptBtn.addEventListener('click',      () => this._retryTranscription());
    this.retrySummaryBtn.addEventListener('click',     () => this._retryTranscription());
    this.retryTranslationBtn.addEventListener('click', () => this._retryTranscription());
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
    if (this.rssImportJsonBtn && this.rssJsonFileInput) {
      this.rssImportJsonBtn.addEventListener('click', () => this.rssJsonFileInput.click());
      this.rssJsonFileInput.addEventListener('change', () => this._rssImportJsonFile(this.rssJsonFileInput.files && this.rssJsonFileInput.files[0]));
    }
    if (this.rssSearchInput) this.rssSearchInput.addEventListener('input', this._debounce(() => this._rssFilterFeeds(), 200));
    // Summary history page
    if (this.historySearch) this.historySearch.addEventListener('input', this._debounce(() => this._historyRender(), 120));
  }

  /* ── i18n ─────────────────────────────────────────────── */
}

Object.assign(
  VideoTranscriber.prototype,
  window.VTI18nMethods,
  window.VTUiMethods,
  window.VTTranscribeMethods,
  window.VTDownloadMethods,
  window.VTHistoryMethods,
  window.VTRssMethods,
);

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
