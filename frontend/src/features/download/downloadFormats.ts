import type { MediaFormat } from '@/lib/types'

export const VIDEO_AUTO_ID = 'bestvideo+bestaudio/best'
export const AUDIO_AUTO_ID = 'bestaudio/best'

export type FormatKind = 'video' | 'audio'
export type FormatHint = 'compatible' | 'smaller'

export interface FormatRow {
  id: string
  title: string
  isAuto: boolean
  codecLabel: string
  sizeLabel: string
  hint: FormatHint | null
  height: number
  fromLabel: boolean
}

const HEIGHT_LABELS: Array<[number, string]> = [
  [2160, '4K'],
  [1440, '1440p'],
  [1080, '1080p'],
  [720, '720p'],
  [480, '480p'],
  [360, '360p'],
  [240, '240p'],
]

const STANDARD_FPS = [24, 25, 30, 48, 50, 60, 120]

export function isAutoFormat(id: string, kind: FormatKind): boolean {
  if (!id) return false
  if (id === 'best' || id === VIDEO_AUTO_ID || id === AUDIO_AUTO_ID) return true
  return kind === 'audio' && (id === 'bestaudio' || id === 'bestaudio/best')
}

export function humanizeCodec(raw?: string | null): string {
  const s = (raw || '').trim().toLowerCase()
  if (!s || s === 'none') return ''
  if (s.startsWith('avc') || s.includes('h264')) return 'h264'
  if (s.startsWith('hvc') || s.startsWith('hev') || s.includes('hevc') || s.includes('h265')) return 'hevc'
  if (s.startsWith('av01') || s.startsWith('av1')) return 'av1'
  if (s.startsWith('vp09') || s.startsWith('vp9')) return 'vp9'
  if (s.startsWith('vp08') || s.startsWith('vp8')) return 'vp8'
  if (s.startsWith('mp4a') || s.includes('aac')) return 'aac'
  if (s.startsWith('opus')) return 'opus'
  if (s.startsWith('mp3')) return 'mp3'
  if (s.startsWith('flac')) return 'flac'
  if (s.includes('vorbis')) return 'vorbis'
  if (s.includes('ac-3') || s.startsWith('ac3') || s.includes('eac3')) return 'ac3'
  const token = raw!.split('.')[0]?.trim().toLowerCase()
  return token && token.length <= 12 ? token : ''
}

export function humanizeResolution(height?: number | null, resolution?: string | null): string {
  const h = height && height > 0 ? height : parseHeight(resolution)
  if (!h) return ''
  for (const [min, label] of HEIGHT_LABELS) {
    if (h >= min) return label
  }
  return `${h}p`
}

export function humanizeFps(fps?: number | null): string {
  if (!fps || fps <= 0) return ''
  for (const std of STANDARD_FPS) {
    if (Math.abs(fps - std) < 0.5) return `${std}fps`
  }
  return `${Math.round(fps)}fps`
}

export function humanizeBitrate(abr?: number | null): string {
  if (!abr || abr <= 0) return ''
  return `${Math.round(abr)}kbps`
}

