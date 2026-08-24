import { describe, expect, it } from 'vitest'
import { renderMarkdown, splitMarkdownBlocks, stripLeadingTitle } from './markdown'

describe('renderMarkdown', () => {
  it('keeps unordered lists as ul/li so CSS can restore bullets', () => {
    const html = renderMarkdown('Key observations:\n- first point\n- second point')
    expect(html).toContain('<ul>')
    expect(html).toContain('<li>first point</li>')
    expect(html).toContain('<li>second point</li>')
  })
})

describe('stripLeadingTitle', () => {
  it('removes a leading ATX h1 and following blank lines', () => {
    expect(stripLeadingTitle('# Models, Harnesses, and Multi-Agent Systems\n\nContext and Purpose\n\nBody.')).toBe(
      'Context and Purpose\n\nBody.',
    )
  })

  it('leaves ## headings and title-less bodies intact', () => {
    expect(stripLeadingTitle('## Context and Purpose\n\nBody.')).toBe('## Context and Purpose\n\nBody.')
    expect(stripLeadingTitle('Just a paragraph.')).toBe('Just a paragraph.')
  })

  it('returns empty for missing input', () => {
    expect(stripLeadingTitle('')).toBe('')
    expect(stripLeadingTitle(undefined)).toBe('')
    expect(stripLeadingTitle(null)).toBe('')
  })
})

describe('splitMarkdownBlocks', () => {
  it('keeps transcript timestamp blocks separate for progressive rendering', () => {
    expect(splitMarkdownBlocks('**[00:00 - 00:03]**\n\nfirst\n\n**[00:04 - 00:09]**\n\nsecond')).toEqual([
      '**[00:00 - 00:03]**',
      'first',
      '**[00:04 - 00:09]**',
      'second',
    ])
  })
})
