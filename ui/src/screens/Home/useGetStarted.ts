/**
 * useGetStarted — the eight "Get started" tasks, their statuses and the next one, read once.
 *
 * Navigation
 * ----------
 * What it is:   The hook behind Home's task list (`useGetStarted`), with the status types it
 *               classifies (`HomeStatus`, `CONTINUE_STOPS`, `factoryStatusFor`), lifted out
 *               of HomePage.tsx so the shell's "n of 8" reads the same derivation.
 * What it does: Reads every query the eight tasks stand on and derives each task's status,
 *               the number Completed, the next task Continue stops at and the reads that
 *               failed. A failed read is never read as absence (G-164): a task that stands on
 *               one is "Unavailable". `loading` is true while any read is on its first fetch,
 *               so a caller can show nothing rather than a status not yet known.
 * How:          The same hooks HomePage named (`useGitHubApp`, `useAllRepos`, `useRepo`,
 *               `useOracle`, `useOracleControls`, `useCapabilityMap`, `useSignoffs`,
 *               `useTwoPersonReadiness`, `useFactoryBacklog`, `useFactoryTasks`,
 *               `useActiveRun`, `useIntake`, `useHealth`) → `stagesFor` → the task list.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none (DL-042, DL-044, DL-074)
 * Works with:   ui/src/screens/Home/HomePage.tsx (renders the list),
 *               ui/src/components/Layout.tsx (the header's "n of 8" and Continue),
 *               ui/src/screens/Connect/connection.ts (the stages each task reads)
 * Tested by:    ui/src/screens/Home/HomePage.test.tsx, ui/src/components/Layout.test.tsx
 * Touch when:   never for a new repository; a task is added to the walk (connection.ts first; its
 *               `task.home.*` hint in hints.ts second).
 */

import { useMemo } from 'react'
import { matchPath, useLocation, useSearchParams } from 'react-router'
import { useActiveRun, useAllRepos, useCapabilityMap, useFactoryBacklog, useFactoryTasks, useGitHubApp, useHealth, useIntake, useOracle, useOracleControls, useRepo, useSignoffs, useTwoPersonReadiness } from '../../api/hooks'
import { isApiError } from '../../api/client'
import type { TagTone, TaskItem } from '../../components/govuk'
import { useAuth } from '../../lib/auth'
import { kOfN } from '../../lib/format'
import { type StageStatus, stageComplete, stagesFor } from '../Connect/connection'

const TONE: Record<StageStatus, TagTone> = { done: 'pale', warn: 'pale', running: 'blue', todo: 'blue', failed: 'red', blocked: 'grey' }
const LABEL: Record<StageStatus, HomeStatus> = { done: 'Completed', warn: 'Completed', running: 'In progress', todo: 'Incomplete', failed: 'Failed', blocked: 'Cannot start yet' }

function notRun(err: unknown): boolean {
  return isApiError(err) && err.status === 404
}

/** A read that failed for any reason but "not run yet" (a 404 on a stage that has not run). */
function failedRead(q: { isError: boolean; error: unknown }): boolean {
  return q.isError && !notRun(q.error)
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

/** The repository a repository-scoped page names in its path, if the page is one. */
export function routeRepo(pathname: string): string | null {
  for (const pattern of ['/connect/:repo/*', '/repos/:repo/*', '/library/:repo/*', '/tasks/:repo/*']) {
    const hit = matchPath(pattern, pathname)
    if (hit?.params.repo) return hit.params.repo
  }
  return null
}

/**
 * Home's eight tasks for the chosen repository (the page's path, `?repo=`, or the most recently updated): each
 * status, the number Completed, the task Continue stops at, and every read that failed.
 */
export function useGetStarted() {
  const { me, can } = useAuth()
  const [params] = useSearchParams()
  const { pathname } = useLocation()
  const gh = useGitHubApp()
  const repos = useAllRepos()
  const health = useHealth()
  const chosen = useMemo(() => {
    const items = repos.data?.items ?? []
    // the page's own repository first: its path (/connect/beta/measure), then its ?repo=
    for (const wanted of [routeRepo(pathname), params.get('repo')]) {
      if (wanted && items.some((r) => r.name === wanted)) return wanted
    }
    return items.slice().sort((a, b) => (b.updated > a.updated ? 1 : -1))[0]?.name ?? ''
  }, [repos.data, params, pathname])
  const repo = useRepo(chosen)
  const oracle = useOracle(chosen)
  const controls = useOracleControls(chosen)
  const map = useCapabilityMap(chosen, ['capability_class', 'size'])
  const backlog = useFactoryBacklog(chosen)
  const factoryTasks = useFactoryTasks(chosen)
  const factoryRun = useActiveRun(chosen, 'factory')
  // G-548 — where task 8's work comes from: the board, and whether intake is listening
  const intake = useIntake(chosen)
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
  const admin = can('admin')

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
    { label: 'the board intake', q: intake, failed: failedRead(intake) },
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
    { num: 7, name: 'Invite an approver', ...(twoPerson.isError ? UNAVAILABLE : { status: approverKnown === true ? 'Completed' : approverKnown === false ? (inviteWaiting ? 'In progress' : 'Incomplete') : 'Not known yet', tone: approverKnown === true ? 'pale' : approverKnown === false ? 'blue' : 'grey' }), ...(admin ? { to: '/settings#invite' } : {}), hint: 'task.home.invite_approver' },
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
  // true while any read is on its first fetch: its task's status is not known yet
  const loading = reads.some((r) => r.q.isLoading)
  return { me, health, chosen, intake, ready, approverKnown, admin, q, unread, reposUnread, measured, measuring, anyRows, operator, tasks, completed, nextTask, listed, loading }
}
