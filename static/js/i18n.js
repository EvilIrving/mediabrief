/* UI copy dictionaries. Keep translations here instead of app.js. */
window.VT_LANGUAGES = [
  { code: 'en', label: 'English', htmlLang: 'en' },
  { code: 'zh', label: '中文', htmlLang: 'zh-CN' },
  { code: 'ja', label: '日本語', htmlLang: 'ja' },
  { code: 'ko', label: '한국어', htmlLang: 'ko' },
];

window.VT_I18N = {
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
    ui_language: 'UI language', api_url_required: 'API key & URL required',
  },
  zh: {
    title: 'AI Transcriber', subtitle: '转录，摘要，保存历史。', nav_transcribe: '转录', nav_download: '下载', nav_history: '历史', toggle_theme: '切换主题', video_url_placeholder: '粘贴视频链接...', start_transcription: '转录', ai_settings: '设置', model_base_url: 'Model API 地址', model_base_url_placeholder: 'https://openrouter.ai/api/v1', api_key: 'API Key', api_key_placeholder: 'sk-...', fetch_models: '获取', model_select: '模型', model_default: '服务器默认', two_step_summary: '双步摘要', summary_language: '语言', processing_progress: '处理进度', total_progress: '总进度', preparing: '准备中…', transcript_text: '转录文本', intelligent_summary: '智能摘要', translation: '翻译', download_transcript: '转录', download_translation: '翻译', download_summary: '摘要', copy: '复制', copy_transcript: '复制转录文本', copy_summary: '复制摘要', copy_translation: '复制翻译', empty_hint: '粘贴链接或上传文件。', footer_text: '<a class="repo-primary" href="https://github.com/EvilIrving/ai-transcriber" target="_blank">ai-transcriber</a> · 致谢 <a href="https://github.com/wendy7756/AI-Video-Transcriber" target="_blank">AI-Video-Transcriber</a>', processing: '处理中…', downloading_video: '正在下载音频…', parsing_video: '正在解析视频信息…', transcribing_audio: '正在转录音频…', optimizing_transcript: '正在优化转录文本…', generating_summary: '正在生成摘要…', detecting_subtitles: '正在检测字幕…', subtitle_found: '已获取字幕…', no_subtitle: '下载音频…', mode_subtitle: '字幕', mode_whisper: 'Whisper', completed: '完成', error_invalid_url: '请输入有效的视频链接', error_processing_failed: '处理失败：', error_no_download: '没有可下载的文件', error_download_failed: '下载失败：', fetching_models: '正在获取模型列表…', models_loaded: (n) => `已加载 ${n} 个模型`, models_error: '获取模型失败', upload_or: '或拖放文件到此处', upload_formats: '.mp3 · .mp4 · .wav · .m4a · .webm · .mkv · .ogg · .flac', upload_files_btn: '上传文件', error_upload_type: '不支持的文件类型', error_upload_empty: '文件为空', error_upload_size: (mb) => `文件超过 ${mb} MB 限制`, download_page_title: '下载', download_page_subtitle: '选择视频、音频或字幕。', detect: '检测', video: '视频', audio: '音频', subtitle_file: '字幕', choose_quality: '选择清晰度：', choose_audio_quality: '选择音质：', output_format: '输出格式：', subtitle_language: '字幕语言：', download_video_btn: '下载视频', download_audio_btn: '下载音频', download_subtitle_btn: '下载字幕', downloading: '下载中', download_file: '下载文件', copyright_notice: '请遵守版权规定。', history_page_title: '历史', history_page_subtitle: '搜索、查看、删除摘要。', history_search_placeholder: '搜索历史...', history_empty: '暂无历史。', rss_page_subtitle: '订阅后可摘要或下载。', rss_url_placeholder: '粘贴 RSS 链接...', subscribe: '订阅', rss_empty: '暂无订阅。', cancel: '取消', transcript_pending: '转录文本仍在优化…', processing_error: '处理错误', sse_disconnected: 'SSE 连接中断', request_failed: '请求失败', unknown_error: '未知错误', history_db_failed: '无法打开历史数据库', url_required: '请输入链接', detecting: '检测中…', detect_failed: '检测失败：', audio_unavailable: '无纯音频流。', no_subtitles: '无字幕', manual_subtitles: '手动：', auto_subtitles: '自动：', subtitles_available: '有字幕', manual: '手动', auto: '自动', download_failed: '下载失败：', unnamed_summary: '未命名摘要', history_load_failed: '读取失败：', no_matches: '无匹配结果。', source_link: '来源链接', local_task: '本地任务', view: '查看', collapse: '收起', delete: '删除', confirm_delete_history: '确定要删除这条历史摘要吗？', delete_failed: '删除失败：', adding: '添加中…', subscribe_failed: '订阅失败：', timeout: '请求超时', rss_refresh_failed: '刷新失败', new_count: (n) => `${n} 新`, item_count: (n) => `${n} 条`, updated: '更新:', never_updated: '未更新', refresh: '刷新', confirm_delete_feed: '确定要删除此订阅吗？', expand_entries_hint: '点击展开条目列表', feed_missing: '订阅不存在', no_entries: '暂无条目', summarized: '已摘要', summarize: '摘要', downloaded: '已下载', task_creation_failed: '任务创建失败：', refresh_failed: '刷新失败：', found_new_items: (n) => `发现 ${n} 条新内容`, ui_language: '界面语言', api_url_required: '需要 API Key 和 URL',
  },
};

