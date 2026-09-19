/**
 * Measure — "this step spends money": how many attempts, what is kept, what it costs, confirm.
 *
 * Navigation
 * ----------
 * What it is:   The walk's sixth stage as a page (/connect/:name/measure): the attempt
 *               count as three radios with what each buys ("enough to see the shape, not to
 *               route" / "the first useful picture" / "tighter intervals, longer wait"), the
 *               two retention switches with the policy statement, a "Before you start"
 *               summary (estimated cost from the repository's own measured cost per
 *               attempt, the absence of a spend cap, retention, posture) and one red button
 *               that names the estimate — the MoJ "confirm an action" pattern. While a
 *               replay is already queued or running for the repository the button and the
 *               estimate give way to a banner naming that run, so the page can never queue
 *               a second spend by accident (J-ONR-4).
 * What it does: Replaces the technical run dialog for the person who has never used the
 *               product: every number on the page is the deployment's (the cost estimate is
 *               the repository's measured mean per attempt when it has one, else the
 *               documented range), the button says "estimated" because the request carries
 *               no cost cap (F5b: nothing on this page promises a ceiling nothing enforces),
 *               the posture is the real sandbox mode, and nothing is queued until the red
 *               button.
 * How:          `useRepo` (+ `last_run` → `useRun`, polled, for the in-flight banner),
 *               `useCapabilityMap` (cost_usd_mean over measured cells), `useHealth` (sandbox
 *               posture and the builder), `builderChoice` (ui/src/lib/builder.ts) for the
 *               builder the deployment can run, `useCreateRun` with `{kind: replay, mode:
 *               sighted, limit, retain}`; on success the walk resumes on the repository with
 *               the run watched. The kicker is `journeyEyebrow(pathname, 'task 5 of 8 · …')`.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0006-zero-raw-retention-and-evidence-packs.md
 * Works with:   ui/src/lib/builder.ts (`builderChoice`, shared with the Factory),
 *               ui/src/components/govuk.tsx, ui/src/components/Layout.tsx (`journeyEyebrow`),
 *               ui/src/components/Help.tsx (`DocLink`), ui/src/screens/Connect/ConnectPage.tsx
 *               (the walk that lands here), ui/src/screens/Runs/RunNewDialog.tsx (the full
 *               form for an operator who wants every knob), src/crb/server/routes/runs.py
 * Tested by:    ui/src/screens/Connect/MeasurePage.test.tsx
 * Touch when:   the run request grows a field the walk should expose.
 */

import { useMemo, useState } from 'react'
import { Link, useLocation, useNavigate, useParams } from 'react-router'
import { useCapabilityMap, useCreateRun, useHealth, useRepo, useRun } from '../../api/hooks'
import { NOT_YET_MEASURED } from '../../api/types'
import { ErrorState } from '../../components/ErrorState'
import { DocLink } from '../../components/Help'
import { journeyEyebrow } from '../../components/Layout'
import { BackLink, Kicker, Lede, NotificationBanner, PageTitle, SummaryList, WarningButton, type SummaryRow } from '../../components/govuk'
import { useAuth } from '../../lib/auth'
import { builderChoice } from '../../lib/builder'

const LIMITS: Array<{ n: number; note: string }> = [
  { n: 10, note: 'enough to see the shape, not to route' },
  { n: 30, note: 'the first useful picture' },
  { n: 60, note: 'tighter intervals, longer wait' },
]
//: the per-attempt planning band docs/ONBOARDING-A-REPO.md quotes for Claude Sonnet (not a measured
//: interval for THIS repository) — used only while the repository has no measured mean of its own
const RANGE_LOW = 0.2
const RANGE_HIGH = 0.6

function usd(x: number): string {
  return `$${x.toFixed(2)}`
}

/**
 * The posture sentence from what `/health` actually says: the sandbox probe's `executor`
 * (explicit) and its status. "Countable as evidence" is claimed only for a docker executor
 * whose daemon answered; an API-role process that skipped the probe says so rather than
 * guessing; a local executor is a development reading.
 */
export function posturePhrase(sandbox: { status: string; data?: Record<string, unknown> } | undefined): string {
  if (!sandbox) return 'unknown — the health check has not answered'
  const executor = String(sandbox.data?.executor ?? '')
  if (executor === 'docker' && sandbox.status === 'ok') return 'sealed (docker) — countable as evidence'
  if (executor === 'docker' && sandbox.status === 'skipped') return 'docker executor — the worker’s own health check decides whether it is sealed; this process did not probe it'
  if (executor === 'docker') return `docker executor, daemon ${sandbox.status} — a development reading, not evidence, until the sandbox answers`
  if (executor === 'local') return 'local executor — a development reading, not evidence (tests run unisolated)'
  return `${sandbox.status} — a development reading, not evidence, until the sandbox is available`
}

