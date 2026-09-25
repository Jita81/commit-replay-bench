/**
 * Learn — the learning half of the loop: the prevention register (bug class → the change that
 * removes it, ADR-0020), then three read-only reports: refusals → guard corpus, weak oracles →
 * strengthening backlog, apparatus change → re-measurement plan (/learn).
 *
 * Navigation
 * ----------
 * What it is:   The screen at /learn: the prevention register card, then three derivations
 *               from one repo's ledger, each a card with tiles and a table.
 * What it does: Renders `GET /learn/register` (every bug class with its lever, before → after
 *               and status; its switch, revert and register controls are operator-only —
 *               ui/src/screens/Learn/PreventionSection.tsx), then `GET /learn/refusals`
 *               (protocol rows grouped by guard, reason and command shape, every verdict
 *               "unsure"), `/learn/strengthen` (cells withheld from deliver for a weak oracle,
 *               as frozen-backlog-shaped items) and `/learn/remeasure` (cells whose rows predate
 *               the current apparatus, with the rows and spend still needed). The three reports
 *               act on nothing: each stops where a person decides.
 * How:          Three local hooks (the shapes mirror `crb.core.learn` `to_dict()`s) → one
 *               section component each with tiles + `DataTable`; the note the server attaches
 *               is shown verbatim under each table.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   docs/LEARNING-LOOP.md (what each report means and why it stops at a human),
 *               src/crb/core/learn.py (the three derivations), src/crb/server/routes/learn.py
 *               (the routes), ui/src/components/StatTile.tsx and ui/src/components/DataTable.tsx,
 *               ui/src/components/Help.tsx (`Term` — stale, oracle strength and apparatus open
 *               their definitions inline), ui/src/screens/Oracle/OraclePage.tsx (where the
 *               strengthen report sends you)
 * Tested by:    ui/src/screens/Learn/LearnPage.test.tsx (plain eyebrows, the intro sentences,
 *               the terms, no write affordance in the three reports, the register card and its
 *               operator controls); the derivations are pinned in
 *               tests/test_learn.py and the routes in tests/test_server_routes_learn.py
 * Touch when:   a report gains a field (src/crb/core/learn.py — mirror the interface here)
 *               or a fourth play is added to docs/LEARNING-LOOP.md; never for a new repository.
 */
import { useMemo } from 'react'
import { useQuery, type UseQueryResult } from '@tanstack/react-query'
import { Link, useSearchParams } from 'react-router'
import { api, ApiError } from '../../api/client'
import { Card } from '../../components/Card'
import { DataTable, type Column } from '../../components/DataTable'
import { EmptyState } from '../../components/EmptyState'
import { ErrorState } from '../../components/ErrorState'
import { Term } from '../../components/Help'
import { PageHeader } from '../../components/PageHeader'
import { Pill } from '../../components/Pill'
import { RepoPicker, useRepoParam } from '../../components/RepoPicker'
import { Hint } from '../../components/Hint'
import { StatTile } from '../../components/StatTile'
import { fmtInt, fmtPct, fmtUsd } from '../../lib/format'
import { PreventionSection } from './PreventionSection'

// ---------------------------------------------------------------------------
// Shapes (mirror crb.core.learn *.to_dict(); see docs/LEARNING-LOOP.md)
// ---------------------------------------------------------------------------

/** One refusal class: (guard prefix, reason, command shape) with its cost and the candidate corpus lines; `verdict` is always "unsure" here — a human writes honest / refuse. */
export interface RefusalGroup {
  group_id: string
  prefix: string
  reason: string
  shape: string
  n: number
  cost_usd: number
  minutes: number
  repos: string[]
  tasks: string[]
  examples: string[]
  truncated: boolean
  candidate_honest: string
  candidate_refused: string
  verdict: string
}

/** `GET /learn/refusals` — mirrors `crb.core.learn.RefusalReport.to_dict()`. */
export interface RefusalReport {
  repo: string
  rows_total: number
  rows_protocol: number
  protocol_share: number
  /** The same share with its n and Wilson 95% interval — the form a rate is rendered in. */
  share: RefusalShare
  /** The share per apparatus version — never blended across versions on screen. */
  by_apparatus: Array<RefusalShare & { apparatus_version: string }>
  cost_usd: number
  minutes: number
  unparsed: number
  apparatus_versions: string[]
  groups: RefusalGroup[]
  note: string
}

export interface RefusalShare {
  rows_total: number
  rows_protocol: number
  share: number
  ci_low: number
  ci_high: number
}

