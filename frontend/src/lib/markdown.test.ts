import { describe, it, expect } from 'vitest'
import { renderMarkdown } from './markdown'

describe('renderMarkdown', () => {
  it('returns empty string for nullish input', () => {
    expect(renderMarkdown(undefined)).toBe('')
    expect(renderMarkdown(null)).toBe('')
    expect(renderMarkdown('')).toBe('')
  })

  it('renders headings and paragraphs to HTML', () => {
    const html = renderMarkdown('# Title\n\nbody text')
    expect(html).toContain('<h1')
    expect(html).toContain('Title')
    expect(html).toContain('<p>body text</p>')
  })

  it('renders bold and lists', () => {
    const html = renderMarkdown('**bold**\n\n- one\n- two')
    expect(html).toContain('<strong>bold</strong>')
    expect(html).toContain('<li>one</li>')
    expect(html).toContain('<li>two</li>')
  })

  it('returns a string synchronously (not a Promise)', () => {
    const out = renderMarkdown('plain')
    expect(typeof out).toBe('string')
  })
})
