import { afterEach, describe, expect, it, vi } from 'vitest'
import { reportUiLang } from './desktop'

describe('reportUiLang', () => {
  afterEach(() => {
    delete (window as unknown as { pywebview?: unknown }).pywebview
  })

  it('calls the desktop bridge when present', () => {
    const setUiLang = vi.fn()
    ;(window as unknown as { pywebview: { api: { set_ui_lang: typeof setUiLang } } }).pywebview = {
      api: { set_ui_lang: setUiLang },
    }
    reportUiLang('zh')
    expect(setUiLang).toHaveBeenCalledWith('zh')
  })

  it('is a no-op without the desktop bridge', () => {
    expect(() => reportUiLang('zh')).not.toThrow()
  })
})
