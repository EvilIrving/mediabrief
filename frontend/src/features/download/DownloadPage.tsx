import { useEffect, useMemo, useRef, useState } from 'react'
import { Icon } from '@/components/IconSprite'
import { ErrorBanner } from '@/components/ErrorBanner'
import { api } from '@/lib/api'
import type { ApiError, DownloadFormatsResponse, MediaFormat, TaskPayload } from '@/lib/types'
import { useAutoDismissError } from '@/hooks/useAutoDismissError'
import { useI18n } from '@/i18n/I18nContext'

type DwnTab = 'video' | 'audio' | 'subtitle'

function formatSize(bytes?: number): string {
  if (!bytes || bytes <= 0) return ''
  const units = ['B', 'KB', 'MB', 'GB']
  let i = 0
  let val = bytes
  while (val >= 1024 && i < units.length - 1) {
    val /= 1024
    i++
  }
  return val.toFixed(i > 0 ? 1 : 0) + ' ' + units[i]
}

function clampPct(value: unknown): number {
  const n = Number(value)
  if (!Number.isFinite(n)) return 0
  return Math.max(0, Math.min(100, n))
}

export function DownloadPage() {
  const { t } = useI18n()
  const { msg: error, show: showError, hide: hideError } = useAutoDismissError()

  const [url, setUrl] = useState('')
  const [detecting, setDetecting] = useState(false)
  const [data, setData] = useState<DownloadFormatsResponse | null>(null)
  const [tab, setTab] = useState<DwnTab>('video')
  const [videoFmt, setVideoFmt] = useState('bestvideo+bestaudio/best')
  const [audioFmt, setAudioFmt] = useState('bestaudio/best')
  const [audioContainer, setAudioContainer] = useState('m4a')
  const [subLang, setSubLang] = useState('')
  const [phase, setPhase] = useState<'formats' | 'progress' | 'completed' | 'none'>('none')
  const [progress, setProgress] = useState({ pct: 0, stageName: '', msg: '' })
  const [completed, setCompleted] = useState({ filename: '', fileUrl: '#' })

  const esRef = useRef<EventSource | null>(null)
  const taskIdRef = useRef<string | null>(null)

  const stopSSE = () => {
    if (esRef.current) {
      esRef.current.close()
      esRef.current = null
    }
  }
  useEffect(() => () => stopSSE(), [])

  const videoFormats = data?.video_formats || []
  const audioFormats = data?.audio_formats || []
  const subLangs = useMemo(() => {
    const subs = data?.subtitles || {}
    return [...new Set([...(subs.manual || []), ...(subs.auto || [])])].sort()
  }, [data])
  const manualSet = useMemo(() => new Set(data?.subtitles?.manual || []), [data])

  const detect = async () => {
    const trimmed = url.trim()
    if (!trimmed) {
      showError(t('url_required'))
      return
    }
    setDetecting(true)
    hideError()
    setData(null)
    setPhase('none')
    try {
      const fd = new FormData()
      fd.append('url', trimmed)
      const resp = await api.downloadFormats(fd).catch((err: ApiError) => {
        throw new Error(err.detail || (t('request_failed') as string))
      })
      setData(resp)
      setVideoFmt('bestvideo+bestaudio/best')
      setAudioFmt('bestaudio/best')
      /* Default subtitle language: English, then first available. */
      const subs = resp.subtitles || {}
      const all = [...new Set([...(subs.manual || []), ...(subs.auto || [])])].sort()
      const prefer = ['en', 'en-orig', 'zh-Hans', 'zh-Hant', 'zh']
      setSubLang(prefer.find((p) => all.includes(p)) || all[0] || '')
      setTab('video')
      setPhase('formats')
    } catch (e) {
      showError(t('detect_failed') + (e as Error).message)
    } finally {
      setDetecting(false)
    }
  }

  const startDownload = async (type: DwnTab) => {
    const trimmed = url.trim()
    if (!trimmed) return
    setPhase('progress')
    setProgress({ pct: 0, stageName: '', msg: '' })
    try {
      const fd = new FormData()
      fd.append('url', trimmed)
      let call: Promise<{ task_id: string }>
      if (type === 'video') {
        fd.append('format_id', videoFmt)
        fd.append('filename', data?.title || '')
        call = api.downloadVideo(fd)
      } else if (type === 'audio') {
        fd.append('format_id', audioFmt)
        fd.append('filename', data?.title || '')
        fd.append('audio_format', audioContainer)
        call = api.downloadAudio(fd)
      } else {
        fd.append('lang', subLang)
        fd.append('filename', data?.title || '')
        call = api.downloadSubtitles(fd)
      }
      const resp = await call.catch((err: ApiError) => {
        throw new Error(err.detail || (t('request_failed') as string))
      })
      taskIdRef.current = resp.task_id
      startSSE()
    } catch (e) {
      showError(t('download_failed') + (e as Error).message)
      setPhase('none')
    }
  }

  const startSSE = () => {
    if (!taskIdRef.current) return
    stopSSE()
    const es = new EventSource(api.streamUrl(taskIdRef.current))
    esRef.current = es
    es.onmessage = (ev) => {
      try {
        const task = JSON.parse(ev.data) as TaskPayload
        if (task.type === 'heartbeat') return
        const pct = clampPct(task.progress || 0)
        setProgress({
          pct,
          stageName: task.current_stage_label || '',
          msg: task.message || '',
        })
        if (task.status === 'completed') {
          stopSSE()
          setCompleted({
            filename: task.filename || '',
            fileUrl: api.videoFileUrl(task.filename || ''),
          })
          setPhase('completed')
        } else if (task.status === 'error') {
          stopSSE()
          showError(task.error || (t('download_failed') as string))
          setPhase('none')
        }
      } catch {
        /* ignore */
      }
    }
    es.onerror = () => stopSSE()
  }

  return (
    <div>
      <div className="page-topbar">
        <div className="page-topbar-left">
          <h1 className="page-topbar-title">{t('download_page_title')}</h1>
          <span className="page-topbar-sub">{t('download_page_subtitle')}</span>
        </div>
      </div>

      <ErrorBanner msg={error} />

      <div className="input-row">
        <div className="url-wrap">
          <Icon name="i-link" className="icon url-icon" />
          <input
            type="url"
            className="url-input"
            placeholder={t('video_url_placeholder')}
            value={url}
            onChange={(e) => setUrl(e.target.value)}
          />
        </div>
        <button className="btn-go" disabled={detecting} onClick={() => void detect()}>
          <span>{detecting ? t('detecting') : t('detect')}</span>
        </button>
      </div>

      {phase === 'formats' && data && (
        <div>
          <div className="dwn-tabs">
            <button className={`dwn-tab-btn${tab === 'video' ? ' active' : ''}`} onClick={() => setTab('video')}>
              <span>{t('video')}</span>
            </button>
            <button className={`dwn-tab-btn${tab === 'audio' ? ' active' : ''}`} onClick={() => setTab('audio')}>
              <span>{t('audio')}</span>
            </button>
            <button className={`dwn-tab-btn${tab === 'subtitle' ? ' active' : ''}`} onClick={() => setTab('subtitle')}>
              <span>{t('subtitle_file')}</span>
            </button>
          </div>

          {tab === 'video' && (
            <div className="dwn-tab-pane">
              <p className="dwn-field-note">{t('choose_quality')}</p>
              <FormatList formats={videoFormats} selected={videoFmt} onSelect={setVideoFmt} kind="video" />
              <button className="btn-go dwn-start-btn" onClick={() => void startDownload('video')}>
                <span>{t('download_video_btn')}</span>
              </button>
            </div>
          )}

          {tab === 'audio' && (
            <div className="dwn-tab-pane">
              <p className="dwn-field-note">{t('choose_audio_quality')}</p>
              {audioFormats.length ? (
                <FormatList formats={audioFormats} selected={audioFmt} onSelect={setAudioFmt} kind="audio" />
              ) : (
                <div className="fmt-list"><div className="dwn-empty">{t('audio_unavailable')}</div></div>
              )}
              <div className="dwn-inline-field">
                <label>
                  <span>{t('output_format')}</span>
                  <select value={audioContainer} onChange={(e) => setAudioContainer(e.target.value)}>
                    <option value="m4a">m4a (AAC)</option>
                    <option value="mp3">mp3</option>
                    <option value="opus">opus</option>
                    <option value="flac">flac</option>
                    <option value="wav">wav</option>
                  </select>
                </label>
              </div>
              <button className="btn-go dwn-start-btn" disabled={!audioFormats.length} onClick={() => void startDownload('audio')}>
                <span>{t('download_audio_btn')}</span>
              </button>
            </div>
          )}

          {tab === 'subtitle' && (
            <div className="dwn-tab-pane">
              {subLangs.length ? (
                <>
                  <div className="dwn-sub-info">
                    {(data.subtitles?.manual?.length ?? 0) > 0 && (
                      <><Icon name="i-closed-captioning" /> {t('manual_subtitles')}{data.subtitles!.manual!.join(', ')}<br /></>
                    )}
                    {(data.subtitles?.auto?.length ?? 0) > 0 && (
                      <><Icon name="i-wand-magic-sparkles" /> {t('auto_subtitles')}{data.subtitles!.auto!.join(', ')}</>
                    )}
                  </div>
                  <div className="dwn-subtitle-row">
                    <label>{t('subtitle_language')}</label>
                    <select value={subLang} onChange={(e) => setSubLang(e.target.value)}>
                      {subLangs.map((l) => (
                        <option key={l} value={l}>{l}{manualSet.has(l) ? ` (${t('manual')})` : ` (${t('auto')})`}</option>
                      ))}
                    </select>
                  </div>
                  <button className="btn-go dwn-start-btn" onClick={() => void startDownload('subtitle')}>
                    <span>{t('download_subtitle_btn')}</span>
                  </button>
                </>
              ) : (
                <p className="dwn-sub-empty"><Icon name="i-circle-info" /> {t('no_subtitles')}</p>
              )}
            </div>
          )}
        </div>
      )}

      {phase === 'progress' && (
        <div className="progress-panel show">
          <div className="prog-top">
            <div className="prog-top-left"><span>{t('downloading')}</span></div>
            <span>{Math.round(progress.pct)}%</span>
          </div>
          <div className="prog-stage-row">
            <span className="prog-stage-name">{progress.stageName}</span>
          </div>
          <div className="prog-bar"><div className="prog-fill" style={{ width: `${progress.pct}%` }} /></div>
        </div>
      )}

      {phase === 'completed' && (
        <div className="dwn-completed show">
          <p className="dwn-completed-title"><Icon name="i-circle-check" /> {t('completed')}</p>
          <p className="dwn-completed-file">{completed.filename}</p>
          <a className="btn-go dwn-file-link" href={completed.fileUrl}>
            <span>{t('download_file')}</span>
          </a>
        </div>
      )}

      <p className="inline-info"><Icon name="i-circle-info" /> {t('copyright_notice')}</p>
    </div>
  )
}

function FormatList({
  formats, selected, onSelect, kind,
}: {
  formats: MediaFormat[]
  selected: string
  onSelect: (id: string) => void
  kind: 'video' | 'audio'
}) {
  return (
    <div className="fmt-list">
      {formats.map((f) => (
        <div
          key={f.id}
          className={`fmt-item${f.id === selected ? ' selected' : ''}`}
          onClick={() => onSelect(f.id)}
        >
          <div className="fmt-main">
            <span className="fmt-name">{f.note || f.resolution || f.id}</span>
            <span className="fmt-detail">
              {f.ext || ''}
              {kind === 'video' && f.vcodec ? ' · ' + f.vcodec : ''}
              {kind === 'audio' && f.acodec ? ' · ' + f.acodec : ''}
              {kind === 'audio' && f.abr ? ' · ' + f.abr + 'kbps' : ''}
            </span>
          </div>
          <span className="fmt-size">{f.filesize ? formatSize(f.filesize) : ''}</span>
        </div>
      ))}
    </div>
  )
}