/** One strengthening proposal in the frozen-backlog shape (`test.add`, structural slots only). */
export interface StrengthenItem {
  id: string
  title: string
  description: string
  capability_class: string
  labels: Record<string, string>
}

/** `GET /learn/strengthen` — cells withheld from deliver for a weak oracle, and the items that would strengthen them. */
export interface StrengthenReport {
  repo: string
  threshold: number
  cells_flagged: string[]
  cells_without_scores: string[]
  items: StrengthenItem[]
  note: string
}

/** One cell with rows older than the current apparatus: how many are stale, how many current, how many still needed for n ≥ min_n, and the estimated spend. */
export interface RemeasureCell {
  label: string
  stale_versions: string[]
  n_stale: number
  n_current: number
  n_needed: number
  est_cost_usd: number
  est_minutes: number
  cost_known: boolean
  repos: string[]
  requests: Array<Record<string, unknown>>
}

/** `GET /learn/remeasure` — evidence expires with the apparatus (EVIDENCE-AND-CLAIMS §4). */
export interface RemeasurePlan {
  repo: string
  current_apparatus: string
  min_n: number
  rows_total: number
  rows_stale: number
  cells: RemeasureCell[]
  up_to_date: string[]
  summary: { cells_stale: number; n_needed_total: number; est_cost_usd_total: number; est_minutes_total: number; cost_known_cells: number }
  note: string
}

const enc = encodeURIComponent

/** `GET /learn/refusals?repo=`. */
function useLearnRefusals(repo: string): UseQueryResult<RefusalReport, ApiError> {
  return useQuery({
    queryKey: ['learn', repo, 'refusals'] as const,
    queryFn: () => api<RefusalReport>(`/learn/refusals?repo=${enc(repo)}`),
    enabled: repo.length > 0,
    retry: false,
  })
}

/** `GET /learn/strengthen?repo=`. */
function useLearnStrengthen(repo: string): UseQueryResult<StrengthenReport, ApiError> {
  return useQuery({
    queryKey: ['learn', repo, 'strengthen'] as const,
    queryFn: () => api<StrengthenReport>(`/learn/strengthen?repo=${enc(repo)}`),
    enabled: repo.length > 0,
    retry: false,
  })
}

/** `GET /learn/remeasure?repo=`. */
function useLearnRemeasure(repo: string): UseQueryResult<RemeasurePlan, ApiError> {
  return useQuery({
    queryKey: ['learn', repo, 'remeasure'] as const,
    queryFn: () => api<RemeasurePlan>(`/learn/remeasure?repo=${enc(repo)}`),
    enabled: repo.length > 0,
    retry: false,
  })
}

// ---------------------------------------------------------------------------
// Sections
// ---------------------------------------------------------------------------

/** The loading line for a report; says what is being derived. */
function Pending({ what }: { what: string }) {
  return (
    <p role="status" className="text-sm text-on-surface-muted">
      Deriving {what}…
    </p>
  )
}

