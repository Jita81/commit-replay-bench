/**
 * The hint ratchet — every element a reader meets carries a hint, on every enforced route,
 * in the shell and in every shared component; native `title=` only where allowed.
 *
 * Navigation
 * ----------
 * What it is:   The ratchet for the hint layer: the collector, the per-route table read
 *               against App.tsx, the ALLOWLIST of routes not yet enforced (empty since the
 *               shippable wave), the shell and shared-component checks, and the `title=`
 *               allowlist.
 * What it does: (1) Reads every `<Route path>` in App.tsx: each screen route must be either
 *               an entry in `SCREENS` (enforced: rendered per role under its fixtures, every
 *               element resolved to a registry id, at least `MIN_HINTS[route]` hinted
 *               elements) or in `ALLOWLIST` (not yet wired) — never both, never neither.
 *               (2) The shell is enforced from the start: every nav link, the health pill,
 *               the role chip, Help, the theme toggle, Sign out, the footer and the
 *               stop-condition banner. (3) Every shared component is enforced: a route,
 *               belt, provenance, controls, failure-kind, model-point, tier, band, gate,
 *               run-status pill, the interval bar, a journey eyebrow, and a StatTile, Tag,
 *               DataTable column, button, field, gate criterion, summary row, task item and
 *               count eyebrow given a hint all carry `data-hint`; a StatTile without one is
 *               reported by the collector, so the collector itself is proved. (4) Native `title=` on an
 *               element (or a component that spreads onto one) is counted per file and may
 *               not exceed `TITLE_ALLOWLIST` — the count only goes down. (5) No orphan: every
 *               registered id is written as a literal by some source, except `SHARED_IDS`
 *               and the derived `tab.repo.*` family — dead copy fails. (6) A fixture's pool
 *               answer agrees with its fixture repository: no clone path, no history share.
 * How:          `renderApp` / `mockApi` from ui/src/test/utils.tsx; the shell through a
 *               layout route; `unhinted(container)` (ui/src/help/hints-collector.ts, re-exported
 *               here) walks the selectors the mechanism names and describes each miss
 *               (`<th> 'Wilson lower' in table 'Route decisions'`); sources read with
 *               `import.meta.glob(…, { query: '?raw' })`.
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/help/hints.ts (`HINTS`, `MIN_HINTS`, `SHARED_IDS`),
 *               ui/src/help/hints-collector.ts (`unhinted`),
 *               ui/src/help/hints-ratchet.onramp.tsx (the on-ramp routes' entries and
 *               fixtures), ui/src/help/hints-ratchet.shell.tsx (`SHELL_SCREENS`: /login,
 *               /help, /help/docs/:name and the catch-all — the four the ratchet used to
 *               skip by name), ui/src/help/hints-ratchet.instrument.tsx (`INSTRUMENT_SCREENS`
 *               and `INSTRUMENT_VARIANTS`: the factory, deployment and instrument routes'
 *               entries and their deeper states — tabs, dialogs, the evidence drawer),
 *               ui/src/components/Hint.tsx (the `data-hint` the collector looks for),
 *               ui/src/App.tsx (the route table), ui/src/components/Layout.tsx (the shell),
 *               ui/src/test/utils.tsx (`renderApp`, `mockApi`, `PRINCIPAL`)
 * Tested by:    ui/src/help/hints-ratchet.test.tsx
 * Touch when:   a screen is added — it needs a `SCREENS` entry (in the on-ramp or instrument
 *               sidecar) with its fixtures and roles before this passes; a `title=` is
 *               retired — lower its file's count; a route is put on `ALLOWLIST` — say why.
 */
import { render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactElement } from 'react'
import { MemoryRouter, Route, Routes } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import appSource from '../App.tsx?raw'
import type { Role } from '../api/types'
import { BeltPills } from '../components/BeltPills'
import { Button, LinkButton } from '../components/Button'
import { Card } from '../components/Card'
import { CiBar } from '../components/CiBar'
import { DataTable } from '../components/DataTable'
import { InlineSelect, SelectField, TextArea, TextField } from '../components/Field'
import { GateBanner } from '../components/GateBanner'
import { Layout } from '../components/Layout'
import { PageHeader } from '../components/PageHeader'
import { Pill } from '../components/Pill'
import { Provenance } from '../components/Provenance'
import { StatTile } from '../components/StatTile'
import { VerdictPill } from '../components/VerdictPill'
import { StartButton, SummaryList, Tag, TaskList, WarningButton } from '../components/govuk'
import { AuthProvider } from '../lib/auth'
import { ControlsPill, FailureSplitPills, ModelPointLine } from '../screens/Capability/FailureSplit'
import { PRINCIPAL, mockApi, renderApp } from '../test/utils'
import { unhinted } from './hints-collector'
import { INSTRUMENT_SCREENS, INSTRUMENT_VARIANTS } from './hints-ratchet.instrument'
import { ONRAMP_SCREENS } from './hints-ratchet.onramp'
import { SHELL_SCREENS } from './hints-ratchet.shell'
import { HINTS, MIN_HINTS, SHARED_IDS } from './hints'

