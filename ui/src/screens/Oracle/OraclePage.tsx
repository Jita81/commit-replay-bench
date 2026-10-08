/**
 * Oracle — how much a green is worth: mutation strength per task and per cell, and the
 * negative-controls report (/oracle).
 *
 * Navigation
 * ----------
 * What it is:   The screen at /oracle: strength tiles, per-cell and per-task tables, and the
 *               controls section with its gate.
 * What it does: Renders `GET /oracle/{repo}` (the latest mutation score per task — strength,
 *               band, the gate a clean grade licenses) and `GET /oracle/{repo}/controls` (the
 *               seven negative controls through the real grader). The controls gate is green
 *               only with zero VIOLATION rows; an ESCAPE is shown as a finding (the repo's
 *               tests could not tell a cheat from an implementation), not as an instrument
 *               failure. Each caught control shows its gold witness — the commit's own change
 *               graded beside it in the same posture — and a red witness reads as an
 *               instrument failure (G-952); a passed report the server reads as unmeasured
 *               has no witness (it predates `controls.v3`) and the gate says it licenses
 *               nothing until the controls run again (P-372). A 404 on controls is the
 *               designed "not measured yet" state with the run button.
 * How:          `useOracle` → tiles computed from the tasks (mean over scored tasks only;
 *               unscoreable never averaged in) → two `DataTable`s; `ControlsSection` reads the
 *               latest report and builds the `GateBanner` criteria from its counts.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0009-text-level-mutators.md, docs/adr/0010-polyglot-negative-controls.md
 * Works with:   ui/src/api/hooks.ts (`useOracle`, `useOracleControls`), ui/src/api/types.ts
 *               (`OracleReport`, `ControlsReport`, `ControlRow`), ui/src/lib/verdict.ts
 *               (`bandDisplay`, `gateDisplay`), ui/src/components/Help.tsx (`Term` — the band,
 *               gate and escape words open their definitions inline), ui/src/lib/auth.tsx
 *               (`can` — the run actions are an operator's), src/crb/server/routes/oracle.py
 *               (the routes), src/crb/core/oracle/adequacy.py (bands and gates),
 *               src/crb/core/oracle/controls.py (the control matrix and verdict vocabulary)
 * Tested by:    ui/src/screens/Oracle/OraclePage.test.tsx (the purpose, no "auto-ship", terms,
 *               the run actions per role, the Wilson interval and served floors, the gold
 *               witness column), ui/e2e/walkthrough/04-oracle-and-controls.spec.ts
 *               (strength, band and gate per task; every control with its verdict; no
 *               VIOLATION), ui/e2e/walkthrough/07-settings-and-a11y.spec.ts
 * Touch when:   never for a new repository; a control or a verdict word is added
 *               (src/crb/core/oracle/controls.py — add it to `VERDICT_TONE` and `ControlName` in
 *               ui/src/api/types.ts).
 * Claims:       A green on a weak or unscored oracle licenses nothing; the gate column is what
 *               a clean grade may be claimed to mean
 *               (docs/EVIDENCE-AND-CLAIMS.md#6a-what-a-signed-cell-may-be-claimed-to-mean-signoff-policyv3).
 */
import { useMemo } from 'react'
import { Link } from 'react-router'
import { useOracle, useOracleControls } from '../../api/hooks'
import type { ControlRow, OracleCell, OracleTask } from '../../api/types'
import { LinkButton } from '../../components/Button'
import { Card } from '../../components/Card'
import { DataTable, type Column } from '../../components/DataTable'
import { EmptyState } from '../../components/EmptyState'
import { ErrorState } from '../../components/ErrorState'
import { GateBanner } from '../../components/GateBanner'
import { Term } from '../../components/Help'
import { Hint } from '../../components/Hint'
import { PageHeader } from '../../components/PageHeader'
import { Pill } from '../../components/Pill'
import { QueryBoundary } from '../../components/QueryBoundary'
import { RepoPicker, useRepoParam } from '../../components/RepoPicker'
import { ShortId } from '../../components/ShortId'
import { StatTile } from '../../components/StatTile'
import { useAuth } from '../../lib/auth'
import { fmtInt, fmtRatio, fmtSeconds, shortId, wilson } from '../../lib/format'
import { bandDisplay, gateDisplay } from '../../lib/verdict'

