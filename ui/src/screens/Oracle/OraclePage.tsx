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
import { PageHeader } from '../../components/PageHeader'
import { Pill } from '../../components/Pill'
import { QueryBoundary } from '../../components/QueryBoundary'
import { RepoPicker, useRepoParam } from '../../components/RepoPicker'
import { StatTile } from '../../components/StatTile'
import { fmtInt, fmtRatio, fmtSeconds, shortId } from '../../lib/format'
import { bandDisplay, gateDisplay } from '../../lib/verdict'

const SIZE_ORDER = ['XS', 'S', 'M', 'L', 'XL']

function BandPill({ band }: { band: string }) {
  const d = bandDisplay(band)
  return (
    <Pill tone={d.tone} glyph={d.glyph} size="xs" label={d.describe}>
      {d.label}
    </Pill>
  )
}

function GatePill({ gate }: { gate: string }) {
  const d = gateDisplay(gate)
  return (
    <Pill tone={d.tone} glyph={d.glyph} size="xs" label={d.describe}>
      {d.label}
    </Pill>
  )
}

const VERDICT_TONE: Record<string, { tone: 'green' | 'red' | 'amber' | 'muted'; glyph: string }> = {
  ok: { tone: 'green', glyph: '✓' },
  VIOLATION: { tone: 'red', glyph: '✗' },
  ESCAPE: { tone: 'amber', glyph: '⚠' },
  not_constructible: { tone: 'muted', glyph: '–' },
  skip: { tone: 'muted', glyph: '–' },
}

function ControlsSection({ repo }: { repo: string }) {
  const q = useOracleControls(repo)
  const columns = useMemo<Column<ControlRow>[]>(
    () => [
      { key: 'task', header: 'Task', mono: true, sortValue: (r) => r.task_id, cell: (r) => <Link to={`/tasks/${encodeURIComponent(r.repo)}/${r.task_id}`} title={r.task_id}>{shortId(r.task_id)}</Link> },
      { key: 'control', header: 'Control', mono: true, sortValue: (r) => r.control, cell: (r) => r.control },
      { key: 'expected', header: 'Expected', sortValue: (r) => r.expected, cell: (r) => r.expected },
      { key: 'observed', header: 'Observed', sortValue: (r) => r.observed, cell: (r) => r.observed },
      {
        key: 'verdict',
        header: 'Verdict',
        sortValue: (r) => r.verdict,
        cell: (r) => {
          const t = VERDICT_TONE[r.verdict] ?? { tone: 'muted' as const, glyph: '?' }
          return (
            <Pill tone={t.tone} glyph={t.glyph} size="xs" label={`Verdict: ${r.verdict}${r.note ? ` — ${r.note}` : ''}`}>
              {r.verdict}
            </Pill>
          )
        },
      },
      { key: 'note', header: 'Note', cell: (r) => <span className="text-xs text-on-surface-muted">{r.note}</span>, hideBelowMd: true },
      { key: 'dur', header: 'Duration', numeric: true, sortValue: (r) => r.duration_s, cell: (r) => fmtSeconds(r.duration_s), hideBelowMd: true },
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
      return <EmptyState title="No controls report yet" reason="The negative-control matrix (gold, noop, test-tamper, stub, regression, hardcode-cheat, env-poison) proves the grader refuses what it must refuse." action={<LinkButton to={`/runs?repo=${encodeURIComponent(repo)}&new=controls`}>Run controls</LinkButton>} />
    }
    return <ErrorState error={q.error} onRetry={() => void q.refetch()} />
  }
  const c = q.data
  return (
    <div className="space-y-4">
      <GateBanner
        title="Negative controls"
        eyebrow="the grader refuses what it must refuse"
        criteria={[
          { label: 'No VIOLATION rows', ok: c.violations === 0, detail: `${fmtInt(c.violations)} violation(s) over ${fmtInt(c.n_rows)} rows` },
          { label: 'Report present', ok: c.n_rows > 0, detail: `${fmtInt(c.n_tasks)} tasks · ${fmtInt(c.n_rows)} control rows` },
          { label: 'Escapes reported (findings, not failures)', ok: true, detail: `${fmtInt(c.escapes)} escape(s) · ${fmtInt(c.not_constructible)} not constructible · ${fmtInt(c.skipped)} skipped` },
        ]}
      />
      <DataTable rows={c.rows} columns={columns} rowKey={(r) => `${r.task_id}|${r.control}`} caption="Negative-control rows" dense initialSort={{ key: 'verdict', dir: 'desc' }} empty={<EmptyState compact title="No control rows" />} />
    </div>
  )
}