// ─── the per-route table ──────────────────────────────────────────────────────────────────

/** One enforced route: rendered per role under its fixtures; every element must resolve to a registry id. */
interface ScreenEntry {
  /** The initial URL (query string included). */
  route: string
  /** The route pattern the screen mounts at (App.tsx's string). */
  path: string
  element: ReactElement
  /** The `mockApi` table the screen needs to render its data (never an empty or not-found state). */
  api: Record<string, unknown>
  /** The roles that change what renders (`can()` branches). */
  roles: Role[]
}

/**
 * Enforced routes, keyed by App.tsx pattern. A stream that wires a screen adds its entry here
 * and removes the pattern from `ALLOWLIST`; the `minHints` floor comes from `MIN_HINTS`.
 *
 * Example:
 *   '/results': { route: '/results?repo=r', path: '/results', element: <ResultsPage />, api: RESULTS_API, roles: ['viewer', 'approver'] },
 */
const SCREENS: Record<string, ScreenEntry> = { ...ONRAMP_SCREENS, ...INSTRUMENT_SCREENS, ...SHELL_SCREENS }

/**
 * Routes not yet wired. Empty since the shippable wave: every route the shell serves is in
 * `SCREENS` and enforced. A route added here has no `SCREENS` entry — and a reviewer asks why.
 */
const ALLOWLIST: readonly string[] = []

// ─── the collector ────────────────────────────────────────────────────────────────────────

/** `unhinted(root)` lives in hints-collector.ts so a screen test can import it without this suite; re-exported for the contract. */
export { unhinted }

/** The count of hinted elements in `root`. */
function hinted(root: ParentNode): number {
  return root.querySelectorAll('[data-hint]').length
}

// ─── the title= allowlist ─────────────────────────────────────────────────────────────────

/**
 * Native `title=` per file (a hover-only attribute nothing on touch or a keyboard can reach):
 * the maximum each file may carry. The count only ever goes down, and it is now zero —
 * G-906 retired the last six and G-287 the seventh (`/learn`'s strengthening table put the
 * item's description on its id; it is a second line under the id now). The full value of a
 * shortened id or hash is the element's accessible text (`ui/src/components/ShortId.tsx`), a
 * truncated string is already whole in the DOM, or the value was made visible (the evidence
 * pack's argv), so hover is never the only way to read anything (DL-048). An entry added here
 * is a regression: explain the copy some other way instead.
 */
const TITLE_ALLOWLIST: Record<string, number> = {}

/**
 * A `title=` on a native element, or on a component that spreads its props onto one (`Hint`
 * included: `<Hint as="button" … title=>` renders the attribute). An arrow-function prop
 * (`onClick={() => …}`) inside the tag does not end the match.
 *
 * `Link` and `NavLink` are react-router's, and they spread onto an `<a>`, so a `title=` on one
 * is as hover-only as a `title=` on an anchor. They were missing from this list until G-906
 * emptied the allowlist and three `<Link title={fullId}>{shortId(…)}</Link>` cells — two on
 * Oracle, one on Runs — turned out to be escaping the gate: the very pattern `ShortId`
 * replaced everywhere else. A component that takes `title` as COPY rather than as an
 * attribute (`Card`, `EmptyState`, `ErrorState`, `PageHeader`, `Section`, `Dialog`) is not
 * listed and must not be — it renders a heading, not a tooltip.
 */
const TITLE_RE = /<(?:a|abbr|button|code|div|img|input|li|p|span|svg|td|th|tr|time|strong|small|em|label|select|textarea|pre|dd|dt|h[1-6]|Button|LinkButton|AnchorButton|Link|NavLink|Pill|Tag|Hint)\b(?:[^>]|=>)*?\btitle=/g

const SOURCES = import.meta.glob(['../components/**/*.tsx', '../screens/**/*.tsx', '!**/*.test.tsx'], { query: '?raw', import: 'default', eager: true }) as Record<string, string>

