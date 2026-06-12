import { renderMarkdown } from '@/lib/markdown'

/* Renders markdown into the shared .md-content styling. */
export function Markdown({ source, className = 'md-content' }: { source: string; className?: string }) {
  return <div className={className} dangerouslySetInnerHTML={{ __html: renderMarkdown(source) }} />
}
