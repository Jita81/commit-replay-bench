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
 *               attempt, the run's spend cap and how it is kept, retention, posture) and one
 *               red button that names the estimate and the cap — the MoJ "confirm an action"
 *               pattern. A spend cap field starts at the top of the estimate (F5b). While a
 *               replay is already queued or running for the repository the button and the
 *               estimate give way to a banner naming that run, so the page can never queue
 *               a second spend by accident (J-ONR-4).
 * What it does: Replaces the technical run dialog for the person who has never used the
 *               product: every number on the page is the deployment's (the cost estimate is
 *               the repository's measured mean per attempt when it has one, else the
 *               documented range), the button says "estimated" and names the cap the request
 *               carries as `max_cost_usd` and the worker keeps (F5b); a last replay that
 *               stopped itself at its cap is said in a banner with its reason and its run,
 *               the posture is the real sandbox mode, and nothing is queued until the red
 *               button. A reader without the operator role is told so under the title and
 *               sees the choices as read-only lists — nothing a role cannot act on is shown
 *               as a control. Every element a reader meets — the back link, the kicker, the
 *               in-flight banner's lead line, each radio and checkbox (or its read-only row),
 *               the gold-clean cap note, every "Before you start" row, the "Every knob" link
 *               and the red button — is a hint trigger (`link.measure.*`, `nav.measure.kicker`,
 *               `banner.measure.inflight`, `banner.measure.spend_cap_stop`, `field.measure.*`,
 *               `stat.measure.*`,
 *               `summary.measure.*`, `button.measure.start`).
 * How:          `useRepo` (+ `last_run` → `useRun`, polled, for the in-flight banner),
 *               `useCapabilityMap` (its economics fold, read by `measuredCostPerAttempt`),
 *               `useHealth` (sandbox posture and the builder), `builderChoice`
 *               (ui/src/lib/builder.ts) for the builder the deployment can run,
 *               `useCreateRun` with `{kind: replay, mode: sighted, limit, retain,
 *               max_cost_usd}`; on success the walk resumes on the repository with
 *               the run watched. The kicker is `journeyEyebrow(pathname, 'task 5 of 8 · …')`.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0006-zero-raw-retention-and-evidence-packs.md
 * Works with:   ui/src/lib/builder.ts (`builderChoice`, shared with the Factory),
 *               ui/src/components/govuk.tsx (SummaryList, WarningButton, BackLink),
 *               ui/src/components/Layout.tsx (`journeyEyebrow`), ui/src/help/hints.ts (the
 *               `*.measure.*` copy; the trigger is `Hint`), ui/src/components/Help.tsx
 *               (`DocLink`), ui/src/screens/Connect/ConnectPage.tsx (the walk that lands here),
 *               ui/src/screens/Runs/RunNewDialog.tsx (the full form for an operator who wants
 *               every knob), src/crb/server/routes/runs.py (the request it submits)
 * Tested by:    ui/src/screens/Connect/MeasurePage.test.tsx, ui/src/help/hints-ratchet.test.tsx
 *               (every element resolves to a registry id)
 * Touch when:   the run request grows a field the walk should expose.
 */

