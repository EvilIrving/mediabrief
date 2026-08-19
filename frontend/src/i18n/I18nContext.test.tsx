import { render } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { I18nProvider, useI18n } from './I18nContext'

vi.mock('@/lib/desktop', () => ({
  reportUiLang: vi.fn(),
}))

import { reportUiLang } from '@/lib/desktop'

function Probe() {
  const { lang } = useI18n()
  return <span>{lang}</span>
}

describe('I18nProvider desktop language', () => {
  afterEach(() => {
    vi.mocked(reportUiLang).mockClear()
    localStorage.clear()
  })

  it('reports the current UI language to the desktop shell', () => {
    localStorage.setItem('vt_ui_lang', 'zh')
    render(
      <I18nProvider>
        <Probe />
      </I18nProvider>,
    )
    expect(reportUiLang).toHaveBeenCalledWith('zh')
  })
})
