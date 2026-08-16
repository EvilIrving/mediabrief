import { describe, expect, it } from 'vitest'
import type { MediaFormat } from '@/lib/types'
import { I18N } from '@/i18n/dictionaries'
import {
  formatSize,
  humanizeBitrate,
  humanizeCodec,
  humanizeFps,
  humanizeResolution,
  presentFormats,
  type FormatHint,
} from './downloadFormats'

const HINT_KEYS: Record<FormatHint, string> = {
  compatible: 'fmt_hint_compatible',
  smaller: 'fmt_hint_smaller',
}

describe('humanizeCodec', () => {
  it('maps common video and audio fourccs', () => {
    expect(humanizeCodec('avc1.640034')).toBe('h264')
    expect(humanizeCodec('hvc1.1.6.L153.90')).toBe('hevc')
    expect(humanizeCodec('av01.0.13M.08.0.110.01.01.01.0')).toBe('av1')
    expect(humanizeCodec('mp4a.40.2')).toBe('aac')
    expect(humanizeCodec('opus')).toBe('opus')
    expect(humanizeCodec('none')).toBe('')
    expect(humanizeCodec('')).toBe('')
  })
})

describe('humanizeResolution', () => {
  it('maps any height onto the usual ladder, not a fixed list of examples', () => {
    expect(humanizeResolution(2160)).toBe('4K')
    expect(humanizeResolution(1440)).toBe('1440p')
    expect(humanizeResolution(1080)).toBe('1080p')
    expect(humanizeResolution(720)).toBe('720p')
    expect(humanizeResolution(480)).toBe('480p')
    expect(humanizeResolution(360)).toBe('360p')
    expect(humanizeResolution(240)).toBe('240p')
    expect(humanizeResolution(144)).toBe('144p')
    expect(humanizeResolution(900)).toBe('720p')
    expect(humanizeResolution(undefined, '1280x720')).toBe('720p')
    expect(humanizeResolution(undefined, '640x360')).toBe('360p')
    expect(humanizeResolution(undefined, '3840x2160')).toBe('4K')
    expect(humanizeResolution(undefined, '1920x1080')).toBe('1080p')
  })
})

describe('humanizeFps / bitrate / size', () => {
  it('rounds near-60 and fractional bitrates', () => {
    expect(humanizeFps(59.933)).toBe('60fps')
    expect(humanizeFps(29.97)).toBe('30fps')
    expect(humanizeBitrate(84.785)).toBe('85kbps')
    expect(humanizeBitrate(65.684)).toBe('66kbps')
    expect(formatSize(110.3 * 1024 * 1024)).toBe('110.3 MB')
    expect(formatSize(0)).toBe('')
  })
})

