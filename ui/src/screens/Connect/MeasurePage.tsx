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
 *               attempt, the budget cap, retention, posture) and one red button that says
 *               the amount — the MoJ "confirm an action" pattern.
 * What it does: Replaces the technical run dialog for the person who has never used the
 *               product: every number on the page is the deployment's (the cost estimate is
 *               the repository's measured mean per attempt when it has one, else the
 *               documented range), the posture is the real sandbox mode, and nothing is
 *               queued until the red button.
 * How:          `useRepo`, `useCapabilityMap` (cost_usd_mean over measured cells),
 *               `useSettings` (sandbox posture; admin only — falls back to /health),
 *               `useCreateRun` with `{kind: replay, mode: sighted, limit, retain}`; on
 *               success the walk resumes on the repository with the run watched.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0006-zero-raw-retention-and-evidence-packs.md
 * Works with:   ui/src/components/govuk.tsx, ui/src/screens/Connect/ConnectPage.tsx (the
 *               walk that lands here), ui/src/screens/Runs/RunNewDialog.tsx (the full form
 *               for an operator who wants every knob), src/crb/server/routes/runs.py
 * Tested by:    ui/src/screens/Connect/MeasurePage.test.tsx
 * Touch when:   the run request grows a field the walk should expose.
 */

import { useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router'
import { useCapabilityMap, useCreateRun, useHealth, useRepo } from '../../api/hooks'
import { NOT_YET_MEASURED } from '../../api/types'
import { ErrorState } from '../../components/ErrorState'
import { BackLink, Kicker, Lede, PageTitle, SummaryList, WarningButton } from '../../components/govuk'
import { useAuth } from '../../lib/auth'

const LIMITS: Array<{ n: number; note: string }> = [
  { n: 10, note: 'enough to see the shape, not to route' },
  { n: 30, note: 'the first useful picture' },
  { n: 60, note: 'tighter intervals, longer wait' },
]
//: the documented per-attempt range when the repository has no measured mean yet
const RANGE_LOW = 0.2
const RANGE_HIGH = 0.6

export interface BuilderChoice {
  builder: string
  model: string
  builder_config?: Record<string, unknown>
  /** What the "Before you start" row says. */
  label: string
  /** True when the choice is the operator's own CLI login — a development posture. */
  development: boolean
}

/**
 * The builder the walk measures with, from what the deployment has configured (the
 * `/health` builders probe reports presence only): an Anthropic key → Claude Code in
 * production auth; only a Claude Code CLI login → Claude Code with `{auth: "cli"}` (the
 * operator's own login — development and evaluation only, and the row says so); nothing
 * usable → null (the page points at the full run form).
 */
export function builderChoice(keys: Record<string, unknown> | undefined): BuilderChoice | null {
  if (!keys) return null
  if (keys.anthropic) return { builder: 'claude_code', model: 'claude-sonnet-5', label: 'Claude Code · claude-sonnet-5 · API key (production)', development: false }
  if (keys.claude_code_cli) return { builder: 'claude_code', model: 'claude-sonnet-5', builder_config: { auth: 'cli' }, label: 'Claude Code · claude-sonnet-5 · the operator\u2019s own CLI login (development and evaluation only)', development: true }
  return null
}

function usd(x: number): string {
  return `$${x.toFixed(2)}`
}

export function MeasurePage() {
  const { name = '' } = useParams()
  const navigate = useNavigate()
  const { can } = useAuth()
  const repo = useRepo(name)
  const map = useCapabilityMap(name, ['capability_class', 'size'])
  const health = useHealth()
  const create = useCreateRun()
  const [limit, setLimit] = useState(30)
  const [worktrees, setWorktrees] = useState(false)
  const [transcripts, setTranscripts] = useState(false)

  // the repository's own measured mean per attempt, when it has one
  const measuredMean = useMemo(() => {
    const cells = (map.data?.cells ?? []).filter((c) => c.route !== NOT_YET_MEASURED && c.n > 0 && c.cost_usd_mean > 0)
    if (cells.length === 0) return null
    const n = cells.reduce((a, c) => a + c.n, 0)
    return cells.reduce((a, c) => a + c.cost_usd_mean * c.n, 0) / n
  }, [map.data])
  const lo = measuredMean !== null ? measuredMean * 0.8 * limit : RANGE_LOW * limit
  const hi = measuredMean !== null ? measuredMean * 1.2 * limit : RANGE_HIGH * limit
  const sandbox = health.data?.probes.find((p) => p.name === 'sandbox')
  const builders = health.data?.probes.find((p) => p.name === 'builders')
  const choice = builderChoice(builders?.data)
  const sealed = sandbox?.status === 'ok'
  const gold = repo.data?.task_counts.gold_clean ?? 0
  const retention = !worktrees && !transcripts ? 'Nothing retained — grades and hashes only' : `${[worktrees && 'worktrees', transcripts && 'transcripts'].filter(Boolean).join(' and ')} kept until deleted`

  const start = () => {
    if (!choice) return
    create.mutate(
      {
        repo: name,
        kind: 'replay',
        mode: 'sighted',
        builder: choice.builder,
        model: choice.model,
        ...(choice.builder_config ? { builder_config: choice.builder_config } : {}),
        limit: Math.min(limit, Math.max(gold, 1)),
        retain: { worktrees, transcripts },
      },
      { onSuccess: () => navigate(`/connect/${encodeURIComponent(name)}`) },
    )
  }

  return (
    <>
      <BackLink to={`/connect/${encodeURIComponent(name)}`}>Back to the instrument proof</BackLink>
      <div>
        <Kicker>Task 5 of 7 · this step spends money</Kicker>
      </div>
      <PageTitle>Measure {name}</PageTitle>
      {repo.isError && <ErrorState error={repo.error} onRetry={() => void repo.refetch()} />}
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
            { key: 'Estimated cost', value: `${usd(lo)} to ${usd(hi)} for ${limit} attempts${measuredMean !== null ? `, at about ${usd(measuredMean)} each (this repository's measured mean)` : `, at ${usd(RANGE_LOW)}–${usd(RANGE_HIGH)} each (the documented range; this repository has no measured mean yet)`}` },
            { key: 'Builder', value: choice ? choice.label : 'No builder is configured on this deployment — an admin adds a provider key (Settings), or use the full run form', changeTo: '/runs', changeLabel: 'Every knob' },
            { key: 'Budget cap', value: 'Per attempt — the builder’s ladder caps turns, tool calls and wall clock; a run can be cancelled at any point' },
            { key: 'Retention', value: retention },
            { key: 'Posture', value: sealed ? 'sealed (docker) — countable as evidence' : `${sandbox?.status ?? 'unknown'} — a development reading, not evidence, until the sandbox is available` },
          ]}
        />
        <p className="mb-4 mt-6 text-[19px] leading-[1.47]">You can cancel the run at any point. Attempts already made are still charged.</p>
        {can('operator') ? (
          <WarningButton onClick={start} disabled={create.isPending || !repo.data || !choice}>
            Start the run and spend up to {usd(hi)}
          </WarningButton>
        ) : (
          <p className="m-0 text-[16px] text-on-surface-muted">Starting a run needs the operator role.</p>
        )}
        {create.isError && <ErrorState compact error={create.error} />}
      </div>
    </>
  )
}
