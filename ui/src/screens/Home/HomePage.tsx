/**
 * Home — "Get started": the eight tasks between an empty deployment and a delivered change.
 *
 * Navigation
 * ----------
 * What it is:   The landing screen (/home): a GOV.UK task list — Connect GitHub, Choose a
 *               repository, Confirm its shape, Prove the instrument (£0), Measure (spends
 *               money), Read the baseline, Invite an approver, Deliver your first change —
 *               with a status per task derived from the API, "You have completed n of 8",
 *               the instrument's health as a notification banner when it is degraded, the
 *               cost statement, "Why two people" (the operator who queues the runs is not
 *               the approver who signs), one Continue button that names the next task, and
 *               the north star above the list (ValueTile: working changes per pound, blind).
 * What it does: Gives a tech lead trying the product in an afternoon one page that says
 *               what to do next and what it costs; nothing here spends money without a
 *               queued run they can see and cancel (tasks 1–4 cost nothing). Statuses are
 *               never kept locally: the GitHub App info, the repositories, the chosen
 *               repository's stages (`stagesFor`), the server's record that a person read the
 *               baseline (`baseline_read`) or a sign-off the API flags `active` and not
 *               `stale` (task 6 — a stale one lifts nothing, so completes nothing; DL-074),
 *               the two-person readiness (task 7) and the active factory run (task 8: "Backlog
 *               frozen — run the factory" until a run exists, then "In progress — item k of n")
 *               decide them. A read that fails is never read as absence (G-164): one error envelope
 *               names every read that failed, with Retry, and each task that stands on one
 *               reads "Unavailable" rather than "Incomplete" or "Cannot start yet" — the
 *               GitHub App and the factory runs included, so task 8 never claims "Backlog
 *               frozen — run the factory" on a runs read that failed. Continue points at the
 *               first task `CONTINUE_STOPS` marks — one to act on now, or one that could not
 *               be read — so the first press never lands on an empty screen and a failed read
 *               never offers "Continue to the factory"; every status is a `HomeStatus`, so
 *               one nobody classified fails the type check (P-175). A viewer
 *               (sponsor, auditor) and an approver get the same list read as a progress
 *               report — "Where this deployment is" — not as their to-do list: an approver
 *               outranks an operator but works none of the tasks, so the operators' view is
 *               gated on operator or admin (G-911, DL-074); a measurement in flight
 *               reads "In progress", and the baseline opens as soon as any row exists.
 *               Every element a reader meets — the kicker, the sandbox banner's lead line,
 *               the "n of 8" summary, each task's status tag and Continue — is a hint
 *               trigger (`stat.home.*`, `banner.home.sandbox`, `task.home.*`,
 *               `button.home.continue`), so what a status means is one hover, focus or
 *               tap away and listed in the About block.
 * How:          `useGitHubApp`, `useAllRepos`, the chosen repository (`?repo=` or the most
 *               recently updated) → `useRepo` + `useOracle` + `useOracleControls` +
 *               `useCapabilityMap` → `stagesFor`; `useSignoffs` for task 6;
 *               `useTwoPersonReadiness(repo)` for task 7 (the real readiness to produce a
 *               signature the two-person rule accepts for the repository shown, read by every
 *               role — not the presence of an admin, a viewer, or the admin who queued every
 *               run (G-477); a waiting invitation reads "In progress");
 *               `useFactoryBacklog` +
 *               `useFactoryTasks` + `useActiveRun(repo, 'factory')` → `factoryStatusFor`; every
 *               query's error state (the App's and the runs' included) feeds the one
 *               `ErrorState`.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none (DL-042, DL-044, DL-074)
 * Works with:   ui/src/components/govuk.tsx (TaskList, NotificationBanner, InsetText),
 *               ui/src/components/ErrorState.tsx (the failed reads, with Retry),
 *               ui/src/help/hints.ts (the `task.home.*` copy; the trigger is `Hint`),
 *               ui/src/api/hooks.ts (`useActiveRun`, `useSignoffs`),
 *               ui/src/screens/Connect/connection.ts (the connection state each task reads),
 *               ui/src/screens/Factory/FactoryPage.tsx (where the tasks lead: with Connect
 *               and Results, the routes in ui/src/App.tsx),
 *               ui/src/screens/Home/ValueTile.tsx (the scorecard tile),
 *               src/crb/server/routes/repos.py (`baseline_read` on the repository — task 6)
 * Tested by:    ui/src/screens/Home/HomePage.test.tsx, ui/src/help/hints-ratchet.test.tsx
 *               (every element resolves to a registry id), ui/e2e/walkthrough/13-orient.spec.ts
 *               (task tags against the live stack — G-166)
 * Touch when:   never for a new repository; a task is added to the walk (connection.ts first; its
 *               `task.home.*` hint in hints.ts second).
 */