import { useMemo, useState } from 'react'
import { Link, useLocation, useNavigate, useParams } from 'react-router'
import { useCapabilityMap, useCreateRun, useHealth, useRepo, useRun } from '../../api/hooks'
import { ErrorState } from '../../components/ErrorState'
import { DocLink } from '../../components/Help'
import { Hint } from '../../components/Hint'
import { journeyEyebrow } from '../../components/Layout'
import { BackLink, Kicker, Lede, NotificationBanner, PageTitle, SummaryList, WarningButton, type SummaryRow } from '../../components/govuk'
import { useAuth } from '../../lib/auth'
import { builderChoice } from '../../lib/builder'
import { measuredCostPerAttempt, noMeasuredCostReason } from '../../lib/economics'

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
  const lastReplayId = lastRun && lastRun.kind === 'replay' ? lastRun.id : ''
  const activeId = lastRun && lastRun.kind === 'replay' && (lastRun.status === 'queued' || lastRun.status === 'running') ? lastRun.id : ''
  // the last replay, read whether or not it is still in flight: the banner names a run in
  // flight, and a finished one that stopped itself at its spend cap is said as such (F5b)
  const active = useRun(lastReplayId, { poll: Boolean(activeId) })
  const inFlight = activeId.length > 0 && (!active.data || active.data.status === 'queued' || active.data.status === 'running')
  const capStop = !inFlight && active.data?.counts?.stopped_code === 'spend_cap' ? active.data : null
  const map = useCapabilityMap(name, ['capability_class', 'size'])
  const health = useHealth()
  const create = useCreateRun()
  const [limit, setLimit] = useState(30)
  const [worktrees, setWorktrees] = useState(false)
  const [transcripts, setTranscripts] = useState(false)
  const operator = can('operator')

  // the repository's own measured cost per attempt, when it has one: the map's economics
  // fold (F35) — its mean over the attempts with a KNOWN cost (a known $0 is $0), that
  // count as n, and the apparatus; never the cells' flat means filtered by > 0 (P-064)
  const measured = useMemo(() => measuredCostPerAttempt(map.data?.economics), [map.data])
  const measuredMean = measured?.mean ?? null
  const gold = repo.data?.task_counts.gold_clean ?? 0
  // the run makes one attempt per gold-clean task: the estimate, the button and the
  // request all use the SAME capped number, never the radio's face value
  const runLimit = gold > 0 ? Math.min(limit, gold) : limit
  const lo = measuredMean !== null ? measuredMean * 0.8 * runLimit : RANGE_LOW * runLimit
  const hi = measuredMean !== null ? measuredMean * 1.2 * runLimit : RANGE_HIGH * runLimit
  // F5b — the run's own spend cap, which the worker keeps: it starts at the top of the
  // estimate, rounded up to the dollar, and follows it until the operator types another
  const [capDraft, setCapDraft] = useState<string | null>(null)
  const capText = capDraft ?? String(Math.max(1, Math.ceil(hi)))
  const cap = Number(capText)
  const capOk = capText.trim() !== '' && Number.isFinite(cap) && cap > 0
  const sandbox = health.data?.probes.find((p) => p.name === 'sandbox')
  const choice = builderChoice(health.data)
  const posture = posturePhrase(sandbox)
  const retention = !worktrees && !transcripts ? 'Nothing retained — grades and hashes only' : `${[worktrees && 'worktrees', transcripts && 'transcripts'].filter(Boolean).join(' and ')} kept until deleted`
  const estimate: SummaryRow = {
    key: 'Estimated cost',
    hint: 'stat.measure.estimate',
    value: (
      <>
        {usd(lo)} to {usd(hi)} for {runLimit} attempts
        {measured
          ? `, at about ${usd(measured.mean)} each (this repository's measured mean over n=${measured.n} attempts with a known cost at apparatus ${measured.apparatus || '—'}; the range is a ±20 % planning band, not a measured interval).`
          : `, at ${usd(RANGE_LOW)}–${usd(RANGE_HIGH)} each — a planning range, not a measured interval: this repository has no measured mean yet (${noMeasuredCostReason(map.data?.economics)}); the range is the per-attempt band the onboarding guide quotes for Claude Sonnet across earlier repositories, and carries no apparatus of its own.`}{' '}
        <DocLink to="ONBOARDING-A-REPO#step-4--measure-operator-the-money-step">Measure: the money step</DocLink>
      </>
    ),
  }

  const start = () => {
    if (!choice || inFlight || !capOk) return
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
        max_cost_usd: cap,
      },
      { onSuccess: () => navigate(`/connect/${encodeURIComponent(name)}`) },
    )
  }

  return (
    <>
      <Hint id="link.measure.back">
        <BackLink to={`/connect/${encodeURIComponent(name)}`}>Back to the walk for {name}</BackLink>
      </Hint>
      <div>
        <Hint id="nav.measure.kicker">
          <Kicker>{journeyEyebrow(pathname, 'task 5 of 8 · this step spends money')}</Kicker>
        </Hint>
      </div>
      <PageTitle>Measure {name}</PageTitle>
      {!operator && (
        <p className="m-0 mb-4 max-w-[44em] text-[19px] leading-[1.47]" data-testid="measure-role-note">
          Starting a run needs the operator role. This page shows what an operator confirms here: the attempts, the retention and the estimate. You can read it and change nothing.
        </p>
      )}
      {repo.isError && <ErrorState error={repo.error} onRetry={() => void repo.refetch()} />}
      {capStop && (
        <NotificationBanner title="Stopped at its spend cap">
          <Hint as="p" id="banner.measure.spend_cap_stop" className="m-0 mb-2 font-bold">
            The last measurement of {name} stopped itself at its spend cap of {usd(capStop.max_cost_usd ?? 0)}: {usd(capStop.cost_usd)} spent over {capStop.counts.rows} attempts, before an attempt that could have passed it.
          </Hint>
          <p className="m-0 mb-2" data-testid="measure-cap-stop-reason">{capStop.counts.stopped_reason}</p>
          <p className="m-0">
            <Link to={`/runs/${encodeURIComponent(capStop.id)}`}>Open the run</Link> · the attempts it made are graded and kept; start another run below to reach the tasks it did not.
          </p>
        </NotificationBanner>
      )}
      {inFlight && (
        <NotificationBanner title="Important">
          <Hint as="p" id="banner.measure.inflight" className="m-0 mb-2 font-bold">
            A measurement is already {active.data?.status === 'queued' ? 'queued' : 'running'} for {name}.
            {active.data && (
              <>
                {' '}
                {active.data.started ? `Started ${clock(active.data.started)}; ` : 'Not started yet; '}
                {active.data.progress.total > 0 ? `${active.data.progress.done} of ${active.data.progress.total} attempts made` : 'no attempt made yet'}; {usd(active.data.cost_usd)} spent so far.
              </>
            )}
          </Hint>
          <p className="m-0 mb-2">
            <Link to={`/runs/${encodeURIComponent(activeId)}`}>Open the run</Link> · <Link to={`/connect/${encodeURIComponent(name)}`}>Back to the walk</Link>
          </p>
          <p className="m-0">Start another run only when this one has finished or been cancelled.</p>
        </NotificationBanner>
      )}
      <h2 className="mb-2 text-[24px] font-bold leading-[1.3]">How many attempts</h2>
      <div className="mb-8 max-w-[44em]">
        {operator ? (
          LIMITS.map((l) => (
            <Hint as="label" id="field.measure.attempts" key={l.n} className="flex cursor-pointer items-center gap-4 py-2 text-[19px] leading-[1.47]">
              <input type="radio" name="limit" className="h-6 w-6 accent-[var(--trust)]" checked={limit === l.n} onChange={() => setLimit(l.n)} />
              <span>{l.n} attempts</span>
              <span className="text-on-surface-muted">{l.note}</span>
            </Hint>
          ))
        ) : (
          // nothing a role cannot act on is shown as a control: the choices as a read-only list
          <SummaryList label="How many attempts" rows={LIMITS.map((l) => ({ key: `${l.n} attempts`, value: `${l.note}${l.n === limit ? ' (the default)' : ''}`, hint: 'field.measure.attempts' }))} />
        )}
        {gold > 0 && gold < limit && (
          <Hint as="p" id="stat.measure.gold_cap" className="m-0 mt-2 text-[16px] text-on-surface-muted">
            {name} has {gold} gold-clean tasks, so this run makes {gold} attempts (one per task).
          </Hint>
        )}
        {repo.data && gold === 0 && (
          <p className="m-0 mt-2 text-[16px] font-bold text-status-red" data-testid="no-gold">
            {name} has no gold-clean task to replay, so a run would make no attempt. Mine the repository first (stage 3 of the walk) and check its gold status under <Link to={`/repos/${encodeURIComponent(name)}`}>Configuration</Link>.
          </p>
        )}
      </div>
      <h2 className="mb-2 text-[24px] font-bold leading-[1.3]">Spend cap</h2>
      <div className="mb-8 max-w-[44em]">
        {operator ? (
          <>
            <Hint as="label" id="field.measure.spend_cap" className="flex items-center gap-4 py-2 text-[19px] leading-[1.47]">
              <span>Stop the run at $</span>
              <input
                type="number"
                min={0.01}
                step="0.01"
                inputMode="decimal"
                className="w-32 border-2 border-[var(--ink)] bg-surface px-2 py-1 text-[19px]"
                value={capText}
                onChange={(e) => setCapDraft(e.target.value)}
                aria-describedby="measure-cap-note"
              />
            </Hint>
            <p id="measure-cap-note" className="m-0 mt-2 text-[16px] text-on-surface-muted">
              The run stops itself before an attempt that could take its spend past this amount. It starts at the top of the estimate.
            </p>
            {!capOk && (
              <p className="m-0 mt-2 text-[16px] font-bold text-status-red" data-testid="cap-invalid">
                Enter an amount above $0: the run needs a cap it can keep.
              </p>
            )}
          </>
        ) : (
          <SummaryList label="Spend cap" rows={[{ key: 'Stop the run at', value: `${usd(capOk ? cap : 0)}, the top of the estimate unless the operator sets another`, hint: 'field.measure.spend_cap' }]} />
        )}
      </div>
      <h2 className="mb-2 text-[24px] font-bold leading-[1.3]">Retention</h2>
      <Lede className="mb-2">This deployment retains no raw artefacts by default. Anything you keep here is stored until you delete it and is in scope for your own retention policy.</Lede>
      <div className="mb-8 max-w-[44em]">
        {operator ? (
          <>
            <Hint as="label" id="field.measure.retain_worktrees" className="flex cursor-pointer items-center gap-4 py-2 text-[19px] leading-[1.47]">
              <input type="checkbox" className="h-6 w-6 accent-[var(--trust)]" checked={worktrees} onChange={(e) => setWorktrees(e.target.checked)} />
              <span>Keep worktrees for failed attempts</span>
            </Hint>
            <Hint as="label" id="field.measure.retain_transcripts" className="flex cursor-pointer items-center gap-4 py-2 text-[19px] leading-[1.47]">
              <input type="checkbox" className="h-6 w-6 accent-[var(--trust)]" checked={transcripts} onChange={(e) => setTranscripts(e.target.checked)} />
              <span>Keep builder transcripts</span>
            </Hint>
          </>
        ) : (
          <SummaryList
            label="Retention"
            rows={[
              { key: 'Worktrees for failed attempts', value: 'not kept unless the operator chooses to', hint: 'field.measure.retain_worktrees' },
              { key: 'Builder transcripts', value: 'not kept unless the operator chooses to', hint: 'field.measure.retain_transcripts' },
            ]}
          />
        )}
      </div>
      <div className="mb-8 max-w-[44em] border border-border p-6 shadow-[0_4px_0_var(--line)]" data-testid="before-you-start">
        <h2 className="mb-4 text-[24px] font-bold leading-[1.3]">Before you start</h2>
        <SummaryList
          rows={[
            // the estimate gives way to the banner while a run is in flight: no second spend is priced
            ...(inFlight ? [] : [estimate]),
            {
              key: 'Builder',
              hint: 'summary.measure.builder',
              value: choice ? choice.label : 'No builder is configured on this deployment — an admin adds a provider key (Settings), or use the full run form',
              // the door to the full run form, with its own hint (a summary row's Change slot cannot carry one)
              note: (
                <Hint as={Link} id="link.measure.every_knob" to="/runs" className="underline">
                  Every knob<span className="sr-only"> — the full run form</span>
                </Hint>
              ),
            },
            // F5b: the cap the request carries and the worker keeps, and how it is kept
            {
              key: 'Budget cap',
              hint: 'summary.measure.budget_cap',
              value: capOk
                ? `${usd(cap)} for the whole run. Before each attempt the run counts what it has spent plus what that attempt could cost, and stops if the sum would pass ${usd(cap)}; an attempt with no cost cap of its own is counted at the dearest attempt so far. You can also cancel at any point; attempts already made are still charged.`
                : 'No valid cap yet: enter an amount above $0 under Spend cap.',
            },
            { key: 'Retention', hint: 'summary.measure.retention', value: retention },
            { key: 'Posture', hint: 'summary.measure.posture', value: posture },
          ]}
        />
        {inFlight ? (
          <p className="mb-0 mt-6 text-[19px] leading-[1.47]">A measurement is in flight for {name} (see above). Cancel it from the run page if you need to; attempts already made are still charged.</p>
        ) : (
          <>
            <p className="mb-4 mt-6 text-[19px] leading-[1.47]">You can cancel the run at any point. Attempts already made are still charged.</p>
            {operator && (
              <WarningButton hint="button.measure.start" onClick={start} disabled={create.isPending || !repo.data || !choice || gold === 0 || !capOk}>
                Start the run — estimated {usd(lo)} to {usd(hi)}{capOk ? `, stops at ${usd(cap)}` : ''}
              </WarningButton>
            )}
          </>
        )}
        {create.isError && <ErrorState compact error={create.error} />}
      </div>
    </>
  )
}
