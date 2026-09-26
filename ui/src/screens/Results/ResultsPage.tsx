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
 *               waiting on me — before any grid. Every number keeps its n, an interval or an
 *               honest "95% CI —" with the reason, and the apparatus from the data (never a
 *               UI constant); the bar in a tile is the policy in force; the route names are
 *               terms with a definition one click away; the page says in words what
 *               "deliver" means and does not mean. A replay in flight is announced above the
 *               numbers with its progress, because a baseline that is moving must say so —
 *               and a queued replay says it is waiting, with no attempt number. A
 *               reader is offered only the acts their role can take (Decisions' rule): a
 *               viewer reads, and sees who acts. Reached without `?repo=`, the screen chooses
 *               the most recently updated repository itself. A tile whose request failed says
 *               "not loaded" with a Try again, because a failed request is not the API saying
 *               a number is unknown (only a 404 on controls or oracle is "not run"). Every query
 *               is read through `currentData`, so a refetch that fails never leaves an old
 *               value shown as current: sign-offs that did not load mean no cell reads
 *               signed and no licence sentence; sign-offs or a backlog that did not load mean
 *               the "waiting on a person" list says so rather than "nothing is waiting"; a
 *               repository that did not load means the page says it cannot tell whether a
 *               measurement is running. Every
 *               element a reader meets —
 *               the in-flight banner's line, each tile, the map's headers and cells, the
 *               licence heading, the throughput callout, every door button and each
 *               decision's kind pill and act — is a hint trigger (`stat.results.*`,
 *               `banner.results.*`, `button.results.*`, `pill.results.decision_kind`), so
 *               what a number counts and what its value means opens on hover, focus and tap.
 * How:          `useRepoParam({ defaultToLatest })` + `RepoPicker`; `useCapabilityMap`
 *               (summary + cells), `useOracleControls`, `useOracle`, `useRepoPool` (where
 *               the tasks come from — the miner's recency bias, shown), `useSignoffs`,
 *               `useFactoryTasks` → `decisionsFor` for the "waiting on a person" panel;
 *               `useRepo` → `last_run` + `useRun` (polling) for the in-flight banner;
 *               `StatTile`s for the headline; links to the existing detail screens.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0003-one-routing-rule.md
 * Works with:   ui/src/screens/Results/MapTable.tsx (the grid; `canSign`),
 *               ui/src/screens/Decisions/decisions.ts (the rows and the role rule reused
 *               here), ui/src/components/RepoPicker.tsx (`defaultToLatest`),
 *               ui/src/components/StatTile.tsx (the tile anatomy), ui/src/components/Help.tsx
 *               (`Term` on the route tiles), ui/src/help/hints.ts (the `stat.results.*` copy;
 *               the trigger is `Hint`), ui/src/screens/Capability/CapabilityPage.tsx
 *               (the full grid), docs/EVIDENCE-AND-CLAIMS.md (what a number may be said to mean)
 * Tested by:    ui/src/screens/Results/ResultsPage.test.tsx, ui/src/help/hints-ratchet.test.tsx
 *               (every element resolves to a registry id)
 * Touch when:   a headline fact is added to the map summary; the wording of what `deliver`
 *               means changes (EVIDENCE-AND-CLAIMS §6 first).
 */

import { useMemo, type ReactNode } from 'react'
import { Link } from 'react-router'
import { currentData, useCapabilityMap, useFactoryTasks, useOracle, useOracleControls, useRepo, useRepoPool, useRun, useSignoffs } from '../../api/hooks'
import { isApiError } from '../../api/client'
import { NOT_YET_MEASURED, isRunTerminal, type CapabilityCell, type FactoryTask, type RepoPool } from '../../api/types'
import { Button, LinkButton } from '../../components/Button'
import { Card } from '../../components/Card'
import { EmptyState } from '../../components/EmptyState'
import { ErrorState } from '../../components/ErrorState'
import { Hint } from '../../components/Hint'
import { PageHeader } from '../../components/PageHeader'
import { Pill } from '../../components/Pill'
import { RepoPicker, useRepoParam } from '../../components/RepoPicker'
import { StatTile } from '../../components/StatTile'
import { Term } from '../../components/Help'
import type { HintId } from '../../help/hints'
import { useAuth } from '../../lib/auth'
import { kOfN } from '../../lib/format'
import type { Tone } from '../../lib/verdict'
import { KIND_LABEL, decisionsFor } from '../Decisions/decisions'
import { InsetText, NotificationBanner, WarningCallout } from '../../components/govuk'
import { MapTable, licenseSentence } from './MapTable'

const CONTROLS_TONE: Record<string, Tone> = { passed: 'green', failed: 'red', thin: 'amber', escaped: 'red', unmeasured: 'muted' }
/** The four routes the rule produces, as tiles — each label is a term with its definition, each tile a hint. */
const ROUTE_TILES = ['deliver', 'calibrate', 'granularize', 'human'] as const
const ROUTE_TILE_HINT: Record<(typeof ROUTE_TILES)[number], HintId> = {
  deliver: 'stat.results.route_deliver',
  calibrate: 'stat.results.route_calibrate',
  granularize: 'stat.results.route_granularize',
  human: 'stat.results.route_human',
}

function pct(x: number): string {
  return `${(x * 100).toFixed(0)}%`
}

/** An author date as a day, in UTC so the range reads the same in every time zone: "1 Aug 2026". */
function day(iso: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '—' : d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' })
}

/** Why the share of history is unknown, in the words a reader can act on. */
const POOL_UNAVAILABLE: Record<Exclude<RepoPool['history_unavailable'], ''>, string> = {
  no_clone_path: 'no clone of the repository on this host, so the share of its history is not known',
  clone_unavailable: 'the clone path is not a git repository on this host, so the share is not known',
  git_failed: 'git could not read the clone’s history, so the share is not known',
}

/** A tile's value when its request failed: said as a failure, never as "unknown" (PR #54 review). */
const NOT_LOADED = 'not loaded'
/** A 404 on the factory's tasks is "no backlog yet": an empty list, not a failure. */
const NO_TASKS: FactoryTask[] = []

/**
 * The line under a tile whose request failed, with the retry: a failed request is not the
 * API saying the number is unknown, so the reader is told which it is and can ask again.
 */
function RetryLine({ onRetry }: { onRetry: () => void }) {
  return (
    <span className="flex flex-wrap items-center gap-2">
      <span>the request failed, so no value is shown</span>
      <Button size="sm" variant="ghost" hint="button.results.retry_tile" onClick={onRetry}>
        Try again
      </Button>
    </span>
  )
}

/**
 * A section whose request failed: what did not load, what the page therefore does not show,
 * and a Try again. A failed request is never shown as an empty answer or an old one.
 */
function FailedNotice({ title, children, onRetry, testId }: { title: string; children: ReactNode; onRetry: () => void; testId: string }) {
  return (
    <div role="alert" data-testid={testId} className="mb-4 rounded-[var(--radius-card)] border border-status-red/40 bg-status-red-soft px-4 py-3 text-sm text-on-surface">
      <p className="m-0 font-semibold">{title}</p>
      <p className="m-0 mt-1">{children}</p>
      <div className="mt-1">
        <RetryLine onRetry={onRetry} />
      </div>
    </div>
  )
}

/**
 * The pool-window tile (assessment 2026-09-25, B4): its value, its n, its interval, its method
 * line and its footer, from one place so the n is always the denominator of the value shown —
 * the share is `window_commits / history_commits`, so its n is `history_commits`, and the tasks
 * are counted in the method line (PR #54 review).
 */
function poolTile(pool: RepoPool | undefined, pending: boolean, failed: boolean): { value: string; n: number | null; ci?: null; apparatus: string; footer: string } {
  const method = 'the mined tasks’ author dates against the clone’s history'
  if (failed) return { value: NOT_LOADED, n: null, apparatus: method, footer: '' }
  if (!pool) return { value: pending ? '…' : 'unknown', n: null, apparatus: method, footer: '' }
  if (pool.n_tasks === 0 || !pool.oldest_authored) return { value: 'no tasks', n: 0, apparatus: 'nothing mined yet', footer: 'mine the repository to see where its tasks come from' }
  const range = `${pool.n_tasks} tasks authored ${day(pool.oldest_authored)} – ${day(pool.newest_authored)}`
  if (pool.share === null || pool.history_unavailable || pool.history_commits === null) {
    return { value: 'not known', n: null, apparatus: range, footer: pool.history_unavailable ? POOL_UNAVAILABLE[pool.history_unavailable] : '' }
  }
  return {
    value: pct(pool.share),
    n: pool.history_commits,
    ci: null,
    // an author-date cut: every non-merge commit authored on or after the oldest task, which
    // is not "the newest N" in history order when author dates and commit order disagree
    apparatus: `${range} · ${pool.window_commits} of ${pool.history_commits} non-merge commits authored since the oldest task`,
    footer: 'no interval: an exact count of the clone’s commits, not a sample · older work, merges and changes made without a test are not in the pool',
  }
}

/** The controls report's own stamp: `apparatus 2.2 · controls.v3`; the keys the report writes (crb.core.oracle.controls). */
function controlsApparatus(stamp: Record<string, unknown>): string {
  const v = typeof stamp.apparatus_version === 'string' ? stamp.apparatus_version : '—'
  const c = typeof stamp.controls_version === 'string' ? ` · ${stamp.controls_version}` : ''
  return `apparatus ${v}${c}`
}

export function ResultsPage() {
  const [repo, setRepo] = useRepoParam({ defaultToLatest: true })
  const { can } = useAuth()
  const map = useCapabilityMap(repo, ['capability_class', 'size'])
  const controls = useOracleControls(repo)
  const oracle = useOracle(repo)
  const pool = useRepoPool(repo)
  const signoffs = useSignoffs(repo)
  const tasks = useFactoryTasks(repo)
  const repoDetail = useRepo(repo)
  // a request that failed after an earlier success keeps the earlier data: every query on
  // this page — the numbers, the sign-offs that allow delivery, the backlog and the run — is
  // read only through `currentData`, so an old value is never shown as current, and a source
  // ratchet in the page's test refuses any `<query>.data` read (PR #54 review)
  const mapData = currentData(map)
  const controlsData = currentData(controls)
  const oracleData = currentData(oracle)
  const poolData = currentData(pool)
  const signoffsData = currentData(signoffs)
  const tasksNoBacklog = tasks.isError && isApiError(tasks.error) && tasks.error.status === 404
  const tasksData = tasksNoBacklog ? NO_TASKS : currentData(tasks)
  const repoData = currentData(repoDetail)
  // without the sign-offs or the backlog the page cannot say what waits on a person
  const decisionsFailed = signoffs.isError || (tasks.isError && !tasksNoBacklog)
  // a replay still queued or running: the numbers below move as each attempt is graded
  const lastRun = repoData?.last_run
  const activeReplayId = lastRun && lastRun.kind === 'replay' && !isRunTerminal(lastRun.status) ? lastRun.id : ''
  const run = useRun(activeReplayId)
  const runData = currentData(run)
  // the poll sees the run finish before the repo's `last_run` is re-read: the banner goes with it
  const replayRunning = Boolean(activeReplayId) && !(runData && isRunTerminal(runData.status))
  // queued wording until the poll says `running`: a queued run has graded nothing, whatever
  // `progress` still carries (a reclaimed run keeps its old counts while it waits)
  const replayQueued = replayRunning && (runData ? runData.status === 'queued' : lastRun?.status === 'queued')
  const replayProgress = runData && runData.status === 'running' ? kOfN(runData.progress.done, runData.progress.total) : null
  const q = `repo=${encodeURIComponent(repo)}`

  const measured: CapabilityCell[] = useMemo(() => (mapData?.cells ?? []).filter((c) => c.route !== NOT_YET_MEASURED && c.n > 0), [mapData])
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
  // null until the map, the sign-offs and the backlog have all loaded: "nothing is waiting"
  // is said only when it is known
  const decisions = useMemo(
    () => (mapData && signoffsData && tasksData ? decisionsFor({ repo, cells: mapData.cells, signoffs: signoffsData.items, tasks: tasksData }) : null),
    [repo, mapData, signoffsData, tasksData],
  )
  const licence = useMemo(() => (mapData && signoffsData ? licenseSentence(repo, mapData, signoffsData.items) : null), [repo, mapData, signoffsData])
  const economics = useMemo(() => {
    const n = measured.reduce((a, c) => a + c.n, 0)
    const clean = measured.reduce((a, c) => a + c.clean, 0)
    const costed = measured.filter((c) => c.cost_usd_mean > 0)
    const costN = costed.reduce((a, c) => a + c.n, 0)
    const perAttempt = costN ? costed.reduce((a, c) => a + c.cost_usd_mean * c.n, 0) / costN : null
    const timed = measured.filter((c) => c.latency_s_mean > 0)
    const timeN = timed.reduce((a, c) => a + c.n, 0)
    const latency = timeN ? timed.reduce((a, c) => a + c.latency_s_mean * c.n, 0) / timeN : null
    return { n, clean, perAttempt, perClean: perAttempt !== null && clean ? (perAttempt * n) / clean : null, latency }
  }, [measured])
  const controlsNotRun = controls.isError && isApiError(controls.error) && controls.error.status === 404
  const oracleNotRun = oracle.isError && isApiError(oracle.error) && oracle.error.status === 404
  const verdict = controlsData?.verdict
  const apparatus = mapData ? `apparatus ${mapData.summary.apparatus_versions.join(', ') || '—'} · Wilson 95%` : '—'
  const oracleMean = oracleData && oracleData.tasks.length > 0 ? oracleData.tasks.reduce((a, t) => a + (t.strength ?? 0), 0) / oracleData.tasks.length : null
  // the bar is the policy in force, never a constant; the apparatus is the report's own
  const oracleBar = mapData ? mapData.policy.min_oracle_strength : null
  // a failed request is not a missing report: only a 404 on controls / oracle means "not run"
  const controlsFailed = controls.isError && !controlsNotRun
  const oracleFailed = oracle.isError && !oracleNotRun
  const poolView = poolTile(poolData, pool.isPending, pool.isError)
  const oracleApparatus = oracleData ? `apparatus ${oracleData.apparatus_versions.join(', ') || '—'} · mean of per-task mutation scores${oracleBar !== null ? ` · ≥ ${pct(oracleBar)} per cell to deliver` : ''}` : 'one mutation score per task, from the oracle run'

  return (
    <>
      <PageHeader
        title="Baseline"
        purpose="What the evidence says about this repository — the baseline the factory runs on — in the order it matters: is the instrument trustworthy here, what may the builder be trusted to do, and what is waiting on a person."
        actions={<RepoPicker value={repo} onChange={setRepo} />}
      />
      {!repo && <EmptyState title="Choose a repository" reason="Results are per repository — a cell says nothing about a repository it was not measured on." action={<LinkButton to="/connect">Connect one</LinkButton>} />}
      {repo && map.isPending && <p className="text-sm text-on-surface-muted">Loading the baseline for {repo}…</p>}
      {repo && map.isError && <ErrorState error={map.error} onRetry={() => void map.refetch()} />}
      {repo && mapData && (
        <>
          {replayRunning && (
            <NotificationBanner title={replayQueued ? 'A measurement is queued' : 'A measurement is running'}>
              <Hint as="p" id="banner.results.replay_running" className="m-0">
                {replayQueued
                  ? `A measurement is waiting for a worker${(runData?.progress?.done ?? 0) > 0 ? ` — ${runData?.progress?.done} attempt(s) were graded before it went back to the queue` : '; nothing has been graded yet'}.`
                  : `A measurement is running${replayProgress ? `: attempt ${replayProgress}, $${(runData?.cost_usd ?? 0).toFixed(2)} spent so far` : ''}.`}{' '}
                The numbers on this page change as each attempt is graded.{' '}
                <Link to={`/runs/${encodeURIComponent(activeReplayId)}`}>Open the run</Link>
              </Hint>
            </NotificationBanner>
          )}
          {repoDetail.isError && (
            <FailedNotice testId="repo-failed" title="Could not check whether a measurement is running" onRetry={() => void repoDetail.refetch()}>
              The repository did not load, so this page cannot say whether the numbers below are still moving.
            </FailedNotice>
          )}
          <Card title="Is the instrument trustworthy here?" eyebrow="the gates every number below stands under">
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <StatTile
                label="Negative controls"
                value={verdict ? verdict.state : controlsNotRun ? 'not run' : controls.isPending ? '…' : controlsFailed ? NOT_LOADED : 'unknown'}
                n={controlsData?.n_rows ?? null}
                apparatus={controlsData ? controlsApparatus(controlsData.apparatus) : 'seven deliberate cheats the grader must catch'}
                tone={verdict ? CONTROLS_TONE[verdict.state] : 'muted'}
                hint="stat.results.controls"
                footer={controlsData ? `${controlsData.violations} violations · ${controlsData.escapes} escapes · ${controlsData.not_constructible} not constructible` : controlsFailed ? <RetryLine onRetry={() => void controls.refetch()} /> : verdict ? undefined : 'run the controls from Connect'}
                data-testid="tile-negative-controls"
              />
              <StatTile
                label="Oracle strength"
                value={oracleMean === null ? (oracleNotRun ? 'not scored' : oracle.isPending ? '…' : oracleFailed ? NOT_LOADED : 'unknown') : pct(oracleMean)}
                n={oracleData?.tasks.length ?? null}
                ci={null}
                apparatus={oracleApparatus}
                tone={oracleMean === null ? 'muted' : oracleBar !== null && oracleMean >= oracleBar ? 'green' : 'amber'}
                hint="stat.results.oracle_strength"
                footer={oracleFailed ? <RetryLine onRetry={() => void oracle.refetch()} /> : 'no interval: a mean of per-task scores, not a rate'}
                data-testid="tile-oracle-strength"
              />
              <StatTile
                label="Where the tasks come from"
                value={poolView.value}
                n={poolView.n}
                ci={poolView.ci}
                apparatus={poolView.apparatus}
                tone="muted"
                hint="stat.results.pool_window"
                footer={pool.isError ? <RetryLine onRetry={() => void pool.refetch()} /> : poolView.footer || undefined}
                data-testid="tile-pool-window"
              />
              <StatTile label="False-Q1" value={String(mapData.summary.false_q1_total)} n={mapData.summary.n_total} apparatus={apparatus} tone={mapData.summary.false_q1_total === 0 ? 'green' : 'red'} hint="stat.results.false_q1" footer="must be zero; refused at write" />
            </div>
          </Card>

          <Card title="What may the builder be trusted to do?" eyebrow="the routes, with n" actions={<LinkButton size="sm" to={`/capability?${q}`} hint="button.results.full_map">Open the full map</LinkButton>}>
            {measured.length === 0 ? (
              <EmptyState compact glyph="◌" title="Nothing measured yet" reason="A first sighted replay puts rows on the map." action={<LinkButton size="sm" to={`/connect/${encodeURIComponent(repo)}`}>Back to the walk</LinkButton>} />
            ) : (
              <>
                <div className="grid gap-3 sm:grid-cols-4">
                  {ROUTE_TILES.map((r) => (
                    <StatTile
                      key={r}
                      label={<Term id={r}>{r}</Term>}
                      value={String(byRoute[r]?.cells ?? 0)}
                      n={byRoute[r]?.n ?? 0}
                      apparatus={`${byRoute[r]?.cells ?? 0} of ${measured.length} measured cells`}
                      tone={r === 'deliver' ? 'green' : r === 'human' ? 'amber' : 'muted'}
                      hint={ROUTE_TILE_HINT[r]}
                    />
                  ))}
                </div>
                <p className="mt-3 max-w-[80ch] text-sm text-on-surface-body">
                  <strong>deliver</strong> means the cell clears the published bar (n ≥ {mapData.policy.min_n}, point ≥ {pct(mapData.policy.min_point)}, Wilson-low ≥ {pct(mapData.policy.min_ci_low)}, false-Q1 = 0, oracle ≥ {pct(mapData.policy.min_oracle_strength)}, controls passed) so the factory may open a branch and a pull request for that class of change under human review. It never means a change is safe to merge or deploy.
                </p>
                <h3 className="mb-2 mt-6 text-[24px] font-bold leading-[1.3]">What it can do, by class and size</h3>
                <p className="m-0 mb-4 max-w-[44em] text-[16px] leading-[1.5] text-on-surface-body">
                  Each cell carries its own <code>n</code>, its point estimate and its Wilson interval. An empty cell says "not measured" — it does not say zero.
                </p>
                {signoffs.isError && (
                  <FailedNotice testId="signoffs-failed" title="The sign-offs did not load" onRetry={() => void signoffs.refetch()}>
                    Until they load, no cell is shown as signed and no licence sentence is shown.
                  </FailedNotice>
                )}
                <MapTable map={mapData} signoffs={signoffsData?.items ?? null} repo={repo} canSign={can('approver')} />
                {licence && (
                  <InsetText>
                    <Hint as="h3" id="banner.results.licence" className="m-0 mb-2 text-[19px] font-bold leading-[1.4]">
                      What this licenses you to say
                    </Hint>
                    <p className="m-0" data-testid="licence-sentence">{licence}</p>
                  </InsetText>
                )}
                <h3 className="mb-3 text-[24px] font-bold leading-[1.3]">Economics</h3>
                <div className="mb-4 grid gap-3 sm:grid-cols-4">
                  <StatTile label="Cost per attempt" value={economics.perAttempt === null ? '—' : `$${economics.perAttempt.toFixed(2)}`} n={economics.n} apparatus="a mean of builder-reported $ over cells with a known cost, current apparatus — no interval yet: the API serves the mean only" hint="stat.results.cost_per_attempt" />
                  <StatTile label="Cost per clean attempt" value={economics.perClean === null ? '—' : `$${economics.perClean.toFixed(2)}`} n={economics.clean} apparatus={`${economics.clean} clean of ${economics.n} — the same mean divided by the clean rate; no interval`} hint="stat.results.cost_per_clean" />
                  <StatTile label="Latency per attempt" value={economics.latency === null ? '—' : `${Math.floor(Math.round(economics.latency) / 60)}m ${Math.round(economics.latency) % 60}s`} n={economics.n} apparatus="a mean over cells with a known latency — no interval yet: the API serves the mean only" hint="stat.results.latency" />
                  <StatTile label="Clean rate" value={economics.n ? pct(economics.clean / economics.n) : '—'} n={economics.n} apparatus="all attempts, all cells — never a routing input" hint="stat.results.clean_rate" />
                </div>
                <Hint as="div" id="banner.results.no_throughput">
                  <WarningCallout title="No throughput headline">
                    The ledger records neither human hours nor merge outcomes yet, so cost per accepted change cannot be shown here honestly. What is shown is cost per clean attempt, which is measured.
                  </WarningCallout>
                </Hint>
                <div className="mt-3 flex flex-wrap gap-2">
                  <LinkButton size="sm" to={`/routing?${q}`} hint="button.results.routing">
                    Every route with its reason
                  </LinkButton>
                  <LinkButton size="sm" to={`/oracle?${q}`} hint="button.results.oracle">
                    Oracle and controls
                  </LinkButton>
                  <LinkButton size="sm" to={`/ledger?${q}`} hint="button.results.ledger">
                    The ledger
                  </LinkButton>
                </div>
              </>
            )}
          </Card>

          <Card title="Waiting on a person" eyebrow={decisions ? `${decisions.length} for this repository` : decisionsFailed ? NOT_LOADED : 'loading'} eyebrowHint="stat.results.waiting_count" actions={<LinkButton size="sm" to="/decisions" hint="button.results.all_decisions">All decisions</LinkButton>}>
            {decisionsFailed ? (
              <FailedNotice
                testId="decisions-failed"
                title="What is waiting on a person did not load"
                onRetry={() => {
                  if (signoffs.isError) void signoffs.refetch()
                  if (tasks.isError && !tasksNoBacklog) void tasks.refetch()
                }}
              >
                The sign-offs or the factory&rsquo;s backlog did not load, so this list is not shown rather than shown out of date.
              </FailedNotice>
            ) : !decisions ? (
              <p className="m-0 text-sm text-on-surface-muted">Loading what is waiting on a person…</p>
            ) : decisions.length === 0 ? (
              <EmptyState compact glyph="✓" title="Nothing is waiting on a person here" />
            ) : (
              <ul className="m-0 list-none divide-y divide-border p-0" aria-label={`Decisions for ${repo}`}>
                {decisions.slice(0, 6).map((d, i) => {
                  // Decisions' rule: the act only for the role that can take it; everyone else reads, and sees who acts
                  const allowed = d.role === 'viewer' || can(d.role)
                  return (
                    <li key={`${d.kind}-${i}`} className="flex flex-wrap items-center gap-2 py-2 text-sm">
                      <Pill tone={d.kind === 'signoff_due' ? 'primary' : d.kind === 'do_not_ship' ? 'red' : 'amber'} size="xs" hint="pill.results.decision_kind">
                        {KIND_LABEL[d.kind]}
                      </Pill>
                      <span className="min-w-0 flex-1">{d.title}</span>
                      <span className="text-right">
                        <LinkButton size="sm" to={d.href} hint="button.results.decision_act">
                          {allowed ? d.act : 'Read'}
                        </LinkButton>
                        {!allowed && <span className="block text-[13px] text-on-surface-muted">{d.role} acts</span>}
                      </span>
                    </li>
                  )
                })}
              </ul>
            )}
          </Card>
        </>
      )}
    </>
  )
}
