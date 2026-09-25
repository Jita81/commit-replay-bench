/**
 * Capability map — per (class × size) cell: pass rate with n and interval, false-Q1, cost, latency,
 * oracle strength, and the route that evidence licenses (/capability).
 *
 * Navigation
 * ----------
 * What it is:   The screen at /capability: summary tiles, the controls tile, the class × size
 *               grid of cells, and a cell detail card.
 * What it does: Renders `GET /capability-map` for one repo (projection by class × size,
 *               optionally × language / × model). An absent cell is drawn as NOT_YET_MEASURED
 *               with n = 0 — never zero-filled; a cell with false-Q1 > 0 is red and a page-wide
 *               alert says every number is untrusted until the ledger is audited. Every cell
 *               shows its route, n, point, Wilson interval with the policy ticks, the model
 *               point beside it, the failure split and fQ1; the five abbreviated numbers are
 *               explained by one legend (visible under the grid and in the detail card, with
 *               terms that open inline) that every tile is `aria-describedby` — never a hover
 *               title inside the tile, and never a button inside the tile's button. The
 *               detail card recomputes the interval in the browser and flags drift from the
 *               server's rather than hiding it. The run action in the empty state is an
 *               operator's; other roles read who acts.
 * How:          `useRepoParam` → `useCapabilityMapWithControls(repo, projection)` → index the
 *               cells by `class|size` → the full taxonomy × size order as the grid so 0-count
 *               classes render honestly → `CellBox` per cell, `CellDetail` on click.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0003-one-routing-rule.md,
 *               docs/adr/0001-four-belts-and-false-q1-at-write.md
 * Works with:   ui/src/screens/Capability/contract.ts (the extended map type and hook),
 *               ui/src/screens/Capability/ReasonCode.tsx (a reason code's sentence, inline),
 *               ui/src/screens/Capability/FailureSplit.tsx (split, model point, controls pill),
 *               ui/src/components/Help.tsx (`Term` in the legend), ui/src/api/types.ts
 *               (`CapabilityMap`, `CellField`, `NOT_YET_MEASURED`), ui/src/components/StatTile.tsx
 *               (the numbers with their method), src/crb/server/routes/capability.py (the
 *               route and the cell statistics), src/crb/core/taxonomy.py (`ALL_CLASSES` —
 *               the list `ALL_CLASSES` here must match)
 * Tested by:    ui/src/screens/Capability/CapabilityPage.test.tsx,
 *               ui/e2e/walkthrough/05-replay-fake.spec.ts
 *               (a real cell with route `calibrate`),
 *               ui/e2e/walkthrough/07-settings-and-a11y.spec.ts
 * Touch when:   the class taxonomy changes (src/crb/core/taxonomy.py — mirror `ALL_CLASSES`
 *               here), a cell field is added to docs/API.md "/capability-map" (type it in
 *               ui/src/screens/Capability/contract.ts first), or the routing policy gains a
 *               threshold worth a tick; never for a new repository.
 * Claims:       The map shows measured cells only; coverage is `null` until the repo has a
 *               change profile (docs/EVIDENCE-AND-CLAIMS.md#6-permitted-claim-shapes-by-maturity).
 */
import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router'
import { NOT_YET_MEASURED, type CapabilityMap, type CellField } from '../../api/types'
import { AnchorButton, LinkButton } from '../../components/Button'
import { Card } from '../../components/Card'
import { CiBar } from '../../components/CiBar'
import { EmptyState } from '../../components/EmptyState'
import { InlineSelect } from '../../components/Field'
import { Term } from '../../components/Help'
import { Hint } from '../../components/Hint'
import { PageHeader } from '../../components/PageHeader'
import { Pill } from '../../components/Pill'
import { Provenance } from '../../components/Provenance'
import { QueryBoundary } from '../../components/QueryBoundary'
import { RepoPicker, useRepoParam } from '../../components/RepoPicker'
import { StatTile } from '../../components/StatTile'
import { VerdictPill } from '../../components/VerdictPill'
import { apiUrl } from '../../api/client'
import { useAuth } from '../../lib/auth'
import { fmtInt, fmtPct, fmtRatio, fmtSeconds, fmtUsd, wilson } from '../../lib/format'
import { tierDisplay } from '../../lib/verdict'
import { controlsDisplay, useCapabilityMapWithControls, type CapabilityCellSplit as CapabilityCell, type ControlsVerdict } from './contract'
import { ControlsPill, FailureSplitPills, ModelPointLine } from './FailureSplit'
import { ReasonCode } from './ReasonCode'

