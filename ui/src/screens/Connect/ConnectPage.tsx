/**
 * Connect — the guided walk from a Git URL to the baseline, and the connected repositories.
 *
 * Navigation
 * ----------
 * What it is:   The first screen of the journey (/connect): the repositories already connected
 *               with the stage each is at, and — for one repository (/connect/:name) — the six
 *               stages as a task list (register → probe → mine → oracle → controls → first
 *               measurement) with the action for the next one and, while a stage runs, an
 *               in-flight panel (the attempt in hand of total (`kOfN`), spend so far, started, Cancel).
 * What it does: Lets an enterprise tech lead connect a repository and get to the baseline
 *               without knowing the product's vocabulary: every stage says what it proves and
 *               what it costs ("no model involved" / "spends model budget"), gold-clean, oracle
 *               strength and negative controls carry their definitions (`Term`), the status is
 *               derived from the API (`stagesFor`), so the walk resumes where the repository
 *               is, and the action is gated on the operator role like the API is (a
 *               non-operator reads "An operator runs this."). Nothing here fabricates
 *               progress: a stage is done only when the API holds its evidence, a queued run
 *               reads "Queued" with its place in the line (the server's `queue_position`),
 *               the running stage's line is the polled run's own counter (`runningDetail`),
 *               and a passed controls report that still carries a finding (an escape, a
 *               thin set) reads "Done, with a finding" in amber — deliver is withheld until
 *               it is answered. Every door to /results is named "Baseline", as the nav
 *               names it, and opens /results (a measured row's button; an unmeasured row's
 *               reads "Continue" and opens the walk); at phone width the repository link
 *               is the row's door to the walk.
 * How:          `useAllRepos` → the table; `useRepo` + `useOracle` + `useOracleControls` +
 *               `useCapabilityMap` (+ the polled `useRun` while a stage runs, and
 *               `useQueuedRuns` only for an older server that sends no `queue_position`)
 *               → `stagesFor` → the stage list; actions are the existing mutations
 *               (`useProbeRepo`, `useCreateRun`, `useCancelRun` behind a confirm) and dialogs
 *               (`RepoNewDialog`, `RunNewDialog`); the watched run's end refetches the inputs.
 *               The eyebrow is `PageHeader`'s default (`journeyEyebrow`).
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/screens/Connect/connection.ts (the derivation), ui/src/api/hooks.ts
 *               (`useRun`, `useQueuedRuns`, `useCancelRun`), ui/src/components/Help.tsx
 *               (`Term`), ui/src/screens/Repos/* (registration and config live there; this
 *               screen links to them), ui/src/screens/Results/ResultsPage.tsx (the baseline,
 *               where the walk ends), docs/ONBOARDING-A-REPO.md (the same steps for the CLI)
 * Tested by:    ui/src/screens/Connect/ConnectPage.test.tsx
 * Touch when:   a stage is added (connection.ts first); the API grows a GitHub App install
 *               flow (replace the URL field with the installation's repository picker).
 */

import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router'
import {
  useAllRepos,
  useCancelRun,
  useCapabilityMap,
  useCreateRun,
  useGitHubApp,
  useOracle,
  useOracleControls,
  useProbeRepo,
  useQueuedRuns,
  useRepo,
  useRun,
} from '../../api/hooks'
import { isApiError } from '../../api/client'
import type { RepoSummary, Run } from '../../api/types'
import { Button, LinkButton } from '../../components/Button'
import { Card } from '../../components/Card'
import { EmptyState } from '../../components/EmptyState'
import { ErrorState } from '../../components/ErrorState'
import { Term } from '../../components/Help'
import { PageHeader } from '../../components/PageHeader'
import { Pill } from '../../components/Pill'
import { useAuth } from '../../lib/auth'
import { kOfN } from '../../lib/format'
import type { Tone } from '../../lib/verdict'
import { RepoNewDialog } from '../Repos/RepoNewDialog'
import { RunNewDialog } from '../Runs/RunNewDialog'
import { GitHubConnectDialog } from './GitHubConnectDialog'
import { type Stage, type StageStatus, stageComplete, stageSummary, stagesFor } from './connection'