window.VT_I18N.ja = { ...window.VT_I18N.en,
  subtitle: '文字起こし、要約、履歴保存。', nav_transcribe: '文字起こし', nav_download: 'ダウンロード', nav_history: '履歴', toggle_theme: 'テーマ切替', video_url_placeholder: '動画 URL を貼り付け...', start_transcription: '文字起こし', ai_settings: '設定', model_default: 'サーバー既定', two_step_summary: '2 段階要約', summary_language: '言語', total_progress: '全体', preparing: '準備中…', transcript_text: '文字起こし', intelligent_summary: 'AI 要約', translation: '翻訳', download_transcript: '文字起こし', download_translation: '翻訳', download_summary: '要約', copy: 'コピー', copy_transcript: '文字起こしをコピー', copy_summary: '要約をコピー', copy_translation: '翻訳をコピー', empty_hint: 'リンクを貼り付けるかファイルをアップロードしてください。', processing: '処理中…', parsing_video: '動画情報を解析中…', transcribing_audio: '音声を文字起こし中…', optimizing_transcript: '文字起こしを最適化中…', generating_summary: '要約を生成中…', detecting_subtitles: '字幕を検出中…', subtitle_found: '字幕を取得しました…', mode_subtitle: '字幕', completed: '完了', error_invalid_url: 'URL を入力してください', error_processing_failed: '処理に失敗しました: ', error_no_download: 'ダウンロードできるファイルがありません', fetching_models: 'モデル一覧を取得中…', models_loaded: (n) => `${n} 件のモデルを読み込みました`, models_error: 'モデル取得に失敗しました', upload_or: 'ファイルをアップロード', upload_files_btn: 'ファイルをアップロード', error_upload_type: '未対応のファイル形式です', error_upload_empty: 'ファイルが空です', error_upload_size: (mb) => `ファイルが ${mb} MB の上限を超えています`, download_page_title: 'ダウンロード', download_page_subtitle: '動画、音声、字幕を選択します。', detect: '検出', video: '動画', audio: '音声', subtitle_file: '字幕', choose_quality: '画質を選択:', choose_audio_quality: '音質を選択:', output_format: '形式:', subtitle_language: '字幕言語:', download_video_btn: '動画をダウンロード', download_audio_btn: '音声をダウンロード', download_subtitle_btn: '字幕をダウンロード', downloading: 'ダウンロード中', download_file: 'ファイルをダウンロード', copyright_notice: '著作権を遵守してください。', history_page_title: '履歴', history_page_subtitle: '要約を検索、表示、削除します。', history_search_placeholder: '履歴を検索...', history_empty: '履歴はまだありません。', rss_page_subtitle: 'フィード項目を要約またはダウンロードできます。', rss_url_placeholder: 'RSS URL を貼り付け...', subscribe: '購読', rss_empty: '購読はまだありません。', cancel: 'キャンセル', transcript_pending: '文字起こしを最適化中です…', processing_error: '処理エラー', sse_disconnected: 'SSE 接続が切断されました', request_failed: 'リクエスト失敗', unknown_error: '不明なエラー', history_db_failed: '履歴データベースを開けません', url_required: 'URL を入力してください', detecting: '検出中…', detect_failed: '検出に失敗しました: ', audio_unavailable: '音声のみのストリームがありません。', no_subtitles: '字幕なし', manual_subtitles: '手動:', auto_subtitles: '自動:', subtitles_available: '字幕あり', manual: '手動', auto: '自動', unnamed_summary: '無題の要約', history_load_failed: '読み込み失敗: ', no_matches: '一致なし。', source_link: '元リンク', local_task: 'ローカルタスク', view: '表示', collapse: '閉じる', delete: '削除', confirm_delete_history: 'この要約を削除しますか？', delete_failed: '削除失敗: ', adding: '追加中…', subscribe_failed: '購読失敗: ', timeout: 'リクエストがタイムアウトしました', rss_refresh_failed: '更新失敗', new_count: (n) => `${n} 件の新着`, item_count: (n) => `${n} 件`, updated: '更新:', never_updated: '未更新', refresh: '更新', confirm_delete_feed: 'この購読を削除しますか？', expand_entries_hint: 'クリックして項目を読み込む', feed_missing: '購読が見つかりません', no_entries: '項目なし', summarized: '要約済み', summarize: '要約', downloaded: 'ダウンロード済み', task_creation_failed: 'タスク作成失敗: ', refresh_failed: '更新失敗: ', found_new_items: (n) => `${n} 件の新着があります`, ui_language: 'UI 言語', api_url_required: 'API Key と URL が必要です',
};

