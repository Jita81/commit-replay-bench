/**
 * Home — "Get started": the eight tasks between an empty deployment and a delivered change.
 *
 * Navigation
 * ----------
 * What it is:   The landing screen (/home): a GOV.UK task list — Connect GitHub, Choose a
 *               repository, Confirm its shape, Prove the instrument (£0), Measure (spends
 *               money), Read the baseline, Invite an approver, Deliver your first change —
 *               with a status per task derived from the API, "You have completed n of 8",
 *               the instrument's health as a notification banner when it is degraded — the
 *               sandbox's own banner, and one banner naming every other probe that is
 *               degraded or down with its detail and the guide section (G-397; a skipped
 *               probe is silent and a ledger down on false-Q1 is the shell's halt banner) —
 *               task 8's note saying that work enters from the enterprise's board and whether
 *               intake is listening (G-548, the same words as the Factory head), the
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
 *               the two-person readiness (task 7, whose note names the next step for the
 *               server's reason and whose admin link lands on the invite card) and the active
 *               factory run (task 8: "Backlog
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
 *               `useFactoryTasks` + `useActiveRun(repo, 'factory')` → `factoryStatusFor`;
 *               `useIntake` → `intakeState` (screens/Factory/intake.ts) for task 8's note;
 *               `probesNeedingAttention(health.probes)` → `PROBE_LABEL` (the probe in words)
 *               and `PROBE_GUIDE` for the banner; every
 *               query's error state (the App's and the runs' included) feeds the one
 *               `ErrorState`.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none (DL-042, DL-044, DL-074)
 * Works with:   ui/src/screens/Home/useGetStarted.ts (the reads in hooks.ts and the statuses
 *               below, shared with the shell's "n of 8"),
 *               ui/src/components/govuk.tsx (TaskList, NotificationBanner, InsetText),
 *               ui/src/components/ErrorState.tsx (the failed reads, with Retry),
 *               ui/src/help/hints.ts (the `task.home.*` copy; the trigger is `Hint`),
 *               ui/src/screens/Connect/connection.ts (the connection state each task reads),
 *               ui/src/screens/Factory/FactoryPage.tsx (where the tasks lead: with Connect
 *               and Results, the routes in ui/src/App.tsx; screens/Factory/intake.ts is the
 *               intake line task 8 shares with it),
 *               ui/src/screens/Home/ValueTile.tsx (the scorecard tile),
 *               src/crb/server/routes/repos.py (`baseline_read` on the repository — task 6)
 * Tested by:    ui/src/screens/Home/HomePage.test.tsx, ui/src/help/hints-ratchet.test.tsx
 *               (every element resolves to a registry id), ui/e2e/walkthrough/13-orient.spec.ts
 *               (task tags against the live stack — G-166)
 * Touch when:   never for a new repository; a task is added to the walk (connection.ts first; its
 *               `task.home.*` hint in hints.ts second).
 */

import { Link } from 'react-router'
import { ErrorState } from '../../components/ErrorState'
import { DocLink } from '../../components/Help'
import { Hint } from '../../components/Hint'
import type { Probe } from '../../api/types'
import type { DocAnchor } from '../../help/docs'
import { InsetText, Kicker, Lede, NotificationBanner, PageTitle, StartButton, TaskList } from '../../components/govuk'
import { sentence } from '../../lib/format'
import { INTAKE_LEAD, intakeState, intakeWords } from '../Factory/intake'
import { useGetStarted } from './useGetStarted'
import { ValueTile } from './ValueTile'

// the task statuses and their derivation live with the hook the shell shares (useGetStarted.ts)
export { CONTINUE_STOPS, factoryStatusFor, type FactoryStatus, type HomeStatus } from './useGetStarted'

/** "a", "a and b", "a, b and c" — the reads that failed, in words. */
function inWords(items: string[]): string {
  return items.length < 2 ? (items[0] ?? '') : `${items.slice(0, -1).join(', ')} and ${items.at(-1)}`
}


/**
 * Task 7's next step for the reason the deployment is not two-person ready — the step that
 * helps, for the reader's role: an invited person who has not arrived needs their link used,
 * not another invitation; only an admin can invite.
 */
export function task7NextStep(reasonCode: string, admin: boolean): string {
  switch (reasonCode) {
    case 'approver_never_signed_in':
      return admin
        ? 'The approver you invited has not signed in: ask them to open their one-time link. If it has expired, invite them again on the Settings screen.'
        : 'The approver who was invited has not signed in: ask them to open their one-time link. If it has expired, an admin invites them again.'
    case 'single_person':
      return admin
        ? 'Invite a second person on the Settings screen, somebody who did not run the measurements: the account is created inactive and you pass on a one-time link.'
        : 'Only an admin can invite somebody. Ask your admin to invite a second person who did not run the measurements.'
    case 'runner_is_the_only_signer':
      return admin
        ? 'Invite an approver who did not run them on the Settings screen: the account is created inactive and you pass on a one-time link.'
        : 'Only an admin can invite somebody. Ask your admin to invite an approver who did not run them.'
    default:
      return admin
        ? 'Invite an approver on the Settings screen: the account is created inactive and you pass on a one-time link.'
        : 'Only an admin can invite somebody. Ask your admin to invite an approver.'
  }
}