/** Column order of the grid — the size tiers as the apparatus defines them. */
const SIZE_ORDER = ['XS', 'S', 'M', 'L', 'XL']

/** The full taxonomy (crb.core.spec.ALL_CLASSES) — so 0-count classes render honestly. */
const ALL_CLASSES = [
  'backend.migration.add',
  'backend.model.edit',
  'backend.route.add',
  'backend.route.edit',
  'bug.fix',
  'ci.workflow.edit',
  'docs.update',
  'frontend.component.add',
  'frontend.component.edit',
  'frontend.route.add',
  'infra.helm.edit',
  'infra.terraform.edit',
  'test.add',
  'test.fix',
]

/** `class|size[|language][|model]` — the map's index key for one projection. */
function cellKey(c: { capability_class: string; size: string; language?: string; model?: string }, projection: CellField[]): string {
  return projection.map((f) => (f === 'capability_class' ? c.capability_class : f === 'size' ? c.size : f === 'language' ? (c.language ?? '') : f === 'model' ? (c.model ?? '') : '')).join('|')
}

/** A cell counts as measured only with rows behind it (`n > 0` and a real route); the type guard the grid and the tiles share. */
export function isMeasured(c: CapabilityCell | undefined): c is CapabilityCell {
  return Boolean(c) && c!.route !== NOT_YET_MEASURED && c!.n > 0
}

/** One grid cell: the NOT_YET_MEASURED placeholder, or the route, n, point, interval bar, model point, split and fQ1 as a clickable button. */
/** `apparatus 2.2 · belts v5` — the provenance every rendered rate keeps (CodeRabbit on PR #6). */
function provenance(c: { apparatus_versions?: string[]; belt_sets?: string[]; belt_set?: string }): string {
  const app = c.apparatus_versions?.length ? c.apparatus_versions.join('/') : '—'
  const belts = c.belt_sets?.length ? c.belt_sets.join('/') : (c.belt_set ?? '—')
  return `${app} · belts ${belts}`
}

/** The id of the one visually-hidden legend every tile is `aria-describedby`; it replaces per-number hover titles. */
const CELL_LEGEND_ID = 'cell-legend'

/**
 * The tile's five numbers, in plain text, for assistive technology: read once from the
 * legend under the grid instead of a hover title on each number (J-HEL-14).
 */
const CELL_LEGEND_TEXT =
  'Each tile: the route, n, point = clean / n with its 95 % Wilson interval in brackets, then fQ1 = the false-Q1 count (must be 0), $ = mean cost per trial, mean latency per trial, or = mean oracle strength, and a glyph for the verification tier: ✓ human-verified or A/B-confirmed, ◐ automated pass, ✗ untrusted.'

