/**
 * help.ts — the ratchet: every route has help, every anchor resolves, every term exists.
 *
 * Navigation
 * ----------
 * What it is:   The help registry's ratchet test.
 * What it does: Pins that (1) every path in the app's route table — `/login`, the help
 *               pages and `*` included — has a `helpFor()` hit that is its OWN entry, and the
 *               catch-all is declared once and last (G-926); (2) every
 *               `readMore.to` and every term's `readMore` names a bundled guide and, when it
 *               carries a slug, a heading in that file slugifies to it; (3) every `terms[]` id
 *               is in `TERMS`; (4) copy lint — purpose / next / numbers use "cell",
 *               "apparatus", "belt", "Wilson", "false-Q1" or "oracle" only when that term is
 *               in the screen's `terms[]`; every string is plain (no exclamation mark) and
 *               `next.viewer` always exists; (5) the /learn About block says the product
 *               decides nothing on its own, in the words its DoD criteria cite; (6) no About
 *               block states a policy threshold as a number — in symbols (`≥ 0.80`, `>= 10`,
 *               `n = 10`), in words (`at least 10`) or as the rule's own values — every
 *               threshold is the served policy's, which a deployment may tighten, so the
 *               copy points at the card that shows it (G-255, G-204); the matcher is pinned
 *               on its own strings, and the one non-policy number (the password floor) is on
 *               a list that only shrinks; (7) every About block with a non-goal criterion
 *               says what its page does not do — the Ledger's (no verify on demand, no
 *               repair, filters only what the URL carries, G-185), the Operate journey's on
 *               Runs and Deployment (no deployment-wide budget, no dashboard, no doctor
 *               screen, G-402) — the Operate path is named on its stops (G-396), and "Verify
 *               proves", which read as a button that is not there, is gone.
 * How:          Reads `ui/src/App.tsx` and the nine guides as `?raw` text so the ratchet
 *               needs no React; `matchPath` through `helpFor`.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/help/help.ts, ui/src/App.tsx (the route table it reads),
 *               ui/src/help/glossary.ts, ui/src/help/docs.ts (`slugify`, `isDocName`)
 * Tested by:    ui/src/help/help.test.ts
 * Touch when:   never for a new repository; a screen is added — it needs a `HELP` entry before this
 *               passes.
 */
import { describe, expect, it } from 'vitest'
import appSource from '../App.tsx?raw'
import { docPath, isDocName, slugify, type DocAnchor } from './docs'
import { TERMS, type TermId } from './glossary'
import { HELP, OPERATE_NON_GOALS, OPERATE_PATH, helpFor } from './help'

/** The guides' text, eagerly, keyed by file name — the same files ui/src/help/docs.ts bundles. */
const DOC_TEXT = import.meta.glob(['../../../docs/{ONBOARDING-A-REPO,OPERATOR,EVIDENCE-AND-CLAIMS,GITHUB-APP,SECURITY,DATA-RETENTION,LEARNING-LOOP,DEPLOYMENT}.md', '../../../docs/reviews/human-review-guide.md'], { query: '?raw', import: 'default', eager: true }) as Record<string, string>

/** Every `<Route path="…">` in App.tsx, read from the source so the ratchet cannot drift from the table. */
function appRoutePaths(): string[] {
  return Array.from(appSource.matchAll(/<Route\s+path="([^"]+)"/g), (m: RegExpMatchArray) => m[1]!)
}

/** A concrete pathname for a react-router pattern (`/runs/:id` → `/runs/x`). */
function concrete(pattern: string): string {
  return pattern.replace(/:[A-Za-z]+/g, 'x')
}