/** Play 04: protocol rows → candidate guard-corpus lines (tiles + table); the share tile turns amber above 5 %. */
function RefusalsSection({ repo }: { repo: string }) {
  const q = useLearnRefusals(repo)
  const columns = useMemo<Column<RefusalGroup>[]>(
    () => [
      { key: 'n', header: 'n', hint: 'col.learn_refusals.n', numeric: true, sortValue: (g) => g.n, cell: (g) => fmtInt(g.n) },
      {
        key: 'prefix',
        header: 'Guard',
        hint: 'col.learn_refusals.guard',
        sortValue: (g) => g.prefix,
        cell: (g) => (
          <Pill tone={g.prefix === 'network' ? 'blue' : g.prefix === 'archaeology' ? 'violet' : 'muted'} size="xs" label={`Guard family: ${g.prefix}`} hint="pill.learn.guard" tabStop={false}>
            {g.prefix}
          </Pill>
        ),
      },
      { key: 'reason', header: 'Reason', hint: 'col.learn_refusals.reason_shape', cell: (g) => <span className="text-xs">{g.reason}</span> },
      { key: 'shape', header: 'Command shape', hint: 'col.learn_refusals.reason_shape', mono: true, cell: (g) => <span className="text-xs">{g.shape}{g.truncated ? ' …' : ''}</span> },
      { key: 'cost', header: '$ lost', hint: 'col.learn_refusals.cost', numeric: true, sortValue: (g) => g.cost_usd, cell: (g) => fmtUsd(g.cost_usd), hideBelowMd: true },
      {
        key: 'verdict',
        header: 'Verdict',
        hint: 'col.learn_refusals.verdict',
        sortValue: (g) => g.verdict,
        cell: (g) => (
          <Pill tone="amber" glyph="?" size="xs" label="The product never decides: a human writes honest / refuse via `crb learn refusals --apply`" hint="pill.learn.verdict" tabStop={false}>
            {g.verdict}
          </Pill>
        ),
      },
    ],
    [],
  )
  if (q.isPending) return <Pending what="the refusal triage" />
  if (q.isError) return <ErrorState error={q.error} onRetry={() => void q.refetch()} />
  const r = q.data
  const byApp = r.by_apparatus ?? []
  // One apparatus → the rate is that apparatus's, with its interval. Several → the tile
  // shows each version's own rate; the blended number is never the headline
  // (CodeRabbit on PR #6: a rate is never blended across apparatus versions).
  const single = byApp.length === 1 ? byApp[0]! : null
  const headline = single ?? r.share
  const apparatus = single ? `apparatus ${single.apparatus_version} · failure_kind = protocol · Wilson 95%` : byApp.length > 1 ? `${byApp.length} apparatus versions — see each below · failure_kind = protocol` : 'no rows'
  return (
    <div className="space-y-4">
      <p className="m-0 text-sm text-on-surface-muted">
        Rows the builder’s guards refused, grouped into classes with the spend they cost, per <Term id="apparatus">apparatus</Term> version. A person judges each class honest or refused and writes the line into the guard corpus, the list of refusals the guards then recognise; until then every verdict here is unsure.
      </p>
      <div className="grid gap-3 sm:grid-cols-3">
        <StatTile
          label={byApp.length > 1 ? 'Instrument-caused rows (per apparatus)' : 'Instrument-caused rows'}
          value={byApp.length > 1 ? byApp.map((a) => `${a.apparatus_version}: ${fmtPct(a.share)}`).join(' · ') : headline && headline.rows_total ? fmtPct(headline.share) : '—'}
          n={headline?.rows_total ?? r.rows_total}
          ci={byApp.length === 1 && headline.rows_total ? { low: headline.ci_low, high: headline.ci_high } : null}
          apparatus={byApp.length > 1 ? `${byApp.map((a) => `${a.apparatus_version}: ${a.rows_protocol}/${a.rows_total} [${fmtPct(a.ci_low, 0)}–${fmtPct(a.ci_high, 0)}]`).join(' · ')} · Wilson 95%` : apparatus}
          tone={byApp.some((a) => a.share > 0.05) ? 'amber' : 'green'}
          footer="review §7.5: read every one until this is < 5%"
          hint="stat.learn.refusal_share"
        />
        <StatTile label="Refusal classes" hint="stat.learn.refusal_classes" value={r.groups.length ? fmtInt(r.groups.length) : '—'} n={r.rows_protocol} apparatus="grouped by (guard, reason, command shape)" />
        <StatTile label="Spent on refusals" hint="stat.learn.refusal_cost" value={r.rows_protocol ? fmtUsd(r.cost_usd) : '—'} n={r.rows_protocol} apparatus={`${fmtInt(Math.round(r.minutes))} builder-minutes`} />
      </div>
      <DataTable
        rows={r.groups}
        columns={columns}
        rowKey={(g) => g.group_id}
        caption="Refusal classes — candidate guard-corpus lines, every verdict unsure"
        dense
        initialSort={{ key: 'n', dir: 'desc' }}
        empty={<EmptyState compact title="No protocol rows" reason="Nothing was refused by a guard in this repo's ledger." />}
      />
      <p className="text-xs text-on-surface-muted">{r.note}</p>
    </div>
  )
}