/** Every non-test source a hint id may be referenced from (the registry and this suite excluded). */
const ALL_SOURCES = import.meta.glob(['../components/**/*.{ts,tsx}', '../screens/**/*.{ts,tsx}', '../lib/**/*.{ts,tsx}', '../App.tsx', '!**/*.test.{ts,tsx}'], { query: '?raw', import: 'default', eager: true }) as Record<string, string>

/** Id families a component derives from its data (`tab.repo.${t.id}`): exempt from the literal scan along with `SHARED_IDS`. */
const DERIVED_FAMILIES = ['tab.repo.']

// ─── the shell ────────────────────────────────────────────────────────────────────────────

function renderShell(role: Role, falseQ1 = 0) {
  mockApi({
    'GET /auth/me': { ...PRINCIPAL, role },
    'GET /health': { status: 'ok', probes: [{ name: 'ledger', status: 'ok', data: { false_q1: falseQ1 } }] },
    'GET /version': { crb: '2.0.0a1', apparatus: '2.2', policy: 'routing.v1', oidc_enabled: false },
    'GET /repos': { items: [] },
  })
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/results']}>
        <AuthProvider>
          <Routes>
            <Route element={<Layout />}>
              <Route path="/results" element={<h1>Baseline</h1>} />
            </Route>
          </Routes>
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

// ─── the tests ────────────────────────────────────────────────────────────────────────────

describe('hint ratchet: the route table', () => {
  it('every screen route in App.tsx is enforced (SCREENS) or allowlisted — never both, never neither', () => {
    // every route App.tsx declares, with nothing skipped by name: /login, /help,
    // /help/docs/:name and the catch-all are enforced like the rest since G-909
    const routes = Array.from(appSource.matchAll(/<Route\s+path="([^"]+)"/g), (m: RegExpMatchArray) => m[1]!)
    expect(routes.length).toBeGreaterThan(15)
    for (const r of routes) {
      const enforced = r in SCREENS
      const allowed = ALLOWLIST.includes(r)
      expect(enforced || allowed, `${r}: neither a SCREENS entry nor on the ALLOWLIST`).toBe(true)
      expect(enforced && allowed, `${r}: on the ALLOWLIST although it has a SCREENS entry — remove it from the allowlist`).toBe(false)
      expect(MIN_HINTS[r], `${r}: no MIN_HINTS floor`).toBeGreaterThan(0)
    }
    for (const r of Object.keys(SCREENS)) expect(routes, `SCREENS names ${r}, which App.tsx does not route`).toContain(r)
    for (const r of ALLOWLIST) expect(routes, `ALLOWLIST names ${r}, which App.tsx does not route`).toContain(r)
  })

  it('a fixture pool answer agrees with its fixture repository: no clone path, no history share', () => {
    // the pool contract (docs/API.md `/repos/{name}/pool`): without a clone path on this host
    // the history fields are null and the answer says `no_clone_path`. A fixture that served a
    // share for a repository with no clone showed a number its own premise could not produce
    // (PR #54 review); every fixture pool is held to the contract here.
    let checked = 0
    for (const [pattern, entry] of [...Object.entries(SCREENS), ...INSTRUMENT_VARIANTS.map((v) => [v.name, v] as const)]) {
      for (const [key, pool] of Object.entries(entry.api)) {
        const m = /^GET \/repos\/([^/]+)\/pool$/.exec(key)
        if (!m || typeof pool !== 'object' || pool === null) continue
        const repo = entry.api[`GET /repos/${m[1]}`] as { clone_path?: string; config?: { path?: string } } | undefined
        if (!repo || typeof repo !== 'object') continue
        checked += 1
        if (!repo.clone_path && !repo.config?.path) {
          const p = pool as { share: unknown; history_commits: unknown; window_commits: unknown; history_unavailable: unknown }
          expect({ share: p.share, history_commits: p.history_commits, window_commits: p.window_commits, history_unavailable: p.history_unavailable }, `${pattern}: ${key}`).toEqual({
            share: null,
            history_commits: null,
            window_commits: null,
            history_unavailable: 'no_clone_path',
          })
        }
      }
    }
    expect(checked, 'no fixture serves a pool beside its repository').toBeGreaterThan(0)
  })

  afterEach(() => vi.unstubAllGlobals())

  for (const [pattern, s] of Object.entries(SCREENS)) {
    for (const role of s.roles) {
      it(`${pattern} as ${role}: every element carries a resolved hint; at least ${MIN_HINTS[pattern]} hinted`, async () => {
        mockApi({ 'GET /auth/me': { ...PRINCIPAL, role }, ...s.api })
        const { container } = renderApp(s.element, { route: s.route, path: s.path })
        await screen.findByRole('heading', { level: 1 })
        await waitFor(() => expect(hinted(container)).toBeGreaterThanOrEqual(MIN_HINTS[pattern]!))
        const misses = unhinted(container)
        expect(misses, `unhinted elements on ${pattern} as ${role}:\n  ${misses.join('\n  ')}`).toEqual([])
      })
    }
  }

  // the deeper states one route entry cannot reach — a tab, an open dialog, an open drawer —
  // held to the same collector (the fixtures and open steps live beside the screens' entries)
  for (const v of INSTRUMENT_VARIANTS) {
    for (const role of v.roles) {
      it(`${v.name} as ${role}: every element carries a resolved hint`, async () => {
        mockApi({ 'GET /auth/me': { ...PRINCIPAL, role }, ...v.api })
        const { container } = renderApp(v.element, { route: v.route, path: v.path })
        await screen.findByRole('heading', { level: 1 })
        if (v.open) await v.open(container)
        await waitFor(() => expect(hinted(container)).toBeGreaterThanOrEqual(v.minHints ?? 4))
        const misses = unhinted(container)
        expect(misses, `unhinted elements in ${v.name} as ${role}:\n  ${misses.join('\n  ')}`).toEqual([])
      })
    }
  }
})

describe('hint ratchet: the shell (enforced from the start)', () => {
  afterEach(() => vi.unstubAllGlobals())

  for (const role of ['viewer', 'operator', 'admin'] as Role[]) {
    it(`as ${role}: every nav link, the chrome and the footer carry a resolved hint`, async () => {
      const { container } = renderShell(role)
      await waitFor(() => expect(screen.getByTestId('user-chip')).toBeInTheDocument())
      await waitFor(() => expect(container.querySelector('[data-hint="nav.version_line"]')).not.toBeNull())
      const misses = unhinted(container)
      expect(misses, `unhinted shell elements as ${role}:\n  ${misses.join('\n  ')}`).toEqual([])
      // the chrome beyond the selectors: theme, sign out, the role chip, the footer line
      for (const id of ['button.shell.theme', 'button.shell.sign_out', 'pill.shell.role', 'pill.shell.health', 'nav.help', 'nav.version_line', 'nav.footer_help', 'nav.footer_glossary', 'nav.decisions_count']) {
        expect(container.querySelector(`[data-hint="${id}"]`), id).not.toBeNull()
      }
      const floor = role === 'admin' ? 22 : role === 'operator' ? 21 : 16
      expect(hinted(container), `hinted elements in the shell as ${role}`).toBeGreaterThanOrEqual(floor)
    })
  }

  it('the stop-condition banner carries its hint', async () => {
    const { container } = renderShell('viewer', 2)
    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument())
    expect(container.querySelector('[data-hint="banner.shell.stop_condition"]')).not.toBeNull()
  })
})

