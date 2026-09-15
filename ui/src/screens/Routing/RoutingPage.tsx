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
 *               beside it.
 * How:          `useRepoParam` → `useRoutesWithControls` → count decisions per route for the
 *               tiles → `DataTable` sorted by route. The interval bar's upper bound is
 *               synthesised symmetrically because a decision carries `ci_low` only (see the
 *               comment at the column).
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0003-one-routing-rule.md
 * Works with:   ui/src/screens/Capability/contract.ts (the extended decision type, the hook,
 *               `REASON_DISPLAY`), ui/src/screens/Capability/FailureSplit.tsx (controls pill,
 *               split, model point), ui/src/api/types.ts (`RouteDecision`, `ROUTES`),
 *               src/crb/core/routing.py (`route()` — the rule this page describes),
 *               src/crb/server/routes/capability.py (the `/routes` route),
 *               ui/src/components/VerdictPill.tsx and ui/src/components/CiBar.tsx
 * Tested by:    ui/src/screens/Routing/RoutingPage.test.tsx,
 *               ui/e2e/walkthrough/07-settings-and-a11y.spec.ts
 * Touch when:   the routing policy gains a threshold or a reason code (an ADR-0003 amendment)
 *               — add it to the policy card and to ui/src/screens/Capability/contract.ts;
 *               never for a new repository.
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
import { PageHeader } from '../../components/PageHeader'
import { QueryBoundary } from '../../components/QueryBoundary'
import { RepoPicker, useRepoParam } from '../../components/RepoPicker'
import { StatTile } from '../../components/StatTile'
import { VerdictPill } from '../../components/VerdictPill'
import { fmtInt, fmtPct, fmtRatio } from '../../lib/format'
import { ROUTES } from '../../api/types'
import { routeDisplay } from '../../lib/verdict'
import { REASON_DISPLAY, useRoutesWithControls, type ControlsVerdict, type RouteDecisionWithControls, type RoutingPolicyWithControls } from '../Capability/contract'
import { ControlsPill, FailureSplitPills, ModelPointLine } from '../Capability/FailureSplit'

/** A decision as the base contract types it, with the A2 fields optional so an older server still renders. */
type Decision = RouteDecision & Partial<RouteDecisionWithControls>

/** The thresholds in force and the rule in words — the same rule `crb.core.routing.route` applies. */
function PolicyCard({ policy, controls }: { policy: RoutingPolicyWithControls; controls?: ControlsVerdict }) {
  return (
    <Card title="Policy in force" eyebrow={`${policy.version}${policy.controls_version ? ` + ${policy.controls_version}` : ''}`} actions={<ControlsPill verdict={controls} />}>
      <dl className="num grid gap-x-6 gap-y-1 text-sm sm:grid-cols-2 lg:grid-cols-5">
        <div>
          <dt className="label">min n</dt>
          <dd>{fmtInt(policy.min_n)}</dd>
        </div>
        <div>
          <dt className="label">min point</dt>
          <dd>{fmtPct(policy.min_point, 0)}</dd>
        </div>
        <div>
          <dt className="label">min Wilson lower</dt>
          <dd>{fmtPct(policy.min_ci_low, 0)}</dd>
        </div>
        <div>
          <dt className="label">min oracle strength</dt>
          <dd>{fmtRatio(policy.min_oracle_strength)}</dd>
        </div>
        <div>
          <dt className="label">granularize sizes</dt>
          <dd className="font-mono text-xs">{policy.granularize_sizes.join(', ') || '—'}</dd>
        </div>
        {policy.controls_version && (
          <>
            <div>
              <dt className="label">min controls constructible</dt>
              <dd>{fmtPct(policy.min_controls_share, 0)}</dd>
            </div>
            <div>
              <dt className="label">max controls escapes</dt>
              <dd>{fmtInt(policy.max_controls_escapes)}</dd>
            </div>
          </>
        )}
      </dl>
      <p className="mt-3 text-xs text-on-surface-muted" data-testid="policy-rule">
        The one rule: <em>deliver</em> iff n ≥ {policy.min_n} ∧ point ≥ {fmtPct(policy.min_point, 0)} ∧ Wilson-lower ≥ {fmtPct(policy.min_ci_low, 0)} ∧ false-Q1 = 0 ∧ (oracle strength ≥ {fmtRatio(policy.min_oracle_strength)} when measured)
        {policy.controls_version ? <> ∧ negative controls passed ∧ ≥ {fmtPct(policy.min_controls_share, 0)} of control rows constructible ∧ escapes ≤ {fmtInt(policy.max_controls_escapes)}</> : null}. Any false-Q1 ⇒ <em>do not ship</em>; XL ⇒ <em>granularize</em>; a FAILED controls gate, a weak oracle or an escaped control ⇒ <em>human</em>; controls unmeasured or thin ⇒ <em>calibrate</em>; otherwise <em>calibrate</em>. The all-rows point routes; the model rate on fair attempts is shown beside it, never instead of it.
      </p>
    </Card>
  )
}