/** The same legend as one visible line whose words open their definitions inline; shown under the grid and in the open cell. */
function CellLegend({ 'data-testid': testId }: { 'data-testid'?: string }) {
  return (
    // the legend carries the per-number hints (never nested inside a tile's button): each segment explains one number every tile shows
    <Hint as="p" id="tile.capability.legend" className="m-0 text-[12px] leading-5 text-on-surface-muted" data-testid={testId}>
      <span className="font-semibold text-on-surface">Legend</span>{' '}
      <Hint id="map.cell.point">
        point [<Term id="wilson">Wilson 95 %</Term>]
      </Hint>{' '}
      ·{' '}
      <Hint id="map.cell.n">
        <Term id="clean">clean</Term>/n
      </Hint>{' '}
      ·{' '}
      <Hint id="map.cell.fq1">
        fQ1 = <Term id="false_q1">false-Q1</Term> count
      </Hint>{' '}
      · <Hint id="map.cell.cost">$ mean cost</Hint> · <Hint id="map.cell.latency">mean latency</Hint> ·{' '}
      <Hint id="map.cell.oracle">
        or = mean <Term id="oracle_strength">oracle strength</Term>
      </Hint>{' '}
      · <Hint id="map.cell.tier">✓ ◐ ✗ = verification tier</Hint>
    </Hint>
  )
}

function CellBox({ cell, policy, onOpen, dim }: { cell: CapabilityCell | undefined; policy: CapabilityMap['policy'] | undefined; onOpen: () => void; dim?: string }) {
  if (!isMeasured(cell)) {
    return (
      <Hint
        as="div"
        id="map.cell.grid_not_measured"
        tabStop={false}
        data-testid="cell-not-measured"
        className="flex h-full min-h-[92px] flex-col items-center justify-center rounded-[var(--radius-control)] border border-dashed border-border px-2 py-2 text-center"
      >
        <VerdictPill route={NOT_YET_MEASURED} size="xs" />
        <span className="mt-1 text-[10px] text-on-surface-muted">n = 0</span>
      </Hint>
    )
  }
  const bad = cell.false_q1 > 0
  const tier = tierDisplay(cell.verification_tier)
  return (
    <Hint
      as="button"
      id="map.cell.tile"
      type="button"
      onClick={onOpen}
      data-testid={bad ? 'cell-false-q1' : 'cell-measured'}
      aria-label={`${cell.capability_class} ${cell.size}${dim ? ` ${dim}` : ''}: ${cell.route}, n ${cell.n}, point ${fmtPct(cell.point)}, 95% CI ${fmtPct(cell.ci_low)} to ${fmtPct(cell.ci_high)}, false-Q1 ${cell.false_q1}, apparatus ${provenance(cell)}`}
      aria-describedby={CELL_LEGEND_ID}
      className={`flex h-full min-h-[92px] w-full flex-col gap-1 rounded-[var(--radius-control)] border px-2 py-2 text-left hover:bg-surface-high ${
        bad ? 'border-status-red bg-status-red-soft' : 'border-border bg-surface-container'
      }`}
    >
      <div className="flex items-center justify-between gap-1">
        <VerdictPill route={cell.route} size="xs" reason={cell.reason} />
        <span className="num text-[10px] text-on-surface-muted">n={fmtInt(cell.n)}</span>
      </div>
      {dim && <span className="truncate font-mono text-[10px] text-on-surface-muted">{dim}</span>}
      <div className="num flex items-baseline gap-1">
        <span className="text-[15px] font-semibold text-on-surface">{fmtPct(cell.point)}</span>
        <span className="text-[10px] text-on-surface-muted">
          [{fmtPct(cell.ci_low, 0)}, {fmtPct(cell.ci_high, 0)}]
        </span>
        <span className="text-[10px] text-on-surface-muted">clean {fmtInt(cell.clean)}/{fmtInt(cell.n)}</span>
      </div>
      <CiBar point={cell.point} low={cell.ci_low} high={cell.ci_high} n={cell.n} minPoint={policy?.min_point} minCiLow={policy?.min_ci_low} width={110} provenance={provenance(cell)} />
      {cell.failure_split && (
        <div className="flex flex-wrap items-center gap-x-2">
          <ModelPointLine modelPoint={cell.model_point ?? null} modelN={cell.model_n ?? 0} clean={cell.clean} ciLow={cell.model_ci_low ?? null} ciHigh={cell.model_ci_high ?? null} apparatus={cell.apparatus_versions} />
          <FailureSplitPills split={cell.failure_split} />
        </div>
      )}
      <div className="num flex flex-wrap items-center gap-x-2 text-[10px] text-on-surface-muted" data-testid="cell-numbers">
        <span className={bad ? 'font-semibold text-status-red' : ''} data-testid="cell-false-q1-value">
          fQ1 {cell.false_q1}
          {bad ? ' ✗' : ''}
        </span>
        <span>{fmtUsd(cell.cost_usd_mean)}</span>
        <span>{fmtSeconds(cell.latency_s_mean)}</span>
        <span>or {fmtRatio(cell.oracle_strength_mean)}</span>
        {tier && <span className={`${tier.tone === 'green' ? 'text-status-green' : tier.tone === 'red' ? 'text-status-red' : 'text-status-amber'}`}>{tier.glyph}</span>}
      </div>
    </Hint>
  )
}