/** Play 03: oracle-held cells → test work; links to the Oracle page for cells without per-task scores. */
function StrengthenSection({ repo }: { repo: string }) {
  const q = useLearnStrengthen(repo)
  const columns = useMemo<Column<StrengthenItem>[]>(
    () => [
      {
        key: 'id',
        header: 'Item',
        hint: 'col.learn_strengthen.item',
        mono: true,
        sortValue: (i) => i.id,
        // The description is a second line under the id, as text. It used to be a native
        // `title=`, which opens on hover alone: no keyboard and no touch reader could ever
        // read it (G-287). Nothing here is hover-only.
        cell: (i) => (
          <span className="block text-xs">
            {i.id}
            {i.description ? <span className="mt-0.5 block font-sans font-normal text-on-surface-muted">{i.description}</span> : null}
          </span>
        ),
      },
      { key: 'title', header: 'Title', hint: 'col.learn_strengthen.item', cell: (i) => <span className="text-xs">{i.title}</span> },
      { key: 'cell', header: 'Cell', hint: 'col.learn_strengthen.cell', mono: true, sortValue: (i) => i.labels.cell, cell: (i) => i.labels.cell },
      {
        key: 'reason',
        header: 'Held because',
        hint: 'col.learn_strengthen.reason',
        sortValue: (i) => i.labels.reason_code,
        cell: (i) => (
          <Pill tone="amber" size="xs" hint="pill.learn.held_reason" tabStop={false}>
            {i.labels.reason_code}
          </Pill>
        ),
      },
      { key: 'strength', header: 'Strength', hint: 'col.learn_strengthen.strength', numeric: true, sortValue: (i) => i.labels.oracle_strength, cell: (i) => `${i.labels.oracle_strength ?? '—'} / ${i.labels.threshold ?? '—'}` },
      { key: 'escaped', header: 'Escaped', hint: 'col.learn_strengthen.escaped', numeric: true, sortValue: (i) => Number(i.labels.escaped ?? -1), cell: (i) => i.labels.escaped ?? '—', hideBelowMd: true },
    ],
    [],
  )
  if (q.isPending) return <Pending what="the strengthening backlog" />
  if (q.isError) return <ErrorState error={q.error} onRetry={() => void q.refetch()} />
  const s = q.data
  return (
    <div className="space-y-4">
      <p className="m-0 text-sm text-on-surface-muted">
        <Term id="cell">Cells</Term> withheld from deliver because their <Term id="oracle_strength">oracle strength</Term> is under the bar or their <Term id="negative_controls">negative controls</Term> escaped or were thin, each as a test-writing item a person can freeze on the Factory. More attempts will not move these cells; stronger tests will.
      </p>
      <div className="grid gap-3 sm:grid-cols-3">
        <StatTile label="Oracle-held cells" hint="stat.learn.oracle_held" value={s.cells_flagged.length ? fmtInt(s.cells_flagged.length) : '—'} n={s.cells_flagged.length} apparatus={`routing.v1 · oracle threshold ${s.threshold.toFixed(2)}`} tone={s.cells_flagged.length ? 'amber' : 'green'} />
        <StatTile label="Strengthening items" hint="stat.learn.items" value={s.items.length ? fmtInt(s.items.length) : '—'} n={s.items.length} apparatus="test.add · structural slots only · DoR: build" />
        <StatTile
          label="Cells without per-task scores"
          hint="stat.learn.no_scores"
          value={s.cells_without_scores.length ? fmtInt(s.cells_without_scores.length) : '—'}
          n={s.cells_without_scores.length}
          apparatus="run an oracle run to list the escaped mutants"
          footer={
            <Hint as={Link} id="link.learn.oracle" to={`/oracle?repo=${enc(repo)}`}>
              Oracle
            </Hint>
          }
        />
      </div>
      <DataTable
        rows={s.items}
        columns={columns}
        rowKey={(i) => i.id}
        caption="Strengthening backlog — proposals in the frozen-backlog shape"
        dense
        empty={<EmptyState compact title="No oracle-held cells" reason="No cell is withheld from deliver for a weak oracle, a controls escape or thin controls." />}
      />
      <p className="text-xs text-on-surface-muted">{s.note}</p>
    </div>
  )
}

