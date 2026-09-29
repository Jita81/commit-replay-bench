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
 * What it does: Lets an enterprise tech lead connect a repository and get to the baseline without
 *               knowing the product's vocabulary: every stage says what it proves and what it costs
 *               ("no model involved" / "spends model budget"), gold-clean, oracle strength and
 *               negative controls carry their definitions (`Term`), the status is derived from the
 *               API (`stagesFor`), so the walk resumes where the repository is, and the action is
 *               gated on the operator role like the API is (a non-operator reads "An operator runs
 *               this."). Nothing here fabricates progress: a stage is done only when the API holds
 *               its evidence, a queued run reads "Queued" with its place in the line (the server's
 *               `queue_position`), the running stage's line is the polled run's own counter
 *               (`runningDetail`), and a passed controls report that still carries a finding (an
 *               escape, a thin set) reads "Done, with a finding" in amber — deliver is withheld
 *               until it is answered. A row whose oracle, controls or map read fails for a reason
 *               other than 404 (never run) shows that error with Retry in its Next stage cell,
 *               never a stage state (G-124); on the walk, such a failed read (`failedRead`) is
 *               said with Retry in place of the stages, with no stage action offered, so a
 *               failed map never reads "Not started" beside a paid Measure… (G-730). Every door
 *               to /results is named "Baseline", as the nav names it, and opens /results (a
 *               measured row's button; an unmeasured row's reads
 *               "Continue" and opens the walk); at phone width the repository link is the row's
 *               door to the walk, and the door column's header is visually hidden text a
 *               screen reader names ("Next", G-127). The header offers every role the flat
 *               list at /repos ("All repositories", G-228). The sixth stage's Measure… opens
 *               the designed Measure page (`/connect/:name/measure`, the same surface Home task
 *               5 opens) and posts nothing itself (G-907); a failed replay's Retry takes the
 *               same door. Cancel the run asks first in the app's own dialog — "Cancel this
 *               run?", Keep it running / Cancel the run — so the question is hinted, reachable
 *               and axe-checked, never `window.confirm` (G-117). An unknown repository name
 *               renders `UnknownRepo` ("No repository called <name>", Open Connection) under a
 *               header that reads Not found, never a bare retry (G-979). Under the mine stage,
 *               the config changes the mine's notes imply (`GET /repos/{name}/config-candidates`,
 *               DL-316) are listed with Accept and Reject for an operator; nothing changes
 *               until one decides. Every element a reader meets — the connect buttons, each
 *               column header, the stage-summary pill and row action, each stage's title, status
 *               pill, "spends" pill, detail line, run link and action, each candidate and its
 *               two acts, the in-flight panel's counters and Cancel, and the question's two
 *               buttons — is a hint trigger (`button.connect.*`, `col.connect.*`,
 *               `pill.connect.*`, `stage.walk.*`, `pill.walk.*`, `stat.walk.*`, `link.walk.*`,
 *               `button.walk.*`) so what each shows opens on hover, focus and tap and is listed in
 *               the About block.
 * How:          `useAllRepos` → the table; `useRepo` + `useOracle` + `useOracleControls` +
 *               `useCapabilityMap` + `useConfigCandidates` (+ the polled `useRun` while a stage
 *               runs, and `useQueuedRuns` only for an older server that sends no
 *               `queue_position`) → `stagesFor` → the stage list; actions are the existing
 *               mutations (`useProbeRepo`, `useCreateRun`, `useCancelRun` behind the `Dialog`,
 *               `useDecideCandidate`), the `RepoNewDialog`, and `navigate` to the Measure page;
 *               the watched run's end refetches the inputs. The eyebrow is `PageHeader`'s
 *               default (`journeyEyebrow`).
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/screens/Connect/connection.ts (the derivation), ui/src/api/hooks.ts
 *               (`useRun`, `useQueuedRuns`, `useCancelRun`, `useConfigCandidates`,
 *               `useDecideCandidate`), ui/src/components/Help.tsx
 *               (`Term`), ui/src/components/Hint.tsx + ui/src/help/hints.ts (the triggers
 *               and their copy), ui/src/components/Dialog.tsx (the cancel question),
 *               ui/src/components/UnknownRepo.tsx (the 404 state), ui/src/screens/Repos/*
 *               (registration and config live there; this screen links to them),
 *               ui/src/screens/Connect/MeasurePage.tsx (where Measure… lands),
 *               ui/src/screens/Results/ResultsPage.tsx (the baseline,
 *               where the walk ends), ui/src/components/FlowPanel.tsx (the connect stream's own
 *               lead time and spend under the walk), docs/ONBOARDING-A-REPO.md (the same steps
 *               for the CLI)
 * Tested by:    ui/src/screens/Connect/ConnectPage.test.tsx, ui/src/help/hints-ratchet.test.tsx
 *               (every element on /connect and /connect/:name resolves to a registry id, the
 *               cancel question included)
 * Touch when:   never for a new repository (it appears on the list once connected); a stage
 *               is added (connection.ts first); the API grows a GitHub App install flow
 *               (replace the URL field with the installation's repository picker).
 */

