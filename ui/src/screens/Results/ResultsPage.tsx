/**
 * Results — what the evidence says about one repository, and what it does not.
 *
 * Navigation
 * ----------
 * What it is:   The destination of the connection walk (/results?repo=): the instrument's
 *               standing on the repository (controls, oracle, false-Q1), the routes the rule
 *               produced (how many cells deliver / calibrate / human, with n), the decisions
 *               waiting on a person for this repository, and the doors into the full map,
 *               the routes with their reasons, the oracle and the ledger.
 * What it does: Gives an enterprise reader the answer in the order they need it — is the
 *               instrument trustworthy here, what may the builder be trusted to do, what is
 *               waiting on me — before any grid. Every number keeps its n and its apparatus;
 *               the page says in words what "deliver" means and does not mean.
 * How:          `useRepoParam` + `RepoPicker`; `useCapabilityMap` (summary + cells),
 *               `useOracleControls`, `useOracle`, `useSignoffs`, `useFactoryTasks` →
 *               `decisionsFor` for the "waiting on a person" panel; `StatTile`s for the
 *               headline; links to the existing detail screens.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0003-one-routing-rule.md
 * Works with:   ui/src/screens/Capability/CapabilityPage.tsx (the full grid),
 *               ui/src/screens/Routing/RoutingPage.tsx (every decision with its reason),
 *               ui/src/screens/Decisions/decisions.ts, ui/src/screens/Connect/ConnectPage.tsx
 *               (the walk that leads here), docs/EVIDENCE-AND-CLAIMS.md
 * Tested by:    ui/src/screens/Results/ResultsPage.test.tsx
 * Touch when:   a headline fact is added to the map summary; the wording of what `deliver`
 *               means changes (EVIDENCE-AND-CLAIMS §6 first).
 */

import { useMemo } from 'react'
import { useCapabilityMap, useFactoryTasks, useOracle, useOracleControls, useSignoffs } from '../../api/hooks'
import { isApiError } from '../../api/client'
import { NOT_YET_MEASURED, type CapabilityCell } from '../../api/types'
import { LinkButton } from '../../components/Button'
import { Card } from '../../components/Card'
import { EmptyState } from '../../components/EmptyState'
import { ErrorState } from '../../components/ErrorState'
import { PageHeader } from '../../components/PageHeader'
import { Pill } from '../../components/Pill'
import { RepoPicker, useRepoParam } from '../../components/RepoPicker'
import { StatTile } from '../../components/StatTile'
import type { Tone } from '../../lib/verdict'
import { KIND_LABEL, decisionsFor } from '../Decisions/decisions'

const CONTROLS_TONE: Record<string, Tone> = { passed: 'green', failed: 'red', thin: 'amber', escaped: 'red', unmeasured: 'muted' }

function pct(x: number): string {
  return `${(x * 100).toFixed(0)}%`
}

