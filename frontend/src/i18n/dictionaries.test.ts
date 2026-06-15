import { describe, it, expect } from 'vitest'
import { I18N, LANGUAGES } from './dictionaries'

const LANG_CODES = ['en', 'zh', 'ja', 'ko'] as const

describe('i18n dictionaries', () => {
  it('exposes all four languages', () => {
    expect(Object.keys(I18N).sort()).toEqual([...LANG_CODES].sort())
    expect(LANGUAGES.map((l) => l.code).sort()).toEqual([...LANG_CODES].sort())
  })

  it('every language has the same set of keys as English (no missing/extra copy)', () => {
    const enKeys = new Set(Object.keys(I18N.en))
    for (const code of LANG_CODES) {
      const keys = new Set(Object.keys(I18N[code]))
      const missing = [...enKeys].filter((k) => !keys.has(k))
      const extra = [...keys].filter((k) => !enKeys.has(k))
      expect({ code, missing, extra }).toEqual({ code, missing: [], extra: [] })
    }
  })

  it('matches the value type (string vs function) across languages for each key', () => {
    for (const key of Object.keys(I18N.en)) {
      const enType = typeof I18N.en[key]
      for (const code of LANG_CODES) {
        expect(`${code}.${key}:${typeof I18N[code][key]}`).toBe(`${code}.${key}:${enType}`)
      }
    }
  })

  it('has no empty string values', () => {
    for (const code of LANG_CODES) {
      for (const [key, val] of Object.entries(I18N[code])) {
        if (typeof val === 'string') {
          expect(val.length, `${code}.${key} should not be empty`).toBeGreaterThan(0)
        }
      }
    }
  })
})