/** The card under the grid for the selected cell: tiles for every number with its method, the split, and links to the ledger rows and the routing decision. */
function CellDetail({ cell, repo, onClose }: { cell: CapabilityCell; repo: string; onClose: () => void }) {
  const tier = tierDisplay(cell.verification_tier)
  const ci = wilson(cell.clean, cell.n)
  return (
    <Card
      title={`${cell.capability_class} × ${cell.size}${cell.language ? ` × ${cell.language}` : ''}${cell.model ? ` × ${cell.model}` : ''}`}
      eyebrow="cell"
      actions={
        <Hint as="button" id="button.capability.close" type="button" onClick={onClose} className="text-xs text-on-surface-muted hover:text-on-surface">
          close
        </Hint>
      }
    >
      <div className="space-y-3">
        <Hint as="div" id="tile.capability.detail_head" className="flex flex-wrap items-center gap-2">
          <VerdictPill route={cell.route} reason={cell.reason} />
          {tier && (
            <Pill tone={tier.tone} glyph={tier.glyph} size="xs" label={tier.describe} hint={tier.hint}>
              {tier.label}
            </Pill>
          )}
          <Provenance apparatus={cell.apparatus_versions} beltSet={cell.belt_set ?? null} />
        </Hint>
        <Hint as="p" id="tile.capability.reason" className="text-sm" data-testid="cell-reason">
          {cell.reason_code && (
            <span className="mr-2">
              <ReasonCode code={cell.reason_code} />
            </span>
          )}
          {cell.reason}
        </Hint>
        {cell.failure_split && (
          <Hint as="div" id="tile.capability.split" className="flex flex-wrap items-center gap-3 text-xs" data-testid="cell-split">
            <span className="label">Why not clean</span>
            <FailureSplitPills split={cell.failure_split} size="sm" data-testid="cell-split-pills" />
            <span className="text-on-surface-muted">
              n = clean + red + budget + protocol + harness; DQ sits outside n. Instrument rows (protocol, harness) count against autonomy until the instrument is fixed.
            </span>
          </Hint>
        )}
        <div className="flex flex-wrap gap-3">
          <StatTile label="Pass rate" hint="stat.capability.point" value={fmtPct(cell.point)} n={cell.n} ci={{ low: cell.ci_low, high: cell.ci_high }} apparatus={`all rows: ${fmtInt(cell.clean)} clean of ${fmtInt(cell.n)} eligible · Wilson 95% · the rate that routes`} data-testid="tile-point" />
          <StatTile label="Distinct tasks" hint="stat.capability.n_tasks" value={cell.n_tasks == null ? '—' : fmtInt(cell.n_tasks)} n={cell.n} apparatus="n counts attempts; this is the number of commits behind them — the clustering the rate hides" tone={cell.n_tasks != null && cell.n_tasks < 5 ? 'amber' : undefined} data-testid="tile-n-tasks" />
          {cell.failure_split && (
            <StatTile
              label="Model rate (fair attempts)"
              hint="stat.capability.model_point"
              value={cell.model_point === null || cell.model_point === undefined ? '—' : fmtPct(cell.model_point)}
              n={cell.model_n ?? 0}
              ci={cell.model_point == null || cell.model_ci_low == null || cell.model_ci_high == null ? null : { low: cell.model_ci_low, high: cell.model_ci_high }}
              apparatus={`${fmtInt(cell.clean)} clean of ${fmtInt(cell.model_n ?? 0)} finished attempts (clean + red) · Wilson 95% · diagnostic, not a gate`}
              data-testid="tile-model-point"
            />
          )}
          <StatTile label="false-Q1" hint="stat.capability.cell_false_q1" value={String(cell.false_q1)} n={cell.n} apparatus="clean rows with a failed belt — must be 0" tone={cell.false_q1 > 0 ? 'red' : 'green'} />
          <StatTile label="Cost / trial" hint="stat.capability.cost" value={fmtUsd(cell.cost_usd_mean)} n={cell.n} apparatus="mean of builder-reported USD" />
          <StatTile label="Latency / trial" hint="stat.capability.latency" value={fmtSeconds(cell.latency_s_mean)} n={cell.n} apparatus="mean wall-clock of the build" />
          <StatTile label="Oracle strength" hint="stat.capability.oracle" value={fmtRatio(cell.oracle_strength_mean)} n={cell.n} apparatus="mean mutation kill-rate of the tasks' oracles" />
        </div>
        <CellLegend data-testid="cell-legend-line" />
        {(Math.abs(ci.low - cell.ci_low) > 0.01 || Math.abs(ci.high - cell.ci_high) > 0.01) && (
          <Hint as="p" id="banner.capability.ci_drift" className="text-xs text-status-amber" role="status">
            The interval recomputed in the browser ({fmtPct(ci.low)}–{fmtPct(ci.high)}) differs from the server's — the server's is shown; the drift is flagged, not hidden.
          </Hint>
        )}
        <div className="flex flex-wrap gap-2">
          <LinkButton size="sm" to={`/ledger?repo=${encodeURIComponent(repo)}&capability_class=${encodeURIComponent(cell.capability_class)}&size=${encodeURIComponent(cell.size)}`} hint="button.capability.rows">
            Rows in ledger
          </LinkButton>
          <LinkButton size="sm" to={`/routing?repo=${encodeURIComponent(repo)}`} hint="button.capability.routing">
            Routing decision
          </LinkButton>
        </div>
      </div>
    </Card>
  )
}

