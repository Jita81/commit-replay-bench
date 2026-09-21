/**
 * A subset markdown renderer for the bundled guides — React elements, never raw HTML.
 *
 * Supported: headings h1–h4 (deeper ones render as h4) with GitHub slug ids, paragraphs,
 * bullet and numbered lists (nested by indentation), fenced code, tables, blockquotes,
 * horizontal rules, links, emphasis, strong and inline code. Anything else — an HTML tag,
 * an image, a footnote — is shown as the text it is. Links: another bundled guide becomes an
 * in-app link to /help/docs/…; an in-page `#anchor` stays; `http(s)` gets
 * `rel="noopener noreferrer"`; any other relative path (an ADR, a source file) renders as
 * text because the UI has no target for it.
 *
 * Navigation
 * ----------
 * What it is:   `renderMarkdown(src)` — the guides' renderer — and `parseMarkdown(src)`, its block parser.
 * What it does: Turns a guide's markdown into React elements through `createElement`, so
 *               nothing in a document can inject markup; gives every heading the id
 *               `slugify()` produces (with GitHub's `-1`, `-2` suffixes for repeats) so the
 *               docs' own `#anchors` and the screens' `readMore` links resolve.
 * How:          A line-based block parser (`parseMarkdown`) then a small inline tokeniser for
 *               code / strong / em / links, both pure; no dependency (the UI has no kit by
 *               design).
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/screens/Help/DocPage.tsx (the only caller), ui/src/help/docs.ts
 *               (`slugify`, `isDocName`, `docHref` for the link rewrite), ui/src/help/help.ts
 *               (the `readMore` anchors whose slugs the headings rendered here must satisfy)
 * Tested by:    ui/src/help/markdown.test.tsx
 * Touch when:   a guide uses a construct this does not render (add it here with a test);
 *               never for a new repository.
 */
import { createElement, Fragment, type ReactNode } from 'react'
import { Link } from 'react-router'
import { docHref, isDocName, slugify } from './docs'

export type Block =
  | { kind: 'heading'; level: number; text: string }
  | { kind: 'paragraph'; text: string }
  | { kind: 'code'; lang: string; text: string }
  | { kind: 'list'; ordered: boolean; items: ListItem[] }
  | { kind: 'table'; header: string[]; rows: string[][] }
  | { kind: 'quote'; text: string }
  | { kind: 'rule' }

export interface ListItem {
  text: string
  children?: Block[]
}