import { useMemo } from 'react'
import { Link, useSearchParams } from 'react-router'
import { useActiveRun, useAllRepos, useCapabilityMap, useFactoryBacklog, useFactoryTasks, useGitHubApp, useHealth, useOracle, useOracleControls, useRepo, useSignoffs, useTwoPersonReadiness } from '../../api/hooks'
import { isApiError } from '../../api/client'
import { ErrorState } from '../../components/ErrorState'
import { Hint } from '../../components/Hint'
import { InsetText, Kicker, Lede, NotificationBanner, PageTitle, StartButton, type TagTone, TaskList, type TaskItem } from '../../components/govuk'
import { useAuth } from '../../lib/auth'
import { kOfN } from '../../lib/format'
import { type StageStatus, stageComplete, stagesFor } from '../Connect/connection'
import { ValueTile } from './ValueTile'

const TONE: Record<StageStatus, TagTone> = { done: 'pale', warn: 'pale', running: 'blue', todo: 'blue', failed: 'red', blocked: 'grey' }
const LABEL: Record<StageStatus, HomeStatus> = { done: 'Completed', warn: 'Completed', running: 'In progress', todo: 'Incomplete', failed: 'Failed', blocked: 'Cannot start yet' }

function notRun(err: unknown): boolean {
  return isApiError(err) && err.status === 404
}

/** A read that failed for any reason but "not run yet" (a 404 on a stage that has not run). */
function failedRead(q: { isError: boolean; error: unknown }): boolean {
  return q.isError && !notRun(q.error)
}

/** "a", "a and b", "a, b and c" — the reads that failed, in words. */
function inWords(items: string[]): string {
  return items.length < 2 ? (items[0] ?? '') : `${items.slice(0, -1).join(', ')} and ${items.at(-1)}`
}

/** The tag of a task whose evidence could not be read: never "Incomplete" or "Cannot start yet". */
const UNAVAILABLE: { status: HomeStatus; tone: TagTone } = { status: 'Unavailable', tone: 'grey' }

/** Every status a task on Home can carry. A task's `status` is typed as one, so a new status
 * cannot be shown until `CONTINUE_STOPS` says whether Continue stops at it (P-175). */
export type HomeStatus =
  | 'Completed'
  | 'Incomplete'
  | 'In progress'
  | 'Failed'
  | 'Cannot start yet'
  | 'Unavailable'
  | 'Checking'
  | 'Optional'
  | 'Not configured'
  | 'Not known yet'
  | 'Backlog frozen — run the factory'
  | 'No cell routes deliver yet'

/**
 * Whether Continue stops at a task with this status — a Record over the whole union, so the
 * type check refuses a status nobody classified (the class of G-164's regression: "Unavailable"
 * was added to the tags and not to the set Continue read, so a failed read sent an operator on
 * to "Continue to the factory"). A task that could not be read stops Continue: its state is
 * unknown, so it is never skipped as if it were done.
 */
export const CONTINUE_STOPS: Record<HomeStatus, boolean> = {
  Completed: false,
  Incomplete: true,
  'In progress': true,
  Failed: true,
  'Cannot start yet': false,
  Unavailable: true,
  Checking: false,
  Optional: false,
  'Not configured': false,
  'Not known yet': false,
  'Backlog frozen — run the factory': true,
  'No cell routes deliver yet': false,
}

