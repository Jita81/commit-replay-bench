/**
 * Home — "Get started": the eight tasks between an empty deployment and a delivered change.
 *
 * Navigation
 * ----------
 * What it is:   The landing screen (/home): a GOV.UK task list — Connect GitHub, Choose a
 *               repository, Confirm its shape, Prove the instrument (£0), Measure (spends
 *               money), Read the map, Invite an approver — with a status per task derived
 *               from the API, "You have completed n of 8", the instrument's health as a
 *               notification banner when it is degraded, the cost statement, and "Why two
 *               people" (the operator who queues the runs is not the approver who signs).
 * What it does: Gives a tech lead trying the product in an afternoon one page that says
 *               what to do next and what it costs; nothing here spends money without a
 *               queued run they can see and cancel (tasks 1–4 cost nothing). Statuses are
 *               never kept locally: the GitHub App info, the repositories, the chosen
 *               repository's stages (`stagesFor`) and the users list decide them. A viewer
 *               (sponsor, auditor) gets the same list read as a progress report — "Where
 *               this deployment is" — not as their to-do list; a measurement in flight
 *               reads "In progress", and the map opens as soon as any row exists.
 * How:          `useGitHubApp`, `useAllRepos`, the chosen repository (`?repo=` or the most
 *               recently updated) → `useRepo` + `useOracle` + `useOracleControls` +
 *               `useCapabilityMap` → `stagesFor`; `useUsers` (admin) or the principal's role
 *               for the approver task.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none (DL-042)
 * Works with:   ui/src/components/govuk.tsx (TaskList, NotificationBanner, InsetText),
 *               ui/src/screens/Connect/connection.ts, ui/src/screens/Connect/ConnectPage.tsx,
 *               ui/src/screens/Results/ResultsPage.tsx, ui/src/screens/Decisions/DecisionsPage.tsx
 * Tested by:    ui/src/screens/Home/HomePage.test.tsx
 * Touch when:   a task is added to the walk (connection.ts first).
 */

import { useMemo } from 'react'
import { useSearchParams } from 'react-router'
import { useAllRepos, useCapabilityMap, useFactoryBacklog, useFactoryTasks, useGitHubApp, useHealth, useOracle, useOracleControls, useRepo, useUsers } from '../../api/hooks'
import { isApiError } from '../../api/client'
import { InsetText, Kicker, Lede, NotificationBanner, PageTitle, StartButton, type TagTone, TaskList, type TaskItem } from '../../components/govuk'
import { useAuth } from '../../lib/auth'
import { type StageStatus, stagesFor } from '../Connect/connection'

const TONE: Record<StageStatus, TagTone> = { done: 'pale', running: 'blue', todo: 'blue', failed: 'red', blocked: 'grey' }
const LABEL: Record<StageStatus, string> = { done: 'Completed', running: 'In progress', todo: 'Incomplete', failed: 'Failed', blocked: 'Cannot start yet' }

function notRun(err: unknown): boolean {
  return isApiError(err) && err.status === 404
}

export type FactoryStatus = 'delivered' | 'running' | 'ready' | 'no_deliver_cell' | 'blocked' | 'unknown'
const FACTORY_LABEL: Record<FactoryStatus, string> = {
  delivered: 'Completed',
  running: 'In progress',
  ready: 'Incomplete',
  no_deliver_cell: 'No cell routes deliver yet',
  blocked: 'Cannot start yet',
  unknown: 'Checking',
}
const FACTORY_TONE: Record<FactoryStatus, TagTone> = { delivered: 'pale', running: 'blue', ready: 'blue', no_deliver_cell: 'grey', blocked: 'grey', unknown: 'grey' }

/**
 * Task 8's status from the API: Completed once an item has a pull request or was accepted;
 * In progress once a backlog is frozen (items exist, none delivered); Incomplete when the
 * map has a cell that routes `deliver` and no backlog yet; "No cell routes deliver yet"
 * when measured but nothing licensed (a run would build and withhold); Cannot start yet
 * before any measurement.
 */