window.VT_I18N.ko = { ...window.VT_I18N.en,
  subtitle: '전사, 요약, 기록 저장.', nav_transcribe: '전사', nav_download: '다운로드', nav_history: '기록', toggle_theme: '테마 전환', video_url_placeholder: '동영상 URL 붙여넣기...', start_transcription: '전사', ai_settings: '설정', model_default: '서버 기본값', two_step_summary: '2단계 요약', summary_language: '언어', total_progress: '전체', preparing: '준비 중…', transcript_text: '전사 텍스트', intelligent_summary: 'AI 요약', translation: '번역', download_transcript: '전사', download_translation: '번역', download_summary: '요약', copy: '복사', copy_transcript: '전사 텍스트 복사', copy_summary: '요약 복사', copy_translation: '번역 복사', empty_hint: '링크를 붙여넣거나 파일을 업로드하세요.', processing: '처리 중…', parsing_video: '동영상 정보 분석 중…', transcribing_audio: '오디오 전사 중…', optimizing_transcript: '전사 텍스트 최적화 중…', generating_summary: '요약 생성 중…', detecting_subtitles: '자막 감지 중…', subtitle_found: '자막을 가져왔습니다…', mode_subtitle: '자막', completed: '완료', error_invalid_url: 'URL을 입력하세요', error_processing_failed: '처리 실패: ', error_no_download: '다운로드할 파일이 없습니다', fetching_models: '모델 목록 가져오는 중…', models_loaded: (n) => `${n}개 모델 로드됨`, models_error: '모델 가져오기 실패', upload_or: '파일 업로드', upload_files_btn: '파일 업로드', error_upload_type: '지원하지 않는 파일 형식', error_upload_empty: '파일이 비어 있습니다', error_upload_size: (mb) => `파일이 ${mb} MB 제한을 초과했습니다`, download_page_title: '다운로드', download_page_subtitle: '동영상, 오디오 또는 자막을 선택하세요.', detect: '감지', video: '동영상', audio: '오디오', subtitle_file: '자막', choose_quality: '화질 선택:', choose_audio_quality: '음질 선택:', output_format: '형식:', subtitle_language: '자막 언어:', download_video_btn: '동영상 다운로드', download_audio_btn: '오디오 다운로드', download_subtitle_btn: '자막 다운로드', downloading: '다운로드 중', download_file: '파일 다운로드', copyright_notice: '저작권을 준수하세요.', history_page_title: '기록', history_page_subtitle: '요약을 검색, 보기, 삭제합니다.', history_search_placeholder: '기록 검색...', history_empty: '기록이 없습니다.', rss_page_subtitle: '피드 항목을 요약하거나 다운로드합니다.', rss_url_placeholder: 'RSS URL 붙여넣기...', subscribe: '구독', rss_empty: '구독이 없습니다.', cancel: '취소', transcript_pending: '전사 텍스트를 최적화 중입니다…', processing_error: '처리 오류', sse_disconnected: 'SSE 연결 끊김', request_failed: '요청 실패', unknown_error: '알 수 없는 오류', history_db_failed: '기록 데이터베이스를 열 수 없습니다', url_required: 'URL을 입력하세요', detecting: '감지 중…', detect_failed: '감지 실패: ', audio_unavailable: '오디오 전용 스트림이 없습니다.', no_subtitles: '자막 없음', manual_subtitles: '수동:', auto_subtitles: '자동:', subtitles_available: '자막 있음', manual: '수동', auto: '자동', unnamed_summary: '제목 없는 요약', history_load_failed: '로드 실패: ', no_matches: '일치하는 결과 없음.', source_link: '원본 링크', local_task: '로컬 작업', view: '보기', collapse: '접기', delete: '삭제', confirm_delete_history: '이 요약을 삭제할까요?', delete_failed: '삭제 실패: ', adding: '추가 중…', subscribe_failed: '구독 실패: ', timeout: '요청 시간 초과', rss_refresh_failed: '새로고침 실패', new_count: (n) => `새 항목 ${n}개`, item_count: (n) => `${n}개 항목`, updated: '업데이트:', never_updated: '없음', refresh: '새로고침', confirm_delete_feed: '이 구독을 삭제할까요?', expand_entries_hint: '클릭하여 항목 불러오기', feed_missing: '구독을 찾을 수 없음', no_entries: '항목 없음', summarized: '요약됨', summarize: '요약', downloaded: '다운로드됨', task_creation_failed: '작업 생성 실패: ', refresh_failed: '새로고침 실패: ', found_new_items: (n) => `새 항목 ${n}개 발견`, ui_language: 'UI 언어', api_url_required: 'API Key와 URL이 필요합니다',
};

window.VTI18nMethods = {
  t(key) {
    const dict = this.i18n[this.currentLang] || this.i18n.en || {};
    const fallback = this.i18n.en || {};
    return dict[key] || fallback[key] || key;
  },

  _switchLang(lang) {
    const next = this.i18n[lang] ? lang : 'en';
    this.currentLang = next;
    const meta = (this.languages || []).find(l => l.code === next) || { code: next, label: next, htmlLang: next };
    if (this.langSelect) this.langSelect.value = next;
    if (this.langText) this.langText.textContent = meta.label;
    try { localStorage.setItem('vt_ui_lang', next); } catch (_) {}
    document.documentElement.lang = meta.htmlLang || next;
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
  },
};