export type FactoryStatus = 'delivered' | 'running' | 'frozen' | 'ready' | 'no_deliver_cell' | 'blocked' | 'unknown'
const FACTORY_LABEL: Record<FactoryStatus, HomeStatus> = {
  delivered: 'Completed',
  running: 'In progress',
  frozen: 'Backlog frozen — run the factory',
  ready: 'Incomplete',
  no_deliver_cell: 'No cell routes deliver yet',
  blocked: 'Cannot start yet',
  unknown: 'Checking',
}
const FACTORY_TONE: Record<FactoryStatus, TagTone> = { delivered: 'pale', running: 'blue', frozen: 'blue', ready: 'blue', no_deliver_cell: 'grey', blocked: 'grey', unknown: 'grey' }

/**
 * Task 8's status from the API: Completed once an item has a pull request or was accepted;
 * In progress only while a factory run is queued or running; "Backlog frozen — run the
 * factory" when a backlog is frozen and no run is behind it (a status is never shown
 * without a run and an event behind it); Incomplete when the map has a cell that routes
 * `deliver` and no backlog yet; "No cell routes deliver yet" when measured but nothing
 * licensed (a run would build and withhold); Cannot start yet before any measurement.
 */
export function factoryStatusFor(input: { measured: boolean; deliverCells: boolean; backlog: 'frozen' | 'none' | 'unknown'; items: Array<{ pr_url: string | null; status: string }>; activeRun?: boolean }): FactoryStatus {
  if (input.items.some((t) => t.pr_url || t.status === 'accepted')) return 'delivered'
  if (input.backlog === 'unknown') return 'unknown'
  if (input.backlog === 'frozen') return input.activeRun ? 'running' : 'frozen'
  if (!input.measured) return 'blocked'
  return input.deliverCells ? 'ready' : 'no_deliver_cell'
}