/** The heading slugs of a bundled doc, with GitHub's -1/-2 suffixes for duplicates. */
function headingSlugs(name: string): Set<string> {
  const text = DOC_TEXT[`../../../docs/${isDocName(name) ? docPath(name) : name}.md`] ?? ''
  const seen = new Map<string, number>()
  const out = new Set<string>()
  let fence = false
  for (const line of text.split('\n')) {
    if (/^```/.test(line)) {
      fence = !fence
      continue
    }
    if (fence) continue
    const m = /^#{1,6}\s+(.*?)\s*#*$/.exec(line)
    if (!m) continue
    const base = slugify(m[1]!)
    const n = seen.get(base) ?? 0
    seen.set(base, n + 1)
    out.add(n === 0 ? base : `${base}-${n}`)
  }
  return out
}

function expectAnchorResolves(anchor: DocAnchor, where: string): void {
  const [name, slug] = anchor.split('#')
  expect(isDocName(name ?? ''), `${where}: ${anchor} is not a bundled guide`).toBe(true)
  if (slug) expect(headingSlugs(name!).has(slug), `${where}: no heading in docs/${name}.md slugifies to #${slug}`).toBe(true)
}

/** Word → the term id that must be in `terms[]` when the word appears in copy. */
const LINT: Array<[RegExp, TermId]> = [
  [/\bcells?\b/i, 'cell'],
  [/\bapparatus\b/i, 'apparatus'],
  [/\bbelts?\b/i, 'belt'],
  [/\bWilson\b/, 'wilson'],
  [/false-Q1/, 'false_q1'],
  [/\boracle\b/i, 'oracle_strength'],
]

describe('HELP ratchet', () => {
  it('every route in App.tsx has an entry of its own — /login, the help pages and the catch-all included', () => {
    const paths = appRoutePaths()
    expect(paths.length).toBeGreaterThan(20)
    for (const p of paths) {
      // the catch-all answers for any address the table does not route
      const pathname = p === '*' ? '/nowhere/at/all' : concrete(p)
      // its OWN entry, never the catch-all's: a route that fell through to `*` would show the
      // 404's help on a real screen, so "has an entry" alone would pass and prove nothing
      expect(helpFor(pathname)?.route, `no HELP entry of its own for ${p}`).toBe(p)
    }
  })

  it('the catch-all is declared once and last, so it never answers for a routed screen', () => {
    expect(HELP.filter((h) => h.route === '*')).toHaveLength(1)
    expect(HELP.at(-1)?.route).toBe('*')
    expect(helpFor('/nowhere')?.route).toBe('*')
    expect(helpFor('/home')?.route).toBe('/home')
  })

  it('helpFor matches in declaration order and returns the most specific declared entry', () => {
    expect(helpFor('/connect/cobra/measure')?.route).toBe('/connect/:name/measure')
    expect(helpFor('/connect/cobra')?.route).toBe('/connect/:name')
    expect(helpFor('/connect')?.route).toBe('/connect')
    expect(helpFor('/runs/abc')?.route).toBe('/runs/:id')
  })

  it('every readMore anchor (screens and terms) names a bundled guide and a real heading', () => {
    for (const h of HELP) {
      expect(h.readMore.length, `${h.route}: readMore is empty`).toBeGreaterThan(0)
      for (const r of h.readMore) {
        expect(r.label.trim().length, `${h.route}: readMore label`).toBeGreaterThan(0)
        expectAnchorResolves(r.to, h.route)
      }
    }
    for (const [id, t] of Object.entries(TERMS)) {
      if (t.readMore) expectAnchorResolves(t.readMore, `term ${id}`)
    }
  })

  it('every terms[] id exists and is not repeated', () => {
    for (const h of HELP) {
      const ids = h.terms ?? []
      for (const id of ids) expect(TERMS[id], `${h.route}: unknown term ${id}`).toBeDefined()
      expect(new Set(ids).size, `${h.route}: repeated term`).toBe(ids.length)
    }
  })

  it('the /learn About block names the register and the three reports and says the product decides nothing on its own', () => {
    const learn = helpFor('/learn')!
    expect(learn.purpose).toContain('the prevention register lists every bug class')
    expect(learn.purpose).toMatch(/three reports list refusals .* weak oracles .* evidence that has gone stale/)
    expect(learn.purpose).toContain('The product decides nothing on its own: the register acts only under an operator’s switch, and each report’s decision is made here by an operator and recorded with their name.')
  })

  // G-548 — the stream starts at the board: the About blocks say so in the same terms as the
  // page head and Home's task 8, so the page's own explanation never contradicts its head
  it('the /factory and /home About blocks say work enters from the board through intake, beside the frozen backlog (G-548)', () => {
    const factory = helpFor('/factory')!
    expect(factory.purpose).toContain('Work enters from your board through intake')
    expect(factory.purpose).toContain('a ticket in the watched column becomes a frozen backlog item')
    expect(factory.next.operator).toContain('Switch the listener on, or freeze a backlog here, then Run the factory')
    const home = helpFor('/home')!
    expect(home.next.operator).toContain('Task 8 starts at your board')
  })

  it('the /signoff About block links the Step 6 human-review guide and says where the read of a diff is recorded (G-481)', () => {
    const h = helpFor('/signoff')!
    expect(h.readMore.map((r) => r.to)).toContain('HUMAN-REVIEW-GUIDE')
    expect(h.next.approver).toContain('run’s Review panel')
  })

  it('every About block with a non-goal criterion says what its page does not do', () => {
    // the Ledger (G-185): what the server does and what the page does not, and where an operator verifies
    const ledger = helpFor('/ledger')!
    expect(ledger.purpose).toContain('The server re-checks the chain on every load. If rows are removed from the end, only comparing with a head hash you recorded earlier shows it.')
    expect(ledger.purpose).toContain('The page does not verify on demand, repair a chain or filter beyond what the URL carries — each as a control on the page or, where it has none, a chip; verify an export with crb ledger verify (and the store itself with --store).')
    expect(ledger.purpose).not.toContain('each shown as a chip')
    // the Operate journey (G-402): its non-goals where the person is — Runs and Deployment
    expect(OPERATE_NON_GOALS).toContain('No budget spans a deployment or a repository: every limit belongs to one run.')
    expect(OPERATE_NON_GOALS).toContain('There is no metrics dashboard and no view of the platform’s own logs (a run page streams that run’s log), and no crb doctor screen.')
    for (const route of ['/runs', '/posture']) expect(helpFor(route)!.purpose, route).toContain(OPERATE_NON_GOALS)
    // the path itself is named on its stops (G-396)
    expect(OPERATE_PATH).toBe('One stop on the Operate path: health → Runs → Ledger → Settings.')
    for (const route of ['/runs', '/ledger']) expect(helpFor(route)!.purpose, route).toContain(OPERATE_PATH)
    // "Verify proves …" read as a button that is not there: the server verifies on read
    for (const h of HELP) {
      for (const s of [h.purpose, ...Object.values(h.next), h.numbers ?? '']) expect(s, h.route).not.toContain('Verify proves')
    }
  })

  it('copy lint: a term word appears only when the term is on the screen; plain English throughout', () => {
    for (const h of HELP) {
      const strings = [h.purpose, ...Object.values(h.next), h.numbers ?? '']
      expect(h.next.viewer.trim().length, `${h.route}: next.viewer`).toBeGreaterThan(0)
      for (const s of strings) {
        expect(s, `${h.route}: exclamation mark`).not.toMatch(/!/)
        expect(s.split(/(?<=[.?])\s+(?=[A-Z"])/).length, `${h.route}: more than 6 sentences: ${s}`).toBeLessThanOrEqual(6)
        for (const [re, id] of LINT) {
          if (re.test(s)) expect(h.terms ?? [], `${h.route}: uses "${re.source}" without term ${id}: ${s}`).toContain(id)
        }
      }
    }
  })

  it('no About block states a policy threshold as a number: the served policy may be tightened, and the copy would drift (G-255, G-204)', () => {
    for (const h of HELP) {
      for (const s of [h.purpose, ...Object.values(h.next), h.numbers ?? '']) {
        const rest = NOT_A_POLICY_THRESHOLD.filter((x) => x.route === h.route).reduce((acc, x) => acc.replace(x.phrase, ''), s)
        expect(statesAThreshold(rest), `${h.route}: a hard-coded threshold: ${s}`).toBe(false)
      }
    }
    // the list only shrinks: a phrase no longer in its block is removed from it
    for (const x of NOT_A_POLICY_THRESHOLD) {
      const h = helpFor(x.route)!
      expect([h.purpose, ...Object.values(h.next), h.numbers ?? ''].join(' '), x.phrase).toContain(x.phrase)
    }
    expect(helpFor('/routing')!.numbers).toContain('the ones on the Policy in force card')
  })

  it('the threshold matcher finds a threshold however it is written, and passes a number that is not one', () => {
    for (const s of [
      'n ≥ 10',
      'strong ≥ 0.80',
      'n >= 10',
      'point <= 0.9',
      'Wilson lower > 0.8',
      'n at least 10, point at least 0.90',
      'a Wilson lower bound of at least 0.80',
      'at most 0 escapes',
      'no less than 0.8',
      'no fewer than 10 attempts',
      'not below 0.9',
      'n = 10',
      'n=10',
      'a minimum of 10',
      'the oracle floor is 0.80',
      'a point of 0.9',
      'half (0.5) constructed',
    ]) {
      expect(statesAThreshold(s), s).toBe(true)
    }
    for (const s of [
      'the bracket is the 95 % Wilson interval',
      'point = clean / n',
      'Route counts are cells, not attempts.',
      'fQ1 is the false-Q1 count and must be 0',
      'the least n, point and Wilson lower bound',
      'one cell per class and size',
      '375 px',
    ]) {
      expect(statesAThreshold(s), s).toBe(false)
    }
  })
})

/**
 * Numbers an About block states that are not a routing or adequacy policy value, each with where
 * it is pinned to the server instead. Only shrinks.
 */
const NOT_A_POLICY_THRESHOLD: ReadonlyArray<{ route: string; phrase: string; why: string }> = [
  {
    route: '/settings',
    phrase: 'at least 12 characters',
    why: 'the password floor (MIN_PASSWORD_LENGTH), a server constant no deployment policy tightens; the hints that state it are pinned to it by tests/test_server_auth.py::test_the_recovery_hints_state_the_numbers_the_server_enforces',
  },
]

/**
 * True when copy states a policy threshold as a number, in any of the ways it is written: a
 * comparator before a number (`≥ 0.80`, `>= 10`, `n = 10`), a worded one (`at least 10`, `no
 * less than 0.8`, `a minimum of 10`), or one of the published rule's values themselves (ADR-0003:
 * 0.80, 0.90 and the controls' half, in any decimal spelling) standing as a number.
 */
function statesAThreshold(s: string): boolean {
  const comparator = /(?:[≥≤]|[<>]=?|=>|=<)\s*\d/
  const nEquals = /\bn\s*=\s*\d/
  const worded = /\b(?:at least|at most|no less than|no more than|no fewer than|not less than|not below|not above|a minimum of|a maximum of)\s+\d/i
  const ruleValue = /(?<![\d.])0?\.(?:80?|90?|50?)(?![\d])/
  return comparator.test(s) || nEquals.test(s) || worded.test(s) || ruleValue.test(s)
}