import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router'
import {
  useAllRepos,
  useCancelRun,
  useCapabilityMap,
  useConfigCandidates,
  useCreateRun,
  useDecideCandidate,
  useGitHubApp,
  useOracle,
  useOracleControls,
  useProbeRepo,
  useQueuedRuns,
  useRepo,
  useRun,
} from '../../api/hooks'
import { isApiError } from '../../api/client'
import type { ConfigCandidate, RepoSummary, Run } from '../../api/types'
import type { HintId } from '../../help/hints'
import { Button, LinkButton } from '../../components/Button'
import { Card } from '../../components/Card'
import { Dialog } from '../../components/Dialog'
import { EmptyState } from '../../components/EmptyState'
import { ErrorState } from '../../components/ErrorState'
import { FlowPanel } from '../../components/FlowPanel'
import { Term } from '../../components/Help'
import { Hint } from '../../components/Hint'
import { PageHeader } from '../../components/PageHeader'
import { Pill } from '../../components/Pill'
import { UnknownRepo, isUnknownRepo } from '../../components/UnknownRepo'
import { useAuth } from '../../lib/auth'
import { kOfN } from '../../lib/format'
import type { Tone } from '../../lib/verdict'
import { RepoNewDialog } from '../Repos/RepoNewDialog'
import { GitHubConnectDialog } from './GitHubConnectDialog'
import { type Stage, type StageId, type StageStatus, stageComplete, stageSummary, stagesFor } from './connection'

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

/** What each stage proves and costs — the hint on its title. */
const STAGE_HINT: Record<StageId, HintId> = {
  register: 'stage.walk.register',
  probe: 'stage.walk.probe',
  mine: 'stage.walk.mine',
  oracle: 'stage.walk.oracle',
  controls: 'stage.walk.controls',
  measure: 'stage.walk.measure',
}

/** The stage title with its term one click away (titles are plain strings in connection.ts) and its hint on hover. */
function StageTitle({ stage }: { stage: Stage }) {
  if (stage.id === 'oracle') {
    return (
      <Hint id={STAGE_HINT.oracle} className="font-semibold">
        <Term id="oracle_strength">Oracle strength</Term> scored
      </Hint>
    )
  }
  if (stage.id === 'controls') {
    return (
      <Hint id={STAGE_HINT.controls} className="font-semibold">
        <Term id="negative_controls">Negative controls</Term> passed
      </Hint>
    )
  }
  return (
    <Hint id={STAGE_HINT[stage.id]} className="font-semibold">
      {stage.title}
    </Hint>
  )
}

/** "14:05" — the wall-clock time a run started, for the in-flight panel. */
function clock(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hourCycle: 'h23' })
}

/** A 404 from the oracle / controls routes means "never run" — a stage state, not an error. */
function notRun(err: unknown): boolean {
  return isApiError(err) && err.status === 404
}

interface Read {
  isError: boolean
  error: unknown
  refetch: () => unknown
}

/**
 * The first of a repository's three stage reads that failed for a reason other than 404
 * (never run), with what it reads, or `undefined`. While one has failed the walk cannot say
 * where the repository is — a stage read from nothing would say "Not started" — so the list
 * row and the walk each show this error with Retry in place of any stage (G-124, G-730).
 */