/** The negative-controls verdict as a tile: FAILED / escapes / thin / passed / — with constructible k of N and the gate the policy applies. */
function ControlsTile({ verdict, policy }: { verdict: ControlsVerdict | undefined; policy: CapabilityMap['policy'] | undefined }) {
  const d = controlsDisplay(verdict, (policy as { min_controls_share?: number } | undefined)?.min_controls_share)
  const measured = Boolean(verdict?.measured)
  const value = !measured ? '—' : verdict!.state === 'failed' ? 'FAILED' : verdict!.state === 'escaped' ? `${verdict!.escapes} escape${verdict!.escapes === 1 ? '' : 's'}` : verdict!.state === 'thin' ? 'thin' : 'passed'
  return (
    <Hint as="div" id="stat.capability.controls" data-testid="tile-controls" className="min-w-[150px] flex-[1_1_150px] rounded-[var(--radius-card)] border border-border bg-surface-container px-4 py-3 shadow-[var(--shadow-card)]">
      <div className="label">Negative controls</div>
      <div className={`num mt-1 text-[24px] font-semibold leading-8 ${!measured ? 'text-on-surface-muted' : d.tone === 'green' ? 'text-status-green' : d.tone === 'red' ? 'text-status-red' : 'text-status-amber'}`}>{value}</div>
      <dl className="num mt-1 space-y-0.5 text-[11px] text-on-surface-muted">
        <div className="flex gap-1">
          <dt>constructible</dt>
          <dd>{measured ? `${fmtInt(verdict!.constructible)} of ${fmtInt(verdict!.total)}` : '—'}</dd>
        </div>
        <div className="flex gap-1">
          <dt>gate</dt>
          <dd>{policy ? `${(policy as { controls_version?: string }).controls_version ?? '—'} · deliver needs passed ∧ ≥ 50% constructible ∧ 0 escapes` : '—'}</dd>
        </div>
      </dl>
      <div className="mt-2">
        <ControlsPill verdict={verdict} size="xs" />
      </div>
      <p className="mt-1 text-[11px] text-on-surface-muted">{d.describe}</p>
    </Hint>
  )
}