describe('presentFormats', () => {
  const video: MediaFormat[] = [
    { id: 'bestvideo+bestaudio/best', note: '自动选择最佳视频+音频', ext: 'mp4', filesize: 87800000 },
    { id: '401+bestaudio', note: '3840x2160 (mp4) [avc1.640034] 59.933fps', resolution: '3840x2160', height: 2160, fps: 59.933, ext: 'mp4', vcodec: 'avc1.640034', filesize: 269600000 },
    { id: '337+bestaudio', note: '3840x2160 (mp4) [hvc1.1.6.L153.90] 59.933fps', resolution: '3840x2160', height: 2160, fps: 59.933, ext: 'mp4', vcodec: 'hvc1.1.6.L153.90', filesize: 110300000 },
    { id: '701+bestaudio', note: '3840x2160 (mp4) [av01.0.13M.08.0.110.01.01.01.0] 59.933fps', resolution: '3840x2160', height: 2160, fps: 59.933, ext: 'mp4', vcodec: 'av01.0.13M.08.0.110.01.01.01.0', filesize: 82000000 },
    { id: '299+bestaudio', note: '1920x1080 (mp4) [avc1.640032] 59.933fps', resolution: '1920x1080', height: 1080, fps: 59.933, ext: 'mp4', vcodec: 'avc1.640032', filesize: 73200000 },
  ]

  it('joins available fields as resolution ext fps codec', () => {
    const rows = presentFormats(video, 'video')
    expect(rows[0].isAuto).toBe(true)
    expect(rows[0].title).toBe('')
    expect(rows[0].sizeLabel).toBe('')
    expect(rows.map((r) => r.title)).toEqual([
      '',
      '4K mp4 60fps h264',
      '4K mp4 60fps hevc',
      '4K mp4 60fps av1',
      '1080p mp4 60fps h264',
    ])
    expect(rows.some((r) => r.title.includes('avc1'))).toBe(false)
  })

  it('tags same-resolution choices by compatibility and size', () => {
    const rows = presentFormats(video, 'video')
    const fourK = rows.filter((r) => r.height === 2160)
    expect(fourK.find((r) => r.codecLabel === 'h264')?.hint).toBe('compatible')
    expect(fourK.find((r) => r.codecLabel === 'av1')?.hint).toBe('smaller')
    expect(fourK.find((r) => r.codecLabel === 'hevc')?.hint).toBeNull()
    expect(rows.find((r) => r.height === 1080)?.hint).toBeNull()
  })

  it('composes the labels a person actually reads', () => {
    const t = (key: string) => I18N.zh[key] as string
    const labels = presentFormats(video, 'video').map((row) => {
      const hint = row.hint ? t(HINT_KEYS[row.hint]) : ''
      const title = row.isAuto ? t('fmt_best_video') : [row.title, hint].filter(Boolean).join(' ')
      return { title, size: row.sizeLabel }
    })
    expect(labels).toEqual([
      { title: '最佳画质', size: '' },
      { title: '4K mp4 60fps h264 更兼容', size: formatSize(269600000) },
      { title: '4K mp4 60fps hevc', size: formatSize(110300000) },
      { title: '4K mp4 60fps av1 更小', size: formatSize(82000000) },
      { title: '1080p mp4 60fps h264', size: formatSize(73200000) },
    ])
  })

  it('keeps 720p and 360p as first-class rows when the source has them', () => {
    const mixed: MediaFormat[] = [
      { id: 'bestvideo+bestaudio/best', note: 'best' },
      { id: '136+bestaudio', resolution: '1280x720', height: 720, fps: 30, ext: 'mp4', vcodec: 'avc1.4d401f', filesize: 40_000_000 },
      { id: '247+bestaudio', resolution: '1280x720', height: 720, fps: 30, ext: 'webm', vcodec: 'vp9', filesize: 22_000_000 },
      { id: '134+bestaudio', resolution: '640x360', height: 360, fps: 30, ext: 'mp4', vcodec: 'avc1.4d401e', filesize: 8_000_000 },
    ]
    const rows = presentFormats(mixed, 'video')
    expect(rows.map((r) => r.title)).toEqual(['', '720p mp4 30fps h264', '720p webm 30fps vp9', '360p mp4 30fps h264'])
    expect(rows.find((r) => r.codecLabel === 'h264' && r.height === 720)?.hint).toBe('compatible')
    expect(rows.find((r) => r.codecLabel === 'vp9')?.hint).toBe('smaller')
    expect(rows.find((r) => r.height === 360)?.hint).toBeNull()
  })

  it('uses a server-provided label as-is', () => {
    const rows = presentFormats(
      [
        { id: 'bestaudio/best' },
        { id: '140', label: 'm4a 129kbps aac', ext: 'm4a', acodec: 'mp4a.40.2', abr: 129 },
        { id: '251', label: 'webm 118kbps opus', ext: 'webm', acodec: 'opus', abr: 118 },
      ],
      'audio',
    )
    expect(rows.map((r) => r.title)).toEqual(['', 'm4a 129kbps aac', 'webm 118kbps opus'])
  })

  it('uses bitrate as the audio title', () => {
    const audio: MediaFormat[] = [
      { id: 'bestaudio/best', note: '最佳音质（自动选择）', ext: 'm4a' },
      { id: '140', note: '(m4a) [mp4a.40.2] ~84.785kbps', ext: 'm4a', acodec: 'mp4a.40.2', abr: 84.785 },
      { id: '139', note: '(m4a) [mp4a.40.2] ~65.684kbps', ext: 'm4a', acodec: 'mp4a.40.2', abr: 65.684 },
    ]
    const rows = presentFormats(audio, 'audio')
    expect(rows[0].isAuto).toBe(true)
    expect(rows.map((r) => r.title)).toEqual(['', 'm4a 85kbps aac', 'm4a 66kbps aac'])
  })
})