const STATUS_DISPLAY: Record<StageStatus, { label: string; tone: Tone; glyph: string }> = {
  done: { label: 'Done', tone: 'green', glyph: '✓' },
  // the stage holds its evidence and the walk goes on, but the evidence carries a finding
  // (a controls escape, a thin set): read before spending — deliver is withheld meanwhile
  warn: { label: 'Done, with a finding', tone: 'amber', glyph: '!' },
  running: { label: 'In progress', tone: 'blue', glyph: '◐' },
  todo: { label: 'Not started', tone: 'muted', glyph: '○' },
  failed: { label: 'Failed', tone: 'red', glyph: '✕' },
  blocked: { label: 'Waiting', tone: 'muted', glyph: '·' },
}
/** A queued run is not in progress: nothing has started and nothing has been spent. */
const QUEUED_DISPLAY = { label: 'Queued', tone: 'muted' as Tone, glyph: '…' }

/** The stage title with its term one click away (titles are plain strings in connection.ts). */
function StageTitle({ stage }: { stage: Stage }) {
  if (stage.id === 'oracle') {
    return (
      <span className="font-semibold">
        <Term id="oracle_strength">Oracle strength</Term> scored
      </span>
    )
  }
  if (stage.id === 'controls') {
    return (
      <span className="font-semibold">
        <Term id="negative_controls">Negative controls</Term> passed
      </span>
    )
  }
  return <span className="font-semibold">{stage.title}</span>
}

/** "14:05" — the wall-clock time a run started, for the in-flight panel. */
function clock(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hourCycle: 'h23' })
}

/** A 404 from the oracle / controls routes means "never run" — a stage state, not an error. */
function notRun(err: unknown): boolean {
  return isApiError(err) && err.status === 404
}

// ---------------------------------------------------------------------------
// /connect — the connected repositories
// ---------------------------------------------------------------------------