/** Sort order for the size column. */
const SIZE_ORDER = ['XS', 'S', 'M', 'L', 'XL']

/** An oracle band as a pill. */
function BandPill({ band }: { band: string }) {
  const d = bandDisplay(band)
  return (
    <Pill tone={d.tone} glyph={d.glyph} size="xs" label={d.describe} hint={d.hint} tabStop={false}>
      {d.label}
    </Pill>
  )
}

/** An oracle gate (what a clean grade licenses) as a pill. */
function GatePill({ gate }: { gate: string }) {
  const d = gateDisplay(gate)
  return (
    <Pill tone={d.tone} glyph={d.glyph} size="xs" label={d.describe} hint={d.hint} tabStop={false}>
      {d.label}
    </Pill>
  )
}

/** Control verdicts: `VIOLATION` red (the grader passed what it must refuse — an instrument bug); `ESCAPE` amber (the repo's own tests could not tell — a finding about the oracle, not the grader). */
const VERDICT_TONE: Record<string, { tone: 'green' | 'red' | 'amber' | 'muted'; glyph: string }> = {
  ok: { tone: 'green', glyph: '✓' },
  VIOLATION: { tone: 'red', glyph: '✗' },
  ESCAPE: { tone: 'amber', glyph: '⚠' },
  not_constructible: { tone: 'muted', glyph: '–' },
  skip: { tone: 'muted', glyph: '–' },
}