export function OraclePage() {
  const [repo, setRepo] = useRepoParam()
  const oracle = useOracle(repo)

  const cellCols = useMemo<Column<OracleCell>[]>(
    () => [
      { key: 'class', header: 'Class', mono: true, sortValue: (c) => c.capability_class, cell: (c) => c.capability_class },
      { key: 'size', header: 'Size', sortValue: (c) => SIZE_ORDER.indexOf(c.size), cell: (c) => <span className="font-mono text-xs">{c.size}</span> },
      { key: 'n', header: 'n', numeric: true, sortValue: (c) => c.n, cell: (c) => fmtInt(c.n) },
      { key: 'strength', header: 'Strength (mean)', numeric: true, sortValue: (c) => c.strength_mean ?? -1, cell: (c) => fmtRatio(c.strength_mean) },
      { key: 'band', header: 'Band', sortValue: (c) => c.band, cell: (c) => <BandPill band={c.band} /> },
      { key: 'gate', header: 'Gate', sortValue: (c) => c.gate, cell: (c) => <GatePill gate={c.gate} /> },
    ],
    [],
  )
  const taskCols = useMemo<Column<OracleTask>[]>(
    () => [
      { key: 'task', header: 'Task', mono: true, sortValue: (t) => t.task_id, cell: (t) => <Link to={`/tasks/${encodeURIComponent(repo)}/${t.task_id}`} title={t.task_id}>{shortId(t.task_id)}</Link> },
      { key: 'class', header: 'Class', mono: true, sortValue: (t) => t.capability_class, cell: (t) => t.capability_class },
      { key: 'size', header: 'Size', sortValue: (t) => SIZE_ORDER.indexOf(t.size), cell: (t) => <span className="font-mono text-xs">{t.size}</span> },
      { key: 'strength', header: 'Strength', numeric: true, sortValue: (t) => t.strength ?? -1, cell: (t) => fmtRatio(t.strength) },
      { key: 'mutants', header: 'Killed / mutants', numeric: true, sortValue: (t) => t.mutants, cell: (t) => `${fmtInt(t.killed)} / ${fmtInt(t.mutants)}` },
      { key: 'band', header: 'Band', sortValue: (t) => t.band, cell: (t) => <BandPill band={t.band} /> },
      { key: 'gate', header: 'Gate', sortValue: (t) => t.gate, cell: (t) => <GatePill gate={t.gate} /> },
    ],
    [repo],
  )

  return (
    <>
      <PageHeader
        eyebrow="Oracle adequacy"
        title="Oracle"
        purpose="How much a green is worth. false-Q1 = 0 forbids a clean grade with a RED oracle; adequacy governs whether a GREEN one licenses auto-delivery: strength is the mutation kill-rate on the changed lines, banded against the same floor the router uses."
        actions={<RepoPicker value={repo} onChange={setRepo} />}
      />
      <QueryBoundary query={oracle} loading="Loading oracle strength…" idle={<EmptyState title="Choose a repo to see its oracle adequacy" action={<LinkButton to="/repos">Go to repos</LinkButton>} />}>
        {(o) => {
          const scored = o.tasks.filter((t) => t.strength !== null)
          const mean = scored.length ? scored.reduce((a, t) => a + (t.strength ?? 0), 0) / scored.length : null
          const bands = { strong: 0, adequate: 0, weak: 0, unscoreable: 0 }
          for (const t of o.tasks) bands[t.band] = (bands[t.band] ?? 0) + 1
          return (
            <div className="space-y-6">
              <div className="flex flex-wrap gap-3">
                <StatTile label="Mean strength" value={fmtRatio(mean)} n={scored.length} apparatus={`kill-rate over ${fmtInt(scored.length)} scored tasks · ${o.policy.version}`} />
                <StatTile label="Strong (≥ auto-ship floor)" value={fmtInt(bands.strong)} n={o.tasks.length} apparatus={`floor ${fmtRatio(o.policy.autoship_floor)}`} tone={bands.strong ? 'green' : undefined} />
                <StatTile label="Adequate" value={fmtInt(bands.adequate)} n={o.tasks.length} apparatus={`floor ${fmtRatio(o.policy.adequate_floor)}`} tone={bands.adequate ? 'primary' : undefined} />
                <StatTile label="Weak" value={fmtInt(bands.weak)} n={o.tasks.length} apparatus="a green on these routes to a human" tone={bands.weak ? 'amber' : undefined} />
                <StatTile label="Unscoreable" value={fmtInt(bands.unscoreable)} n={o.tasks.length} apparatus="no mutants — never licenses auto-ship" />
              </div>
              <Card padded={false} title="Per cell">
                <DataTable rows={o.cells} columns={cellCols} rowKey={(c) => `${c.capability_class}|${c.size}`} caption="Oracle strength per cell" empty={<EmptyState compact title="No cells scored" reason="Run an oracle run to measure mutation strength per task." action={<LinkButton to={`/runs?repo=${encodeURIComponent(repo)}&new=oracle`}>Run oracle</LinkButton>} />} />
              </Card>
              <Card padded={false} title="Per task">
                <DataTable rows={o.tasks} columns={taskCols} rowKey={(t) => t.task_id} caption="Oracle strength per task" dense initialSort={{ key: 'strength', dir: 'asc' }} empty={<EmptyState compact title="No tasks scored" />} />
              </Card>
              <Card title="Negative controls" eyebrow="latest report">
                <ControlsSection repo={repo} />
              </Card>
            </div>
          )
        }}
      </QueryBoundary>
    </>
  )
}

export default OraclePage