describe('hint ratchet: the shared components (enforced from the start)', () => {
  it('the collector reports a StatTile without a hint, a column without one and a count eyebrow without one (a prose eyebrow is not a number)', () => {
    const { container } = render(
      <MemoryRouter>
        <StatTile label="X" value="1" n={1} apparatus="a" />
        <DataTable rows={[{ a: 1 }]} columns={[{ key: 'a', header: 'A', cell: (r) => r.a }]} rowKey={() => 'r'} caption="A table" empty={<span>none</span>} />
        <Card title="Counted" eyebrow="2 waiting">
          x
        </Card>
        <Card title="Described" eyebrow="the routes, with n">
          y
        </Card>
        <Card title="Hinted" eyebrow="3 for this repository" eyebrowHint="stat.results.waiting_count">
          z
        </Card>
      </MemoryRouter>,
    )
    expect(unhinted(container)).toEqual(["tile <div> 'X1n =1apparatusa'", "column header <th> 'A' in table 'A table'", "count eyebrow <div> '2 waiting'"])
    expect(container.querySelector('[data-eyebrow][data-hint="stat.results.waiting_count"]')?.textContent).toBe('3 for this repository')
  })

  it('every pill a shared component derives carries its own id', () => {
    const { container } = render(
      <MemoryRouter>
        <VerdictPill route="deliver" />
        <VerdictPill route={null} />
        <VerdictPill route="something-new" />
        <BeltPills belts={{ tests_unmodified: true, target_green: true, no_new_failures: false, source_changed: true, repo_lint_clean: null }} beltSet="v5" />
        <Provenance apparatus="2.2" beltSet="v5" />
        <Provenance apparatus={['2.1', '2.2']} />
        <Provenance apparatus="2.2" provenance="imported:census" />
        <ControlsPill verdict={null} />
        <ControlsPill verdict={{ measured: true, passed: true, complete: true, constructible: 5, total: 7, share: 0.71, escapes: 0, run_id: 'r', created: 'now', state: 'passed' }} />
        <FailureSplitPills split={{ builder_red: 1, lint: 0, budget: 0, protocol: 0, harness: 0, outage: 0, disqualified: 0 }} />
        <ModelPointLine modelPoint={0.5} modelN={2} clean={1} />
        <CiBar point={0.5} low={0.2} high={0.8} n={4} />
        <Pill tone="green" label="x" hint="run.status">
          ok
        </Pill>
        <Tag tone="green" hint="tier.verification">
          done
        </Tag>
      </MemoryRouter>,
    )
    expect(unhinted(container)).toEqual([])
    expect(container.querySelector('[data-testid="verdict-deliver"]')).toHaveAttribute('data-hint', 'route.deliver')
    expect(container.querySelector('[data-testid="verdict-NOT_YET_MEASURED"]')).toHaveAttribute('data-hint', 'route.not_yet_measured')
    expect(container.querySelector('[data-testid="verdict-something-new"]')).toHaveAttribute('data-hint', 'route.not_yet_measured')
    expect(container.querySelector('[data-testid="belt-no_new_failures"]')).toHaveAttribute('data-hint', 'belt.no_new_failures')
    expect(container.querySelector('[data-testid="belt-repo_lint_clean"]')).toHaveAttribute('data-hint', 'belt.repo_lint_clean')
    expect(Array.from(container.querySelectorAll('[data-testid="provenance"] [data-hint]')).map((e) => e.getAttribute('data-hint'))).toEqual(['provenance.measured', 'provenance.mixed', 'provenance.imported'])
    expect(container.querySelector('[data-testid="controls-unmeasured"]')).toHaveAttribute('data-hint', 'controls.unmeasured')
    expect(container.querySelector('[data-testid="controls-passed"]')).toHaveAttribute('data-hint', 'controls.passed')
    expect(container.querySelector('[data-testid="kind-budget"]')).toHaveAttribute('data-hint', 'kind.budget')
    expect(container.querySelector('[data-testid="model-point"]')).toHaveAttribute('data-hint', 'stat.shared.model_rate')
    expect(container.querySelector('[data-testid="ci-bar"]')).toHaveAttribute('data-hint', 'chart.ci_bar')
    expect(container.querySelector('[data-testid="ci-bar"] title')).not.toBeNull()
    // no native title survives on a pill or a failure kind
    expect(container.querySelectorAll('[title]').length).toBe(0)
  })

  it('a StatTile, DataTable column, button, field, gate criterion, summary row and task item given a hint carry it on the element the collector finds', () => {
    const { container } = render(
      <MemoryRouter>
        <StatTile label="False-Q1" value="0" n={12} apparatus="a" hint="stat.results.false_q1" footer="must be zero" data-testid="tile-fq1" />
        <DataTable
          rows={[{ a: 1, b: 2 }]}
          columns={[
            { key: 'a', header: 'Sortable', cell: (r) => r.a, sortValue: (r) => r.a, hint: 'col.ledger.belts' },
            { key: 'b', header: 'Plain', cell: (r) => r.b, hint: 'col.ledger.provenance' },
            { key: 'c', header: '', cell: () => '' },
          ]}
          rowKey={() => 'r'}
          caption="Rows"
          empty={<span>none</span>}
        />
        <Button variant="filled" hint="button.ledger.export_jsonl">
          Export
        </Button>
        <Button type="submit" hint="button.login.submit">
          Sign in
        </Button>
        <Button>Plain outlined</Button>
        <LinkButton to="/x" variant="filled" hint="button.home.continue">
          Continue
        </LinkButton>
        <StartButton hint="button.home.continue">Start</StartButton>
        <WarningButton hint="button.measure.start">Spend</WarningButton>
        <TextField label="Name" hint="field.login.username" description="a description" />
        <SelectField label="Role" hint="field.settings.new_role">
          <option>viewer</option>
        </SelectField>
        <TextArea label="Statement" hint="field.signoff.statement" />
        <InlineSelect label="Repository" hint="field.shared.repo_picker">
          <option>r</option>
        </InlineSelect>
        <GateBanner title="Ledger" criteria={[{ label: 'Chain intact', ok: true, hint: 'gate.ledger.chain' }]} />
        <SummaryList rows={[{ key: 'Roles', value: 'four', hint: 'summary.posture.roles' }]} />
        <TaskList tasks={[{ num: 1, name: 'Connect', status: 'Completed', tone: 'green', to: '/connect', hint: 'task.home.connect_github' }]} completed={1} />
        <PageHeader title="Baseline" />
      </MemoryRouter>,
    )
    expect(unhinted(container)).toEqual([])
    const tile = container.querySelector('[data-testid="tile-fq1"]')!
    expect(tile).toHaveAttribute('data-hint', 'stat.results.false_q1')
    expect(tile.textContent).toContain('must be zero')
    expect(container.querySelector('th button[data-hint="col.ledger.belts"]')).not.toBeNull()
    expect(container.querySelector('th [data-hint="col.ledger.provenance"]')).not.toBeNull()
    expect(container.querySelectorAll('[data-primary]').length).toBe(5)
    const input = screen.getByLabelText('Name')
    expect(input.getAttribute('aria-describedby')!.split(' ').length).toBe(2)
    expect(input).toHaveAccessibleDescription(`a description ${HINTS['field.login.username']}`)
    expect(screen.getByLabelText('Repository')).toHaveAccessibleDescription(HINTS['field.shared.repo_picker'])
    expect(container.querySelector('[data-component="gate"] li [data-hint="gate.ledger.chain"]')).not.toBeNull()
    // the whole summary row is the trigger: the value (the number) opens it, not only the key
    const row = container.querySelector('[data-hint="summary.posture.roles"]')!
    expect(row.querySelector('dt')).not.toBeNull()
    expect(row.querySelector('dd')?.textContent).toBe('four')
    expect(container.querySelector('[data-hint="task.home.connect_github"]')).toHaveAttribute('data-component', 'pill')
    // a journey eyebrow renders through PageHeader on /results? this MemoryRouter is at "/", so no eyebrow: the eyebrow case is below
  })

  it('a journey eyebrow carries nav.journey_position', () => {
    const { container } = render(
      <MemoryRouter initialEntries={['/results']}>
        <PageHeader title="Baseline" />
      </MemoryRouter>,
    )
    expect(container.querySelector('[data-hint="nav.journey_position"]')?.textContent).toBe('Journey · 2 of 4 · Baseline')
  })
})

