/* Shared domain types for the API layer and feature hooks. */

export interface ApiError extends Error {
  detail?: string
  status?: number
}

/* ── Task / SSE payloads (transcribe + download share the stream) ── */
export interface StageItem {
  name?: string
  state?: 'pending' | 'current' | 'done' | 'skipped' | string
}

export interface ResultItem {
  key?: string
  state?: 'ready' | 'waiting' | string
}

export interface TaskPayload {
  type?: string
  task_id?: string
  status?: 'processing' | 'completed' | 'error' | 'cancelled' | string
  progress?: number
  progress_key?: string
  progress_step_current?: number
  progress_step_total?: number
  message?: string
  current_stage?: string
  mode?: 'subtitle' | 'whisper' | string
  stage_items?: StageItem[]
  result_items?: ResultItem[]
  error_code?: string
  task_type?: string
  /* completion fields */
  script?: string
  summary?: string
  translation?: string
  video_title?: string
  detected_language?: string
  summary_language?: string
  filename?: string
  file_size?: number
  error?: string
}

export interface TaskCreateResponse {
  task_id: string
}

/* ── Download formats ── */
export interface MediaFormat {
  id: string
  note?: string
  resolution?: string
  ext?: string
  vcodec?: string
  acodec?: string
  abr?: number
  filesize?: number
}

export interface DownloadFormatsResponse {
  title?: string
  video_formats?: MediaFormat[]
  audio_formats?: MediaFormat[]
  subtitles?: { manual?: string[]; auto?: string[] }
}

/* ── Models ── */
export interface ModelInfo {
  id: string
  name?: string
}

export interface ModelsResponse {
  data?: ModelInfo[]
  models?: ModelInfo[]
}

/* ── Whisper (ASR) models ── */
export interface WhisperModelInfo {
  size: string
  downloaded: boolean
  builtin: boolean
  approx_mb: number
  default: boolean
}

/* ── RSS ── */
export interface RssEntry {
  id: string
  title?: string
  link?: string
  summary?: string
  content?: string
  enclosure_url?: string
  enclosure_type?: string
  published?: string
  processed?: 'seen' | 'summarized' | 'downloaded' | string
}

export interface RssFeed {
  id: string
  url: string
  title?: string
  topic?: string
  region?: string
  type?: string
  favorite?: boolean
  added_at?: string
  last_checked?: string
  last_error?: string
  new_count?: number
  entries?: RssEntry[]
}

export interface RssFeedSummary {
  id: string
  title?: string
  topic?: string
  region?: string
  favorite: boolean
  type?: string
  url: string
  last_checked?: string
  last_error?: string
  entry_count: number
  new_count: number
}

export interface RssParseResponse {
  feed: RssFeed
}

/* ── Source descriptor (for history saving) ── */
export interface SourceDescriptor {
  type: 'url' | 'file' | 'rss'
  value: string
  title: string
}

/* ── History (backend DB) ── */
export interface HistoryItem {
  task_id: string
  video_title: string
  source_type: string
  source_value: string
  url: string
  summary: string
  summary_language: string
  created_at: string
  updated_at: string
  // 列表接口已不再附带 script 全文（节流），转录稿经 GET /api/task/{id}/transcript 按需取。
  has_transcript?: boolean
}

export interface TranscriptResponse {
  task_id: string
  script: string
}

/* 队列状态聚合（轻量徽标用） */
export interface QueueStats {
  queue_name: string
  by_status: Record<string, number>
  total: number
  queued: number
  processing: number
}

export interface QueueItemsResponse {
  items: QueueItem[]
  total: number
}

/* ── Task Queue ── */
export interface QueueItem {
  id: string
  queue_name: string
  item_type: string
  job_kind?: string
  item_key: string
  source_label?: string
  status: 'queued' | 'processing' | 'completed' | 'error' | 'cancelled'
  task_status?: 'processing' | 'completed' | 'error' | 'cancelled' | string
  task_id: string
  position: number
  created_at: string
  started_at: string
  completed_at: string
  error: string
  progress?: number
  progress_key?: string
  progress_step_current?: number
  progress_step_total?: number
  current_stage?: string
  mode?: 'subtitle' | 'whisper' | string
  task_type?: string
  stage_items?: StageItem[]
  result_items?: ResultItem[]
  summary_ready?: boolean
  transcript_ready?: boolean
  message?: string
}

export interface QueueState {
  queue_name: string
  items: QueueItem[]
  processing: QueueItem | null
  pending_count: number
}

export interface QueueEnqueueResponse {
  id: string
  status: string
  duplicate: boolean
}

/* ── Bot integration ──────────────────────────────────── */
export interface BotLLMConfig {
  api_key: string
  base_url: string
  model: string
  summary_language: string
  whisper_model: string
}

export interface BotPlatformConfig {
  enabled: boolean
  token: string
  extras?: Record<string, unknown>
}

export interface BotsConfigureBody {
  bots: Record<string, BotPlatformConfig>
  llm: BotLLMConfig
}

export interface BotRuntimeStatus {
  status: 'stopped' | 'starting' | 'running' | 'error'
  message?: string
  uptime_seconds?: number
  messages_processed?: number
  last_error?: string | null
  bot_name?: string
}

export interface BotsStatusResponse {
  bots: Record<string, BotRuntimeStatus>
}

/* ── Unified app settings ─────────────────────────────── */
export interface TtsConfig {
  enabled: boolean
  apiKey: string
  speaker: string
  resourceId: string
  apiKeyConfigured?: boolean
}

export interface AppBotPlatformConfig extends BotPlatformConfig {
  tokenConfigured?: boolean
  appTokenConfigured?: boolean
}

export interface AppSettingsPayload {
  baseUrl: string
  apiKey: string
  apiKeyConfigured?: boolean
  model: string
  summaryLang: string
  useTwoStep: boolean
  models: ModelInfo[]
  whisperModel: string
  hfEndpoint: string
  browserCookiesAutoDetect: boolean
  botConfigs: Record<string, AppBotPlatformConfig>
  ttsConfig: TtsConfig
}
