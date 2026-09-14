import { useMemo, useState } from 'react'
import { Link } from 'react-router'
import { NOT_YET_MEASURED, type CapabilityMap, type CellField } from '../../api/types'
import { AnchorButton, LinkButton } from '../../components/Button'
import { Card } from '../../components/Card'
import { CiBar } from '../../components/CiBar'
import { EmptyState } from '../../components/EmptyState'
import { InlineSelect } from '../../components/Field'
import { PageHeader } from '../../components/PageHeader'
import { Pill } from '../../components/Pill'
import { Provenance } from '../../components/Provenance'
import { QueryBoundary } from '../../components/QueryBoundary'
import { RepoPicker, useRepoParam } from '../../components/RepoPicker'
import { StatTile } from '../../components/StatTile'
import { VerdictPill } from '../../components/VerdictPill'
import { apiUrl } from '../../api/client'
import { fmtInt, fmtPct, fmtRatio, fmtSeconds, fmtUsd, wilson } from '../../lib/format'
import { tierDisplay } from '../../lib/verdict'
import { REASON_DISPLAY, controlsDisplay, useCapabilityMapWithControls, type CapabilityCellSplit as CapabilityCell, type ControlsVerdict } from './contract'
import { ControlsPill, FailureSplitPills, ModelPointLine } from './FailureSplit'

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

function cellKey(c: { capability_class: string; size: string; language?: string; model?: string }, projection: CellField[]): string {
  return projection.map((f) => (f === 'capability_class' ? c.capability_class : f === 'size' ? c.size : f === 'language' ? (c.language ?? '') : f === 'model' ? (c.model ?? '') : '')).join('|')
}

export function isMeasured(c: CapabilityCell | undefined): c is CapabilityCell {
  return Boolean(c) && c!.route !== NOT_YET_MEASURED && c!.n > 0
}

function CellBox({ cell, policy, onOpen }: { cell: CapabilityCell | undefined; policy: CapabilityMap['policy'] | undefined; onOpen: () => void }) {
  if (!isMeasured(cell)) {
    return (
      <div
        data-testid="cell-not-measured"
        className="flex h-full min-h-[92px] flex-col items-center justify-center rounded-[var(--radius-control)] border border-dashed border-border px-2 py-2 text-center"
      >
        <VerdictPill route={NOT_YET_MEASURED} size="xs" />
        <span className="mt-1 text-[10px] text-on-surface-muted">n = 0</span>
      </div>
    )
  }
  const bad = cell.false_q1 > 0
  const tier = tierDisplay(cell.verification_tier)
  return (
    <button
      type="button"
      onClick={onOpen}
      data-testid={bad ? 'cell-false-q1' : 'cell-measured'}
      aria-label={`${cell.capability_class} ${cell.size}: ${cell.route}, n ${cell.n}, point ${fmtPct(cell.point)}, false-Q1 ${cell.false_q1}`}
      className={`flex h-full min-h-[92px] w-full flex-col gap-1 rounded-[var(--radius-control)] border px-2 py-2 text-left hover:bg-surface-high ${
        bad ? 'border-status-red bg-status-red-soft' : 'border-border bg-surface-container'
      }`}
    >
      <div className="flex items-center justify-between gap-1">
        <VerdictPill route={cell.route} size="xs" reason={cell.reason} />
        <span className="num text-[10px] text-on-surface-muted">n={fmtInt(cell.n)}</span>
      </div>
      <div className="num flex items-baseline gap-1">
        <span className="text-[15px] font-semibold text-on-surface" title={`clean ${fmtInt(cell.clean)} of ${fmtInt(cell.n)} eligible rows — the all-rows rate that routes`}>{fmtPct(cell.point)}</span>
        <span className="text-[10px] text-on-surface-muted">
          [{fmtPct(cell.ci_low, 0)}, {fmtPct(cell.ci_high, 0)}]
        </span>
        <span className="text-[10px] text-on-surface-muted">clean {fmtInt(cell.clean)}/{fmtInt(cell.n)}</span>
      </div>
      <CiBar point={cell.point} low={cell.ci_low} high={cell.ci_high} n={cell.n} minPoint={policy?.min_point} minCiLow={policy?.min_ci_low} width={110} />
      {cell.failure_split && (
        <div className="flex flex-wrap items-center gap-x-2">
          <ModelPointLine modelPoint={cell.model_point ?? null} modelN={cell.model_n ?? 0} clean={cell.clean} />
          <FailureSplitPills split={cell.failure_split} />
        </div>
      )}
      <div className="num flex flex-wrap items-center gap-x-2 text-[10px] text-on-surface-muted">
        <span className={bad ? 'font-semibold text-status-red' : ''} data-testid="cell-false-q1-value">
          fQ1 {cell.false_q1}
          {bad ? ' ✗' : ''}
        </span>
        <span>{fmtUsd(cell.cost_usd_mean)}</span>
        <span>{fmtSeconds(cell.latency_s_mean)}</span>
        <span title="oracle strength (mean)">or {fmtRatio(cell.oracle_strength_mean)}</span>
        {tier && (
          <span className={`${tier.tone === 'green' ? 'text-status-green' : tier.tone === 'red' ? 'text-status-red' : 'text-status-amber'}`} title={tier.describe}>
            {tier.glyph}
          </span>
        )}
      </div>
    </button>
  )
}