/** `class · size[ · language · builder · model · provider]` — the projected key fields present. */
const cellLabel = (c: Record<string, string>) =>
  [c.capability_class, c.size, c.language, c.builder, c.model, c.provider].filter(Boolean).join(' · ')

/** The screen; `?repo=` from the URL. */
export function RoutingPage() {
  const [repo, setRepo] = useRepoParam()
  const routes = useRoutesWithControls(repo)

  const columns = useMemo<Column<Decision>[]>(
    () => [
      { key: 'cell', header: 'Cell', mono: true, sortValue: (d) => cellLabel(d.cell), cell: (d) => cellLabel(d.cell) },
      { key: 'route', header: 'Route', sortValue: (d) => ROUTES.indexOf(d.route), cell: (d) => <VerdictPill route={d.route} reason={d.reason} size="xs" /> },
      {
        key: 'code',
        header: 'Why',
        mono: true,
        sortValue: (d) => d.reason_code ?? '',
        cell: (d) => (d.reason_code ? <code className="rounded bg-surface-high px-1 py-0.5 text-[11px]" title={REASON_DISPLAY[d.reason_code]} data-testid="reason-code">{d.reason_code}</code> : <span className="text-xs text-on-surface-muted">—</span>),
      },
      { key: 'n', header: 'n', numeric: true, sortValue: (d) => d.n, cell: (d) => fmtInt(d.n) },
      { key: 'point', header: 'Point', numeric: true, sortValue: (d) => d.point, cell: (d) => fmtPct(d.point) },
      {
        key: 'model',
        header: 'Model rate · split',
        sortValue: (d) => d.model_point ?? -1,
        cell: (d) =>
          d.failure_split ? (
            <span className="inline-flex flex-col gap-0.5">
              <ModelPointLine modelPoint={d.model_point ?? null} modelN={d.model_n ?? 0} clean={Math.round(d.point * d.n)} size="xs" />
              <FailureSplitPills split={d.failure_split} />
            </span>
          ) : (
            <span className="text-xs text-on-surface-muted">—</span>
          ),
        hideBelowMd: true,
      },
      { key: 'ci_low', header: 'Wilson lower', numeric: true, sortValue: (d) => d.ci_low, cell: (d) => fmtPct(d.ci_low) },
      // A RouteDecision carries `ci_low` only (the bound that routes), so the bar's upper
      // end is mirrored from the lower one. The Wilson interval is asymmetric, so this is a
      // glance aid; the capability page draws the server's true interval.
      { key: 'bar', header: 'Interval', cell: (d) => <CiBar point={d.point} low={d.ci_low} high={Math.min(1, d.point + (d.point - d.ci_low))} n={d.n} width={80} />, hideBelowMd: true },
      { key: 'fq1', header: 'false-Q1', numeric: true, sortValue: (d) => d.false_q1, cell: (d) => <span className={d.false_q1 > 0 ? 'font-semibold text-status-red' : ''}>{d.false_q1}{d.false_q1 > 0 ? ' ✗' : ''}</span> },
      { key: 'oracle', header: 'Oracle', numeric: true, sortValue: (d) => d.oracle_strength ?? -1, cell: (d) => fmtRatio(d.oracle_strength), hideBelowMd: true },
      { key: 'reason', header: 'Reason', sortValue: (d) => d.reason, cell: (d) => <span className="text-xs text-on-surface-muted">{d.reason}</span> },
      { key: 'policy', header: 'Policy', mono: true, cell: (d) => d.policy_version, hideBelowMd: true },
    ],
    [],
  )

  return (
    <>
      <PageHeader
        eyebrow="Routing"
        title="Routing"
        purpose="What the factory may do with each class of change, decided by the one published rule over measured evidence. Every decision carries its reason and the policy version that produced it."
        actions={<RepoPicker value={repo} onChange={setRepo} />}
      />
      <QueryBoundary query={routes} loading="Loading route decisions…" idle={<EmptyState title="Choose a repo to see its routing decisions" reason="Routes are derived from the repo's capability cells." action={<LinkButton to="/repos">Go to repos</LinkButton>} />}>
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
                  return <StatTile key={route} label={d.label} value={fmtInt(n)} n={total} apparatus={`cells routed ${route} · ${r.policy.version}`} tone={n ? d.tone : undefined} />
                })}
              </div>
              <Card padded={false} title="Decisions">
                <DataTable
                  rows={r.decisions}
                  columns={columns}
                  rowKey={(d) => cellLabel(d.cell)}
                  caption={`Route decisions for ${repo}`}
                  initialSort={{ key: 'route', dir: 'asc' }}
                  empty={<EmptyState title="No decisions yet" reason="A decision exists per measured cell. Run a replay to populate the ledger." action={<LinkButton to={`/runs?repo=${encodeURIComponent(repo)}&new=replay`}>Start a replay run</LinkButton>} />}
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
