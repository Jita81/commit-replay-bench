/**
 * Routing — what the factory may do with each class of change, decided by the one published rule
 * (/routing).
 *
 * Navigation
 * ----------
 * What it is:   The screen at /routing: the policy in force, one tile per route with its cell
 *               count, and the decisions table.
 * What it does: Renders `GET /routes?repo=` — a `RouteDecision` per measured cell with its
 *               route, reason code, n, point, Wilson lower bound, false-Q1, oracle strength,
 *               the model rate and split, and the policy version that produced it. The policy
 *               card states the rule in words with the thresholds in force, including the
 *               controls gate; the controls verdict every decision was taken under is shown
 *               beside it. Each decision row carries two doors (G-253): Rows, to the ledger
 *               rows behind it (repo, class, size, and language, builder and model where the
 *               decision carries them — the ledger page filters by neither provider nor
 *               process step), and Map cell, to its class × size cell on the map with the
 *               detail open (`?cell=`). Reached without `?repo=`, the page shows the most
 *               recently updated repository, as Baseline does (G-977).
 * How:          `useRepoParam({ defaultToLatest })` → `useRoutesWithControls` → count decisions
 *               per route for the tiles → `DataTable` sorted by route. The interval bar's upper bound is
 *               synthesised symmetrically because a decision carries `ci_low` only (see the
 *               comment at the column).
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0003-one-routing-rule.md
 * Works with:   ui/src/screens/Capability/contract.ts (the extended decision type and the hook),
 *               ui/src/screens/Capability/ReasonCode.tsx (a reason code's sentence, inline),
 *               ui/src/screens/Capability/FailureSplit.tsx (controls pill, split, model point),
 *               ui/src/lib/auth.tsx (`can` — the run action is an operator's),
 *               ui/src/components/RepoPicker.tsx (`useRepoParam`), ui/src/api/types.ts
 *               (`RouteDecision`, `ROUTES`), ui/src/screens/Ledger/LedgerPage.tsx and
 *               ui/src/screens/Capability/CapabilityPage.tsx (where the doors land),
 *               src/crb/core/routing.py (`route()` — the rule this page describes),
 *               src/crb/server/routes/capability.py (the `/routes` route),
 *               ui/src/components/VerdictPill.tsx (the route pill with its sentence)
 * Tested by:    ui/src/screens/Routing/RoutingPage.test.tsx,
 *               ui/e2e/walkthrough/07-settings-and-a11y.spec.ts
 * Touch when:   never for a new repository; the routing policy gains a threshold or a reason
 *               code (an ADR-0003 amendment) — add it to the policy card and to
 *               ui/src/screens/Capability/contract.ts.
 * Claims:       A route is a decision under a named policy version over measured evidence;
 *               `deliver` licenses a branch + PR, never a merge
 *               (docs/EVIDENCE-AND-CLAIMS.md#7-what-must-never-be-said).
 */
import { useMemo } from 'react'
import type { RouteDecision } from '../../api/types'
import { LinkButton } from '../../components/Button'
import { Card } from '../../components/Card'
import { CiBar } from '../../components/CiBar'
import { DataTable, type Column } from '../../components/DataTable'
import { EmptyState } from '../../components/EmptyState'
import { Hint } from '../../components/Hint'
import { PageHeader } from '../../components/PageHeader'
import { QueryBoundary } from '../../components/QueryBoundary'
import { RepoPicker, useRepoParam } from '../../components/RepoPicker'
import { StatTile } from '../../components/StatTile'
import { VerdictPill } from '../../components/VerdictPill'
import { useAuth } from '../../lib/auth'
import { fmtInt, fmtPct, fmtRatio } from '../../lib/format'
import { ROUTES } from '../../api/types'
import { routeDisplay } from '../../lib/verdict'
import { useRoutesWithControls, type ControlsVerdict, type RouteDecisionWithControls, type RoutingPolicyWithControls } from '../Capability/contract'
import { ControlsPill, FailureSplitPills, ModelPointLine } from '../Capability/FailureSplit'
import { ReasonCode } from '../Capability/ReasonCode'

/** A decision as the base contract types it, with the A2 fields optional so an older server still renders. */
type Decision = RouteDecision & Partial<RouteDecisionWithControls>

/** `{"20": 0, "30": 1, "40": 2}` → `20/20 · 29/30 · 38/40` — the look rule's deliver points. */
export function lookText(looks: Record<string, number> | undefined): string {
  if (!looks) return '—'
  return Object.entries(looks)
    .map(([n, m]) => [Number(n), m] as const)
    .sort((a, b) => a[0] - b[0])
    .map(([n, m]) => `${n - m}/${n}`)
    .join(' · ')
}

