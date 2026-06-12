import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { I18N, LANGUAGES, type LanguageMeta } from './dictionaries'

interface I18nValue {
  lang: string
  languages: LanguageMeta[]
  setLang: (lang: string) => void
  /* Returns the raw dictionary value: a string, or a function for
     interpolated copy. Mirrors the original t() so callers can do
     t('models_loaded')(n) just like before. */
  t: (key: string) => any
}

const I18nContext = createContext<I18nValue | null>(null)

const STORAGE_KEY = 'vt_ui_lang'

function initialLang(): string {
  const saved = localStorage.getItem(STORAGE_KEY)
  return saved && I18N[saved] ? saved : 'en'
}

export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<string>(initialLang)

  const t = useCallback(
    (key: string): any => {
      const dict = I18N[lang] || I18N.en || {}
      const fallback = I18N.en || {}
      return dict[key] ?? fallback[key] ?? key
    },
    [lang],
  )

  const setLang = useCallback((next: string) => {
    const value = I18N[next] ? next : 'en'
    setLangState(value)
    try {
      localStorage.setItem(STORAGE_KEY, value)
    } catch {
      /* ignore */
    }
  }, [])

  useEffect(() => {
    const meta = LANGUAGES.find((l) => l.code === lang) || { htmlLang: lang }
    document.documentElement.lang = meta.htmlLang || lang
    const title = (I18N[lang]?.title as string) || 'AI Transcriber'
    document.title = title
  }, [lang])

  const value = useMemo<I18nValue>(
    () => ({ lang, languages: LANGUAGES, setLang, t }),
    [lang, setLang, t],
  )

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>
}

export function useI18n(): I18nValue {
  const ctx = useContext(I18nContext)
  if (!ctx) throw new Error('useI18n must be used within I18nProvider')
  return ctx
}
