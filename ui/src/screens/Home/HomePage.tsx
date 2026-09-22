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
 *               the approver who signs) and one Continue button that names the next task.
 * What it does: Gives a tech lead trying the product in an afternoon one page that says
 *               what to do next and what it costs; nothing here spends money without a
 *               queued run they can see and cancel (tasks 1–4 cost nothing). Statuses are
 *               never kept locally: the GitHub App info, the repositories, the chosen
 *               repository's stages (`stagesFor`), a sign-off the API flags `active` and not
 *               `stale` (task 6 — a stale one lifts nothing, so completes nothing), the users
 *               list (task 7) and the active factory run (task 8: "Backlog frozen — run the
 *               factory" until a run exists, then "In progress — item k of n") decide them.
 *               Continue points at the first task that is neither Completed nor Cannot
 *               start yet, so the first press never lands on an empty screen. A viewer
 *               (sponsor, auditor) gets the same list read as a progress report — "Where
 *               this deployment is" — not as their to-do list; a measurement in flight
 *               reads "In progress", and the baseline opens as soon as any row exists.
 * How:          `useGitHubApp`, `useAllRepos`, the chosen repository (`?repo=` or the most
 *               recently updated) → `useRepo` + `useOracle` + `useOracleControls` +
 *               `useCapabilityMap` → `stagesFor`; `useSignoffs` for task 6; `useUsers`
 *               (admin) or the principal's role for task 7; `useFactoryBacklog` +
 *               `useFactoryTasks` + `useActiveRun(repo, 'factory')` → `factoryStatusFor`.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none (DL-042, DL-044)
 * Works with:   ui/src/components/govuk.tsx (TaskList, NotificationBanner, InsetText),
 *               ui/src/api/hooks.ts (`useActiveRun`, `useSignoffs`),
 *               ui/src/screens/Connect/connection.ts, ui/src/screens/Connect/ConnectPage.tsx,
 *               ui/src/screens/Results/ResultsPage.tsx, ui/src/screens/Factory/FactoryPage.tsx,
 *               ui/src/screens/Posture/PosturePage.tsx (the health banner's target)
 * Tested by:    ui/src/screens/Home/HomePage.test.tsx
 * Touch when:   a task is added to the walk (connection.ts first).
 */

import { useMemo } from 'react'
import { Link, useSearchParams } from 'react-router'
import { useActiveRun, useAllRepos, useCapabilityMap, useFactoryBacklog, useFactoryTasks, useGitHubApp, useHealth, useOracle, useOracleControls, useRepo, useSignoffs, useUsers } from '../../api/hooks'
import { isApiError } from '../../api/client'
import { InsetText, Kicker, Lede, NotificationBanner, PageTitle, StartButton, type TagTone, TaskList, type TaskItem } from '../../components/govuk'
import { useAuth } from '../../lib/auth'
import { kOfN } from '../../lib/format'
import { type StageStatus, stageComplete, stagesFor } from '../Connect/connection'

const TONE: Record<StageStatus, TagTone> = { done: 'pale', warn: 'pale', running: 'blue', todo: 'blue', failed: 'red', blocked: 'grey' }
const LABEL: Record<StageStatus, string> = { done: 'Completed', warn: 'Completed', running: 'In progress', todo: 'Incomplete', failed: 'Failed', blocked: 'Cannot start yet' }

function notRun(err: unknown): boolean {
  return isApiError(err) && err.status === 404
}

export type FactoryStatus = 'delivered' | 'running' | 'frozen' | 'ready' | 'no_deliver_cell' | 'blocked' | 'unknown'
const FACTORY_LABEL: Record<FactoryStatus, string> = {
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

/** The statuses a person can act on now — Continue goes to the first task carrying one. */
const ACTIONABLE = new Set<string>(['Incomplete', 'In progress', 'Failed', FACTORY_LABEL.frozen])

export function HomePage() {
  const { me, can } = useAuth()
  const [params] = useSearchParams()
  const gh = useGitHubApp()
  const repos = useAllRepos()
  const health = useHealth()
  const users = useUsers(can('admin'))
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
  const ghStatus: { status: string; tone: TagTone } = !gh.data
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
  // it counts as read once someone has acted on it — a sign-off the API itself calls active:
  // a stale one (the apparatus moved on, ADR-0015) lifts nothing, so it completes nothing
  const anyRows = (map.data?.summary.n_total ?? 0) > 0
  const baselineActed = (signoffs.data?.items ?? []).some((s) => s.active && !s.stale)
  const operator = can('operator')
  const approverKnown = users.data ? users.data.items.some((u) => u.role === 'approver' || u.role === 'admin') : me?.role === 'approver' || me?.role === 'admin' ? true : undefined

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
  const factoryLabel = factoryStatus === 'running' && item ? `In progress — item ${item}` : FACTORY_LABEL[factoryStatus]
  const tasks: TaskItem[] = [
    { num: 1, name: 'Connect GitHub', status: ghStatus.status, tone: ghStatus.tone, to: '/connect' },
    { num: 2, name: 'Choose a repository', status: hasRepo ? 'Completed' : 'Incomplete', tone: hasRepo ? 'pale' : 'blue', to: '/connect' },
    { num: 3, name: 'Confirm its shape', status: stage('probe') === 'done' ? 'Completed' : hasRepo ? LABEL[stage('probe') ?? 'todo'] : 'Cannot start yet', tone: stage('probe') === 'done' ? 'pale' : hasRepo ? TONE[stage('probe') ?? 'todo'] : 'grey', to: chosen ? `/repos/${encodeURIComponent(chosen)}` : '/connect' },
    { num: 4, name: 'Prove the instrument (£0)', status: LABEL[proveStatus], tone: TONE[proveStatus], to: walk },
    { num: 5, name: 'Measure — spends money', status: measured ? 'Completed' : measuring ? 'In progress' : proveDone ? 'Incomplete' : 'Cannot start yet', tone: measured ? 'pale' : measuring || proveDone ? 'blue' : 'grey', to: measuring && chosen ? `/connect/${encodeURIComponent(chosen)}` : chosen ? `/connect/${encodeURIComponent(chosen)}/measure` : '/connect' },
    { num: 6, name: 'Read the baseline', status: baselineActed ? 'Completed' : anyRows ? 'Incomplete' : 'Cannot start yet', tone: baselineActed ? 'pale' : anyRows ? 'blue' : 'grey', to: `/results${q}` },
    // only an admin can invite; everyone else reads a state (not an instruction), is not sent
    // to a page that refuses them, and gets the hint under the list
    { num: 7, name: 'Invite an approver', status: approverKnown === true ? 'Completed' : approverKnown === false ? 'Incomplete' : 'Not known yet', tone: approverKnown === true ? 'pale' : approverKnown === false ? 'blue' : 'grey', to: can('admin') ? '/settings' : '/posture' },
    // the destination (DL-044): the factory delivers a change under the baseline the walk earned
    { num: 8, name: 'Deliver your first change', status: factoryLabel, tone: FACTORY_TONE[factoryStatus], to: chosen ? `/factory?repo=${encodeURIComponent(chosen)}` : '/factory' },
  ]
  const completed = tasks.filter((t) => t.status === 'Completed').length
  // the operator's next press: the first task they can act on now; all done → the factory
  const nextTask = tasks.find((t) => ACTIONABLE.has(t.status) || t.status.startsWith('In progress'))
  const sandbox = health.data?.probes.find((p) => p.name === 'sandbox')

  return (
    <>
      <Kicker>{chosen ? `${chosen} · ${measured ? 'measured' : measuring ? 'measuring' : 'trial'}` : 'no repository yet'}</Kicker>
      <PageTitle>{operator ? 'Get started' : 'Where this deployment is'}</PageTitle>
      {!operator && (
        <Lede className="mb-4">
          You can read everything here and change nothing. The tasks below are the operators' progress from an empty deployment to a signed cell; the capability map and Decisions are where {me?.role === 'approver' ? 'an approver reads what the evidence says and signs what is waiting on them' : 'a viewer reads what the evidence says and what is waiting on a person'}.
        </Lede>
      )}
      {sandbox && sandbox.status !== 'ok' && (
        <NotificationBanner title="Important">
          <p className="m-0 mb-2 font-bold">The sandbox probe is {sandbox.status} on this host.</p>
          <p className="m-0">
            Anything measured now is a development reading, not evidence. <Link to="/posture">See the deployment's health</Link>.
          </p>
        </NotificationBanner>
      )}
      <div className="max-w-[44em]">
        <TaskList tasks={tasks} completed={completed} summary={operator ? undefined : `The operators have completed ${completed} of ${tasks.length} tasks.`} />
        {approverKnown !== true && !can('admin') && (
          <p className="m-0 mt-2 text-[16px] text-on-surface-muted">
            <strong>Task 7.</strong> Only an admin can add users. Ask your admin to add someone with the approver role in Settings.
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
        <StartButton to={nextTask?.to ?? (chosen ? `/factory?repo=${encodeURIComponent(chosen)}` : '/factory')}>{nextTask ? `Continue to task ${nextTask.num}: ${nextTask.name}` : 'Continue to the factory'}</StartButton>
      ) : (
        <StartButton to={anyRows ? `/results${q}` : '/decisions'}>{anyRows && chosen ? `Continue to the baseline for ${chosen}` : 'Continue to Decisions'}</StartButton>
      )}
    </>
  )
}