export function ResultsPage() {
  const [repo, setRepo] = useRepoParam()
  const map = useCapabilityMap(repo, ['capability_class', 'size'])
  const controls = useOracleControls(repo)
  const oracle = useOracle(repo)
  const signoffs = useSignoffs(repo)
  const tasks = useFactoryTasks(repo)
  const q = `repo=${encodeURIComponent(repo)}`

  const measured: CapabilityCell[] = useMemo(() => (map.data?.cells ?? []).filter((c) => c.route !== NOT_YET_MEASURED && c.n > 0), [map.data])
  const byRoute = useMemo(() => {
    const out: Record<string, { cells: number; n: number }> = {}
    for (const c of measured) {
      const r = out[c.route] ?? { cells: 0, n: 0 }
      r.cells += 1
      r.n += c.n
      out[c.route] = r
    }
    return out
  }, [measured])
  const decisions = useMemo(
    () => (map.data && signoffs.data ? decisionsFor({ repo, cells: map.data.cells, signoffs: signoffs.data.items, tasks: tasks.data ?? [] }) : []),
    [repo, map.data, signoffs.data, tasks.data],
  )
  const controlsNotRun = controls.isError && isApiError(controls.error) && controls.error.status === 404
  const oracleNotRun = oracle.isError && isApiError(oracle.error) && oracle.error.status === 404
  const verdict = controls.data?.verdict
  const apparatus = map.data ? `apparatus ${map.data.summary.apparatus_versions.join(', ') || '—'} · Wilson 95%` : '—'
  const oracleMean = oracle.data && oracle.data.tasks.length > 0 ? oracle.data.tasks.reduce((a, t) => a + (t.strength ?? 0), 0) / oracle.data.tasks.length : null

  return (
    <>
      <PageHeader
        eyebrow="Journey · 2 of 4"
        title="Results"
        purpose="What the evidence says about this repository, in the order it matters: is the instrument trustworthy here, what may the builder be trusted to do, and what is waiting on a person."
        actions={<RepoPicker value={repo} onChange={setRepo} />}
      />
      {!repo && <EmptyState title="Choose a repository" reason="Results are per repository — a cell says nothing about a repository it was not measured on." action={<LinkButton to="/connect">Connect one</LinkButton>} />}
      {repo && map.isError && <ErrorState error={map.error} onRetry={() => void map.refetch()} />}
      {repo && map.data && (
        <>
          <Card title="Is the instrument trustworthy here?" eyebrow="the gates every number below stands under">
            <div className="grid gap-3 sm:grid-cols-3">
              <StatTile
                label="Negative controls"
                value={verdict ? verdict.state : controlsNotRun ? 'not run' : controls.isPending ? '…' : 'unknown'}
                n={controls.data?.n_rows ?? null}
                apparatus={controls.data ? `${controls.data.violations} violations · ${controls.data.escapes} escapes · ${controls.data.not_constructible} not constructible` : 'seven deliberate cheats the grader must catch'}
                tone={verdict ? CONTROLS_TONE[verdict.state] : 'muted'}
                hint={verdict ? undefined : 'run the controls from Connect'}
              />
              <StatTile
                label="Oracle strength"
                value={oracleMean === null ? (oracleNotRun ? 'not scored' : oracle.isPending ? '…' : 'unknown') : pct(oracleMean)}
                n={oracle.data?.tasks.length ?? null}
                apparatus="mean over scored tasks · ≥ 80% per cell to deliver"
                tone={oracleMean === null ? 'muted' : oracleMean >= 0.8 ? 'green' : 'amber'}
              />
              <StatTile label="False-Q1" value={String(map.data.summary.false_q1_total)} n={map.data.summary.n_total} apparatus={apparatus} tone={map.data.summary.false_q1_total === 0 ? 'green' : 'red'} hint="must be zero; refused at write" />
            </div>
          </Card>

          <Card title="What may the builder be trusted to do?" eyebrow="the routes, with n" actions={<LinkButton size="sm" to={`/capability?${q}`}>Open the full map</LinkButton>}>
            {measured.length === 0 ? (
              <EmptyState compact glyph="◌" title="Nothing measured yet" reason="A first sighted replay puts rows on the map." action={<LinkButton size="sm" to={`/connect/${encodeURIComponent(repo)}`}>Back to the walk</LinkButton>} />
            ) : (
              <>
                <div className="grid gap-3 sm:grid-cols-4">
                  {(['deliver', 'calibrate', 'granularize', 'human'] as const).map((r) => (
                    <StatTile
                      key={r}
                      label={r}
                      value={String(byRoute[r]?.cells ?? 0)}
                      n={byRoute[r]?.n ?? 0}
                      apparatus={`${byRoute[r]?.cells ?? 0} of ${measured.length} measured cells`}
                      tone={r === 'deliver' ? 'green' : r === 'human' ? 'amber' : 'muted'}
                    />
                  ))}
                </div>
                <p className="mt-3 max-w-[80ch] text-sm text-on-surface-body">
                  <strong>deliver</strong> means the cell clears the published bar (n ≥ {map.data.policy.min_n}, point ≥ {pct(map.data.policy.min_point)}, Wilson-low ≥ {pct(map.data.policy.min_ci_low)}, false-Q1 = 0, oracle ≥ {pct(map.data.policy.min_oracle_strength)}, controls passed) so the factory may open a branch and a pull request for that class of change under human review. It never means a change is safe to merge or deploy.
                </p>
                <ul className="m-0 mt-2 list-none space-y-1 p-0 text-sm">
                  {measured
                    .slice()
                    .sort((a, b) => b.n - a.n)
                    .slice(0, 8)
                    .map((c) => (
                      <li key={`${c.capability_class}|${c.size}`} className="flex flex-wrap items-center gap-2">
                        <span className="font-mono text-xs">
                          {c.capability_class} × {c.size}
                        </span>
                        <Pill tone={c.route === 'deliver' ? 'green' : c.route === 'human' ? 'amber' : c.route === 'do_not_ship' ? 'red' : 'muted'} size="xs">
                          {c.route}
                        </Pill>
                        <span className="num font-mono text-xs text-on-surface-muted">
                          n={c.n}
                          {c.n_tasks !== undefined ? ` on ${c.n_tasks} tasks` : ''} · {pct(c.point)} [{pct(c.ci_low)}, {pct(c.ci_high)}]{c.reason_code ? ` · ${c.reason_code}` : ''}
                        </span>
                      </li>
                    ))}
                </ul>
                <div className="mt-3 flex flex-wrap gap-2">
                  <LinkButton size="sm" to={`/routing?${q}`}>
                    Every route with its reason
                  </LinkButton>
                  <LinkButton size="sm" to={`/oracle?${q}`}>
                    Oracle and controls
                  </LinkButton>
                  <LinkButton size="sm" to={`/ledger?${q}`}>
                    The ledger
                  </LinkButton>
                </div>
              </>
            )}
          </Card>

          <Card title="Waiting on a person" eyebrow={`${decisions.length} for this repository`} actions={<LinkButton size="sm" to="/decisions">All decisions</LinkButton>}>
            {decisions.length === 0 ? (
              <EmptyState compact glyph="✓" title="Nothing is waiting on a person here" />
            ) : (
              <ul className="m-0 list-none divide-y divide-border p-0" aria-label={`Decisions for ${repo}`}>
                {decisions.slice(0, 6).map((d, i) => (
                  <li key={`${d.kind}-${i}`} className="flex flex-wrap items-center gap-2 py-2 text-sm">
                    <Pill tone={d.kind === 'signoff_due' ? 'primary' : d.kind === 'do_not_ship' ? 'red' : 'amber'} size="xs">
                      {KIND_LABEL[d.kind]}
                    </Pill>
                    <span className="min-w-0 flex-1">{d.title}</span>
                    <LinkButton size="sm" to={d.href}>
                      {d.act}
                    </LinkButton>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </>
      )}
    </>
  )
}
