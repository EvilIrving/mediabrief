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