const LIST_RE = /^(\s*)([-*+]|\d+[.)])\s+(.*)$/
const HEADING_RE = /^(#{1,6})\s+(.*?)\s*#*$/
const TABLE_SEP_RE = /^\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$/

function isBlank(line: string): boolean {
  return line.trim() === ''
}

function splitRow(line: string): string[] {
  const trimmed = line.trim().replace(/^\|/, '').replace(/\|$/, '')
  return trimmed.split(/(?<!\\)\|/).map((c) => c.trim())
}

/** Parse markdown into blocks; `lines` may be a slice (list item bodies are parsed recursively). */
export function parseMarkdown(src: string): Block[] {
  return parseLines(src.replace(/\r\n?/g, '\n').split('\n'))
}

function parseLines(lines: string[]): Block[] {
  const out: Block[] = []
  let i = 0
  while (i < lines.length) {
    const line = lines[i]!
    if (isBlank(line)) {
      i += 1
      continue
    }
    // fenced code
    const fence = /^\s*(```|~~~)\s*([\w-]*)\s*$/.exec(line)
    if (fence) {
      const close = fence[1]!
      const body: string[] = []
      i += 1
      while (i < lines.length && !lines[i]!.trim().startsWith(close)) {
        body.push(lines[i]!)
        i += 1
      }
      i += 1 // the closing fence (or end of input)
      out.push({ kind: 'code', lang: fence[2] ?? '', text: body.join('\n') })
      continue
    }
    const heading = HEADING_RE.exec(line)
    if (heading) {
      out.push({ kind: 'heading', level: heading[1]!.length, text: heading[2]! })
      i += 1
      continue
    }
    if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(line)) {
      out.push({ kind: 'rule' })
      i += 1
      continue
    }
    if (line.trim().startsWith('|') && i + 1 < lines.length && TABLE_SEP_RE.test(lines[i + 1]!)) {
      const header = splitRow(line)
      const rows: string[][] = []
      i += 2
      while (i < lines.length && lines[i]!.trim().startsWith('|')) {
        rows.push(splitRow(lines[i]!))
        i += 1
      }
      out.push({ kind: 'table', header, rows })
      continue
    }
    if (/^\s*>/.test(line)) {
      const body: string[] = []
      while (i < lines.length && /^\s*>/.test(lines[i]!)) {
        body.push(lines[i]!.replace(/^\s*>\s?/, ''))
        i += 1
      }
      out.push({ kind: 'quote', text: body.join(' ') })
      continue
    }
    const list = LIST_RE.exec(line)
    if (list) {
      const [block, next] = parseList(lines, i, list[1]!.length)
      out.push(block)
      i = next
      continue
    }
    // paragraph: until a blank line or the start of another block
    const body: string[] = []
    while (i < lines.length && !isBlank(lines[i]!) && !startsBlock(lines[i]!)) {
      body.push(lines[i]!.trim())
      i += 1
    }
    if (body.length === 0) {
      // a line that starts a block we did not consume (defensive): show it as text
      body.push(lines[i]!.trim())
      i += 1
    }
    out.push({ kind: 'paragraph', text: body.join(' ') })
  }
  return out
}

function startsBlock(line: string): boolean {
  return HEADING_RE.test(line) || /^\s*(```|~~~)/.test(line) || LIST_RE.test(line) || /^\s*>/.test(line) || line.trim().startsWith('|')
}

/** A list at `indent`: items at that indent, deeper lines become the item's nested blocks. */
function parseList(lines: string[], start: number, indent: number): [Block, number] {
  const items: ListItem[] = []
  let ordered = false
  let i = start
  while (i < lines.length) {
    const m = LIST_RE.exec(lines[i]!)
    if (!m || m[1]!.length !== indent) break
    if (items.length === 0) ordered = /\d/.test(m[2]!)
    else if (/\d/.test(m[2]!) !== ordered) break // a numbered list after bullets is a new list
    const text: string[] = [m[3]!]
    const nested: string[] = []
    i += 1
    // continuation: deeper-indented lines belong to this item (a nested list or wrapped text)
    while (i < lines.length) {
      const l = lines[i]!
      if (isBlank(l)) {
        // a blank line ends the item unless the next non-blank line is still deeper
        const after = lines[i + 1]
        if (after !== undefined && !isBlank(after) && leadingSpaces(after) > indent) {
          nested.push('')
          i += 1
          continue
        }
        break
      }
      if (leadingSpaces(l) > indent) {
        if (LIST_RE.test(l)) nested.push(l)
        else if (nested.length > 0) nested.push(l)
        else text.push(l.trim())
        i += 1
        continue
      }
      break
    }
    const item: ListItem = { text: text.join(' ') }
    if (nested.some((l) => !isBlank(l))) {
      const childIndent = Math.min(...nested.filter((l) => !isBlank(l)).map(leadingSpaces))
      item.children = parseLines(nested.map((l) => l.slice(Math.min(childIndent, leadingSpaces(l)))))
    }
    items.push(item)
    // skip blank lines between items of the same list
    while (i < lines.length && isBlank(lines[i]!) && i + 1 < lines.length) {
      const nx = LIST_RE.exec(lines[i + 1]!)
      if (!nx || nx[1]!.length !== indent || /\d/.test(nx[2]!) !== ordered) break
      i += 1
    }
  }
  return [{ kind: 'list', ordered, items }, i]
}

function leadingSpaces(line: string): number {
  return /^\s*/.exec(line)![0].length
}

// ---------------------------------------------------------------------------
// Inline
// ---------------------------------------------------------------------------

const INLINE_RE = /(`[^`]+`)|(\*\*[^*]+\*\*)|(\*[^*\s][^*]*\*)|((?<![\p{L}\p{N}])_[^_]+_(?![\p{L}\p{N}]))|(\[[^\]]*\]\([^)\s]+\))/u

/** Inline markdown → nodes; every piece of text stays text (no HTML is ever parsed). */
export function renderInline(text: string, keyPrefix = ''): ReactNode[] {
  const out: ReactNode[] = []
  let rest = text
  let k = 0
  while (rest.length > 0) {
    const m = INLINE_RE.exec(rest)
    if (!m || m.index === undefined) {
      out.push(rest)
      break
    }
    if (m.index > 0) out.push(rest.slice(0, m.index))
    const key = `${keyPrefix}${k++}`
    const tok = m[0]
    if (m[1]) out.push(createElement('code', { key }, tok.slice(1, -1)))
    else if (m[2]) out.push(createElement('strong', { key }, ...renderInline(tok.slice(2, -2), `${key}.`)))
    else if (m[3] || m[4]) out.push(createElement('em', { key }, ...renderInline(tok.slice(1, -1), `${key}.`)))
    else if (m[5]) {
      const link = /^\[([^\]]*)\]\(([^)\s]+)\)$/.exec(tok)!
      out.push(renderLink(link[1]!, link[2]!, key))
    }
    rest = rest.slice(m.index + tok.length)
  }
  return out
}

function renderLink(label: string, href: string, key: string): ReactNode {
  const children = renderInline(label, `${key}.`)
  if (/^https?:\/\//i.test(href)) return createElement('a', { key, href, rel: 'noopener noreferrer' }, ...children)
  if (href.startsWith('#')) return createElement('a', { key, href }, ...children)
  const doc = /^(?:\.\/)?([A-Za-z0-9-]+)\.md(#[^#]*)?$/.exec(href)
  if (doc && isDocName(doc[1]!)) {
    const slug = doc[2] ? doc[2].slice(1) : ''
    const to = docHref(slug ? `${doc[1]}#${slug}` : doc[1]!)
    return createElement(Link, { key, to }, ...children)
  }
  // an ADR, a source path, an image: the UI has no target, so the label is shown as text
  return createElement(Fragment, { key }, ...children)
}