export function factoryStatusFor(input: { measured: boolean; deliverCells: boolean; backlog: 'frozen' | 'none' | 'unknown'; items: Array<{ pr_url: string | null; status: string }> }): FactoryStatus {
  if (input.items.some((t) => t.pr_url || t.status === 'accepted')) return 'delivered'
  if (input.backlog === 'unknown') return 'unknown'
  if (input.backlog === 'frozen') return 'running'
  if (!input.measured) return 'blocked'
  return input.deliverCells ? 'ready' : 'no_deliver_cell'
}

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
  const proveDone = stage('oracle') === 'done' && stage('controls') === 'done'
  const proveStatus: StageStatus = proveDone ? 'done' : stage('probe') !== 'done' || stage('mine') !== 'done' ? (stage('mine') === 'running' || stage('probe') === 'running' ? 'running' : 'blocked') : stage('oracle') === 'failed' || stage('controls') === 'failed' ? 'failed' : stage('oracle') === 'running' || stage('controls') === 'running' ? 'running' : 'todo'
  const measureStage = stage('measure')
  const measured = measureStage === 'done'
  const measuring = measureStage === 'running'
  // the map is readable from the first row, whether or not a run is still adding to it
  const anyRows = (map.data?.summary.n_total ?? 0) > 0
  const operator = can('operator')
  const approverKnown = users.data ? users.data.items.some((u) => u.role === 'approver' || u.role === 'admin') : me?.role === 'approver' || me?.role === 'admin' ? true : undefined

  const q = chosen ? `?repo=${encodeURIComponent(chosen)}` : ''
  const walk = chosen ? `/connect/${encodeURIComponent(chosen)}` : '/connect'
  const factoryStatus = factoryStatusFor({
    measured: anyRows,
    deliverCells: (map.data?.summary.deliver_cells ?? 0) > 0,
    backlog: backlog.data ? 'frozen' : backlog.isError && notRun(backlog.error) ? 'none' : 'unknown',
    items: factoryTasks.data ?? [],
  })
  const tasks: TaskItem[] = [
    { num: 1, name: 'Connect GitHub', status: ghStatus.status, tone: ghStatus.tone, to: '/connect' },
    { num: 2, name: 'Choose a repository', status: hasRepo ? 'Completed' : 'Incomplete', tone: hasRepo ? 'pale' : 'blue', to: '/connect' },
    { num: 3, name: 'Confirm its shape', status: stage('probe') === 'done' ? 'Completed' : hasRepo ? LABEL[stage('probe') ?? 'todo'] : 'Cannot start yet', tone: stage('probe') === 'done' ? 'pale' : hasRepo ? TONE[stage('probe') ?? 'todo'] : 'grey', to: chosen ? `/repos/${encodeURIComponent(chosen)}` : '/connect' },
    { num: 4, name: 'Prove the instrument (£0)', status: LABEL[proveStatus], tone: TONE[proveStatus], to: walk },
    { num: 5, name: 'Measure — spends money', status: measured ? 'Completed' : measuring ? 'In progress' : proveDone ? 'Incomplete' : 'Cannot start yet', tone: measured ? 'pale' : measuring || proveDone ? 'blue' : 'grey', to: measuring && chosen ? `/connect/${encodeURIComponent(chosen)}` : chosen ? `/connect/${encodeURIComponent(chosen)}/measure` : '/connect' },
    { num: 6, name: 'Read the map', status: anyRows ? 'Incomplete' : 'Cannot start yet', tone: anyRows ? 'blue' : 'grey', to: `/results${q}` },
    // only an admin can invite; everyone else is told whom to ask and is not sent to a page that refuses them
    { num: 7, name: 'Invite an approver', status: approverKnown === true ? 'Completed' : approverKnown === false ? 'Incomplete' : 'Ask an admin', tone: approverKnown === true ? 'pale' : 'blue', to: can('admin') ? '/settings' : '/posture' },
    // the destination (DL-044): the factory delivers a change under the baseline the walk earned
    { num: 8, name: 'Deliver your first change', status: FACTORY_LABEL[factoryStatus], tone: FACTORY_TONE[factoryStatus], to: chosen ? `/factory?repo=${encodeURIComponent(chosen)}` : '/factory' },
  ]
  const completed = tasks.filter((t) => t.status === 'Completed').length
  const sandbox = health.data?.probes.find((p) => p.name === 'sandbox')

  return (
    <>
      <Kicker>{chosen ? `${chosen} · ${measured ? 'measured' : measuring ? 'measuring' : 'trial'}` : 'no repository yet'}</Kicker>
      <PageTitle>{operator ? 'Get started' : 'Where this deployment is'}</PageTitle>
      {!operator && (
        <Lede className="mb-4">
          You can read everything here and change nothing. The tasks below are the operators' progress from an empty deployment to a signed cell; the capability map and your decisions are where a {me?.role ?? 'viewer'} spends their time.
        </Lede>
      )}
      {sandbox && sandbox.status !== 'ok' && (
        <NotificationBanner title="Important">
          <p className="m-0 mb-2 font-bold">The sandbox probe is {sandbox.status} on this host.</p>
          <p className="m-0">
            Anything measured now is a development reading, not evidence. <a href="/api/v1/health">See the health check</a>.
          </p>
        </NotificationBanner>
      )}
      <div className="max-w-[44em]">
        <TaskList tasks={tasks} completed={completed} summary={operator ? undefined : `The operators have completed ${completed} of ${tasks.length} tasks.`} />
      </div>
      <InsetText className="mt-8">
        <p className="m-0">Nothing spends money without a queued run you can see and cancel. Tasks 1 to 4 cost nothing; tasks 5 and 8 spend model budget and say so first. The factory (task 8) is what the rest is for: it delivers changes only in cells the baseline licenses.</p>
      </InsetText>
      <h2 className="mb-4 text-[32px] font-bold leading-[1.25]">Why two people</h2>
      <Lede className="mb-4">
        The operator who queues the runs should not be the approver who signs the result off. Sign-off needs the approver role and an attestation naming the diff they read; keeping the two roles on two people is how a deployment shows separation of duties — task 7 is not optional before a cell can be signed.
      </Lede>
      <StartButton to={operator ? (factoryStatus === 'ready' || factoryStatus === 'running' ? `/factory${q}` : '/decisions') : anyRows ? `/results${q}` : '/decisions'}>Continue</StartButton>
    </>
  )
}