export function HomePage() {
  const { me, can } = useAuth()
  const [params] = useSearchParams()
  const gh = useGitHubApp()
  const repos = useAllRepos()
  const health = useHealth()
  const chosen = useMemo(() => {
    const items = repos.data?.items ?? []
    const wanted = params.get('repo')
    if (wanted && items.some((r) => r.name === wanted)) return wanted
    return items.slice().sort((a, b) => (b.updated > a.updated ? 1 : -1))[0]?.name ?? ''
  }, [repos.data, params])
  const repo = useRepo(chosen)
  const oracle = useOracle(chosen)
  const controls = useOracleControls(chosen)
  const map = useCapabilityMap(chosen, ['capability_class', 'size'])
  const backlog = useFactoryBacklog(chosen)
  const factoryTasks = useFactoryTasks(chosen)
  const factoryRun = useActiveRun(chosen, 'factory')
  const signoffs = useSignoffs(chosen)
  // G-518/G-477 — task 7 reads the real two-person readiness for the repository shown, not the
  // presence of an admin: an account that can sign but has never signed in, a deployment whose
  // only other account is a viewer, or one where the only signer queued every run of this
  // repository, cannot license anything. Readable by every role.
  const twoPerson = useTwoPersonReadiness(chosen)

  const stages = repo.data
    ? stagesFor({
        repo: repo.data,
        oracle: oracle.data ?? (oracle.isError && notRun(oracle.error) ? null : undefined),
        controls: controls.data ?? (controls.isError && notRun(controls.error) ? null : undefined),
        measuredRows: map.data?.summary.n_total,
      })
    : []
  const stage = (id: string) => stages.find((s) => s.id === id)?.status
  const hasRepo = Boolean(chosen)
  // the connection task is about the App: configured AND at least one installation on record;
  // a repository connected by URL is a valid deployment, so with no App the task is optional
  const connected = gh.data?.configured === true && gh.data.installations.length > 0
  const ghStatus: { status: HomeStatus; tone: TagTone } = !gh.data
    ? gh.isError
      ? { status: 'Unavailable', tone: 'grey' }
      : { status: 'Checking', tone: 'grey' }
    : connected
      ? { status: 'Completed', tone: 'pale' }
      : gh.data.configured
        ? { status: 'Incomplete', tone: 'blue' }
        : hasRepo
          ? { status: 'Optional', tone: 'grey' }
          : { status: 'Not configured', tone: 'blue' }
  const proveDone = stage('oracle') === 'done' && stageComplete(stage('controls') ?? 'todo')
  const proveStatus: StageStatus = proveDone ? 'done' : stage('probe') !== 'done' || stage('mine') !== 'done' ? (stage('mine') === 'running' || stage('probe') === 'running' ? 'running' : 'blocked') : stage('oracle') === 'failed' || stage('controls') === 'failed' ? 'failed' : stage('oracle') === 'running' || stage('controls') === 'running' ? 'running' : 'todo'
  const measureStage = stage('measure')
  const measured = measureStage === 'done'
  const measuring = measureStage === 'running'
  // the baseline is readable from the first row, whether or not a run is still adding to it;
  // it counts as read once the server has recorded a person reading it (`baseline_read`, the
  // `repo.baseline_read` event the Baseline screen writes — DL-074), or once someone has acted
  // on it — a sign-off the API itself calls active: a stale one (the apparatus moved on,
  // ADR-0015) lifts nothing, so it completes nothing
  const anyRows = (map.data?.summary.n_total ?? 0) > 0
  const baselineActed = Boolean(repo.data?.baseline_read) || (signoffs.data?.items ?? []).some((s) => s.active && !s.stale)
  // the operators' view is for the roles that work the tasks: an operator and an admin. An
  // approver outranks an operator (ROLE_ORDER) but works none of the eight tasks, so they read
  // the progress report their About block describes (G-911, DL-074)
  const operator = can('operator') && me?.role !== 'approver'
  const ready = twoPerson.data
  const approverKnown = ready ? ready.ready : undefined
  // a link that was sent and not used is progress a nag would hide
  const inviteWaiting = (ready?.invitations_pending ?? 0) > 0

  const q = chosen ? `?repo=${encodeURIComponent(chosen)}` : ''
  const walk = chosen ? `/connect/${encodeURIComponent(chosen)}` : '/connect'
  const factoryStatus = factoryStatusFor({
    measured: anyRows,
    deliverCells: (map.data?.summary.deliver_cells ?? 0) > 0,
    backlog: backlog.data ? 'frozen' : backlog.isError && notRun(backlog.error) ? 'none' : 'unknown',
    items: factoryTasks.data ?? [],
    activeRun: Boolean(factoryRun.data),
  })
  // "item k of n" from the run's own progress: k is the item in flight, never past n
  const progress = factoryRun.data?.progress
  const item = progress ? kOfN(progress.done, progress.total) : null
  // the tag's words; the status Continue reads stays the union member ("In progress")
  const factoryDetail = factoryStatus === 'running' && item ? `In progress — item ${item}` : undefined
  // every read the tasks stand on; one that failed is shown as failed (G-164), never as absence
  const reads = [
    { label: 'the repositories', q: repos, failed: repos.isError },
    { label: 'the repository’s record', q: repo, failed: repo.isError },
    { label: 'the oracle report', q: oracle, failed: failedRead(oracle) },
    { label: 'the negative controls', q: controls, failed: failedRead(controls) },
    { label: 'the capability map', q: map, failed: map.isError },
    { label: 'the sign-offs', q: signoffs, failed: signoffs.isError },
    { label: 'the deployment’s two-person readiness', q: twoPerson, failed: twoPerson.isError },
    { label: 'the factory backlog', q: backlog, failed: failedRead(backlog) },
    { label: 'the factory items', q: factoryTasks, failed: factoryTasks.isError },
    { label: 'the deployment’s health', q: health, failed: health.isError },
    { label: 'the GitHub App', q: gh, failed: gh.isError },
    { label: 'the factory runs', q: factoryRun, failed: factoryRun.isError },
  ]
  const unread = reads.filter((r) => r.failed)
  const reposUnread = repos.isError
  const repoUnread = reposUnread || repo.isError
  const proveUnread = repoUnread || failedRead(oracle) || failedRead(controls)
  const mapUnread = repoUnread || map.isError
  const tasks: Array<Omit<TaskItem, 'status'> & { status: HomeStatus; label?: string }> = [
    { num: 1, name: 'Connect GitHub', status: ghStatus.status, tone: ghStatus.tone, to: '/connect', hint: 'task.home.connect_github' },
    { num: 2, name: 'Choose a repository', ...(reposUnread ? UNAVAILABLE : { status: hasRepo ? ('Completed' as const) : ('Incomplete' as const), tone: hasRepo ? ('pale' as const) : ('blue' as const) }), to: '/connect', hint: 'task.home.choose_repo' },
    { num: 3, name: 'Confirm its shape', ...(repoUnread ? UNAVAILABLE : { status: stage('probe') === 'done' ? 'Completed' : hasRepo ? LABEL[stage('probe') ?? 'todo'] : 'Cannot start yet', tone: stage('probe') === 'done' ? 'pale' : hasRepo ? TONE[stage('probe') ?? 'todo'] : 'grey' }), to: chosen ? `/repos/${encodeURIComponent(chosen)}` : '/connect', hint: 'task.home.confirm_shape' },
    { num: 4, name: 'Prove the instrument (£0)', ...(proveUnread ? UNAVAILABLE : { status: LABEL[proveStatus], tone: TONE[proveStatus] }), to: walk, hint: 'task.home.prove_instrument' },
    { num: 5, name: 'Measure — spends money', ...(mapUnread ? UNAVAILABLE : { status: measured ? 'Completed' : measuring ? 'In progress' : proveDone ? 'Incomplete' : 'Cannot start yet', tone: measured ? 'pale' : measuring || proveDone ? 'blue' : 'grey' }), to: measuring && chosen ? `/connect/${encodeURIComponent(chosen)}` : chosen ? `/connect/${encodeURIComponent(chosen)}/measure` : '/connect', hint: 'task.home.measure' },
    // a recorded read or an active sign-off is Completed whatever else failed; otherwise a
    // failed read of the map or the sign-offs leaves the task unknown, not "Incomplete"
    { num: 6, name: 'Read the baseline', ...(baselineActed ? { status: 'Completed', tone: 'pale' as TagTone } : mapUnread || signoffs.isError ? UNAVAILABLE : { status: anyRows ? 'Incomplete' : 'Cannot start yet', tone: anyRows ? 'blue' : 'grey' }), to: `/results${q}`, hint: 'task.home.read_baseline' },
    // only an admin can invite; everyone else reads a state (not an instruction), is not sent
    // to a page that refuses them, and gets the note under the list
    { num: 7, name: 'Invite an approver', ...(twoPerson.isError ? UNAVAILABLE : { status: approverKnown === true ? 'Completed' : approverKnown === false ? (inviteWaiting ? 'In progress' : 'Incomplete') : 'Not known yet', tone: approverKnown === true ? 'pale' : approverKnown === false ? 'blue' : 'grey' }), to: can('admin') ? '/settings' : '/posture', hint: 'task.home.invite_approver' },
    // the destination (DL-044): the factory delivers a change under the baseline the walk earned;
    // the runs read decides only "frozen" against "running", so it leaves only a frozen backlog unknown
    { num: 8, name: 'Deliver your first change', ...(factoryStatus !== 'delivered' && (reposUnread || map.isError || failedRead(backlog) || factoryTasks.isError || (factoryRun.isError && factoryStatus === 'frozen')) ? UNAVAILABLE : { status: FACTORY_LABEL[factoryStatus], label: factoryDetail, tone: FACTORY_TONE[factoryStatus] }), to: chosen ? `/factory?repo=${encodeURIComponent(chosen)}` : '/factory', hint: 'task.home.deliver' },
  ]
  const completed = tasks.filter((t) => t.status === 'Completed').length
  // the operator's next press: the first task they can act on now, or one that could not be
  // read (never skipped as if done); only when every task is settled → the factory. And only
  // a task THIS role can act on: task 7 needs an admin, so an operator's Continue never lands
  // on a screen that would refuse them (it is still shown, as a state, above)
  const nextTask = tasks.find((t) => CONTINUE_STOPS[t.status] && (t.num !== 7 || can('admin')))
  const listed: TaskItem[] = tasks.map(({ label, ...t }) => ({ ...t, status: label ?? t.status }))
  const sandbox = health.data?.probes.find((p) => p.name === 'sandbox')

  return (
    <>
      <Hint id="stat.home.kicker">
        <Kicker>{reposUnread ? 'repositories unavailable' : chosen ? `${chosen} · ${measured ? 'measured' : measuring ? 'measuring' : 'trial'}` : 'no repository yet'}</Kicker>
      </Hint>
      <PageTitle>{operator ? 'Get started' : 'Where this deployment is'}</PageTitle>
      {!operator && (
        <Lede className="mb-4">
          You can read everything here and change nothing. The tasks below are the operators' progress from an empty deployment to a signed cell; the capability map and Decisions are where {me?.role === 'approver' ? 'an approver reads what the evidence says and signs what is waiting on them' : 'a viewer reads what the evidence says and what is waiting on a person'}.
        </Lede>
      )}
      {unread.length > 0 && (
        <div className="mb-6 max-w-[44em]">
          <ErrorState error={unread[0]!.q.error} title="Part of this deployment’s state could not be read" onRetry={() => unread.forEach((r) => void r.q.refetch())}>
            <p className="m-0 text-sm">
              Not read: {inWords(unread.map((r) => r.label))}. The tasks that depend on them read “Unavailable” until a retry succeeds — nothing here is shown as missing when it could not be read.
            </p>
          </ErrorState>
        </div>
      )}
      {sandbox && sandbox.status !== 'ok' && (
        <NotificationBanner title="Important">
          <Hint as="p" id="banner.home.sandbox" className="m-0 mb-2 font-bold">
            The sandbox probe is {sandbox.status} on this host.
          </Hint>
          <p className="m-0">
            Anything measured now is a development reading, not evidence. <Link to="/posture">See the deployment's health</Link>.
          </p>
        </NotificationBanner>
      )}
      <div className="mb-6 flex max-w-[44em] flex-wrap gap-4">
        <ValueTile />
      </div>
      <div className="max-w-[44em]">
        <TaskList tasks={listed} completed={completed} summary={<Hint id="stat.home.completed">{operator ? `You have completed ${completed} of ${tasks.length} tasks.` : `The operators have completed ${completed} of ${tasks.length} tasks.`}</Hint>} />
        {approverKnown !== true && ready && (
          <p className="m-0 mt-2 text-[16px] text-on-surface-muted" data-testid="home-task-7-note">
            <strong>Task 7.</strong> {ready.reason}. {can('admin') ? 'Invite them on the Settings screen: the account is created inactive and you pass on a one-time link.' : 'Only an admin can invite somebody. Ask your admin to invite an approver in Settings.'}
          </p>
        )}
      </div>
      <InsetText className="mt-8">
        <p className="m-0">Nothing spends money without a queued run you can see and cancel. Tasks 1 to 4 cost nothing; tasks 5 and 8 spend model budget and say so first. The factory (task 8) is what the rest is for: it delivers changes only in cells the baseline licenses.</p>
      </InsetText>
      <h2 className="mb-4 text-[32px] font-bold leading-[1.25]">Why two people</h2>
      <Lede className="mb-4">
        The operator who queues the runs cannot be the approver who signs the result off: the API refuses a sign-off (<code>same_actor</code>) from the person who queued the run behind the attested row, or who is the only person behind the cell — no setting can waive it. Sign-off also needs the approver role and an attestation naming the diff they read — task 7 is not optional before a cell can be signed.
      </Lede>
      {operator ? (
        <StartButton to={nextTask?.to ?? (chosen ? `/factory?repo=${encodeURIComponent(chosen)}` : '/factory')} hint="button.home.continue">{nextTask ? `Continue to task ${nextTask.num}: ${nextTask.name}` : 'Continue to the factory'}</StartButton>
      ) : (
        <StartButton to={anyRows ? `/results${q}` : '/decisions'} hint="button.home.continue">{anyRows && chosen ? `Continue to the baseline for ${chosen}` : 'Continue to Decisions'}</StartButton>
      )}
    </>
  )
}