describe('hint ratchet: no orphan in the registry', () => {
  it('every registered id is referenced as a literal by some source, or is a shared / derived id', () => {
    const corpus = Object.values(ALL_SOURCES).join('\n')
    const orphans = Object.keys(HINTS).filter((id) => {
      if ((SHARED_IDS as readonly string[]).includes(id) || DERIVED_FAMILIES.some((f) => id.startsWith(f))) return false
      return !corpus.includes(`'${id}'`) && !corpus.includes(`"${id}"`) && !corpus.includes(`\`${id}\``)
    })
    expect(orphans, `registered but rendered nowhere (dead copy): ${orphans.join(', ')}`).toEqual([])
    // and the exemptions are earned: a shared id is derived by a component that never writes the literal
    for (const id of SHARED_IDS) expect(HINTS[id], id).toBeTruthy()
  })
})

describe('hint ratchet: native title= only where allowed, and only ever fewer', () => {
  it('every title= sits in a file the allowlist names, within its count', () => {
    const counts: Record<string, number> = {}
    for (const [path, src] of Object.entries(SOURCES)) {
      const key = path.replace(/^\.\.\//, '')
      const n = (src.match(TITLE_RE) ?? []).length
      if (n > 0) counts[key] = n
    }
    for (const [file, n] of Object.entries(counts)) {
      expect(TITLE_ALLOWLIST[file] ?? 0, `${file}: ${n} native title= attribute(s); a hint is the way to explain an element`).toBeGreaterThanOrEqual(n)
    }
    for (const [file, max] of Object.entries(TITLE_ALLOWLIST)) {
      expect(counts[file] ?? 0, `${file}: the allowlist says ${max} but the file has ${counts[file] ?? 0} — lower the allowlist so it cannot creep back`).toBe(max)
    }
  })
})
