import { marked } from 'marked'

// 摘要/转录落库时会在正文前加一行 `# 标题`；界面顶栏已展示标题，渲染前剥掉。
const LEADING_H1 = /^#\s+.+\s*(?:\n+|$)/

export function stripLeadingTitle(src: string | undefined | null): string {
  if (!src) return ''
  return src.replace(/^\uFEFF/, '').replace(LEADING_H1, '')
}

/* Synchronous markdown -> HTML, matching the original app's marked.parse usage. */
export function renderMarkdown(src: string | undefined | null): string {
  if (!src) return ''
  return marked.parse(src, { async: false }) as string
}

const MAX_BLOCK_CHARS = 4000

function splitOversizedBlock(block: string): string[] {
  if (block.length <= MAX_BLOCK_CHARS || block.includes('```')) return [block]

  const lines = block.split('\n')
  const parts: string[] = []
  let current: string[] = []
  let currentLength = 0

  for (const line of lines) {
    const nextLength = currentLength + line.length + (current.length ? 1 : 0)
    if (current.length && nextLength > MAX_BLOCK_CHARS) {
      parts.push(current.join('\n'))
      current = []
      currentLength = 0
    }
    current.push(line)
    currentLength += line.length + (current.length > 1 ? 1 : 0)
  }

  if (current.length) parts.push(current.join('\n'))
  return parts
}

/**
 * Split long documents at Markdown block boundaries so the UI can render them progressively.
 * Blank lines are safe boundaries for the transcript format and keep each marked.parse call small.
 */
export function splitMarkdownBlocks(src: string | undefined | null): string[] {
  if (!src) return []

  const lines = src.replace(/\r\n?/g, '\n').split('\n')
  const blocks: string[] = []
  const current: string[] = []
  let inFence = false

  const flush = () => {
    if (!current.length) return
    blocks.push(...splitOversizedBlock(current.join('\n')))
    current.length = 0
  }

  for (const line of lines) {
    const trimmed = line.trim()
    const isFence = trimmed.startsWith('```') || trimmed.startsWith('~~~')
    if (!inFence && trimmed === '') {
      flush()
      continue
    }
    current.push(line)
    if (isFence) inFence = !inFence
  }
  flush()

  return blocks
}

/** Used only on an explicit copy action, not during normal rendering. */
export function markdownToPlainText(src: string | undefined | null): string {
  if (!src) return ''
  const container = document.createElement('div')
  container.innerHTML = renderMarkdown(src)
  return container.textContent || ''
}