/** The latest negative-controls report as a gate plus the rows; a 404 is "never run", with the button to run it. */
function ControlsSection({ repo }: { repo: string }) {
  const { can } = useAuth()
  const q = useOracleControls(repo)
  const columns = useMemo<Column<ControlRow>[]>(
    () => [
      { key: 'task', header: 'Task', hint: 'col.controls.task', mono: true, sortValue: (r) => r.task_id, cell: (r) => <Link to={`/tasks/${encodeURIComponent(r.repo)}/${r.task_id}`}><ShortId value={r.task_id} /></Link> },
      { key: 'control', header: 'Control', hint: 'col.controls.control', mono: true, sortValue: (r) => r.control, cell: (r) => r.control },
      { key: 'expected', header: 'Expected', hint: 'col.controls.expected', sortValue: (r) => r.expected, cell: (r) => r.expected },
      { key: 'observed', header: 'Observed', hint: 'col.controls.expected', sortValue: (r) => r.observed, cell: (r) => r.observed },
      // G-952: the gold graded beside a catch in the same posture; a catch with no clean
      // witness is a violation (a report from before controls.v3 carries none: a dash)
      {
        key: 'witness',
        header: 'Gold witness',
        hint: 'col.controls.witness',
        sortValue: (r) => r.witness ?? '',
        cell: (r) =>
          r.witness ? (
            <span className={`font-mono text-xs ${r.witness === 'clean' ? 'text-status-green' : 'font-bold text-status-red'}`} data-testid="controls-witness">
              {r.witness === 'clean' ? 'clean' : `${r.witness} — instrument failure`}
            </span>
          ) : (
            <span className="text-xs text-on-surface-muted">—</span>
          ),
      },
      {
        key: 'verdict',
        header: 'Verdict',
        hint: 'col.controls.verdict',
        sortValue: (r) => r.verdict,
        cell: (r) => {
          const t = VERDICT_TONE[r.verdict] ?? { tone: 'muted' as const, glyph: '?' }
          return (
            <Pill tone={t.tone} glyph={t.glyph} size="xs" label={`Verdict: ${r.verdict}${r.note ? ` — ${r.note}` : ''}`} hint="pill.controls.verdict" tabStop={false}>
              {r.verdict}
            </Pill>
          )
        },
      },
      { key: 'note', header: 'Note', hint: 'col.controls.note_duration', cell: (r) => <span className="text-xs text-on-surface-muted">{r.note}</span>, hideBelowMd: true },
      { key: 'dur', header: 'Duration', hint: 'col.controls.note_duration', numeric: true, sortValue: (r) => r.duration_s, cell: (r) => fmtSeconds(r.duration_s), hideBelowMd: true },
    ],
    [],
  )
  if (q.isPending) {
    return (
      <p role="status" className="text-sm text-on-surface-muted">
        Loading the negative-controls report…
      </p>
    )
  }
  if (q.isError) {
    if (q.error.status === 404) {
      return (
        <EmptyState
          title="No controls report yet"
          reason={`The negative-control matrix (gold, noop, test-tamper, stub, regression, hardcode-cheat, env-poison) proves the grader refuses what it must refuse.${can('operator') ? '' : ' An operator runs the controls.'}`}
          action={can('operator') ? <LinkButton to={`/runs?repo=${encodeURIComponent(repo)}&new=controls`} hint="button.oracle.run_controls">Run controls</LinkButton> : undefined}
        />
      )
    }
    return <ErrorState error={q.error} onRetry={() => void q.refetch()} />
  }
  const c = q.data
  // The gate's state is the SERVER's verdict (the reduction the capability map and the
  // routes gate on), rendered first; the counts below it are supporting detail. A report
  // with no verdict (a bare to_dict) is pending, never derived open from the counts.
  const v = c.verdict
  const verdictOk = v ? (v.state === 'passed' ? true : v.state === 'unmeasured' ? null : false) : null
  // P-372: a passed report the server reads as unmeasured has no gold witness beside its
  // catches (it was written before controls.v3), so it licenses nothing until the controls re-run
  const unwitnessed = v && c.passed && v.state === 'unmeasured'
  const version = typeof c.apparatus?.controls_version === 'string' ? c.apparatus.controls_version : 'before controls.v3'
  const verdictDetail = !v
    ? 'no verdict served with this report'
    : unwitnessed
      ? `unmeasured · no gold witness beside its catches (${version}): run the controls again before anything here can deliver`
      : `${v.state}${v.measured ? ` · ${fmtInt(v.constructible)} of ${fmtInt(v.total)} constructible (${Math.round(v.share * 100)}%) · ${fmtInt(v.escapes)} escape(s)${v.complete ? '' : ' · run cancelled part-way'}` : ''}${v.run_id ? ` · run ${shortId(v.run_id)}` : ''}`
  return (
    <div className="space-y-4">
      <Hint as="div" id="gate.oracle.controls">
        <GateBanner
          title="Negative controls"
          eyebrow="the grader refuses what it must refuse"
          criteria={[
            { label: 'Routing verdict (from the API)', ok: verdictOk, detail: verdictDetail, hint: 'gate.oracle.verdict' },
            { label: 'No VIOLATION rows', ok: c.violations === 0, detail: `${fmtInt(c.violations)} violation(s) over ${fmtInt(c.n_rows)} rows`, hint: 'gate.oracle.violations' },
            { label: 'Report present', ok: c.n_rows > 0, detail: `${fmtInt(c.n_tasks)} tasks · ${fmtInt(c.n_rows)} control rows`, hint: 'gate.oracle.present' },
            { label: 'Escapes reported (findings, not failures)', ok: true, detail: `${fmtInt(c.escapes)} escape(s) · ${fmtInt(c.not_constructible)} not constructible · ${fmtInt(c.skipped)} skipped`, hint: 'gate.oracle.escapes' },
          ]}
        />
      </Hint>
      {(c.escapes > 0 || (v && v.state !== 'passed' && v.state !== 'unmeasured')) && (
        // G-348 / G-432 — the finding's way forward: the strengthen report names the test work,
        // registers it, and re-runs the oracle and the controls for the task once it is done
        <p className="m-0 text-sm">
          Learning loop, step 2 of 6: deliver is withheld until the tests catch what escaped.{' '}
          <Hint as={Link} id="link.oracle.learn" to={`/learn?repo=${encodeURIComponent(repo)}#strengthen`} className="underline underline-offset-4">
            Strengthen the tests on Learn
          </Hint>
        </p>
      )}
      <DataTable rows={c.rows} columns={columns} rowKey={(r) => `${r.task_id}|${r.control}`} caption="Negative-control rows" dense initialSort={{ key: 'verdict', dir: 'desc' }} empty={<EmptyState compact title="No control rows" />} />
    </div>
  )
}