export function formatSize(bytes?: number | null): string {
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

export function presentFormats(formats: MediaFormat[], kind: FormatKind): FormatRow[] {
  const rows = formats.map((f) => presentOne(f, kind))
  applyHints(rows, kind)
  return rows
}

function presentOne(f: MediaFormat, kind: FormatKind): FormatRow {
  const inferred = inferFromNote(f.note)
  const height = f.height && f.height > 0 ? f.height : inferred.height
  const fps = f.fps && f.fps > 0 ? f.fps : inferred.fps
  const rawCodec = (kind === 'video' ? f.vcodec : f.acodec) || inferred.codec
  const codecLabel = humanizeCodec(rawCodec)
  const isAuto = isAutoFormat(f.id, kind)
  const fpsLabel = humanizeFps(fps)
  const bitrateLabel = humanizeBitrate(f.abr)
  const resLabel = humanizeResolution(height, f.resolution || inferred.resolution)

  const tokens: string[] = []
  if (!isAuto) {
    if (kind === 'video') {
      if (resLabel) tokens.push(resLabel)
      if (f.ext) tokens.push(f.ext)
      if (fpsLabel) tokens.push(fpsLabel)
      if (codecLabel) tokens.push(codecLabel)
    } else {
      if (f.ext) tokens.push(f.ext)
      if (bitrateLabel) tokens.push(bitrateLabel)
      if (codecLabel) tokens.push(codecLabel)
    }
  }
  let title = (f.label || '').trim()
  if (!title && !isAuto) {
    title = tokens.join(' ') || stripTechnicalNote(f.note || f.resolution || f.id)
  }

  return {
    id: f.id,
    title,
    isAuto,
    codecLabel,
    sizeLabel: isAuto ? '' : formatSize(f.filesize),
    hint: null,
    height: height || 0,
    fromLabel: Boolean((f.label || '').trim()) && !isAuto,
  }
}

function applyHints(rows: FormatRow[], kind: FormatKind): void {
  if (kind !== 'video') return
  const groups = new Map<number, FormatRow[]>()
  for (const row of rows) {
    if (row.isAuto || row.fromLabel || !row.height) continue
    const list = groups.get(row.height) || []
    list.push(row)
    groups.set(row.height, list)
  }
  for (const group of groups.values()) {
    if (group.length < 2) continue
    const withSize = group.filter((r) => r.sizeLabel)
    if (withSize.length >= 2) {
      const smallest = withSize.reduce((a, b) => (parseSize(a.sizeLabel) <= parseSize(b.sizeLabel) ? a : b))
      const uniquelySmall = withSize.filter((r) => parseSize(r.sizeLabel) === parseSize(smallest.sizeLabel)).length === 1
      if (uniquelySmall && smallest.codecLabel !== 'h264') smallest.hint = 'smaller'
    }
    const hasH264 = group.some((r) => r.codecLabel === 'h264')
    const hasOther = group.some((r) => r.codecLabel && r.codecLabel !== 'h264')
    if (hasH264 && hasOther) {
      for (const row of group) {
        if (row.codecLabel === 'h264' && !row.hint) row.hint = 'compatible'
      }
    }
  }
}

function parseHeight(resolution?: string | null): number {
  if (!resolution) return 0
  const dim = /(\d{3,4})\s*[x×]\s*(\d{3,4})/i.exec(resolution)
  if (dim) return Number(dim[2])
  const p = /(\d{3,4})\s*p\b/i.exec(resolution)
  if (p) return Number(p[1])
  if (/\b4k\b/i.test(resolution)) return 2160
  return 0
}

function inferFromNote(note?: string): { height: number; fps: number; codec: string; resolution: string } {
  const text = note || ''
  const fpsMatch = /([\d.]+)\s*fps/i.exec(text)
  const resMatch = /(\d{3,4}\s*[x×]\s*\d{3,4})/i.exec(text)
  const codecMatch = /\[([^\]]+)\]/.exec(text)
  return {
    height: parseHeight(text),
    fps: fpsMatch ? Number(fpsMatch[1]) : 0,
    codec: codecMatch?.[1] || '',
    resolution: resMatch?.[1] || '',
  }
}

function stripTechnicalNote(text: string): string {
  return text
    .replace(/\[[^\]]+\]/g, '')
    .replace(/\([^)]*\)/g, '')
    .replace(/[\d.]+\s*fps/ig, '')
    .replace(/\s+/g, ' ')
    .trim()
}

function parseSize(label: string): number {
  const m = /([\d.]+)\s*(B|KB|MB|GB)/i.exec(label)
  if (!m) return Number.POSITIVE_INFINITY
  const n = Number(m[1])
  const unit = m[2].toUpperCase()
  const mul = unit === 'GB' ? 1024 ** 3 : unit === 'MB' ? 1024 ** 2 : unit === 'KB' ? 1024 : 1
  return n * mul
}