/**
 * G-397 — the probes Home raises its banner for: every one that is `degraded` or `down`, except
 * the sandbox (its own banner above, whose rule is unchanged) and a ledger probe down on a
 * false-Q1 row (the shell's red halt banner, which links to the ledger). A `skipped` probe is
 * a probe that did not run, not a fault, so it stays silent.
 */
export function probesNeedingAttention(probes: Probe[]): Probe[] {
  return probes.filter((p) => {
    if (p.status !== 'degraded' && p.status !== 'down') return false
    if (p.name === 'sandbox') return false
    if (p.name === 'ledger' && Number(p.data.false_q1 ?? 0) > 0) return false
    return true
  })
}

/** The guide section that says what to do about each probe; the health section for any other. */
export const PROBE_GUIDE_DEFAULT: DocAnchor = 'DEPLOYMENT#93-health'
export const PROBE_GUIDE: Record<string, DocAnchor> = {
  db: 'DEPLOYMENT#93-health',
  migrations: 'DEPLOYMENT#6-upgrade',
  append_only: 'DEPLOYMENT#33-postgresql',
  ledger: 'OPERATOR#6-export-and-verify-the-ledger',
  sandbox: 'OPERATOR#7-when-the-sandbox-is-unavailable',
  provision: 'OPERATOR#21-environment-setup--the-only-network-phase',
  toolchains: 'OPERATOR#21-environment-setup--the-only-network-phase',
  builders: 'OPERATOR#3-run-a-sweep',
  worker: 'DEPLOYMENT#93-health',
  intake: 'OPERATOR#11-intake--work-arriving-from-a-board',
  build: 'DEPLOYMENT#6-upgrade',
}

/** The probe's name in words for the banner's sentence (a probe id is not plain English); the id itself for one not listed. */
export const PROBE_LABEL: Record<string, string> = {
  db: 'database',
  migrations: 'migrations',
  append_only: 'append-only store',
  ledger: 'ledger',
  sandbox: 'sandbox',
  provision: 'provisioning',
  toolchains: 'toolchains',
  builders: 'builders',
  worker: 'worker',
  intake: 'intake',
  build: 'build',
}

export function HomePage() {
  const { me, health, chosen, intake, ready, approverKnown, admin, q, unread, reposUnread, measured, measuring, anyRows, operator, tasks, completed, nextTask, listed } = useGetStarted()
  const sandbox = health.data?.probes.find((p) => p.name === 'sandbox')
  // G-397 — every other probe that is degraded or down raises ONE banner naming each; a
  // `skipped` probe is silent, and a ledger probe down on false-Q1 is the shell's halt banner
  const attention = health.isError ? [] : probesNeedingAttention(health.data?.probes ?? [])

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
      {attention.length > 0 && (
        <NotificationBanner title="Important">
          <p className="m-0 mb-2 font-bold">{attention.length === 1 ? 'A health probe needs attention.' : `${attention.length} health probes need attention.`}</p>
          <ul className="m-0 list-disc pl-5" data-testid="home-probe-banner">
            {attention.map((p) => (
              <Hint as="li" key={p.name} id="banner.home.probe" className="mb-1">
                The {PROBE_LABEL[p.name] ?? p.name} probe is {p.status}{p.detail ? `: ${p.detail}` : ''}. <DocLink to={PROBE_GUIDE[p.name] ?? PROBE_GUIDE_DEFAULT}>What to do</DocLink>
              </Hint>
            ))}
          </ul>
          <p className="m-0 mt-2">
            Every screen's header pill shows the same status. <Link to="/posture">See the deployment's health</Link>.
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
            <strong>Task 7.</strong> {sentence(ready.reason)}. {task7NextStep(ready.reason_code, admin)}
          </p>
        )}
        {chosen && (
          // G-548 — the stream starts at the board: the same words the Factory head shows
          <Hint as="p" id="stat.home.intake_state" className="m-0 mt-2 text-[16px] text-on-surface-muted" data-testid="home-task-8-note">
            <strong>Task 8.</strong> {INTAKE_LEAD}{' '}
            <Link to={`/factory/intake${q}`}>{intakeWords(intakeState(intake.data, intake.isError, intake.isPending))}</Link>
          </Hint>
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