// ---------------------------------------------------------------------------
// Blocks → elements
// ---------------------------------------------------------------------------

class Slugs {
  private seen = new Map<string, number>()
  next(text: string): string {
    const base = slugify(text)
    const n = this.seen.get(base) ?? 0
    this.seen.set(base, n + 1)
    return n === 0 ? base : `${base}-${n}`
  }
}

function renderBlocks(blocks: Block[], slugs: Slugs, keyPrefix: string): ReactNode[] {
  return blocks.map((b, i) => {
    const key = `${keyPrefix}${i}`
    switch (b.kind) {
      case 'heading': {
        const level = Math.min(b.level, 4)
        return createElement(`h${level}`, { key, id: slugs.next(b.text) }, ...renderInline(b.text, `${key}.`))
      }
      case 'paragraph':
        return createElement('p', { key }, ...renderInline(b.text, `${key}.`))
      case 'code':
        return createElement('pre', { key }, createElement('code', b.lang ? { 'data-lang': b.lang } : {}, b.text))
      case 'quote':
        return createElement('blockquote', { key }, ...renderInline(b.text, `${key}.`))
      case 'rule':
        return createElement('hr', { key })
      case 'table':
        return createElement(
          'table',
          { key },
          createElement('thead', {}, createElement('tr', {}, ...b.header.map((h, j) => createElement('th', { key: j, scope: 'col' }, ...renderInline(h, `${key}.h${j}.`))))),
          createElement(
            'tbody',
            {},
            ...b.rows.map((r, ri) => createElement('tr', { key: ri }, ...r.map((c, ci) => createElement('td', { key: ci }, ...renderInline(c, `${key}.${ri}.${ci}.`))))),
          ),
        )
      case 'list':
        return createElement(
          b.ordered ? 'ol' : 'ul',
          { key },
          ...b.items.map((it, j) =>
            createElement('li', { key: j }, ...renderInline(it.text, `${key}.${j}.`), ...(it.children ? renderBlocks(it.children, slugs, `${key}.${j}.c`) : [])),
          ),
        )
    }
  })
}

/** The guide as React elements; heading ids are unique within one call. */
export function renderMarkdown(src: string): ReactNode {
  return createElement(Fragment, {}, ...renderBlocks(parseMarkdown(src), new Slugs(), 'b'))
}