function CellDetail({ cell, repo, onClose }: { cell: CapabilityCell; repo: string; onClose: () => void }) {
  const tier = tierDisplay(cell.verification_tier)
  const ci = wilson(cell.clean, cell.n)
  return (
    <Card
      title={`${cell.capability_class} × ${cell.size}${cell.language ? ` × ${cell.language}` : ''}${cell.model ? ` × ${cell.model}` : ''}`}
      eyebrow="cell"
      actions={
        <button type="button" onClick={onClose} className="text-xs text-on-surface-muted hover:text-on-surface">
          close
        </button>
      }
    >
      <div className="space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <VerdictPill route={cell.route} reason={cell.reason} />
          {tier && (
            <Pill tone={tier.tone} glyph={tier.glyph} size="xs" label={tier.describe}>
              {tier.label}
            </Pill>
          )}
          <Provenance apparatus={cell.apparatus_versions} beltSet={cell.belt_set ?? null} />
        </div>
        <p className="text-sm" data-testid="cell-reason">
          {cell.reason_code && (
            <code className="mr-2 rounded bg-surface-high px-1 py-0.5 font-mono text-[11px]" title={REASON_DISPLAY[cell.reason_code]}>
              {cell.reason_code}
            </code>
          )}
          {cell.reason}
        </p>
        {cell.failure_split && (
          <div className="flex flex-wrap items-center gap-3 text-xs" data-testid="cell-split">
            <span className="label">Why not clean</span>
            <FailureSplitPills split={cell.failure_split} size="sm" data-testid="cell-split-pills" />
            <span className="text-on-surface-muted">
              n = clean + red + budget + protocol + harness; DQ sits outside n. Instrument rows (protocol, harness) count against autonomy until the instrument is fixed.
            </span>
          </div>
        )}
        <div className="flex flex-wrap gap-3">
          <StatTile label="Pass rate (all rows)" value={fmtPct(cell.point)} n={cell.n} ci={{ low: cell.ci_low, high: cell.ci_high }} apparatus={`${fmtInt(cell.clean)} clean of ${fmtInt(cell.n)} eligible · Wilson 95% · the rate that routes`} data-testid="tile-point" />
          {cell.failure_split && (
            <StatTile
              label="Model rate (fair attempts)"
              value={cell.model_point === null || cell.model_point === undefined ? '—' : fmtPct(cell.model_point)}
              n={cell.model_n ?? 0}
              ci={cell.model_point === null || cell.model_point === undefined ? null : { low: cell.model_ci_low, high: cell.model_ci_high }}
              apparatus={`${fmtInt(cell.clean)} clean of ${fmtInt(cell.model_n ?? 0)} finished attempts (clean + red) · Wilson 95% · diagnostic, not a gate`}
              data-testid="tile-model-point"
            />
          )}
          <StatTile label="false-Q1" value={String(cell.false_q1)} n={cell.n} apparatus="clean rows with a failed belt — must be 0" tone={cell.false_q1 > 0 ? 'red' : 'green'} />
          <StatTile label="Cost / trial" value={fmtUsd(cell.cost_usd_mean)} n={cell.n} apparatus="mean of builder-reported USD" />
          <StatTile label="Latency / trial" value={fmtSeconds(cell.latency_s_mean)} n={cell.n} apparatus="mean wall-clock of the build" />
          <StatTile label="Oracle strength" value={fmtRatio(cell.oracle_strength_mean)} n={cell.n} apparatus="mean mutation kill-rate of the tasks' oracles" />
        </div>
        {(Math.abs(ci.low - cell.ci_low) > 0.01 || Math.abs(ci.high - cell.ci_high) > 0.01) && (
          <p className="text-xs text-status-amber" role="status">
            The interval recomputed in the browser ({fmtPct(ci.low)}–{fmtPct(ci.high)}) differs from the server's — the server's is shown; the drift is flagged, not hidden.
          </p>
        )}
        <div className="flex flex-wrap gap-2">
          <LinkButton size="sm" to={`/ledger?repo=${encodeURIComponent(repo)}&capability_class=${encodeURIComponent(cell.capability_class)}&size=${encodeURIComponent(cell.size)}`}>
            Rows in ledger
          </LinkButton>
          <LinkButton size="sm" to={`/routing?repo=${encodeURIComponent(repo)}`}>
            Routing decision
          </LinkButton>
        </div>
      </div>
    </Card>
  )
}

