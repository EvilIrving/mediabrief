import { useEffect, useRef, useState } from 'react'
import { Icon } from '@/components/IconSprite'
import { ErrorBanner } from '@/components/ErrorBanner'
import { useI18n } from '@/i18n/I18nContext'
import { useTaskHandoff } from '@/context/TaskHandoff'
import { useTranscribe } from './useTranscribe'
import { SettingsBar } from './SettingsBar'
import { ProgressPanel } from './ProgressPanel'
import { ResultsPanel } from './ResultsPanel'

const UPLOAD_ACCEPT = '.txt,.mp3,.mp4,.m4a,.wav,.webm,.mkv,.ogg,.flac'

export function TranscribePage() {
  const { t } = useI18n()
  const tr = useTranscribe()
  const { take } = useTaskHandoff()
  const [url, setUrl] = useState('')
  const [dragover, setDragover] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)

  /* Pick up a task handed off from the RSS page. */
  useEffect(() => {
    const pending = take()
    if (pending) tr.adoptRssTask(pending.taskId, pending.source)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    void tr.startTranscription(url)
  }

  const onFiles = (files: FileList | null) => {
    if (files && files[0]) void tr.startFileUpload(files[0])
  }

  return (
    <div>
      <div className="page-topbar">
        <div className="page-topbar-left">
          <h1 className="page-topbar-title">{t('title')}</h1>
          <span className="page-topbar-sub">{t('subtitle')}</span>
        </div>
      </div>

      <form onSubmit={submit} autoComplete="off" noValidate>
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
          <button
            type="submit"
            className={`btn-go${tr.isProcessing ? ' processing' : ''}`}
          >
            <span>{tr.isProcessing ? t('processing') : t('start_transcription')}</span>
          </button>
        </div>
      </form>

      <div className="upload-section">
        <div
          className={`upload-zone${dragover ? ' dragover' : ''}`}
          tabIndex={0}
          role="button"
          aria-label={t('upload_files_btn')}
          onClick={() => fileRef.current?.click()}
          onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') fileRef.current?.click() }}
          onDragOver={(e) => { e.preventDefault(); if (!tr.isProcessing) setDragover(true) }}
          onDragLeave={() => setDragover(false)}
          onDrop={(e) => { e.preventDefault(); setDragover(false); if (!tr.isProcessing) onFiles(e.dataTransfer.files) }}
          style={tr.isProcessing ? { pointerEvents: 'none', opacity: 0.65 } : undefined}
        >
          <p className="upload-or">{t('upload_or')}</p>
          <p className="upload-formats">{t('upload_formats')}</p>
          <button type="button" className="btn-upload-pill" disabled={tr.isProcessing}>
            <span>{t('upload_files_btn')}</span>
          </button>
        </div>
        <input
          ref={fileRef}
          type="file"
          accept={UPLOAD_ACCEPT}
          hidden
          onChange={(e) => onFiles(e.target.files)}
        />
      </div>

      <ErrorBanner msg={tr.error} />

      <SettingsBar />

      <div className="result-panel">
        {tr.phase === 'empty' && (
          <div className="empty-state">
            <span className="es-icon"><Icon name="i-inbox" /></span>
            <span className="es-text">{t('empty_hint')}</span>
          </div>
        )}
        {tr.phase === 'progress' && <ProgressPanel progress={tr.progress} />}
        {tr.phase === 'results' && (
          <ResultsPanel
            results={tr.results}
            isProcessing={tr.isProcessing}
            onTab={tr.setActiveTab}
            onExport={() => void tr.exportContent()}
            onRetry={() => void tr.retryTranscription()}
          />
        )}
      </div>
    </div>
  )
}