export function ConnectPage() {
  const repos = useAllRepos()
  const { can } = useAuth()
  const navigate = useNavigate()
  const gh = useGitHubApp()
  const [params] = useSearchParams()
  // the app's setup callback lands here with ?installation=<id> — open the picker on it
  const landedInstallation = Number(params.get('installation') ?? 0) || 0
  // …and with &unverified=1 when the callback carried no signed state for this session:
  // nothing was recorded; the operator records it with the CSRF-protected sync
  const landedUnverified = params.get('unverified') === '1'
  const [newOpen, setNewOpen] = useState(false)
  const [ghOpen, setGhOpen] = useState(landedInstallation > 0)
  const ghConfigured = gh.data?.configured === true

  return (
    <>
      <PageHeader
        title="Connect a repository"
        purpose="Point the instrument at a repository, let it learn how the code tests itself, and get to the baseline. Nothing is written to the repository; the first five stages involve no model."
        actions={
          can('operator') ? (
            <div className="flex flex-wrap gap-2">
              <Button variant={ghConfigured ? 'filled' : 'outlined'} onClick={() => setGhOpen(true)}>
                Connect from GitHub
              </Button>
              <Button variant={ghConfigured ? 'outlined' : 'filled'} onClick={() => setNewOpen(true)}>
                Connect by URL
              </Button>
            </div>
          ) : undefined
        }
      />
      {gh.data && !gh.data.configured && can('admin') && (
        <p className="m-0 -mt-3 text-xs text-on-surface-muted" data-testid="github-app-hint">
          The GitHub App is not configured: an admin registers it once (app id + private key, <code>docs/GITHUB-APP.md</code>) and organisations then install it on the repositories it may see — the enterprise way to connect, no tokens to hand over.
        </p>
      )}
      <Card title="Connected repositories" eyebrow="where each one is on the walk">
        {repos.isPending && <p className="text-sm text-on-surface-muted">Loading…</p>}
        {repos.isError && <ErrorState error={repos.error} onRetry={() => void repos.refetch()} />}
        {repos.data && repos.data.items.length === 0 && (
          <EmptyState
            glyph="⎇"
            title="No repository connected yet"
            reason="Connect one to start the walk: register, probe, mine, oracle, controls, then a first measurement."
            action={can('operator') ? <Button variant="filled" onClick={() => (ghConfigured ? setGhOpen(true) : setNewOpen(true))}>Connect a repository</Button> : undefined}
          />
        )}
        {repos.data && repos.data.items.length > 0 && (
          <div className="overflow-x-auto" tabIndex={0} role="region" aria-label="Connected repositories, scrollable">
            <table className="w-full text-sm" aria-label="Connected repositories">
              <thead>
                <tr className="text-left text-xs text-on-surface-muted">
                  <th className="py-2 pr-4 font-medium">Repository</th>
                  <th className="py-2 pr-4 font-medium">Language</th>
                  <th className="py-2 pr-4 font-medium">Tasks</th>
                  <th className="py-2 pr-4 font-medium">Next stage</th>
                  <th className="py-2 pr-4 font-medium">Last run</th>
                  <th className="hidden py-2 font-medium sm:table-cell"></th>
                </tr>
              </thead>
              <tbody>
                {repos.data.items.map((r) => (
                  <RepoRow key={r.name} repo={r} />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      <RepoNewDialog
        open={newOpen}
        onClose={() => setNewOpen(false)}
        onCreated={(name) => {
          setNewOpen(false)
          navigate(`/connect/${encodeURIComponent(name)}`)
        }}
      />
      <GitHubConnectDialog
        open={ghOpen}
        initialInstallation={landedInstallation || undefined}
        landedUnverified={landedUnverified}
        onClose={() => setGhOpen(false)}
        onUseUrl={() => {
          setGhOpen(false)
          setNewOpen(true)
        }}
        onConnected={(name) => {
          setGhOpen(false)
          navigate(`/connect/${encodeURIComponent(name)}`)
        }}
      />
    </>
  )
}

function RepoRow({ repo }: { repo: RepoSummary }) {
  // the same inputs the per-repository page uses, so the table never says "oracle next" for
  // a repository that is fully measured (three cached reads per row)
  const oracle = useOracle(repo.name)
  const controls = useOracleControls(repo.name)
  const map = useCapabilityMap(repo.name, ['capability_class', 'size'])
  const stages = stagesFor({
    repo,
    oracle: oracle.data ?? (oracle.isError && notRun(oracle.error) ? null : undefined),
    controls: controls.data ?? (controls.isError && notRun(controls.error) ? null : undefined),
    measuredRows: map.data?.summary.n_total,
  })
  const s = stageSummary(stages)
  const d = STATUS_DISPLAY[s.status]
  return (
    <tr className="border-t border-border">
      <td className="py-2 pr-4 font-mono text-xs">
        <Link to={`/connect/${encodeURIComponent(repo.name)}`}>{repo.name}</Link>
      </td>
      <td className="py-2 pr-4">
        {repo.language}
        {repo.runner ? ` / ${repo.runner}` : ''}
      </td>
      <td className="num whitespace-nowrap py-2 pr-4 font-mono text-xs">
        {repo.task_counts.total} · {repo.task_counts.gold_clean} <Term id="gold_clean">gold-clean</Term>
      </td>
      <td className="py-2 pr-4">
        <Pill tone={d.tone} glyph={d.glyph} size="xs">
          {s.label}
        </Pill>
      </td>
      <td className="py-2 pr-4 font-mono text-xs text-on-surface-muted">
        {repo.last_run ? `${repo.last_run.kind} · ${repo.last_run.status}` : '—'}
      </td>
      {/* below sm the column is off-canvas in the scrolling table: the repository link in column one is the row's action there */}
      <td className="hidden py-2 text-right sm:table-cell">
        {stageComplete(s.status) ? (
          <LinkButton size="sm" to={`/results?repo=${encodeURIComponent(repo.name)}`}>
            Baseline
          </LinkButton>
        ) : (
          <LinkButton size="sm" to={`/connect/${encodeURIComponent(repo.name)}`}>
            Continue
          </LinkButton>
        )}
      </td>
    </tr>
  )
}

// ---------------------------------------------------------------------------
// /connect/:name — the task list for one repository
// ---------------------------------------------------------------------------

export function ConnectRepoPage() {
  const { name = '' } = useParams()
  const { can } = useAuth()
  const repo = useRepo(name)
  const oracle = useOracle(name)
  const controls = useOracleControls(name)
  const map = useCapabilityMap(name, ['capability_class', 'size'])
  const probe = useProbeRepo()
  const createRun = useCreateRun()
  const cancel = useCancelRun()
  const [measureOpen, setMeasureOpen] = useState(false)

  const oracleInput = oracle.data ?? (oracle.isError && notRun(oracle.error) ? null : undefined)
  const controlsInput = controls.data ?? (controls.isError && notRun(controls.error) ? null : undefined)
  // the active run's id comes from the repository's last run; the polled run and the queue
  // are read only while one is active, and feed the stage's live line
  const activeRunId = repo.data?.last_run && (repo.data.last_run.status === 'queued' || repo.data.last_run.status === 'running') ? repo.data.last_run.id : ''
  const watched = useRun(activeRunId, { poll: Boolean(activeRunId) })
  // the place in the line is the server's `queue_position` (1-based, the same (created, id)
  // order the worker claims in); the queued list is read only for an older server that
  // does not send it, and then it is the best the client can do (no id tiebreak)
  const serverPosition = watched.data?.status === 'queued' && typeof watched.data.queue_position === 'number' ? watched.data.queue_position : null
  const queue = useQueuedRuns(watched.data?.status === 'queued' && serverPosition === null)
  const queuedAhead =
    watched.data?.status !== 'queued'
      ? undefined
      : serverPosition !== null
        ? Math.max(0, serverPosition - 1)
        : queue.data
          ? queue.data.items.filter((r) => r.id !== watched.data!.id && r.created < watched.data!.created).length
          : undefined
  const stages = repo.data
    ? stagesFor({ repo: repo.data, oracle: oracleInput, controls: controlsInput, measuredRows: map.data?.summary.n_total, watched: watched.data, queuedAhead })
    : []

  // when the watched run ends, every input may have changed — refetch them all
  const watchedStatus = watched.data?.status
  useEffect(() => {
    if (watchedStatus && watchedStatus !== 'queued' && watchedStatus !== 'running') {
      void repo.refetch()
      void oracle.refetch()
      void controls.refetch()
      void map.refetch()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [watchedStatus])

  const act = (stage: Stage) => {
    if (stage.runKind === 'probe') probe.mutate(name)
    else if (stage.runKind === 'replay') setMeasureOpen(true)
    else if (stage.runKind) createRun.mutate({ repo: name, kind: stage.runKind })
  }
  const cancelRun = (run: Run) => {
    if (!window.confirm('Cancel this run? Attempts already made are still charged.')) return
    cancel.mutate(run.id)
  }
  const busy = probe.isPending || createRun.isPending
  const actionError = probe.error ?? createRun.error ?? cancel.error
  const allDone = stages.length > 0 && stages.every((s) => stageComplete(s.status))
  const next = stages.find((s) => !stageComplete(s.status))

  return (
    <>
      <PageHeader
        title={name}
        purpose={
          allDone
            ? 'Every stage is done — the baseline holds what the evidence says about this repository.'
            : next
              ? `Next: ${next.title.toLowerCase()}. ${next.why}`
              : 'Loading the repository…'
        }
        actions={
          <div className="flex gap-2">
            <LinkButton size="sm" to={`/repos/${encodeURIComponent(name)}`}>
              Configuration
            </LinkButton>
            <LinkButton size="sm" variant={allDone ? 'filled' : 'outlined'} to={`/results?repo=${encodeURIComponent(name)}`}>
              Baseline
            </LinkButton>
          </div>
        }
      />
      {repo.isError && <ErrorState error={repo.error} onRetry={() => void repo.refetch()} />}
      {repo.data && (
        <Card title="The walk" eyebrow="six stages · each says what it proves and what it costs">
          <ol className="m-0 list-none space-y-3 p-0" aria-label="Connection stages">
            {stages.map((s, i) => {
              const d = s.queued ? QUEUED_DISPLAY : STATUS_DISPLAY[s.status]
              const canAct = s.status === 'todo' || s.status === 'failed'
              // the polled run belongs to this stage: the in-flight panel reads from it
              const live = s.status === 'running' && watched.data && watched.data.id === s.runId ? watched.data : null
              return (
                <li key={s.id} className="grid grid-cols-[2rem_1fr_auto] items-start gap-3 border-t border-border pt-3 first:border-t-0 first:pt-0" data-testid={`stage-${s.id}`}>
                  <span className="num font-mono text-sm text-on-surface-muted">{i + 1}.</span>
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <StageTitle stage={s} />
                      <Pill tone={d.tone} glyph={d.glyph} size="xs" label={`${s.title}: ${d.label}`}>
                        {d.label}
                      </Pill>
                      {s.spends && !stageComplete(s.status) && (
                        <Pill tone="amber" size="xs" glyph="$">
                          spends model budget
                        </Pill>
                      )}
                    </div>
                    <p className="mt-1 mb-1 max-w-[70ch] text-sm text-on-surface-body">{s.why}</p>
                    <p className="m-0 text-xs text-on-surface-muted">
                      {s.detail}
                      {s.runId && !live && (
                        <>
                          {' · '}
                          <Link to={`/runs/${s.runId}`}>open run</Link>
                        </>
                      )}
                    </p>
                    {live && <InFlight run={live} stage={s} canCancel={can('operator')} cancelling={cancel.isPending} onCancel={() => cancelRun(live)} />}
                  </div>
                  <div className="text-right">
                    {canAct && s.runKind && can('operator') && (
                      <Button size="sm" variant={s.spends ? 'outlined' : 'filled'} disabled={busy} onClick={() => act(s)}>
                        {s.status === 'failed' ? 'Retry' : s.runKind === 'replay' ? 'Measure…' : 'Run'}
                      </Button>
                    )}
                    {canAct && s.runKind && !can('operator') && (
                      <span className="text-xs text-on-surface-muted">{s.spends ? 'An operator starts this; it spends model budget.' : 'An operator runs this.'}</span>
                    )}
                  </div>
                </li>
              )
            })}
          </ol>
          {actionError && <ErrorState compact error={actionError} />}
        </Card>
      )}
      <RunNewDialog
        open={measureOpen}
        onClose={() => setMeasureOpen(false)}
        repo={name}
        initialKind="replay"
        onCreated={() => {
          setMeasureOpen(false)
          void repo.refetch()
        }}
      />
    </>
  )
}

// ---------------------------------------------------------------------------
// The in-flight panel under a running stage
// ---------------------------------------------------------------------------

/**
 * What the run the person just started is doing, from the run the page already polls:
 * the attempt in hand of total (`kOfN`, the Baseline's number), the builder-reported spend so
 * far, when it started (that line is a `role="status"` region, announced politely), the run link,
 * a Cancel (operator only, behind a confirm — attempts already made are still charged) and
 * the one sentence that says what happens when it finishes. A queued run says it is waiting
 * for a worker and has spent nothing.
 */
function InFlight({ run, stage, canCancel, cancelling, onCancel }: { run: Run; stage: Stage; canCancel: boolean; cancelling: boolean; onCancel: () => void }) {
  const { done, total } = run.progress
  const unit = stage.id === 'measure' ? 'Attempt' : 'Task'
  // "Attempt 4 of 8" = the fourth is running now (`kOfN`: done + 1) — the Baseline banner says the same number.
  // A queued run has nothing in hand, whatever `progress` still carries (a reclaimed run keeps its
  // old counts while it waits): the status is checked before the number is read
  const progress = run.status === 'queued' ? null : kOfN(done, total)
  const head = run.status === 'queued' ? 'Waiting for a worker' : progress ? `${unit} ${progress}` : stage.id === 'measure' ? 'First attempt starting' : 'Running'
  const spend = stage.spends ? ` · $${run.cost_usd.toFixed(2)} spent so far` : ''
  const started = run.started ? ` · started ${clock(run.started)}` : ''
  const next =
    stage.id === 'measure'
      ? 'Rows land on the baseline as each attempt is graded; when the run finishes this stage turns Done and the Baseline button fills in.'
      : 'When the run finishes this stage turns Done and the next stage unlocks.'
  return (
    <div className="mt-2 max-w-[70ch] border-l-4 border-primary pl-3 text-sm" data-testid="in-flight">
      {/* the line that changes every poll is a polite live region; the link and Cancel stay outside it */}
      <p className="m-0" role="status">
        <span className="num font-mono">
          {head}
          {spend}
          {started}.
        </span>{' '}
        {next}
      </p>
      <p className="m-0 mt-1 flex flex-wrap items-center gap-x-3 gap-y-1">
        <Link to={`/runs/${run.id}`}>Open the run</Link>
        {run.cancel_requested ? (
          <span className="text-on-surface-muted">Cancel requested — the worker stops between {stage.id === 'measure' ? 'attempts' : 'tasks'}.</span>
        ) : (
          canCancel && (
            <Button size="sm" variant="outlined" disabled={cancelling} onClick={onCancel}>
              Cancel the run
            </Button>
          )
        )}
        {canCancel && !run.cancel_requested && <span className="text-xs text-on-surface-muted">(attempts already made are still charged)</span>}
      </p>
    </div>
  )
}
