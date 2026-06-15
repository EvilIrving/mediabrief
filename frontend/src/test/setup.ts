import '@testing-library/jest-dom/vitest'
import { afterEach } from 'vitest'
import { cleanup } from '@testing-library/react'

// 每个用例后清理 DOM 与 localStorage，避免跨用例状态泄漏。
afterEach(() => {
  cleanup()
  localStorage.clear()
})
