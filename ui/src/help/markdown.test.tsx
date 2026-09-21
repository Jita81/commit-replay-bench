/**
 * markdown.ts — every supported construct renders as elements; nothing renders as raw HTML.
 *
 * Navigation
 * ----------
 * What it is:   Tests for the subset markdown renderer.
 * What it does: Pins each construct (h1–h4 with slug ids, paragraphs, lists, fenced code,
 *               tables, links, emphasis, inline code), the link rewriting rules (a bundled
 *               doc → `/help/docs/…`; external → `rel="noopener noreferrer"`; other relative
 *               links → text) and that an HTML tag in the source is shown as text, never
 *               injected.
 * How:          `renderMarkdown` into a `MemoryRouter`, asserted through the DOM.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/help/markdown.ts, ui/src/help/docs.ts (`slugify`)
 * Tested by:    ui/src/help/markdown.test.tsx
 * Touch when:   a construct is added to the renderer.
 */
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import { plainText, renderMarkdown } from './markdown'

function mount(src: string) {
  return render(<MemoryRouter>{renderMarkdown(src)}</MemoryRouter>)
}

describe('renderMarkdown', () => {
  it('headings h1–h4 carry GitHub slug ids; deeper headings become h4', () => {
    mount('# Operator guide\n## 2. Configure a repository\n### 2.1 Environment setup — the only network phase\n#### 3.0.1 Token\n##### deep')
    expect(screen.getByRole('heading', { level: 1, name: 'Operator guide' })).toHaveAttribute('id', 'operator-guide')
    expect(screen.getByRole('heading', { level: 2 })).toHaveAttribute('id', '2-configure-a-repository')
    expect(screen.getByRole('heading', { level: 3 })).toHaveAttribute('id', '21-environment-setup--the-only-network-phase')
    expect(screen.getAllByRole('heading', { level: 4 }).map((h) => h.id)).toEqual(['301-token', 'deep'])
  })

  it('duplicate headings get -1, -2 suffixes like GitHub', () => {
    mount('## Notes\n## Notes\n## Notes')
    expect(screen.getAllByRole('heading', { level: 2 }).map((h) => h.id)).toEqual(['notes', 'notes-1', 'notes-2'])
  })

  it('paragraphs, emphasis and inline code', () => {
    const { container } = mount('One **strong** and *em* and _also em_ and `code` here.\n\nSecond paragraph.')
    expect(container.querySelectorAll('p')).toHaveLength(2)
    expect(container.querySelector('strong')).toHaveTextContent('strong')
    expect(container.querySelectorAll('em')).toHaveLength(2)
    expect(container.querySelector('code')).toHaveTextContent('code')
  })

  it('bullet and numbered lists, nested by indentation', () => {
    const { container } = mount('- one\n- two\n  - two a\n  - two b\n- three\n\n1. first\n2. second')
    const ul = container.querySelector('ul')!
    expect(ul.children).toHaveLength(3)
    expect(ul.children[1]!.querySelector('ul')!.children).toHaveLength(2)
    expect(container.querySelector('ol')!.children).toHaveLength(2)
  })

  it('fenced code keeps its text verbatim and is not parsed', () => {
    const { container } = mount('```sh\ncrb ledger verify --path x # **not bold**\n```')
    const pre = container.querySelector('pre code')!
    expect(pre).toHaveTextContent('crb ledger verify --path x # **not bold**')
    expect(container.querySelector('strong')).toBeNull()
  })

  it('tables render a header row and body rows inside a keyboard-reachable scroll region, and stay tables', () => {
    mount('| Belt | Meaning |\n|---|---|\n| B1 | tests unmodified |\n| B2 | target green |')
    const table = screen.getByRole('table')
    expect(screen.getAllByRole('columnheader').map((c) => c.textContent)).toEqual(['Belt', 'Meaning'])
    expect(screen.getAllByRole('row')).toHaveLength(3)
    // the overflow lives on a wrapper (WCAG 2.1.1, axe scrollable-region-focusable) — never on
    // the table itself, whose `display` must stay `table` for the row/column semantics
    const region = table.parentElement!
    expect(region).toHaveClass('table-scroll')
    expect(region).toHaveAttribute('tabindex', '0')
    expect(region).toHaveAttribute('aria-label', 'Table: Belt, Meaning')
    expect(region).toHaveAttribute('role', 'region')
  })

  it('a table whose header carries inline markup is named by its plain text', () => {
    mount('| `belt` | **What** it [checks](OPERATOR.md) |\n|---|---|\n| B1 | x |')
    expect(screen.getByRole('region', { name: 'Table: belt, What it checks' })).toBeInTheDocument()
    expect(plainText('a `b` **c** *d* [e](x.md) f')).toBe('a b c d e f')
  })

  it('links: a bundled doc becomes /help/docs/…, an in-page anchor stays, external gets rel, other relatives become text', () => {
    const { container } = mount('[map](OPERATOR.md#4-read-the-capability-map) [same](#1-install) [ext](https://example.org/x) [adr](adr/0003-one-routing-rule.md) [src](../src/crb/core/grade.py)')
    expect(screen.getByRole('link', { name: 'map' })).toHaveAttribute('href', '/help/docs/OPERATOR#4-read-the-capability-map')
    expect(screen.getByRole('link', { name: 'same' })).toHaveAttribute('href', '#1-install')
    const ext = screen.getByRole('link', { name: 'ext' })
    expect(ext).toHaveAttribute('href', 'https://example.org/x')
    expect(ext).toHaveAttribute('rel', 'noopener noreferrer')
    expect(screen.queryByRole('link', { name: 'adr' })).toBeNull()
    expect(container.textContent).toContain(' adr ')
    expect(screen.queryByRole('link', { name: 'src' })).toBeNull()
  })

  it('never injects HTML: a tag in the source is shown as text', () => {
    const { container } = mount('Before <script>alert(1)</script> after <br> and <a href="x">y</a>')
    expect(container.querySelector('script')).toBeNull()
    expect(container.querySelector('br')).toBeNull()
    expect(container.querySelectorAll('a')).toHaveLength(0)
    expect(container.textContent).toContain('<script>alert(1)</script>')
  })

  it('blockquotes and horizontal rules', () => {
    const { container } = mount('> a quoted line\n\n---\n\ntext')
    expect(container.querySelector('blockquote')).toHaveTextContent('a quoted line')
    expect(container.querySelector('hr')).not.toBeNull()
  })
})