/** The screen. `?repo=` from the URL; projection toggles (by language / by model) are local state. */
export function CapabilityPage() {
  const [repo, setRepo] = useRepoParam()
  const { can } = useAuth()
  const [byLanguage, setByLanguage] = useState(false)
  const [byModel, setByModel] = useState(false)
  const [language, setLanguage] = useState('')
  const [model, setModel] = useState('')
  // The selection is a KEY resolved against the current response, never a stored cell
  // object: a repo / projection / filter change would otherwise keep showing the old
  // detail with the new repo's ledger link (CodeRabbit on PR #6).
  const [selectedKey, setSelectedKey] = useState<string | null>(null)

  const projection = useMemo<CellField[]>(() => {
    const p: CellField[] = ['capability_class', 'size']
    if (byLanguage) p.push('language')
    if (byModel) p.push('model')
    return p
  }, [byLanguage, byModel])

  useEffect(() => {
    setSelectedKey(null)
  }, [repo, byLanguage, byModel, language, model])

  const map = useCapabilityMapWithControls(repo, projection)

  return (
    <>
      <PageHeader
        eyebrow="Instrument · Map grid"
        title="Capability map"
        purpose="Per (class × size) cell: the measured pass rate with its n and Wilson interval, the false-Q1 count (must read 0), cost, latency and oracle strength — and the route that evidence licenses. Unmeasured cells say so."
        actions={
          <>
            <RepoPicker value={repo} onChange={setRepo} />
            {repo && map.data && <ControlsPill verdict={map.data.controls} minShare={map.data.policy?.min_controls_share} />}
            {repo && (
              <AnchorButton size="sm" href={apiUrl(`/ledger/export?format=csv&repo=${encodeURIComponent(repo)}`)} download hint="button.capability.export">
                Export CSV
              </AnchorButton>
            )}
          </>
        }
      />
      <QueryBoundary
        query={map}
        loading="Computing cell statistics from the ledger…"
        idle={<EmptyState title="Choose a repo to see its capability map" reason="The map is computed from the ledger's rows for one repository at a time." action={<LinkButton to="/connect">Connect a repository</LinkButton>} />}
      >
        {(m) => {
          const classes = m.classes.length ? m.classes : ALL_CLASSES
          const sizes = (m.sizes.length ? [...m.sizes] : SIZE_ORDER).sort((a, b) => SIZE_ORDER.indexOf(a) - SIZE_ORDER.indexOf(b))
          const languages = m.languages ?? []
          const models = m.models ?? []
          const visible = m.cells.filter((c) => (!byLanguage || !language || c.language === language) && (!byModel || !model || c.model === model))
          // A projected dimension with no filter puts several cells behind one class×size
          // slot: every one is rendered (stacked), never the last one to win a Map key.
          const index = new Map<string, CapabilityCell[]>()
          for (const c of visible) {
            const k = cellKey(c, ['capability_class', 'size'])
            index.set(k, [...(index.get(k) ?? []), c])
          }
          const dimOf = (c: CapabilityCell) => [byLanguage ? c.language : '', byModel ? c.model : ''].filter(Boolean).join(' · ')
          const selected = selectedKey ? (visible.find((c) => cellKey(c, projection) === selectedKey) ?? null) : null
          const s = m.summary
          const measured = visible.filter(isMeasured)
          const nTotal = measured.reduce((a, c) => a + c.n, 0)
          const badCells = measured.filter((c) => c.false_q1 > 0).length
          const grid = classes.length * sizes.length
          const beltSets = [...new Set(measured.flatMap((c) => c.belt_sets ?? (c.belt_set ? [c.belt_set] : [])))]
          const covApp = `${fmtInt(s.deliver_cells)} deliver of ${fmtInt(s.total_cells || grid)} cells · policy ${m.policy?.version ?? '—'} · apparatus ${s.apparatus_versions?.join('/') || '—'} · belts ${beltSets.join('/') || '—'}`
          return (
            <div className="space-y-6">
              <div className="flex flex-wrap gap-3">
                <StatTile label="Trusted autonomy coverage" hint="stat.capability.coverage" value={fmtPct(s.trusted_autonomy_coverage)} n={s.n_total ?? nTotal} apparatus={covApp} tone="primary" data-testid="tile-coverage" footer="Share of the repo's change volume (its change profile, weighted by commit count) whose cell routes to deliver — a coverage of the profile, not a sampled rate, so it carries no Wilson interval; each cell's rate carries its own." />
                <StatTile label="Measured cells" hint="stat.capability.measured_cells" value={`${fmtInt(s.measured_cells)} / ${fmtInt(s.total_cells || grid)}`} n={s.n_total ?? nTotal} apparatus={`apparatus ${s.apparatus_versions?.join('/') || '—'}`} />
                <StatTile
                  label="false-Q1 total"
                  hint="stat.capability.false_q1"
                  value={String(s.false_q1_total ?? 0)}
                  n={s.n_total ?? nTotal}
                  apparatus="clean rows with a failed belt, across the map — must be 0"
                  tone={(s.false_q1_total ?? 0) > 0 || badCells > 0 ? 'red' : 'green'}
                  data-testid="tile-false-q1"
                />
                <ControlsTile verdict={m.controls} policy={m.policy} />
                <StatTile
                  label="Posture"
                  hint="stat.capability.posture"
                  value={s.posture_class || '—'}
                  n={s.n_total ?? nTotal}
                  apparatus={`${fmtInt(s.unqualified_posture ?? 0)} unqualified-posture rows excluded · ${fmtInt(s.excluded_posture_divergent ?? 0)} rows left out where the task's tests differ between postures`}
                  data-testid="tile-posture"
                />
              </div>

              {((s.false_q1_total ?? 0) > 0 || badCells > 0) && (
                <Hint as="div" id="banner.capability.false_q1" role="alert" className="rounded-[var(--radius-card)] border-2 border-status-red bg-status-red-soft px-5 py-3 text-sm text-status-red" data-testid="false-q1-alert">
                  <strong>✗ false-Q1 &gt; 0.</strong> {badCells} cell{badCells === 1 ? ' contains' : 's contain'} a clean row whose belts did not all hold. The write-time invariant should have made this impossible; treat every number on this page as untrusted until the ledger is audited (<Link to="/ledger">verify chain</Link>).
                </Hint>
              )}

              <Card
                title="Cells"
                eyebrow={`class × size${byLanguage ? ' × language' : ''}${byModel ? ' × model' : ''}`}
                actions={
                  <>
                    <Hint as="label" id="field.capability.by_language" className="inline-flex items-center gap-1.5 text-xs text-on-surface-muted">
                      <input type="checkbox" checked={byLanguage} onChange={(e) => setByLanguage(e.target.checked)} /> by language
                    </Hint>
                    {byLanguage && (
                      <InlineSelect label="Language" hint="field.capability.language" value={language} onChange={(e) => setLanguage(e.target.value)}>
                        <option value="">all</option>
                        {languages.map((l) => (
                          <option key={l} value={l}>
                            {l}
                          </option>
                        ))}
                      </InlineSelect>
                    )}
                    <Hint as="label" id="field.capability.by_model" className="inline-flex items-center gap-1.5 text-xs text-on-surface-muted">
                      <input type="checkbox" checked={byModel} onChange={(e) => setByModel(e.target.checked)} /> by model
                    </Hint>
                    {byModel && (
                      <InlineSelect label="Model" hint="field.capability.model" value={model} onChange={(e) => setModel(e.target.value)}>
                        <option value="">all</option>
                        {models.map((x) => (
                          <option key={x} value={x}>
                            {x}
                          </option>
                        ))}
                      </InlineSelect>
                    )}
                  </>
                }
              >
                {visible.length === 0 && m.cells.length === 0 ? (
                  <EmptyState
                    title="Nothing measured for this repo yet"
                    reason={can('operator') ? 'Every cell below would read NOT_YET_MEASURED. Run a replay to produce ledger rows; each graded trial is one observation in its (class × size) cell.' : 'Every cell below would read NOT_YET_MEASURED; an operator starts a replay run to produce ledger rows. Each graded trial is one observation in its (class × size) cell.'}
                    action={can('operator') ? <LinkButton to={`/runs?repo=${encodeURIComponent(repo)}&new=replay`} hint="button.capability.start_replay">Start a replay run</LinkButton> : undefined}
                  />
                ) : (
                  <div className="overflow-auto" tabIndex={0} role="region" aria-label={`Capability map for ${repo}, scrollable`}>
                    <table className="w-full border-separate border-spacing-1">
                      <caption className="sr-only">Capability map for {repo}: rows are capability classes, columns are size tiers</caption>
                      <thead>
                        <tr>
                          <th scope="col" className="label sticky left-0 bg-surface-container px-2 text-left">
                            <Hint id="col.capability.class">Class</Hint>
                          </th>
                          {sizes.map((sz) => (
                            <th key={sz} scope="col" className="label px-2 text-left">
                              <Hint id="col.capability.size">{sz}</Hint>
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {classes.map((cls) => (
                          <tr key={cls}>
                            <th scope="row" className="sticky left-0 bg-surface-container px-2 text-left align-top font-mono text-xs font-normal text-on-surface">
                              {cls}
                            </th>
                            {sizes.map((sz) => {
                              const cells = index.get(`${cls}|${sz}`) ?? []
                              return (
                                <td key={sz} className="min-w-[150px] align-top">
                                  {cells.length === 0 ? (
                                    <CellBox cell={undefined} policy={m.policy} onOpen={() => undefined} />
                                  ) : (
                                    <div className="flex flex-col gap-1">
                                      {cells.map((cell) => (
                                        <CellBox key={cellKey(cell, projection)} cell={cell} policy={m.policy} dim={dimOf(cell) || undefined} onOpen={() => setSelectedKey(cellKey(cell, projection))} />
                                      ))}
                                    </div>
                                  )}
                                </td>
                              )
                            })}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
                {!(visible.length === 0 && m.cells.length === 0) && (
                  <div className="mt-3 space-y-1">
                    <CellLegend />
                    <p id={CELL_LEGEND_ID} className="sr-only">
                      {CELL_LEGEND_TEXT}
                    </p>
                    <p className="m-0 text-[11px] text-on-surface-muted">
                      The interval bar's ticks are the policy's (point ≥ {fmtPct(m.policy?.min_point, 0)}, lower ≥ {fmtPct(m.policy?.min_ci_low, 0)}); the model rate is clean / (clean + red) on fair attempts, and the split is red · budget · protocol · harness · DQ. Every cell is routed under the repo's controls verdict shown above.
                    </p>
                  </div>
                )}
              </Card>

              {selected && <CellDetail cell={selected} repo={repo} onClose={() => setSelectedKey(null)} />}
            </div>
          )
        }}
      </QueryBoundary>
    </>
  )
}

export default CapabilityPage