function ControlsTile({ verdict, policy }: { verdict: ControlsVerdict | undefined; policy: CapabilityMap['policy'] | undefined }) {
  const d = controlsDisplay(verdict)
  const measured = Boolean(verdict?.measured)
  const value = !measured ? '—' : verdict!.state === 'failed' ? 'FAILED' : verdict!.state === 'escaped' ? `${verdict!.escapes} escape${verdict!.escapes === 1 ? '' : 's'}` : verdict!.state === 'thin' ? 'thin' : 'passed'
  return (
    <div data-testid="tile-controls" className="min-w-[150px] flex-[1_1_150px] rounded-[var(--radius-card)] border border-border bg-surface-container px-4 py-3 shadow-[var(--shadow-card)]">
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
    </div>
  )
}

export function CapabilityPage() {
  const [repo, setRepo] = useRepoParam()
  const [byLanguage, setByLanguage] = useState(false)
  const [byModel, setByModel] = useState(false)
  const [language, setLanguage] = useState('')
  const [model, setModel] = useState('')
  const [selected, setSelected] = useState<CapabilityCell | null>(null)

  const projection = useMemo<CellField[]>(() => {
    const p: CellField[] = ['capability_class', 'size']
    if (byLanguage) p.push('language')
    if (byModel) p.push('model')
    return p
  }, [byLanguage, byModel])

  const map = useCapabilityMapWithControls(repo, projection)

  return (
    <>
      <PageHeader
        eyebrow="Capability"
        title="Capability map"
        purpose="Per (class × size) cell: the measured pass rate with its n and Wilson interval, the false-Q1 count (must read 0), cost, latency and oracle strength — and the route that evidence licenses. Unmeasured cells say so."
        actions={
          <>
            <RepoPicker value={repo} onChange={setRepo} />
            {repo && map.data && <ControlsPill verdict={map.data.controls} />}
            {repo && (
              <AnchorButton size="sm" href={apiUrl(`/ledger/export?format=csv&repo=${encodeURIComponent(repo)}`)} download>
                Export CSV
              </AnchorButton>
            )}
          </>
        }
      />
      <QueryBoundary
        query={map}
        loading="Computing cell statistics from the ledger…"
        idle={<EmptyState title="Choose a repo to see its capability map" reason="The map is computed from the ledger's rows for one repository at a time." action={<LinkButton to="/repos">Go to repos</LinkButton>} />}
      >
        {(m) => {
          const classes = m.classes.length ? m.classes : ALL_CLASSES
          const sizes = (m.sizes.length ? [...m.sizes] : SIZE_ORDER).sort((a, b) => SIZE_ORDER.indexOf(a) - SIZE_ORDER.indexOf(b))
          const languages = m.languages ?? []
          const models = m.models ?? []
          const visible = m.cells.filter((c) => (!byLanguage || !language || c.language === language) && (!byModel || !model || c.model === model))
          const index = new Map(visible.map((c) => [cellKey(c, ['capability_class', 'size']), c]))
          const s = m.summary
          const measured = visible.filter(isMeasured)
          const nTotal = measured.reduce((a, c) => a + c.n, 0)
          const badCells = measured.filter((c) => c.false_q1 > 0).length
          const grid = classes.length * sizes.length
          const covApp = `${fmtInt(s.deliver_cells)} deliver of ${fmtInt(s.total_cells || grid)} cells · policy ${m.policy?.version ?? '—'}`
          return (
            <div className="space-y-6">
              <div className="flex flex-wrap gap-3">
                <StatTile label="Trusted autonomy coverage" value={fmtPct(s.trusted_autonomy_coverage)} n={s.n_total ?? nTotal} apparatus={covApp} tone="primary" data-testid="tile-coverage" hint="Share of the repo's change volume whose cell routes to deliver." />
                <StatTile label="Measured cells" value={`${fmtInt(s.measured_cells)} / ${fmtInt(s.total_cells || grid)}`} n={s.n_total ?? nTotal} apparatus={`apparatus ${s.apparatus_versions?.join('/') || '—'}`} />
                <StatTile
                  label="false-Q1 total"
                  value={String(s.false_q1_total ?? 0)}
                  n={s.n_total ?? nTotal}
                  apparatus="clean rows with a failed belt, across the map — must be 0"
                  tone={(s.false_q1_total ?? 0) > 0 || badCells > 0 ? 'red' : 'green'}
                  data-testid="tile-false-q1"
                />
                <ControlsTile verdict={m.controls} policy={m.policy} />
              </div>

              {((s.false_q1_total ?? 0) > 0 || badCells > 0) && (
                <div role="alert" className="rounded-[var(--radius-card)] border-2 border-status-red bg-status-red-soft px-5 py-3 text-sm text-status-red" data-testid="false-q1-alert">
                  <strong>✗ false-Q1 &gt; 0.</strong> {badCells} cell{badCells === 1 ? ' contains' : 's contain'} a clean row whose belts did not all hold. The write-time invariant should have made this impossible; treat every number on this page as untrusted until the ledger is audited (<Link to="/ledger">verify chain</Link>).
                </div>
              )}

              <Card
                title="Cells"
                eyebrow={`class × size${byLanguage ? ' × language' : ''}${byModel ? ' × model' : ''}`}
                actions={
                  <>
                    <label className="inline-flex items-center gap-1.5 text-xs text-on-surface-muted">
                      <input type="checkbox" checked={byLanguage} onChange={(e) => setByLanguage(e.target.checked)} /> by language
                    </label>
                    {byLanguage && (
                      <InlineSelect label="Language" value={language} onChange={(e) => setLanguage(e.target.value)}>
                        <option value="">all</option>
                        {languages.map((l) => (
                          <option key={l} value={l}>
                            {l}
                          </option>
                        ))}
                      </InlineSelect>
                    )}
                    <label className="inline-flex items-center gap-1.5 text-xs text-on-surface-muted">
                      <input type="checkbox" checked={byModel} onChange={(e) => setByModel(e.target.checked)} /> by model
                    </label>
                    {byModel && (
                      <InlineSelect label="Model" value={model} onChange={(e) => setModel(e.target.value)}>
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
                    reason="Every cell below would read NOT_YET_MEASURED. Run a replay to produce ledger rows; each graded trial is one observation in its (class × size) cell."
                    action={<LinkButton to={`/runs?repo=${encodeURIComponent(repo)}&new=replay`}>Start a replay run</LinkButton>}
                  />
                ) : (
                  <div className="overflow-auto">
                    <table className="w-full border-separate border-spacing-1">
                      <caption className="sr-only">Capability map for {repo}: rows are capability classes, columns are size tiers</caption>
                      <thead>
                        <tr>
                          <th scope="col" className="label sticky left-0 bg-surface-container px-2 text-left">
                            Class
                          </th>
                          {sizes.map((sz) => (
                            <th key={sz} scope="col" className="label px-2 text-left">
                              {sz}
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
                              const cell = index.get(`${cls}|${sz}`)
                              return (
                                <td key={sz} className="min-w-[150px] align-top">
                                  <CellBox cell={cell} policy={m.policy} onOpen={() => cell && setSelected(cell)} />
                                </td>
                              )
                            })}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
                <p className="mt-3 text-[11px] text-on-surface-muted">
                  Each cell: route · n · pass rate [Wilson 95%] · clean n/N · interval bar with policy ticks (point ≥ {fmtPct(m.policy?.min_point, 0)}, lower ≥ {fmtPct(m.policy?.min_ci_low, 0)}) · model rate on fair attempts (clean / (clean + red)) · the split red · budget · protocol · harness · DQ · fQ1 (false-Q1, must be 0) · mean cost · mean latency · or (oracle strength). Every cell is routed under the repo's controls verdict shown above.
                </p>
              </Card>

              {selected && <CellDetail cell={selected} repo={repo} onClose={() => setSelected(null)} />}
            </div>
          )
        }}
      </QueryBoundary>
    </>
  )
}

export default CapabilityPage