function failedRead(oracle: Read, controls: Read, map: Read): { q: Read; what: string } | undefined {
  return [
    { q: oracle, what: 'oracle scores' },
    { q: controls, what: 'controls report' },
    { q: map, what: 'capability map' },
  ].find(({ q }) => q.isError && !notRun(q.error))
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
          <div className="flex flex-wrap gap-2">
            {/* G-228: the flat list is a door for every role, not a typed URL */}
            <LinkButton variant="outlined" to="/repos" hint="button.connect.all_repos">
              All repositories
            </LinkButton>
            {can('operator') && (
              <>
                <Button variant={ghConfigured ? 'filled' : 'outlined'} hint="button.connect.github" onClick={() => setGhOpen(true)}>
                  Connect from GitHub
                </Button>
                <Button variant={ghConfigured ? 'outlined' : 'filled'} hint="button.connect.url" onClick={() => setNewOpen(true)}>
                  Connect by URL
                </Button>
              </>
            )}
          </div>
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
            action={can('operator') ? <Button variant="filled" hint="button.connect.empty_connect" onClick={() => (ghConfigured ? setGhOpen(true) : setNewOpen(true))}>Connect a repository</Button> : undefined}
          />
        )}
        {repos.data && repos.data.items.length > 0 && (
          <div className="overflow-x-auto" tabIndex={0} role="region" aria-label="Connected repositories, scrollable">
            <table className="w-full text-sm" aria-label="Connected repositories">
              <thead>
                <tr className="text-left text-xs text-on-surface-muted">
                  <th scope="col" className="py-2 pr-4 font-medium">
                    <Hint id="col.connect.repository">Repository</Hint>
                  </th>
                  <th scope="col" className="py-2 pr-4 font-medium">
                    <Hint id="col.connect.language">Language</Hint>
                  </th>
                  <th scope="col" className="py-2 pr-4 font-medium">
                    <Hint id="col.connect.tasks">Tasks</Hint>
                  </th>
                  <th scope="col" className="py-2 pr-4 font-medium">
                    <Hint id="col.connect.next_stage">Next stage</Hint>
                  </th>
                  <th scope="col" className="py-2 pr-4 font-medium">
                    <Hint id="col.connect.last_run">Last run</Hint>
                  </th>
                  <th scope="col" className="hidden py-2 font-medium sm:table-cell">
                    {/* G-127: the door column has a name a screen reader announces; it is not drawn */}
                    <Hint id="col.connect.next">
                      <span className="sr-only">Next</span>
                    </Hint>
                  </th>
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
  // G-124: a read that failed for any reason but 404 (never run) is an error on this row,
  // never a stage state: the walk cannot say where the repository is without it
  const failed = failedRead(oracle, controls, map)
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
        {failed ? (
          <div data-testid="connect-row-error" className="min-w-[16em]">
            <ErrorState compact title={`Could not read the ${failed.what}`} error={failed.q.error} onRetry={() => void failed.q.refetch()}>
              <p className="m-0 text-xs">The next stage is unknown until it answers. Retry, or open the repository.</p>
            </ErrorState>
          </div>
        ) : (
          <Pill tone={d.tone} glyph={d.glyph} size="xs" hint="pill.connect.stage_summary">
            {s.label}
          </Pill>
        )}
      </td>
      <td className="py-2 pr-4 font-mono text-xs text-on-surface-muted">
        {repo.last_run ? `${repo.last_run.kind} · ${repo.last_run.status}` : '—'}
      </td>
      {/* below sm the column is off-canvas in the scrolling table: the repository link in column one is the row's action there */}
      <td className="hidden py-2 text-right sm:table-cell">
        {stageComplete(s.status) ? (
          <LinkButton size="sm" to={`/results?repo=${encodeURIComponent(repo.name)}`} hint="button.connect.row_action">
            Baseline
          </LinkButton>
        ) : (
          <LinkButton size="sm" to={`/connect/${encodeURIComponent(repo.name)}`} hint="button.connect.row_action">
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
  const candidates = useConfigCandidates(name)
  const navigate = useNavigate()
  // G-117: the run whose cancel is being asked about; the question is the app's own dialog
  const [confirming, setConfirming] = useState<Run | null>(null)

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
    // G-907: the money stage is the designed Measure page (cost band, retention, confirm) —
    // the same door Home task 5 opens — never the technical run form; a failed replay's Retry
    // takes the same door, and nothing is posted from here
    else if (stage.runKind === 'replay') navigate(`/connect/${encodeURIComponent(name)}/measure`)
    else if (stage.runKind) createRun.mutate({ repo: name, kind: stage.runKind })
  }
  const cancelRun = (run: Run) => setConfirming(run)
  const confirmCancel = () => {
    if (!confirming) return
    cancel.mutate(confirming.id, { onSettled: () => setConfirming(null) })
  }
  const busy = probe.isPending || createRun.isPending
  const actionError = probe.error ?? createRun.error ?? cancel.error
  // G-730: a stage read that failed (not 404) leaves the walk unable to say where the
  // repository is; it is said with Retry, and no stage state or stage action is shown
  const failed = failedRead(oracle, controls, map)
  const allDone = !failed && stages.length > 0 && stages.every((s) => stageComplete(s.status))
  const next = failed ? undefined : stages.find((s) => !stageComplete(s.status))

  return (
    <>
      <PageHeader
        title={name}
        purpose={
          repo.isError
            ? isUnknownRepo(repo.error)
              ? 'Not found'
              : 'The repository could not be read.'
            : failed
              ? 'The walk cannot say where this repository is until every read answers.'
              : allDone
                ? 'Every stage is done — the baseline holds what the evidence says about this repository.'
                : next
                  ? `Next: ${next.title.toLowerCase()}. ${next.why}`
                  : 'Loading the repository…'
        }
        actions={
          // an unknown name has no configuration and no baseline: its one door is below (G-979)
          repo.isError && isUnknownRepo(repo.error) ? undefined : (
            <div className="flex gap-2">
              <LinkButton size="sm" to={`/repos/${encodeURIComponent(name)}`} hint="button.walk.configuration">
                Configuration
              </LinkButton>
              <LinkButton size="sm" variant={allDone ? 'filled' : 'outlined'} to={`/results?repo=${encodeURIComponent(name)}`} hint="button.walk.baseline">
                Baseline
              </LinkButton>
            </div>
          )
        }
      />
      {repo.isError && <UnknownRepo name={name} error={repo.error} onRetry={() => void repo.refetch()} />}
      {repo.data && failed && (
        <Card title="The walk" eyebrow="six stages · each says what it proves and what it costs">
          <div data-testid="connect-walk-error">
            <ErrorState compact title={`Could not read the ${failed.what}`} error={failed.q.error} onRetry={() => void failed.q.refetch()}>
              <p className="m-0 text-xs">The walk cannot say where this repository is until it answers, so no stage is shown and nothing is offered to run. Retry, or open the configuration.</p>
            </ErrorState>
          </div>
        </Card>
      )}
      {repo.data && !failed && (
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
                      <Pill tone={d.tone} glyph={d.glyph} size="xs" label={`${s.title}: ${d.label}`} hint="pill.walk.stage_status">
                        {d.label}
                      </Pill>
                      {s.spends && !stageComplete(s.status) && (
                        <Pill tone="amber" size="xs" glyph="$" hint="pill.walk.spends">
                          spends model budget
                        </Pill>
                      )}
                    </div>
                    <p className="mt-1 mb-1 max-w-[70ch] text-sm text-on-surface-body">{s.why}</p>
                    {/* `break-words`: the first stage's detail is the repository's clone URL, one
                        unbreakable token. Without it a long URL pushed the whole page sideways at
                        375 px (found by 11-screens' scrollWidth check, G-905). */}
                    <p className="m-0 break-words text-xs text-on-surface-muted">
                      {s.detail && <Hint id="stat.walk.stage_detail">{s.detail}</Hint>}
                      {s.runId && !live && (
                        <>
                          {' · '}
                          <Hint as={Link} id="link.walk.open_run" to={`/runs/${s.runId}`}>
                            open run
                          </Hint>
                        </>
                      )}
                    </p>
                    {s.status === 'warn' && (s.id === 'controls' || s.id === 'oracle') && (
                      // G-348 / G-432 — the amber finding's way forward is the Learn strengthen report
                      <p className="m-0 mt-1 text-xs">
                        <Hint as={Link} id="link.walk.learn" to={`/learn?repo=${encodeURIComponent(name)}#strengthen`} className="underline underline-offset-4">
                          Strengthen the tests on Learn
                        </Hint>
                      </p>
                    )}
                    {live && <InFlight run={live} stage={s} canCancel={can('operator')} cancelling={cancel.isPending} onCancel={() => cancelRun(live)} />}
                    {s.id === 'mine' && <Candidates repo={name} query={candidates} canDecide={can('operator')} />}
                  </div>
                  <div className="text-right">
                    {canAct && s.runKind && can('operator') && (
                      <Button size="sm" variant={s.spends ? 'outlined' : 'filled'} hint="button.walk.run_stage" disabled={busy} onClick={() => act(s)}>
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
      {/* the connect stream's own numbers (docs/dod/streams/connect-and-prove.md MEASURE) */}
      <FlowPanel stream="connect-and-prove" repo={name} />
      {/* G-117: the cancel question is the app's own dialog (hinted, reachable, axe-checked) */}
      <Dialog
        open={confirming !== null}
        title="Cancel this run?"
        onClose={() => setConfirming(null)}
        footer={
          <>
            <Button hint="button.connect.cancel_keep" onClick={() => setConfirming(null)}>
              Keep it running
            </Button>
            <Button variant="danger" hint="button.connect.cancel_confirm" pending={cancel.isPending} onClick={confirmCancel}>
              Cancel the run
            </Button>
          </>
        }
      >
        <div data-testid="cancel-confirm" className="space-y-2 text-sm">
          <p className="m-0">Attempts already made are still charged. The worker stops between attempts, and the rows already graded are kept.</p>
          {cancel.isError && <ErrorState compact error={cancel.error} />}
        </div>
      </Dialog>
    </>
  )
}

// ---------------------------------------------------------------------------
// The config changes the mine's notes imply (DL-316)
// ---------------------------------------------------------------------------

/** "runner_opts.timeout: 900 s → 1800 s" — the setting, the limit hit and the proposal. */
function candidateChange(c: ConfigCandidate): string {
  const unit = c.field.endsWith('timeout') ? ' s' : ''
  if (c.scope === 'deployment') return `${c.field} → ${String(c.proposed)} (a deployment setting)`
  return `${c.field}: ${c.observed === null ? 'unset' : `${c.observed}${unit}`} → ${c.proposed}${unit}`
}

/**
 * Under the mine stage: each candidate as one sentence a reader can hover, and — for an
 * operator — Accept (applied through the audited config update, under the session) and
 * Reject (recorded, nothing changed). A deployment-scoped candidate names the variable an
 * operator sets on the deployment and offers no Accept. A failed read is said with Retry,
 * never an empty list (the failed-reads rule).
 */
function Candidates({ repo, query, canDecide }: { repo: string; query: ReturnType<typeof useConfigCandidates>; canDecide: boolean }) {
  const decide = useDecideCandidate()
  if (query.isError) {
    return (
      <div className="mt-2" data-testid="config-candidates-error">
        <ErrorState compact title="Could not read the config candidates" error={query.error} onRetry={() => void query.refetch()} />
      </div>
    )
  }
  const items = query.data?.items ?? []
  if (items.length === 0) return null
  return (
    <div className="mt-2 max-w-[70ch] border-l-4 border-status-amber-fill pl-3 text-sm" data-testid="config-candidates">
      <p className="m-0 text-xs text-on-surface-muted">The mine notes imply {items.length === 1 ? 'a configuration change' : `${items.length} configuration changes`}. Nothing changes until an operator decides.</p>
      <ul className="m-0 mt-1 list-none space-y-2 p-0" aria-label="Configuration candidates">
        {items.map((c) => {
          const pending = decide.isPending && decide.variables?.id === c.id
          return (
            <li key={c.id} className="flex flex-wrap items-start gap-x-3 gap-y-1" data-testid={`candidate-${c.kind}`}>
              <Hint id="stat.walk.candidate" as="div" className="min-w-0 flex-1">
                <span className="font-mono text-xs">{candidateChange(c)}</span>
                <span className="block text-xs text-on-surface-muted">
                  {c.reason} ({c.sources.length === 1 ? '1 commit' : `${c.sources.length} commits`})
                </span>
              </Hint>
              {canDecide ? (
                <span className="flex gap-2">
                  {c.scope === 'repo' && (
                    <Button size="sm" variant="filled" hint="button.walk.candidate_accept" pending={pending} onClick={() => decide.mutate({ name: repo, id: c.id, decision: 'accept' })}>
                      Accept
                    </Button>
                  )}
                  <Button size="sm" variant="outlined" hint="button.walk.candidate_reject" pending={pending} onClick={() => decide.mutate({ name: repo, id: c.id, decision: 'reject' })}>
                    Reject
                  </Button>
                </span>
              ) : (
                <span className="text-xs text-on-surface-muted">An operator decides this.</span>
              )}
            </li>
          )
        })}
      </ul>
      {decide.isError && <ErrorState compact error={decide.error} />}
    </div>
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
  const spend = stage.spends ? `$${run.cost_usd.toFixed(2)} spent so far` : ''
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
          <Hint id="stat.walk.inflight_progress">{head}</Hint>
          {spend && (
            <>
              {' · '}
              <Hint id="stat.walk.inflight_spend">{spend}</Hint>
            </>
          )}
          {started}.
        </span>{' '}
        {next}
      </p>
      <p className="m-0 mt-1 flex flex-wrap items-center gap-x-3 gap-y-1">
        <Hint as={Link} id="link.walk.inflight_open" to={`/runs/${run.id}`}>
          Open the run
        </Hint>
        {run.cancel_requested ? (
          <span className="text-on-surface-muted">Cancel requested — the worker stops between {stage.id === 'measure' ? 'attempts' : 'tasks'}.</span>
        ) : (
          canCancel && (
            <Button size="sm" variant="outlined" hint="button.walk.cancel" disabled={cancelling} onClick={onCancel}>
              Cancel the run
            </Button>
          )
        )}
        {canCancel && !run.cancel_requested && <span className="text-xs text-on-surface-muted">(attempts already made are still charged)</span>}
      </p>
    </div>
  )
}