/** "14:05" — when the in-flight run started. */
function clock(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hourCycle: 'h23' })
}

export function MeasurePage() {
  const { name = '' } = useParams()
  const { pathname } = useLocation()
  const navigate = useNavigate()
  const { can } = useAuth()
  const repo = useRepo(name)
  // a replay already queued or running for this repository: the page must name it, not
  // offer a second spend (the API exposes it as the repository's last run)
  const lastRun = repo.data?.last_run
  const activeId = lastRun && lastRun.kind === 'replay' && (lastRun.status === 'queued' || lastRun.status === 'running') ? lastRun.id : ''
  const active = useRun(activeId, { poll: Boolean(activeId) })
  const inFlight = activeId.length > 0 && (!active.data || active.data.status === 'queued' || active.data.status === 'running')
  const map = useCapabilityMap(name, ['capability_class', 'size'])
  const health = useHealth()
  const create = useCreateRun()
  const [limit, setLimit] = useState(30)
  const [worktrees, setWorktrees] = useState(false)
  const [transcripts, setTranscripts] = useState(false)

  // the repository's own measured mean per attempt, when it has one: a row-weighted mean
  // over the map's measured cells (the map is served on the current apparatus, so the
  // versions are the same set on every cell), carrying the n it rests on and that apparatus
  const measured = useMemo(() => {
    const cells = (map.data?.cells ?? []).filter((c) => c.route !== NOT_YET_MEASURED && c.n > 0 && c.cost_usd_mean > 0)
    if (cells.length === 0) return null
    const n = cells.reduce((a, c) => a + c.n, 0)
    const apparatus = Array.from(new Set(cells.flatMap((c) => c.apparatus_versions))).join(', ')
    return { mean: cells.reduce((a, c) => a + c.cost_usd_mean * c.n, 0) / n, n, apparatus }
  }, [map.data])
  const measuredMean = measured?.mean ?? null
  const gold = repo.data?.task_counts.gold_clean ?? 0
  // the run makes one attempt per gold-clean task: the estimate, the button and the
  // request all use the SAME capped number, never the radio's face value
  const runLimit = gold > 0 ? Math.min(limit, gold) : limit
  const lo = measuredMean !== null ? measuredMean * 0.8 * runLimit : RANGE_LOW * runLimit
  const hi = measuredMean !== null ? measuredMean * 1.2 * runLimit : RANGE_HIGH * runLimit
  const sandbox = health.data?.probes.find((p) => p.name === 'sandbox')
  const choice = builderChoice(health.data)
  const posture = posturePhrase(sandbox)
  const retention = !worktrees && !transcripts ? 'Nothing retained — grades and hashes only' : `${[worktrees && 'worktrees', transcripts && 'transcripts'].filter(Boolean).join(' and ')} kept until deleted`
  const estimate: SummaryRow = {
    key: 'Estimated cost',
    value: (
      <>
        {usd(lo)} to {usd(hi)} for {runLimit} attempts
        {measured
          ? `, at about ${usd(measured.mean)} each (this repository's measured mean over n=${measured.n} attempts at apparatus ${measured.apparatus || '—'}; the range is a ±20 % planning band, not a measured interval).`
          : `, at ${usd(RANGE_LOW)}–${usd(RANGE_HIGH)} each — a planning range, not a measured interval: this repository has no measured mean yet (n = 0 on the current apparatus); the range is the per-attempt band the onboarding guide quotes for Claude Sonnet across earlier repositories, and carries no apparatus of its own.`}{' '}
        <DocLink to="ONBOARDING-A-REPO#step-4--measure-operator-the-money-step">Measure: the money step</DocLink>
      </>
    ),
  }

  const start = () => {
    if (!choice || inFlight) return
    create.mutate(
      {
        repo: name,
        kind: 'replay',
        mode: 'sighted',
        builder: choice.builder,
        model: choice.model,
        ...(Object.keys(choice.builder_config).length > 0 ? { builder_config: choice.builder_config } : {}),
        limit: runLimit,
        retain: { worktrees, transcripts },
      },
      { onSuccess: () => navigate(`/connect/${encodeURIComponent(name)}`) },
    )
  }

  return (
    <>
      <BackLink to={`/connect/${encodeURIComponent(name)}`}>Back to the walk for {name}</BackLink>
      <div>
        <Kicker>{journeyEyebrow(pathname, 'task 5 of 8 · this step spends money')}</Kicker>
      </div>
      <PageTitle>Measure {name}</PageTitle>
      {repo.isError && <ErrorState error={repo.error} onRetry={() => void repo.refetch()} />}
      {inFlight && (
        <NotificationBanner title="Important">
          <p className="m-0 mb-2 font-bold">
            A measurement is already {active.data?.status === 'queued' ? 'queued' : 'running'} for {name}.
            {active.data && (
              <>
                {' '}
                {active.data.started ? `Started ${clock(active.data.started)}; ` : 'Not started yet; '}
                {active.data.progress.total > 0 ? `${active.data.progress.done} of ${active.data.progress.total} attempts made` : 'no attempt made yet'}; {usd(active.data.cost_usd)} spent so far.
              </>
            )}
          </p>
          <p className="m-0 mb-2">
            <Link to={`/runs/${encodeURIComponent(activeId)}`}>Open the run</Link> · <Link to={`/connect/${encodeURIComponent(name)}`}>Back to the walk</Link>
          </p>
          <p className="m-0">Start another run only when this one has finished or been cancelled.</p>
        </NotificationBanner>
      )}
      <h2 className="mb-2 text-[24px] font-bold leading-[1.3]">How many attempts</h2>
      <div className="mb-8 max-w-[44em]">
        {LIMITS.map((l) => (
          <label key={l.n} className="flex cursor-pointer items-center gap-4 py-2 text-[19px] leading-[1.47]">
            <input type="radio" name="limit" className="h-6 w-6 accent-[var(--trust)]" checked={limit === l.n} onChange={() => setLimit(l.n)} />
            <span>{l.n} attempts</span>
            <span className="text-on-surface-muted">{l.note}</span>
          </label>
        ))}
        {gold > 0 && gold < limit && (
          <p className="m-0 mt-2 text-[16px] text-on-surface-muted">
            {name} has {gold} gold-clean tasks, so this run makes {gold} attempts (one per task).
          </p>
        )}
        {repo.data && gold === 0 && (
          <p className="m-0 mt-2 text-[16px] font-bold text-status-red" data-testid="no-gold">
            {name} has no gold-clean task to replay, so a run would make no attempt. Mine the repository first (stage 3 of the walk) and check its gold status under <Link to={`/repos/${encodeURIComponent(name)}`}>Configuration</Link>.
          </p>
        )}
      </div>
      <h2 className="mb-2 text-[24px] font-bold leading-[1.3]">Retention</h2>
      <Lede className="mb-2">This deployment retains no raw artefacts by default. Anything you keep here is stored until you delete it and is in scope for your own retention policy.</Lede>
      <div className="mb-8 max-w-[44em]">
        <label className="flex cursor-pointer items-center gap-4 py-2 text-[19px] leading-[1.47]">
          <input type="checkbox" className="h-6 w-6 accent-[var(--trust)]" checked={worktrees} onChange={(e) => setWorktrees(e.target.checked)} />
          <span>Keep worktrees for failed attempts</span>
        </label>
        <label className="flex cursor-pointer items-center gap-4 py-2 text-[19px] leading-[1.47]">
          <input type="checkbox" className="h-6 w-6 accent-[var(--trust)]" checked={transcripts} onChange={(e) => setTranscripts(e.target.checked)} />
          <span>Keep builder transcripts</span>
        </label>
      </div>
      <div className="mb-8 max-w-[44em] border border-border p-6 shadow-[0_4px_0_var(--line)]" data-testid="before-you-start">
        <h2 className="mb-4 text-[24px] font-bold leading-[1.3]">Before you start</h2>
        <SummaryList
          rows={[
            // the estimate gives way to the banner while a run is in flight: no second spend is priced
            ...(inFlight ? [] : [estimate]),
            { key: 'Builder', value: choice ? choice.label : 'No builder is configured on this deployment — an admin adds a provider key (Settings), or use the full run form', changeTo: '/runs', changeLabel: 'Every knob' },
            // honest until F5b (a per-run cap summed over attempts) lands: the request carries no cap
            { key: 'Budget cap', value: 'No spend cap on this run yet. Each attempt is capped on turns, tool calls and wall clock; you can cancel at any point and attempts already made are still charged.' },
            { key: 'Retention', value: retention },
            { key: 'Posture', value: posture },
          ]}
        />
        {inFlight ? (
          <p className="mb-0 mt-6 text-[19px] leading-[1.47]">A measurement is in flight for {name} (see above). Cancel it from the run page if you need to; attempts already made are still charged.</p>
        ) : (
          <>
            <p className="mb-4 mt-6 text-[19px] leading-[1.47]">You can cancel the run at any point. Attempts already made are still charged.</p>
            {can('operator') ? (
              <WarningButton onClick={start} disabled={create.isPending || !repo.data || !choice || gold === 0}>
                Start the run — estimated {usd(lo)} to {usd(hi)}
              </WarningButton>
            ) : (
              <p className="m-0 text-[16px] text-on-surface-muted">Starting a run needs the operator role.</p>
            )}
          </>
        )}
        {create.isError && <ErrorState compact error={create.error} />}
      </div>
    </>
  )
}