/** The thresholds in force and the rule in words — the same rule `crb.core.routing.route` applies. */
function PolicyCard({ policy, controls }: { policy: RoutingPolicyWithControls; controls?: ControlsVerdict }) {
  return (
    <Card title="Policy in force" eyebrow={`${policy.version}${policy.controls_version ? ` + ${policy.controls_version}` : ''}`} actions={<ControlsPill verdict={controls} />}>
      <dl className="num grid gap-x-6 gap-y-1 text-sm sm:grid-cols-2 lg:grid-cols-5">
        <div>
          <Hint as="dt" id="policy.routing.rule" className="label">
            look rule
          </Hint>
          <dd className="font-mono text-xs">{policy.rule}</dd>
        </div>
        <div>
          <Hint as="dt" id="policy.routing.looks" className="label">
            deliver at
          </Hint>
          <dd>{lookText(policy.looks)}</dd>
        </div>
        <div>
          <Hint as="dt" id="policy.routing.budget" className="label">
            error budget per cell
          </Hint>
          <dd>{fmtRatio(policy.cell_error_budget)}</dd>
        </div>
        <div>
          <Hint as="dt" id="policy.routing.min_oracle" className="label">
            min oracle strength
          </Hint>
          <dd>{fmtRatio(policy.min_oracle_strength)}</dd>
        </div>
        <div>
          <Hint as="dt" id="policy.routing.min_oracle_share" className="label">
            min commits scored
          </Hint>
          <dd>{fmtPct(policy.min_oracle_share, 0)}</dd>
        </div>
        <div>
          <Hint as="dt" id="policy.routing.granularize" className="label">
            granularize sizes
          </Hint>
          <dd className="font-mono text-xs">{policy.granularize_sizes.join(', ') || '—'}</dd>
        </div>
        {policy.controls_version && (
          <>
            <div>
              <Hint as="dt" id="policy.routing.min_controls_share" className="label">
                min controls constructible
              </Hint>
              <dd>{fmtPct(policy.min_controls_share, 0)}</dd>
            </div>
            <div>
              <Hint as="dt" id="policy.routing.max_escapes" className="label">
                max controls escapes
              </Hint>
              <dd>{fmtInt(policy.max_controls_escapes)}</dd>
            </div>
          </>
        )}
      </dl>
      {/* the published bar, word for word as the server renders it (RoutingPolicy.describe — README carries the same sentence) */}
      <Hint as="p" id="tile.routing.rule" className="mt-3 text-xs text-on-surface-muted" data-testid="policy-rule">
        {policy.description}
      </Hint>
    </Card>
  )
}

/** `class · size[ · language · builder · model · provider]` — the projected key fields present. */
const cellLabel = (c: Record<string, string>) =>
  [c.capability_class, c.size, c.language, c.builder, c.model, c.provider].filter(Boolean).join(' · ')

/** A key field the decision carries: present and not the `*` of an unprojected dimension. */
const carried = (v: string | undefined): v is string => Boolean(v) && v !== '*'

/**
 * The ledger rows behind a decision: the ledger's own filters — repo, class and size, plus
 * language, builder and model when the decision carries them. Provider and process step are
 * not filters the ledger page reads, so a decision projected by either opens every row of
 * its class and size (the hint says so).
 */
export function ledgerRowsUrl(repo: string, cell: Record<string, string>): string {
  const q = new URLSearchParams({ repo, capability_class: cell.capability_class ?? '', size: cell.size ?? '' })
  for (const k of ['language', 'builder', 'model'] as const) {
    const v = cell[k]
    if (carried(v)) q.set(k, v)
  }
  return `/ledger?${q.toString()}`
}

/** The decision's class × size cell on the map, with its detail open on arrival (`?cell=`). */
export function mapCellUrl(repo: string, cell: Record<string, string>): string {
  return `/capability?repo=${encodeURIComponent(repo)}&cell=${encodeURIComponent(`${cell.capability_class}|${cell.size}`)}`
}

