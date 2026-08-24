import { memo, useEffect, useMemo, useRef, useState } from 'react'
import { renderMarkdown, splitMarkdownBlocks } from '@/lib/markdown'

const INITIAL_BLOCKS = 40
const BLOCKS_PER_PAGE = 40

const MarkdownBlock = memo(function MarkdownBlock({ source }: { source: string }) {
  const html = useMemo(() => renderMarkdown(source), [source])
  return <div dangerouslySetInnerHTML={{ __html: html }} />
})

interface MarkdownProps {
  source: string
  className?: string
  progressive?: boolean
}

/* 长文按 Markdown block 渐进渲染，避免切换记录时同步创建巨量 HTML/DOM。 */
export function Markdown({ source, className = 'md-content', progressive = true }: MarkdownProps) {
  const blocks = useMemo(() => splitMarkdownBlocks(source), [source])
  const [visibleCount, setVisibleCount] = useState(INITIAL_BLOCKS)
  const [visibleSource, setVisibleSource] = useState(source)
  const sentinelRef = useRef<HTMLDivElement>(null)
  const sourceChanged = visibleSource !== source

  useEffect(() => {
    if (sourceChanged) setVisibleSource(source)
    setVisibleCount(Math.min(INITIAL_BLOCKS, blocks.length))
  }, [blocks.length, source, sourceChanged])

  const renderBlocks = progressive ? blocks : (source ? [source] : [])
  const visibleBlocks = progressive
    ? renderBlocks.slice(0, sourceChanged ? INITIAL_BLOCKS : visibleCount)
    : renderBlocks
  const hasMore = progressive && visibleCount < blocks.length

  useEffect(() => {
    if (!hasMore || !sentinelRef.current) return
    const sentinel = sentinelRef.current
    const observer = new IntersectionObserver(
      (entries) => {
        if (!entries.some((entry) => entry.isIntersecting)) return
        setVisibleCount((count) => Math.min(count + BLOCKS_PER_PAGE, blocks.length))
      },
      { rootMargin: '800px 0px' },
    )
    observer.observe(sentinel)
    return () => observer.disconnect()
  }, [blocks.length, hasMore])

  return (
    <div className={className}>
      {visibleBlocks.map((block, index) => (
        <MarkdownBlock key={`${index}:${block.slice(0, 24)}`} source={block} />
      ))}
      {hasMore && <div ref={sentinelRef} className="markdown-load-sentinel" aria-hidden="true" />}
    </div>
  )
}