/** Stale evidence → the runs to queue; the spend tile is a dash when no cell has a known cost. */
function RemeasureSection({ repo }: { repo: string }) {
  const q = useLearnRemeasure(repo)
  const columns = useMemo<Column<RemeasureCell>[]>(
    () => [
      { key: 'cell', header: 'Cell', hint: 'col.learn_remeasure.cell', mono: true, sortValue: (c) => c.label, cell: (c) => <span className="text-xs">{c.label}</span> },
      { key: 'stale', header: 'Stale', hint: 'col.learn_remeasure.counts', numeric: true, sortValue: (c) => c.n_stale, cell: (c) => `${fmtInt(c.n_stale)} (${c.stale_versions.join(', ')})` },
      { key: 'current', header: 'Current', hint: 'col.learn_remeasure.counts', numeric: true, sortValue: (c) => c.n_current, cell: (c) => fmtInt(c.n_current) },
      { key: 'needed', header: 'Needed', hint: 'col.learn_remeasure.counts', numeric: true, sortValue: (c) => c.n_needed, cell: (c) => fmtInt(c.n_needed) },
      { key: 'cost', header: 'Est. $', hint: 'col.learn_remeasure.cost', numeric: true, sortValue: (c) => (c.cost_known ? c.est_cost_usd : -1), cell: (c) => (c.cost_known ? fmtUsd(c.est_cost_usd) : '?') },
      { key: 'requests', header: 'Runs to queue', hint: 'col.learn_remeasure.runs', numeric: true, sortValue: (c) => c.requests.length, cell: (c) => fmtInt(c.requests.length), hideBelowMd: true },
    ],
    [],
  )
  if (q.isPending) return <Pending what="the re-measurement plan" />
  if (q.isError) return <ErrorState error={q.error} onRetry={() => void q.refetch()} />
  const p = q.data
  return (
    <div className="space-y-4">
      <p className="m-0 text-sm text-on-surface-muted">
        Cells whose rows predate the current <Term id="apparatus">apparatus</Term>. <Term id="stale">Stale</Term> evidence is kept as history and licenses nothing; the plan lists the runs to queue and what they would cost.
      </p>
      <div className="grid gap-3 sm:grid-cols-3">
        <StatTile label="Stale rows" hint="stat.learn.stale_rows" value={p.rows_total ? fmtInt(p.rows_stale) : '—'} n={p.rows_total} apparatus={`older than apparatus ${p.current_apparatus}`} tone={p.rows_stale ? 'amber' : 'green'} />
        <StatTile label="Rows still needed" hint="stat.learn.needed" value={p.cells.length ? fmtInt(p.summary.n_needed_total) : '—'} n={p.cells.length} apparatus={`rule n ≥ ${p.min_n} per cell · ${fmtInt(p.summary.cells_stale)} cell(s)`} />
        <StatTile
          label="Estimated spend"
          hint="stat.learn.remeasure_cost"
          value={p.summary.cost_known_cells ? fmtUsd(p.summary.est_cost_usd_total) : '—'}
          n={p.summary.cost_known_cells}
          apparatus="each cell's own mean row cost × n needed"
          footer={
            <Hint as={Link} id="link.learn.runs" to={`/runs?repo=${enc(repo)}`}>
              Queue runs
            </Hint>
          }
        />
      </div>
      <DataTable
        rows={p.cells}
        columns={columns}
        rowKey={(c) => c.label}
        caption="Cells whose evidence predates the current apparatus"
        dense
        initialSort={{ key: 'needed', dir: 'desc' }}
        empty={<EmptyState compact title="Nothing stale" reason="Every row of this repo carries the current apparatus version." />}
      />
      <p className="text-xs text-on-surface-muted">{p.note}</p>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

/**
 * The learning half of the loop (docs/LEARNING-LOOP.md): the prevention register, which acts
 * only under an operator's switch, then three derivations from the ledger that each stop where
 * a human decides — accepting a corpus line, freezing a strengthening item, queuing a
 * re-measurement — so those three reports have no write affordance by design.
 */
export function LearnPage() {
  const [repo, setRepo] = useRepoParam()
  const [params] = useSearchParams()
  const focus = params.get('class') ?? ''
  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Instrument · Learn"
        title="Learn"
        purpose="What the ledger teaches, and what the loop does about it: every bug class with the change that should remove it and whether it worked, then refusals that should become guard tests, weak oracles that should become test work and stale evidence that should be re-measured. The three reports act on nothing; the register acts only under an operator’s switch."
        actions={<RepoPicker value={repo} onChange={setRepo} />}
      />
      {!repo ? (
        <EmptyState title="Pick a repository" reason="The three reports are derived from one repository's ledger rows." />
      ) : (
        <>
          <Card eyebrow="Prevention" title="Bug classes → the change that removes them" id="prevention">
            <PreventionSection repo={repo} focus={focus} />
          </Card>
          <Card eyebrow="Refusals" title="Refusals → guard corpus">
            <RefusalsSection repo={repo} />
          </Card>
          <Card eyebrow="Weak oracles" title="Weak oracles → strengthening backlog">
            <StrengthenSection repo={repo} />
          </Card>
          <Card eyebrow="Stale evidence" title="Apparatus change → re-measurement plan">
            <RemeasureSection repo={repo} />
          </Card>
        </>
      )}
    </div>
  )
}
