import { useEffect, useMemo, useRef, useState } from 'react'

const DEFAULT_PAGE_SIZE = 50

interface ProgressiveListOptions {
  resetKey?: unknown
  remoteHasMore?: boolean
  onNeedMore?: () => void
}

/** 只把当前滚动附近的第一批列表项放进 DOM，避免大列表首屏全量渲染。 */
export function useProgressiveList<T>(
  items: T[],
  pageSize = DEFAULT_PAGE_SIZE,
  options: ProgressiveListOptions = {},
) {
  const [visibleCount, setVisibleCount] = useState(pageSize)
  const [visibleResetKey, setVisibleResetKey] = useState<unknown>(options.resetKey ?? items)
  const sentinelRef = useRef<HTMLDivElement>(null)
  const { resetKey = items, remoteHasMore = false, onNeedMore } = options
  const resetPending = visibleResetKey !== resetKey

  useEffect(() => {
    if (resetPending) setVisibleResetKey(resetKey)
    setVisibleCount(Math.min(pageSize, items.length))
  }, [pageSize, resetKey, resetPending])

  const effectiveVisibleCount = resetPending ? pageSize : visibleCount
  const hasLocalMore = effectiveVisibleCount < items.length
  const hasMore = hasLocalMore || remoteHasMore
  const visibleItems = useMemo(() => items.slice(0, effectiveVisibleCount), [effectiveVisibleCount, items])

  useEffect(() => {
    if (!hasMore || !sentinelRef.current) return
    const sentinel = sentinelRef.current
    const observer = new IntersectionObserver(
      (entries) => {
        if (!entries.some((entry) => entry.isIntersecting)) return
        if (hasLocalMore) {
          setVisibleCount((count) => Math.min(count + pageSize, items.length))
        } else {
          onNeedMore?.()
        }
      },
      { rootMargin: '600px 0px' },
    )
    observer.observe(sentinel)
    return () => observer.disconnect()
  }, [hasLocalMore, hasMore, items.length, onNeedMore, pageSize, remoteHasMore])

  return { visibleItems, hasMore, sentinelRef }
}