/** The screen. Tiles are computed client-side from the tasks; `unscoreable` tasks are counted but never averaged. */
export function OraclePage() {
  const [repo, setRepo] = useRepoParam()
  const { can } = useAuth()
  const oracle = useOracle(repo)

  const cellCols = useMemo<Column<OracleCell>[]>(
    () => [
      { key: 'class', header: 'Class', hint: 'col.oracle_cell.cell', mono: true, sortValue: (c) => c.capability_class, cell: (c) => c.capability_class },
      { key: 'size', header: 'Size', hint: 'col.oracle_cell.cell', sortValue: (c) => SIZE_ORDER.indexOf(c.size), cell: (c) => <span className="font-mono text-xs">{c.size}</span> },
      { key: 'n', header: 'n', hint: 'col.oracle_cell.n', numeric: true, sortValue: (c) => c.n, cell: (c) => fmtInt(c.n) },
      { key: 'strength', header: 'Strength (mean)', hint: 'col.oracle_cell.strength', numeric: true, sortValue: (c) => c.strength_mean ?? -1, cell: (c) => fmtRatio(c.strength_mean) },
      { key: 'band', header: 'Band', hint: 'col.oracle_cell.band', sortValue: (c) => c.band, cell: (c) => <BandPill band={c.band} /> },
      { key: 'gate', header: 'Gate', hint: 'col.oracle_cell.gate', sortValue: (c) => c.gate, cell: (c) => <GatePill gate={c.gate} /> },
    ],
    [],
  )
  const taskCols = useMemo<Column<OracleTask>[]>(
    () => [
      { key: 'task', header: 'Task', hint: 'col.oracle_task.task', mono: true, sortValue: (t) => t.task_id, cell: (t) => <Link to={`/tasks/${encodeURIComponent(repo)}/${t.task_id}`}><ShortId value={t.task_id} /></Link> },
      { key: 'class', header: 'Class', hint: 'col.oracle_task.task', mono: true, sortValue: (t) => t.capability_class, cell: (t) => t.capability_class },
      { key: 'size', header: 'Size', hint: 'col.oracle_task.task', sortValue: (t) => SIZE_ORDER.indexOf(t.size), cell: (t) => <span className="font-mono text-xs">{t.size}</span> },
      // strength = killed / mutants, a binomial rate: it is shown with its Wilson 95% interval
      // (computed from the served counts, never a fabricated bound) and its n
      {
        key: 'strength',
        header: 'Strength [Wilson 95%]',
        hint: 'col.oracle_task.strength',
        numeric: true,
        sortValue: (t) => t.strength ?? -1,
        cell: (t) => {
          if (t.strength === null || t.mutants <= 0) return fmtRatio(t.strength)
          const w = wilson(t.killed, t.mutants)
          return (
            <span>
              {fmtRatio(t.strength)} <span className="text-[10px] text-on-surface-muted">[{fmtRatio(w.low)}, {fmtRatio(w.high)}]</span>
            </span>
          )
        },
      },
      { key: 'mutants', header: 'Killed / mutants (n)', hint: 'col.oracle_task.mutants', numeric: true, sortValue: (t) => t.mutants, cell: (t) => `${fmtInt(t.killed)} / ${fmtInt(t.mutants)}` },
      { key: 'band', header: 'Band', hint: 'col.oracle_cell.band', sortValue: (t) => t.band, cell: (t) => <BandPill band={t.band} /> },
      { key: 'gate', header: 'Gate', hint: 'col.oracle_cell.gate', sortValue: (t) => t.gate, cell: (t) => <GatePill gate={t.gate} /> },
    ],
    [repo],
  )

  return (
    <>
      <PageHeader
        eyebrow="Instrument · Oracle"
        title="Oracle"
        purpose="How much a green is worth for this repository: whether the tests on the changed lines notice a wrong patch, and whether the grader catches deliberate cheats. A weak oracle sends a cell to a human whatever its pass rate."
        actions={<RepoPicker value={repo} onChange={setRepo} />}
      />
      <QueryBoundary query={oracle} loading="Loading oracle strength…" idle={<EmptyState title="Choose a repo to see its oracle adequacy" action={<LinkButton to="/connect">Connect a repository</LinkButton>} />}>
        {(o) => {
          const scored = o.tasks.filter((t) => t.strength !== null)
          const mean = scored.length ? scored.reduce((a, t) => a + (t.strength ?? 0), 0) / scored.length : null
          const bands = { strong: 0, adequate: 0, weak: 0, unscoreable: 0 }
          for (const t of o.tasks) bands[t.band] = (bands[t.band] ?? 0) + 1
          return (
            <div className="space-y-6">
              <div className="flex flex-wrap gap-3">
                <StatTile label="Mean strength" hint="stat.oracle.mean" value={fmtRatio(mean)} n={scored.length} apparatus={`mean of ${fmtInt(scored.length)} task kill-rates (each carries its own Wilson interval below; a mean of rates has none) · ${o.policy.version} · apparatus ${o.apparatus_versions?.join('/') || '—'}`} />
                <StatTile label="Strong (clears the deliver bar)" hint="stat.oracle.strong" value={fmtInt(bands.strong)} n={o.tasks.length} apparatus={`floor ${fmtRatio(o.policy.autoship_floor)}`} tone={bands.strong ? 'green' : undefined} />
                <StatTile label="Adequate" hint="stat.oracle.adequate" value={fmtInt(bands.adequate)} n={o.tasks.length} apparatus={`floor ${fmtRatio(o.policy.adequate_floor)}`} tone={bands.adequate ? 'primary' : undefined} />
                <StatTile label="Weak" hint="stat.oracle.weak" value={fmtInt(bands.weak)} n={o.tasks.length} apparatus="a green on these routes to a human" tone={bands.weak ? 'amber' : undefined} />
                <StatTile label="Unscoreable" hint="stat.oracle.unscoreable" value={fmtInt(bands.unscoreable)} n={o.tasks.length} apparatus="no mutants — never clears the bar" />
              </div>
              <p className="m-0 text-xs text-on-surface-muted">
                Band is the task’s or cell’s <Term id="oracle_strength">oracle strength</Term> against the policy’s floors. Gate is what a green licenses at that strength: clears the bar (a branch and pull request under review), review-gated, or needs a <Term id="human">human</Term>.
              </p>
              <Card padded={false} title="Per cell">
                <DataTable rows={o.cells} columns={cellCols} rowKey={(c) => `${c.capability_class}|${c.size}`} caption="Oracle strength per cell" empty={<EmptyState compact title="No cells scored" reason={can('operator') ? 'Run an oracle run to measure mutation strength per task.' : 'Mutation strength is measured per task; an operator runs an oracle run.'} action={can('operator') ? <LinkButton to={`/runs?repo=${encodeURIComponent(repo)}&new=oracle`} hint="button.oracle.run_oracle">Run oracle</LinkButton> : undefined} />} />
              </Card>
              <Card padded={false} title="Per task">
                <DataTable rows={o.tasks} columns={taskCols} rowKey={(t) => t.task_id} caption="Oracle strength per task" dense initialSort={{ key: 'strength', dir: 'asc' }} empty={<EmptyState compact title="No tasks scored" />} />
              </Card>
              <Card title="Negative controls" eyebrow="latest report">
                <div className="space-y-4">
                  <p className="m-0 text-xs text-on-surface-muted">
                    The <Term id="negative_controls">negative controls</Term> are deliberate cheats the grader must refuse. A VIOLATION is the grader passing one: an instrument defect. A <Term id="controls_escape">controls escape</Term> is a finding about this repository’s tests, not a failure of the grader.
                  </p>
                  <ControlsSection repo={repo} />
                </div>
              </Card>
            </div>
          )
        }}
      </QueryBoundary>
    </>
  )
}

export default OraclePage