/** The screen; `?repo=` from the URL (the latest repository when absent). */
export function RoutingPage() {
  const [repo, setRepo] = useRepoParam({ defaultToLatest: true })
  const { can } = useAuth()
  const routes = useRoutesWithControls(repo)

  const columns = useMemo<Column<Decision>[]>(
    () => [
      { key: 'cell', header: 'Cell', hint: 'col.routing.cell', mono: true, sortValue: (d) => cellLabel(d.cell), cell: (d) => cellLabel(d.cell) },
      { key: 'route', header: 'Route', hint: 'col.routing.route', sortValue: (d) => ROUTES.indexOf(d.route), cell: (d) => <VerdictPill route={d.route} reason={d.reason} size="xs" /> },
      {
        key: 'code',
        header: 'Why',
        hint: 'col.routing.code',
        mono: true,
        sortValue: (d) => d.reason_code ?? '',
        cell: (d) => (d.reason_code ? <ReasonCode code={d.reason_code} /> : <span className="text-xs text-on-surface-muted">—</span>),
      },
      { key: 'n', header: 'n', hint: 'col.routing.n', numeric: true, sortValue: (d) => d.n, cell: (d) => fmtInt(d.n) },
      { key: 'point', header: 'Point', hint: 'col.routing.point', numeric: true, sortValue: (d) => d.point, cell: (d) => fmtPct(d.point) },
      {
        key: 'model',
        header: 'Model rate · split',
        hint: 'col.routing.model_split',
        sortValue: (d) => d.model_point ?? -1,
        cell: (d) =>
          d.failure_split ? (
            <span className="inline-flex flex-col gap-0.5">
              <ModelPointLine modelPoint={d.model_point ?? null} modelN={d.model_n ?? 0} clean={Math.round(d.point * d.n)} ciLow={d.model_ci_low ?? null} ciHigh={d.model_ci_high ?? null} apparatus={d.apparatus_versions} size="xs" />
              <FailureSplitPills split={d.failure_split} />
            </span>
          ) : (
            <span className="text-xs text-on-surface-muted">—</span>
          ),
        hideBelowMd: true,
      },
      { key: 'ci_low', header: 'Wilson lower', hint: 'col.routing.ci_low', numeric: true, sortValue: (d) => d.ci_low, cell: (d) => fmtPct(d.ci_low) },
      // The server's own asymmetric Wilson interval (`ci_high` is served beside the
      // `ci_low` that routes) with the apparatus + belt-set provenance in the label — never
      // an upper bound mirrored from the lower one (CodeRabbit on PR #6).
      { key: 'bar', header: 'Interval', hint: 'col.routing.interval', cell: (d) => <CiBar point={d.point} low={d.ci_low} high={d.ci_high} n={d.n} width={80} provenance={`apparatus ${d.apparatus_versions?.join('/') || '—'} · belts ${d.belt_sets?.join('/') || '—'}`} />, hideBelowMd: true },
      { key: 'fq1', header: 'false-Q1', hint: 'col.routing.false_q1', numeric: true, sortValue: (d) => d.false_q1, cell: (d) => <span className={d.false_q1 > 0 ? 'font-semibold text-status-red' : ''}>{d.false_q1}{d.false_q1 > 0 ? ' ✗' : ''}</span> },
      { key: 'oracle', header: 'Oracle', hint: 'col.routing.oracle', numeric: true, sortValue: (d) => d.oracle_strength ?? -1, cell: (d) => fmtRatio(d.oracle_strength), hideBelowMd: true },
      { key: 'reason', header: 'Reason', hint: 'col.routing.reason', sortValue: (d) => d.reason, cell: (d) => <span className="text-xs text-on-surface-muted">{d.reason}</span> },
      { key: 'policy', header: 'Policy', hint: 'col.routing.policy', mono: true, cell: (d) => d.policy_version, hideBelowMd: true },
      // the doors (G-253): the same two the Capability detail offers, from the decision itself
      {
        key: 'doors',
        header: 'Doors',
        hint: 'col.routing.doors',
        cell: (d) => (
          <span className="inline-flex flex-wrap gap-1">
            <LinkButton size="sm" to={ledgerRowsUrl(repo, d.cell)} hint="button.routing.rows">
              Rows
            </LinkButton>
            <LinkButton size="sm" to={mapCellUrl(repo, d.cell)} hint="button.routing.map_cell">
              Map cell
            </LinkButton>
          </span>
        ),
        hideBelowMd: true,
      },
    ],
    [repo],
  )

  return (
    <>
      <PageHeader
        eyebrow="Instrument · Routes"
        title="Routing"
        purpose="What the factory may do with each class of change, decided by the one published rule over measured evidence. Every decision carries its reason and the policy version that produced it."
        actions={<RepoPicker value={repo} onChange={setRepo} />}
      />
      <QueryBoundary query={routes} loading="Loading route decisions…" idle={<EmptyState title="Choose a repo to see its routing decisions" reason="Routes are derived from the repo's capability cells." action={<LinkButton to="/connect">Connect a repository</LinkButton>} />}>
        {(r) => {
          const counts = new Map<string, number>()
          for (const d of r.decisions) counts.set(d.route, (counts.get(d.route) ?? 0) + 1)
          const total = r.decisions.length
          return (
            <div className="space-y-6">
              <PolicyCard policy={r.policy} controls={r.controls} />
              <div className="flex flex-wrap gap-3">
                {ROUTES.map((route) => {
                  const d = routeDisplay(route)
                  const n = counts.get(route) ?? 0
                  return <StatTile key={route} label={d.label} hint="stat.routing.route_count" value={fmtInt(n)} n={total} apparatus={`cells routed ${route} · ${r.policy.version}`} tone={n ? d.tone : undefined} />
                })}
              </div>
              <Card padded={false} title="Decisions">
                <DataTable
                  rows={r.decisions}
                  columns={columns}
                  rowKey={(d) => cellLabel(d.cell)}
                  caption={`Route decisions for ${repo}`}
                  initialSort={{ key: 'route', dir: 'asc' }}
                  empty={
                    can('operator') ? (
                      <EmptyState title="No decisions yet" reason="A decision exists per measured cell. Run a replay to populate the ledger." action={<LinkButton to={`/runs?repo=${encodeURIComponent(repo)}&new=replay`} hint="button.capability.start_replay">Start a replay run</LinkButton>} />
                    ) : (
                      <EmptyState title="No decisions yet" reason="A decision exists per measured cell; an operator starts a replay run to populate the ledger." />
                    )
                  }
                />
              </Card>
            </div>
          )
        }}
      </QueryBoundary>
    </>
  )
}

export default RoutingPage
