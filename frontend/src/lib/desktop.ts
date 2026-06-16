/* ────────────────────────────────────────────────────────────
   桌面化交互层：抹掉「网页惯性」，让应用更像原生桌面软件。

   - installDesktopBehaviors(): 进程级一次性安装的全局行为
       · 禁用 UI chrome 上的浏览器右键菜单（文本框/正文区保留，方便复制粘贴）
       · 拦截 Cmd/Ctrl+S、Cmd/Ctrl+P 等浏览器默认快捷键
       · 拦截窗口范围内的误拖放——否则把文件拖到上传区之外会让浏览器
         直接导航去打开该文件，整页 SPA 状态全丢（真实 bug）
   - useGlobalShortcuts(): 组件内安装的键盘快捷键（依赖 react-router 导航）
   ──────────────────────────────────────────────────────────── */
import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'

// 这些区域内保留原生右键/选中行为（文本编辑与正文复制）。
const TEXT_ZONE = 'input, textarea, [contenteditable="true"], .md-content, [data-selectable]'

function inTextZone(target: EventTarget | null): boolean {
  return target instanceof Element && target.closest(TEXT_ZONE) !== null
}

let installed = false

export function installDesktopBehaviors() {
  if (installed || typeof window === 'undefined') return
  installed = true

  // 1) 右键菜单：chrome 区域禁用，文本/正文区放行。
  document.addEventListener('contextmenu', (e) => {
    if (!inTextZone(e.target)) e.preventDefault()
  })

  // 2) 屏蔽浏览器默认快捷键（保存网页 / 打印），它们对桌面应用无意义。
  document.addEventListener(
    'keydown',
    (e) => {
      const mod = e.metaKey || e.ctrlKey
      if (mod && !e.altKey) {
        const k = e.key.toLowerCase()
        if (k === 's' || k === 'p') e.preventDefault()
      }
    },
    // 捕获阶段，先于组件处理，确保拦得住。
    { capture: true },
  )

  // 3) 误拖放保护：上传区自己处理 drop；落在其它任何地方一律吞掉，
  //    避免浏览器导航去打开被拖入的文件而丢失整页状态。
  const guard = (e: DragEvent) => {
    if ((e.target as Element | null)?.closest?.('.upload-zone')) return
    e.preventDefault()
  }
  window.addEventListener('dragover', guard)
  window.addEventListener('drop', guard)
}

const PAGE_BY_DIGIT: Record<string, string> = {
  '1': '/transcribe',
  '2': '/download',
  '3': '/rss',
  '4': '/history',
}

/** 全局键盘快捷键：Cmd/Ctrl+1~4 切页、Cmd/Ctrl+, 打开设置。 */
export function useGlobalShortcuts() {
  const navigate = useNavigate()
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const mod = e.metaKey || e.ctrlKey
      if (!mod || e.altKey || e.shiftKey) return
      const page = PAGE_BY_DIGIT[e.key]
      if (page) {
        e.preventDefault()
        navigate(page)
        return
      }
      if (e.key === ',') {
        e.preventDefault()
        window.dispatchEvent(new Event('open-settings'))
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [navigate])
}
