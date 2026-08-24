import '@testing-library/jest-dom/vitest'
import { afterEach } from 'vitest'
import { cleanup } from '@testing-library/react'

// jsdom 没有 IntersectionObserver；渐进列表 hook 依赖它，给一个空实现避免测试崩溃。
class IntersectionObserverMock {
  observe() {}
  unobserve() {}
  disconnect() {}
  takeRecords() { return [] }
}
if (typeof globalThis.IntersectionObserver === 'undefined') {
  globalThis.IntersectionObserver = IntersectionObserverMock as unknown as typeof IntersectionObserver
}

// 每个用例后清理 DOM 与 localStorage，避免跨用例状态泄漏。
afterEach(() => {
  cleanup()
  localStorage.clear()
})
