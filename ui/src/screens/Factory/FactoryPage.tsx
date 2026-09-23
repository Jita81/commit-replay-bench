/**
 * Factory — the forward-mode process, item by item, with the human acts where they happen.
 *
 * Navigation
 * ----------
 * What it is:   The screen at /factory: one repository's frozen backlog and, for every item,
 *               the six steps of the process as a step list — readiness (structural gaps
 *               signed by an approver) → RED proof → build under the belts → delivery (route-
 *               gated branch + PR) → independent review → outcome — with the act a person can
 *               take at the step that is waiting on them: sign a structural gap (approver),
 *               freeze a backlog and run the loop (operator).
 * What it does: Makes the factory legible as a process rather than a table: which step each
 *               item is at, why it is there (the gap slots, the route, the verdict, the
 *               refusal's own reason from the chain — J-FAC-4), and what the route gate
 *               withheld. Before the run it says what will be spent, with which builder,
 *               how many items can be worked and delivered, and where a pull request would
 *               go — or why delivery is not possible for this repository (J-FAC-2/3); the
 *               button names the estimate, never a cap (F5b: nothing on this page promises
 *               a ceiling nothing enforces). While
 *               a factory run is active the chain polls and a banner names the run and the
 *               item in hand (J-FAC-5 / J-TEL-9). A built item opens its evidence (F15); a
 *               stopped item says the way forward — an evolution that supersedes it, the
 *               route the API serves as `way_forward` (DL-049), one sentence naming what must
 *               be different, and that replacement item already drafted from the stop's own
 *               reason (G-904) — and the freeze form for a
 *               revised backlog (a new hash) starts from the active one (J-FAC-15). Every act goes through the API under its role; the
 *               chain (`/factory/{repo}/evidence`) is the record, and this screen renders the
 *               folded view of it (`task_views`).
 * How:          `useRepoParam({ defaultToLatest: true })` (as the Baseline: reached from the
 *               nav, the latest repository is chosen) → `useFactoryBacklog` + `useFactoryTasks` (polled while `useRuns` lists an
 *               active factory run) → `stepsFor(task)` → `<StepList>`; `builderChoice(health)`
 *               picks the builder exactly as Measure does (an operator may name another —
 *               the factory has no "every knob" form); `estimateFromMap` is Measure's
 *               row-weighted measured mean per attempt; `useSignGap` (POST signoff-gap),
 *               `useRegisterBacklog` (POST backlog, the form or JSON in a dialog),
 *               `useCreateRun` (kind `factory`, `deliver` toggle gated by the backlog's
 *               delivery pre-flight; `deliver_override` for an approver); `EvidenceDrawer`
 *               opens the newest build's pack; `useNarrow` (matchMedia at Tailwind's `sm`)
 *               folds an item's six step cards behind a Details at phone width (J-FAC-14).
 *               A 404 = no backlog registered: the instruction, not an error. `?item=`
 *               scrolls to and highlights one item (the Decisions inbox links here).
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0003-one-routing-rule.md (amendment 2026-09-16: the route gate)
 * Works with:   ui/src/screens/Factory/IntakePage.tsx (the work arriving from the team's own
 *               board — this screen is its only door, and ui/src/App.reachability.test.ts holds
 *               that),
 *               ui/src/api/hooks.ts (`useFactoryBacklog`, `useFactoryTasks`, `useSignGap`,
 *               `useRegisterBacklog`, `useCreateRun`, `useCancelRun`, `useRuns`, `useHealth`,
 *               `useCapabilityMap`, `useAllRepos`), ui/src/api/types.ts (`FactoryTask`,
 *               `FactoryBacklog`), ui/src/lib/builder.ts (`builderChoice`, shared with
 *               Measure), ui/src/components/RepoPicker.tsx (`defaultToLatest`, as the
 *               Baseline), ui/src/screens/Runs/EvidenceDrawer.tsx (the pack view an item
 *               row opens), src/crb/server/routes/factory.py (the shapes — `way_forward`
 *               included — documented under "Factory" in the API doc),
 *               src/crb/server/factory_state.py (`task_views`, the fold of the factory
 *               loop's chain this screen renders; the loop itself is src/crb/factory/loop.py),
 *               ui/src/screens/Decisions/decisions.ts (the inbox rows that link here)
 * Tested by:    ui/src/screens/Factory/FactoryPage.test.tsx, ui/e2e/walkthrough/10-factory.spec.ts
 * Touch when:   a step or a stop status is added to the loop (add it to `stepsFor` and the
 *               loop's docstring); a field is added to `FactoryTaskOut`; a refusal is
 *               recorded in a new shape.
 */

import { useEffect, useMemo, useState, useSyncExternalStore } from 'react'
import { useSearchParams } from 'react-router'
import { useAllRepos, useCancelRun, useCapabilityMap, useCreateRun, useFactoryBacklog, useFactoryCatalogue, useFactoryTasks, useHealth, useRegisterBacklog, useRuns, useSignGap } from '../../api/hooks'
import { NOT_YET_MEASURED, isRunTerminal, type CapabilityCell, type FactoryBacklog, type FactoryBacklogItem, type FactoryCatalogue, type FactoryDeliveryPreflight, type FactoryEvolutionPrefill, type FactoryTask, type Run } from '../../api/types'
import { Button, LinkButton } from '../../components/Button'
import { Card } from '../../components/Card'
import { Dialog } from '../../components/Dialog'
import { EmptyState } from '../../components/EmptyState'
import { ErrorState } from '../../components/ErrorState'
import { SelectField, TextArea, TextField } from '../../components/Field'
import { DocLink, Term } from '../../components/Help'
import { Hint } from '../../components/Hint'
import { PageHeader } from '../../components/PageHeader'
import { Pill } from '../../components/Pill'
import { RepoPicker, useRepoParam } from '../../components/RepoPicker'
import { ShortId } from '../../components/ShortId'
import { Details, NotificationBanner, SummaryList, WarningButton } from '../../components/govuk'
import type { HintId } from '../../help/hints'
import { useAuth } from '../../lib/auth'
import { builderChoice } from '../../lib/builder'
import { fmtDate, fmtInt, kOfN, shortId } from '../../lib/format'
import type { Tone } from '../../lib/verdict'
import { EvidenceDrawer } from '../Runs/EvidenceDrawer'

type StepStatus = 'done' | 'current' | 'todo' | 'failed' | 'skipped'

interface Step {
  id: 'readiness' | 'red' | 'build' | 'delivery' | 'review' | 'outcome'
  title: string
  status: StepStatus
  detail: string
}

/** The hint for each of the six step cards — what the step is and what its state tells the reader. */
const STEP_HINT: Record<Step['id'], HintId> = {
  readiness: 'step.factory.readiness',
  red: 'step.factory.red',
  build: 'step.factory.build',
  delivery: 'step.factory.delivery',
  review: 'step.factory.review',
  outcome: 'step.factory.outcome',
}

const STEP_DISPLAY: Record<StepStatus, { tone: Tone; glyph: string; label: string }> = {
  done: { tone: 'green', glyph: '✓', label: 'done' },
  current: { tone: 'blue', glyph: '◐', label: 'here' },
  todo: { tone: 'muted', glyph: '○', label: 'not yet' },
  failed: { tone: 'red', glyph: '✕', label: 'failed' },
  skipped: { tone: 'muted', glyph: '–', label: 'skipped' },
}

/** The item statuses the loop records (src/crb/factory/loop.py), as a person reads them. */
const STATUS_LABEL: Record<string, string> = {
  pending: 'Not started',
  accepted: 'Accepted',
  rejected: 'Rejected by review',
  not_ready: 'Not ready',
  routed_human: 'Goes to a person',
  no_oracle: 'No test to prove',
  not_red: 'RED proof refused',
  not_clean: 'Build not clean',
  disqualified: 'Disqualified',
  delivery_failed: 'Delivery failed',
  rework_exhausted: 'Rework exhausted',
  oracle_needs_strengthening: 'Test needs strengthening',
  blocked_on_dependency: 'Waiting on a dependency',
  error: 'Error',
}

const FAILED_STATUSES = ['rejected', 'rework_exhausted', 'disqualified', 'delivery_failed', 'error', 'not_clean']

/** The way forward every `oracle_needs_strengthening` reason ends with (composed by the loop,
 * `crb.factory.loop._refuse_rework`) — the outcome sentence gives it once, so the quoted
 * reason is trimmed to the finding and why no stronger test could be had. */
const WAY_FORWARD = 'strengthen the test and register a superseding item'
const findingOf = (reason: string) => reason.replace(new RegExp(`:\\s*${WAY_FORWARD}\\s*$`), '')

/** The reason a delivery refusal records when the opt-in was off (src/crb/factory/loop.py `_deliver`). */
const OPT_IN_OFF = /^delivery is opt-in and OFF/
const ROUTE_GATE = /^route gate: /
const SIGNED_CELL_GATE = /^signed-cell gate: /

/** What an open value slot means, after the readiness detail: it routes, it is never signed. */
function valueGapNote(t: FactoryTask): string {
  const v = t.value_gaps ?? []
  return v.length ? ` · value gap${v.length === 1 ? '' : 's'} ${v.join(', ')} route${v.length === 1 ? 's' : ''} test-first, never signed` : ''
}

/** The six steps of the loop for one item, from the folded task view. */
export function stepsFor(t: FactoryTask): Step[] {
  const gaps = t.dor_gaps.length
  const r = t.refusal
  // `route_hint` is the item's NEWEST route on the chain: after a rule-3 stop that is the
  // `human` the stop routed it to, not the reading readiness made before the build
  const stoppedAfterReview = t.status === 'oracle_needs_strengthening' && t.route_hint === 'human'
  const readiness: Step =
    gaps > 0
      ? {
          id: 'readiness',
          title: 'Readiness',
          status: 'current',
          detail: `${gaps} structural gap${gaps === 1 ? '' : 's'} unsigned: ${t.dor_gaps.join(', ')}${valueGapNote(t)}`,
        }
      : r?.step === 'readiness'
        ? {
            id: 'readiness',
            title: 'Readiness',
            status: 'failed',
            detail: `Routed to a person — ${r.reason}.`,
          }
        : t.route_hint === 'human' && t.status === 'routed_human'
          ? {
              id: 'readiness',
              title: 'Readiness',
              status: 'failed',
              detail: 'Routed to a person — the loop stops here.',
            }
          : t.route_hint === ''
            ? // no route event yet: the factory run has not assessed this item
              {
                id: 'readiness',
                title: 'Readiness',
                status: 'current',
                detail: 'not assessed — a factory run assesses readiness first',
              }
            : stoppedAfterReview
              ? {
                  id: 'readiness',
                  title: 'Readiness',
                  status: 'done',
                  detail: 'built, then routed human after the review — the readiness reading is on the chain',
                }
              : {
                  id: 'readiness',
                  title: 'Readiness',
                  status: 'done',
                  detail: `route ${t.route_hint}${valueGapNote(t)}`,
                }
  const afterReadiness = readiness.status === 'done'
  const red: Step =
    t.red_proof === true
      ? {
          id: 'red',
          title: 'RED proof',
          status: 'done',
          detail: 'the authored test fails before the change',
        }
      : t.red_proof === false || r?.step === 'red'
        ? {
            id: 'red',
            title: 'RED proof',
            status: 'failed',
            detail: r?.step === 'red' ? `RED proof refused — the authored test passed at the parent, so it proves nothing: ${r.reason}.` : 'RED proof refused — the test did not fail at the parent.',
          }
        : {
            id: 'red',
            title: 'RED proof',
            status: afterReadiness ? 'current' : 'todo',
            detail: 'not run',
          }
  // a refusal at the RED step with no oracle at all is worded by the chain ("no authored test…")
  if (r?.step === 'red' && /^no authored test/.test(r.reason)) red.detail = `RED proof refused — ${r.reason}.`
  const buildDone = t.build_status === 'clean'
  const build: Step = buildDone
    ? {
        id: 'build',
        title: 'Build under the belts',
        status: 'done',
        detail: 'clean',
      }
    : t.build_status === 'not_built' || t.build_status === 'not_started' || !t.build_status
      ? // the API folds "no build event" as `not_built` (factory_state.task_views)
        {
          id: 'build',
          title: 'Build under the belts',
          status: red.status === 'done' ? 'current' : 'todo',
          detail: 'not started',
        }
      : {
          id: 'build',
          title: 'Build under the belts',
          status: 'failed',
          detail: t.build_status.replace(/_/g, ' '),
        }
  const delivery: Step = t.pr_url
    ? // `delivery.updated` = a rework re-pointed the branch on the SAME pull request (DL-045)
      {
        id: 'delivery',
        title: 'Delivery',
        status: 'done',
        detail: t.last_event === 'delivery.updated' ? 'pull request updated by a rework' : 'branch + pull request opened',
      }
    : r?.step === 'delivery'
      ? OPT_IN_OFF.test(r.reason)
        ? {
            id: 'delivery',
            title: 'Delivery',
            status: 'skipped',
            detail: 'Delivery withheld — delivery was off for this run. Built and graded locally only.',
          }
        : SIGNED_CELL_GATE.test(r.reason)
          ? {
              id: 'delivery',
              title: 'Delivery',
              status: 'skipped',
              detail: `Delivery withheld — the signed-cell clause: nobody has signed ${t.capability_class} × ${t.size} off, and this deployment opens a pull request only for a cell a person has attested (ADR-0018). Built, graded and reviewed; no pull request opened.`,
            }
          : ROUTE_GATE.test(r.reason)
          ? {
              id: 'delivery',
              title: 'Delivery',
              status: 'skipped',
              detail: `Delivery withheld — the route gate: ${t.capability_class} × ${t.size} ${r.measured_route ? `routes ${r.measured_route}` : 'is not measured'}${r.reason_code ? ` (${r.reason_code}${t.cell_route?.reason_code === r.reason_code && t.cell_route.reason ? `: ${t.cell_route.reason}` : ''})` : ''}. Built, graded and reviewed; no pull request opened.`,
            }
          : {
              id: 'delivery',
              title: 'Delivery',
              status: 'failed',
              detail: `Delivery failed — the push was refused: ${r.reason}.`,
            }
      : {
          id: 'delivery',
          title: 'Delivery',
          status: buildDone ? 'current' : 'todo',
          detail: buildDone ? 'pending' : 'not yet',
        }
  const review: Step = t.review_verdict
    ? {
        id: 'review',
        title: 'Independent review',
        status: t.review_verdict === 'accept' ? 'done' : t.review_verdict === 'reject' ? 'failed' : 'current',
        detail: `${t.review_verdict.replace(/_/g, ' ')}${r?.step === 'review' ? ' — the reviewer asked for a stronger test' : ''}`,
      }
    : {
        id: 'review',
        title: 'Independent review',
        status: buildDone ? 'current' : 'todo',
        detail: 'not yet',
      }
  const outcome: Step =
    t.status === 'accepted'
      ? { id: 'outcome', title: 'Outcome', status: 'done', detail: 'accepted' }
      : t.status === 'oracle_needs_strengthening'
        ? // DL-045 rule 3: the reviewer asked for a stronger TEST and no changed oracle could be
          // had (no test author, or the same bytes back) — the loop refused to rebuild against
          // the same oracle and routed the item to a human; the chain's reason says which
          {
            id: 'outcome',
            title: 'Outcome',
            status: 'failed',
            detail: `the reviewer found the oracle weak and no stronger test could be had — the loop did not rebuild against the same one: ${WAY_FORWARD}${t.outcome_reason ? ` (${findingOf(t.outcome_reason)})` : ''}`,
          }
        : FAILED_STATUSES.includes(t.status)
          ? {
              id: 'outcome',
              title: 'Outcome',
              status: 'failed',
              detail: `${t.status.replace(/_/g, ' ')}${t.error ? ` — ${t.error}` : ''}`,
            }
          : {
              id: 'outcome',
              title: 'Outcome',
              status: 'todo',
              detail: t.status.replace(/_/g, ' '),
            }
  return [readiness, red, build, delivery, review, outcome]
}

/**
 * J-FAC-15 — for an item the loop stopped, one plain sentence with the chain's reason and
 * the two ways forward; `''` when the item is not stopped.
 */
export function refusalSentence(t: FactoryTask): string {
  const r = t.refusal
  // DL-049: a frozen backlog does not change, it evolves — the way forward is an evolution
  // that supersedes this item (the frozen hash stays; the old chain is kept), which the API
  // serves as `way_forward`; freezing a revised backlog (a new hash) is the heavier path
  const evolve = (fix: string) => `To bring it back into the factory, ${fix} and register an evolution that supersedes this item (the frozen hash stays; the old chain is kept); or open the change by hand and mark the item done in the next backlog.`
  if (r?.step === 'dependency') return `${r.reason.replace(/^waiting on /, 'Waiting on ')}, which has not been accepted yet.`
  if (r?.step === 'readiness') return `This item goes to a person: ${r.reason}. ${evolve('add the fact')}`
  if (t.status === 'oracle_needs_strengthening' || r?.step === 'review')
    return `The review found the test too weak to rebuild against${t.outcome_reason || r?.reason ? `: ${findingOf(t.outcome_reason || r?.reason || '')}` : ''}. ${evolve('strengthen the test')}`
  if (r?.step === 'red') return `The factory could not prove the test: ${r.reason}. ${evolve('author a test that fails today')}`
  if (t.status === 'rejected' || t.status === 'rework_exhausted')
    return `The review said ${t.review_verdict?.replace(/_/g, ' ') ?? t.status.replace(/_/g, ' ')}. Read the evidence, then ${evolve('add the fact the review asked for').replace(/^To bring it back into the factory, /, '')}`
  if (t.status === 'no_oracle' || t.status === 'not_red')
    return `No failing test proves this item${r ? `: ${r.reason}` : ''}. ${evolve('author a test that fails today')}`
  return ''
}

/** How a person reads the item's status line. */
function statusLabel(t: FactoryTask): string {
  if (t.dor_gaps.length > 0) return 'Waiting on a signature'
  return STATUS_LABEL[t.status] ?? t.status.replace(/_/g, ' ')
}

/**
 * J-FAC-2 — the repository's own measured mean per attempt, when it has one: a
 * row-weighted mean over the map's measured cells (the map is served on the current
 * apparatus, so the versions are the same set on every cell), carrying the n it rests on
 * and that apparatus. The same calculation as Measure's; `null` when nothing is measured.
 */
export function estimateFromMap(cells: CapabilityCell[]): { mean: number; n: number; apparatus: string } | null {
  const measured = cells.filter((c) => c.route !== NOT_YET_MEASURED && c.n > 0 && c.cost_usd_mean > 0)
  if (measured.length === 0) return null
  const n = measured.reduce((a, c) => a + c.n, 0)
  const apparatus = Array.from(new Set(measured.flatMap((c) => c.apparatus_versions))).join(', ')
  return {
    mean: measured.reduce((a, c) => a + c.cost_usd_mean * c.n, 0) / n,
    n,
    apparatus,
  }
}

//: the per-attempt planning band the onboarding guide (ONBOARDING-A-REPO) quotes for Claude Sonnet (not a
//: measured interval for THIS repository) — used only while the repository has no measured mean
const RANGE_LOW = 0.2
const RANGE_HIGH = 0.6

/** Dollars to the cent — an estimate, not a ledger figure (which `fmtUsd` shows to the mil). */
function usd(x: number): string {
  return `$${x.toFixed(2)}`
}

/** What the chain's newest event for an item means, for the active-run banner. */
const EVENT_PHRASE: Record<string, string> = {
  'readiness.assessed': 'readiness assessed',
  'route.decided': 'route decided',
  'red.proved': 'RED proof — the authored test failed at the parent, so the build may start',
  'red.refused': 'RED proof refused',
  'build.graded': 'build graded under the belts',
  'delivery.opened': 'branch and pull request opened',
  'delivery.updated': 'pull request updated by a rework',
  'delivery.refused': 'delivery withheld',
  'review.verdict': 'review recorded',
  'edit.permitted': 'rework permitted',
  'gap.signoff': 'a gap was signed',
  'item.outcome': 'outcome recorded',
}

const noBacklog = (e: unknown) => e !== null && typeof e === 'object' && 'status' in e && (e as { status: number }).status === 404

/** Tailwind's `sm` breakpoint: below it the six step cards sit behind a Details (J-FAC-14). */
const NARROW = '(max-width: 639px)'
const narrowQuery = () => (typeof window !== 'undefined' && typeof window.matchMedia === 'function' ? window.matchMedia(NARROW) : null)

/** True at phone width; false where `matchMedia` is absent (jsdom), so tests see the grid. */
function useNarrow(): boolean {
  return useSyncExternalStore(
    (notify) => {
      const mq = narrowQuery()
      mq?.addEventListener('change', notify)
      return () => mq?.removeEventListener('change', notify)
    },
    () => narrowQuery()?.matches ?? false,
    () => false,
  )
}

export function FactoryPage() {
  // reached from the nav with no ?repo=, the most recently updated repository is chosen and
  // written into the URL (as the Baseline does): journey step 4 must never open on an empty
  // "choose a repository" for a deployment that has one
  const [repo, setRepo] = useRepoParam({ defaultToLatest: true })
  const repos = useAllRepos()
  const [params] = useSearchParams()
  const focus = params.get('item') ?? ''
  const { can } = useAuth()
  const backlog = useFactoryBacklog(repo)
  // J-FAC-5 / J-TEL-9 — the newest factory runs of this repository: an active one means
  // the chain is moving, so the items poll and the banner names the run
  const runs = useRuns({ repo, kind: 'factory', limit: 10 })
  const activeRun = runs.data?.items.find((r) => !isRunTerminal(r.status)) ?? null
  const lastRun = !activeRun ? (runs.data?.items[0] ?? null) : null
  const tasks = useFactoryTasks(repo, { poll: activeRun !== null })
  const [registerOpen, setRegisterOpen] = useState(false)
  const [dialogKey, setDialogKey] = useState(0)
  const [prefill, setPrefill] = useState<FactoryBacklog | null>(null)
  const [pack, setPack] = useState<{ pack: string; row: string } | null>(null)

  useEffect(() => {
    if (focus) document.getElementById(`item-${focus}`)?.scrollIntoView?.({ block: 'center' })
  }, [focus, tasks.data])

  // when the active run ends, the chain has its final events: read them once more
  const activeId = activeRun?.id ?? ''
  const [seenActive, setSeenActive] = useState('')
  useEffect(() => {
    if (activeId) setSeenActive(activeId)
    else if (seenActive) {
      setSeenActive('')
      void tasks.refetch()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeId])

  /**
   * Open the freeze form. `evolution` is the replacement item the API already drafted for a
   * stopped item: it is put INTO the backlog the form starts from, superseding its
   * predecessor, because the point of a drafted item is that nobody retypes it. Without this
   * the operator read the draft in a Details and then filled a form seeded from something
   * else.
   */
  const openFreeze = (from: FactoryBacklog | null, evolution?: FactoryEvolutionPrefill | null) => {
    setPrefill(evolution ? withEvolution(from, evolution) : from)
    setDialogKey((k) => k + 1)
    setRegisterOpen(true)
  }

  return (
    <>
      <PageHeader
        title="Factory"
        purpose={
          <>
            New work under the same governance as replay: a frozen backlog, structural gaps signed by an approver, a <Term id="red_proof">RED proof</Term> before any build, a build under the belts, a branch and pull request only where the
            map routes <Term id="deliver">deliver</Term> (the <Term id="route_gate">route gate</Term>), an independent review — every step on the evidence chain.
          </>
        }
        actions={<RepoPicker value={repo} onChange={setRepo} />}
      />
      {!repo && repos.data && repos.data.items.length === 0 && (
        <EmptyState
          title="No repository connected yet"
          reason="The factory works one repository at a time, on the baseline the connection walk earns; nothing is connected on this deployment."
          action={can('operator') ? <LinkButton to="/connect">Connect a repository</LinkButton> : undefined}
        />
      )}
      {!repo && (!repos.data || repos.data.items.length > 0) && <EmptyState title="Choose a repository" reason={repos.data ? 'The factory works one repository at a time: choose one from the picker above.' : 'Loading the repositories…'} />}
      {repo && (
        <>
          <Card
            title="Backlog"
            eyebrow="frozen · hashed · the first event of the chain"
            actions={
              // the way IN to intake (ADR-0017). Without a link here the screen was reachable
              // only by typing its URL, and the guides had to hand the reader a raw path.
              // Reading the column is a viewer's act, so the link is not gated on a role.
              <div className="flex flex-wrap gap-2">
                <LinkButton size="sm" to={`/factory/intake?repo=${encodeURIComponent(repo)}`} hint="link.factory.intake">
                  Work arriving from your board
                </LinkButton>
                {can('operator') && (
                  <Button size="sm" onClick={() => openFreeze(null)} disabled={activeRun !== null} hint="button.factory.freeze">
                    Freeze a backlog…
                  </Button>
                )}
              </div>
            }
          >
            {backlog.isPending && <p className="text-sm text-on-surface-muted">Loading…</p>}
            {backlog.isError &&
              (noBacklog(backlog.error) ? (
                <EmptyState
                  glyph="⚙"
                  title="No backlog registered for this repository"
                  reason={
                    can('operator')
                      ? 'Freeze one: the items are validated, hashed and recorded as the first event of the evidence chain; a factory run then works them in dependency order.'
                      : 'An operator freezes one: the items are validated, hashed and recorded as the first event of the evidence chain; a factory run then works them in dependency order.'
                  }
                  action={
                    can('operator') ? (
                      <Button variant="filled" onClick={() => openFreeze(null)} hint="button.factory.freeze">
                        Freeze a backlog…
                      </Button>
                    ) : undefined
                  }
                  data-testid="factory-no-backlog"
                />
              ) : (
                <ErrorState error={backlog.error} onRetry={() => void backlog.refetch()} />
              ))}
            {backlog.data && (
              <div className="space-y-3">
                <div className="flex flex-wrap items-center gap-2 text-sm">
                  <Pill tone={backlog.data.frozen_at ? 'primary' : 'amber'} glyph={backlog.data.frozen_at ? '❄' : '○'} size="xs" label={backlog.data.frozen_at ? `Frozen at ${fmtDate(backlog.data.frozen_at)}` : 'Not frozen'} hint="pill.factory.frozen">
                    {backlog.data.frozen_at ? 'frozen' : 'not frozen'}
                  </Pill>
                  <Hint id="stat.factory.hash">
                    <span className="font-mono text-xs" data-testid="factory-backlog-hash">
                      hash <ShortId value={backlog.data.hash} n={16} />
                    </span>
                  </Hint>
                  <Hint id="stat.factory.items_count" className="text-xs text-on-surface-muted">
                    {fmtInt(backlog.data.items.length)} items
                  </Hint>
                </div>
                {activeRun && <ActiveRunBanner run={activeRun} tasks={tasks.data ?? []} canCancel={can('operator')} />}
                {!activeRun && lastRun && <LastRunLine run={lastRun} />}
                {!activeRun && can('operator') && <BeforeYouStart repo={repo} backlog={backlog.data} tasks={tasks.data} canOverride={can('approver')} />}
              </div>
            )}
          </Card>

          <Card title="Items" eyebrow="readiness → RED proof → build → delivery → review → outcome">
            {tasks.isPending && <p className="text-sm text-on-surface-muted">Loading…</p>}
            {tasks.isError && (noBacklog(tasks.error) ? <EmptyState compact glyph="⚙" title="No factory items — no backlog registered" /> : <ErrorState error={tasks.error} onRetry={() => void tasks.refetch()} />)}
            {tasks.data && tasks.data.length === 0 && <EmptyState compact title="No factory items yet" reason="Items appear once a factory run has worked the backlog." />}
            {tasks.data && tasks.data.length > 0 && (
              <ul className="m-0 list-none divide-y divide-border p-0">
                {tasks.data.map((t) => (
                  <ItemRow
                    key={t.id}
                    repo={repo}
                    task={t}
                    focused={t.id === focus}
                    canSign={can('approver')}
                    canFreeze={can('operator') && activeRun === null}
                    onFreeze={(evolution) => openFreeze(backlog.data ?? null, evolution)}
                    onEvidence={(p, row) => setPack({ pack: p, row })}
                  />
                ))}
              </ul>
            )}
          </Card>
        </>
      )}
      <RegisterBacklogDialog key={dialogKey} open={registerOpen} repo={repo} from={prefill} onClose={() => setRegisterOpen(false)} />
      <EvidenceDrawer packHash={pack?.pack ?? null} rowHash={pack?.row || null} onClose={() => setPack(null)} />
    </>
  )
}

/** J-FAC-5 / J-TEL-9 — the run working this backlog, its progress, the item in hand, and Cancel for an operator. */
function ActiveRunBanner({ run, tasks, canCancel }: { run: Run; tasks: FactoryTask[]; canCancel: boolean }) {
  const cancel = useCancelRun()
  const queued = run.status === 'queued'
  const total = run.progress?.total || tasks.length
  const done = run.progress?.done ?? 0
  // the item in hand: the first one the chain has touched that has no outcome yet
  const current = tasks.find((t) => t.status === 'pending' && t.last_event !== '')
  // a queued run has no item in hand, whatever the chain or a reclaimed run's `progress` still say
  const phrase = queued ? 'waiting for a worker' : current ? `${current.id}: ${EVENT_PHRASE[current.last_event] ?? current.last_event.replace(/[._]/g, ' ')}` : 'starting the next item'
  // the item in hand of total (`kOfN`: done + 1); null while queued or while the total is unknown (no progress, no tasks yet), and then no number at all — never "item 1 of 0"
  const item = queued ? null : kOfN(done, total)
  return (
    <NotificationBanner title="Factory run in progress" className="mb-0">
      <Hint as="p" id="banner.factory.active_run" className="m-0" data-testid="factory-active-run">
        Factory run {shortId(run.id)} is working the backlog{item ? ` — item ${item}` : ''} ({phrase}).
        {run.cost_usd > 0 ? ` ${usd(run.cost_usd)} so far.` : ''}
        {run.started ? ` Started ${fmtDate(run.started)}.` : ''}{' '}
        <LinkButton size="sm" to={`/runs/${run.id}`} hint="button.factory.open_run">
          Open the run
        </LinkButton>
        {canCancel && (
          <>
            {' '}
            <Button size="sm" onClick={() => cancel.mutate(run.id)} disabled={cancel.isPending || cancel.isSuccess} hint="button.factory.cancel">
              {cancel.isSuccess ? 'Cancelling…' : 'Cancel the run'}
            </Button>
          </>
        )}
      </Hint>
      {canCancel && <p className="mb-0 mt-2 text-[16px] text-on-surface-muted">Cancelling stops the loop after the item in hand. Items already built are still charged.</p>}
      {cancel.isError && <ErrorState compact error={cancel.error} />}
    </NotificationBanner>
  )
}

/** After the run: what the newest finished factory run did, in one line. */
function LastRunLine({ run }: { run: Run }) {
  const d = (run.counts?.detail ?? {}) as Record<string, unknown>
  const by = (d.by_status ?? {}) as Record<string, number>
  const parts = Object.entries(by)
    .filter(([k]) => k !== 'accepted')
    .map(([k, v]) => `${v} ${STATUS_LABEL[k]?.toLowerCase() ?? k.replace(/_/g, ' ')}`)
  const items = typeof d.items === 'number' ? d.items : null
  const accepted = typeof d.accepted === 'number' ? d.accepted : null
  return (
    <Hint as="p" id="stat.factory.last_run" className="m-0 text-sm text-on-surface-muted" data-testid="factory-last-run">
      Factory run {shortId(run.id)} {run.status}
      {items !== null && accepted !== null ? ` — ${accepted} of ${items} items accepted${parts.length ? `, ${parts.join(', ')}` : ''}` : ''}
      {run.finished ? ` · ${fmtDate(run.finished)}` : ''} ·{' '}
      <LinkButton size="sm" to={`/runs/${run.id}`} hint="link.factory.last_run">
        run {shortId(run.id)}
      </LinkButton>
    </Hint>
  )
}

/**
 * J-FAC-1/2/3 — the Measure "Before you start" pattern for the factory: the builder the
 * deployment can run (or the operator's own choice), what will be worked and delivered,
 * the estimated spend with the n and apparatus it rests on, where a pull request would
 * go (or why delivery is not possible), and one red button that names the amount.
 */
function BeforeYouStart({ repo, backlog, tasks, canOverride }: { repo: string; backlog: FactoryBacklog; tasks: FactoryTask[] | undefined; canOverride: boolean }) {
  const health = useHealth()
  const map = useCapabilityMap(repo, ['capability_class', 'size'])
  const run = useCreateRun()
  const [deliver, setDeliver] = useState(false)
  const [override, setOverride] = useState(false)
  const [ownBuilder, setOwnBuilder] = useState('')
  const [ownModel, setOwnModel] = useState('')
  const choice = builderChoice(health.data)
  const measured = useMemo(() => estimateFromMap(map.data?.cells ?? []), [map.data])
  // an API older than J-FAC-3 serves no pre-flight: say so rather than guess (never a white screen)
  const delivery: FactoryDeliveryPreflight = backlog.delivery ?? {
    can_deliver: false,
    reason_code: 'not_linked',
    reason: 'Delivery is not possible: this API did not report the delivery pre-flight. Update the API, then reload.',
    full_name: '',
    default_branch: '',
    installation_id: null,
    account_login: '',
  }
  const canDeliver = delivery.can_deliver
  const list = tasks ?? []
  const total = backlog.items.length
  const gapped = list.filter((t) => t.dor_gaps.length > 0).length
  const worked = Math.max(total - gapped, 0)
  const deliverable = deliverableCount(list)
  const lo = measured ? measured.mean * 0.8 * worked : RANGE_LOW * worked
  const hi = measured ? measured.mean * 1.2 * worked : RANGE_HIGH * worked
  const own = ownBuilder.trim()
  const builderRow = own
    ? `${own}${ownModel.trim() ? ` · ${ownModel.trim()}` : ''} — named by you (every knob)`
    : choice
      ? choice.label
      : 'No builder is configured on this deployment — an admin adds a provider key (Settings), or name one below'
  const target = canDeliver ? `pushes a branch to ${delivery.full_name} and opens a pull request against ${delivery.default_branch}; nothing is written to ${delivery.default_branch}` : ''
  const startable = (own.length > 0 || choice !== null) && !run.isPending && worked > 0

  const startRun = () => {
    const body = own
      ? { builder: own, ...(ownModel.trim() ? { model: ownModel.trim() } : {}) }
      : choice
        ? {
            builder: choice.builder,
            model: choice.model,
            ...(Object.keys(choice.builder_config).length > 0 ? { builder_config: choice.builder_config } : {}),
          }
        : null
    if (!body) return
    run.mutate({
      repo,
      kind: 'factory',
      deliver: deliver && canDeliver,
      ...body,
      ...(deliver && canDeliver && override ? { deliver_override: true } : {}),
    })
  }

  return (
    <div className="rounded-[var(--radius-control)] border border-border p-4" data-testid="before-you-start">
      <h3 className="mb-3 mt-0 text-base font-bold">Before you run</h3>
      <SummaryList
        rows={[
          { key: 'Builder', value: builderRow, hint: 'summary.factory.builder' },
          {
            key: 'Items',
            hint: 'summary.factory.items',
            value: `${worked} of ${total} will be worked${gapped ? ` (${gapped} wait${gapped === 1 ? 's' : ''} on a signed gap)` : ''}; ${deliverable} could be delivered as ${deliverable === 1 ? 'a pull request' : 'pull requests'} today`,
            note: 'Readiness is assessed again at the run; an item with an unsigned structural gap is refused before any spend.',
          },
          {
            key: 'Estimated cost',
            hint: 'stat.factory.estimate',
            value:
              worked === 0 ? (
                'nothing — no item can be worked'
              ) : measured ? (
                `${usd(lo)} to ${usd(hi)} for ${worked} item${worked === 1 ? '' : 's'} at about ${usd(measured.mean)} each (this repository's measured mean over n = ${measured.n} attempts at apparatus ${measured.apparatus || '—'}; the band is a ±20 % planning range, not a measured interval)`
              ) : (
                // no path literal here: an unbreakable token this long overflows the 375 px column (J-FAC-14)
                <>
                  {usd(lo)} to {usd(hi)} for {worked} item{worked === 1 ? '' : 's'} at about {usd(RANGE_LOW)}–{usd(RANGE_HIGH)} each — a planning range, not a measured interval: this repository has no measured mean yet (n = 0 on the current apparatus); the range is the per-attempt band the{' '}
                  <DocLink to="ONBOARDING-A-REPO">onboarding guide</DocLink> quotes for Claude Sonnet across earlier repositories, and carries no apparatus of its own
                </>
              ),
          },
          {
            key: 'Delivery',
            hint: 'summary.factory.delivery',
            value: !canDeliver ? 'not linked — no pull request' : deliver ? `on — a clean build in a deliver cell ${target}.` : `off — built and graded locally only. When on, a clean build in a deliver cell ${target}.`,
            note: !canDeliver ? delivery.reason : undefined,
          },
          {
            key: 'Budget cap',
            hint: 'summary.factory.budget_cap',
            value: 'no spend cap yet — the builder’s ladder caps turns, tool calls and wall clock per attempt',
          },
        ]}
        label="Before you run"
      />
      <div className="mt-3 space-y-2 text-sm">
        <Hint as="label" id="field.factory.deliver" className="flex items-start gap-2">
          <input type="checkbox" className="mt-1" checked={deliver && canDeliver} disabled={!canDeliver} onChange={(e) => setDeliver(e.target.checked)} />
          <span>
            Open pull requests where the map routes <code>deliver</code>
            {tasks && (
              <Hint id="stat.factory.deliverable" className="block text-xs text-on-surface-muted" data-testid="factory-deliverable-count">
                {deliverable} of {tasks.length} items sit in a cell this deployment would deliver from today; the rest are built and withheld — by the route, or because nobody has signed the cell off (ADR-0018)
              </Hint>
            )}
          </span>
        </Hint>
        {deliver && canDeliver && canOverride && (
          <Hint as="label" id="field.factory.override" className="flex items-start gap-2">
            <input type="checkbox" className="mt-1" checked={override} onChange={(e) => setOverride(e.target.checked)} />
            <span>
              Override the delivery gate (approver)
              <span className="block text-xs text-on-surface-muted">Recorded on the evidence chain under your name, one clause at a time: the route gate, and the signed-cell clause. It licenses this run to open a pull request; it is not an attestation of the cell and no second person is claimed for it.</span>
            </span>
          </Hint>
        )}
        <Hint as="div" id="details.factory.own_builder">
          <Details summary="Use a different builder" className="mb-0 mt-2 text-sm">
            <p className="m-0 mb-2 text-xs text-on-surface-muted">
              The factory has no full run form: name a registered builder here (as the run form's Builder field) when the deployment's default is not the one you mean. Blank = the builder above.
            </p>
            <div className="grid gap-3 sm:grid-cols-2">
              <TextField label="Builder" value={ownBuilder} onChange={(e) => setOwnBuilder(e.target.value)} description="a registered builder name" hint="field.factory.own_builder" />
              <TextField label="Model" value={ownModel} onChange={(e) => setOwnModel(e.target.value)} description="optional — the builder's default when blank" hint="field.factory.own_model" />
            </div>
          </Details>
        </Hint>
      </div>
      <p className="mb-3 mt-3 text-sm">You can cancel the run at any point. Items already built are still charged.</p>
      <div className="flex flex-wrap items-center gap-3" data-testid="factory-run-controls">
        <WarningButton onClick={startRun} disabled={!startable} hint="button.factory.run">
          {/* an estimate, never a promised cap: the request carries no spend cap (F5b), as the Budget cap row above says */}
          {worked > 0 && (measured || own || choice) ? `Run the factory — estimated ${usd(lo)} to ${usd(hi)}` : 'Run the factory'}
        </WarningButton>
        {run.data && (
          <LinkButton size="sm" to={`/runs/${run.data.id}`} hint="button.factory.started_run">
            run {shortId(run.data.id)}
          </LinkButton>
        )}
      </div>
      {run.isError && <ErrorState compact error={run.error} />}
    </div>
  )
}

function ItemRow({
  repo,
  task: t,
  focused,
  canSign,
  canFreeze,
  onFreeze,
  onEvidence,
}: {
  repo: string
  task: FactoryTask
  focused: boolean
  canSign: boolean
  canFreeze: boolean
  /** Called with the replacement item the API already drafted for this stop, when there is
   *  one, so the freeze form starts from it rather than from a blank of the active backlog. */
  onFreeze: (evolution?: FactoryEvolutionPrefill | null) => void
  onEvidence: (pack: string, row: string) => void
}) {
  const steps = stepsFor(t)
  const current = steps.find((s) => s.status === 'current' || s.status === 'failed') ?? steps[steps.length - 1]!
  const currentIndex = steps.indexOf(current) + 1
  const sentence = refusalSentence(t)
  const narrow = useNarrow()
  return (
    <li id={`item-${t.id}`} className={`py-3 ${focused ? 'rounded-[var(--radius-control)] bg-primary-container/30 px-2' : ''}`} data-testid={`factory-item-${t.id}`}>
      <div className="flex flex-wrap items-center gap-2">
        <Hint id="item.factory.id" tabStop={false} className="font-mono text-xs text-on-surface-muted">
          {t.id}
        </Hint>
        <span className="font-semibold">{t.title}</span>
        <Hint id="item.factory.cell" tabStop={false} className="font-mono text-xs text-on-surface-muted">
          {t.capability_class} · {t.size} · {t.kind}
        </Hint>
        <CellRoutePill t={t} />
        <Hint id="item.factory.status" className="ml-auto text-xs" data-testid={`item-status-${t.id}`}>
          {statusLabel(t)}
        </Hint>
        {t.run_id && (
          <LinkButton size="sm" to={`/runs/${t.run_id}`} hint="button.factory.item_run">
            run {shortId(t.run_id)}
          </LinkButton>
        )}
        {t.pack_hash && (
          <Button size="sm" onClick={() => onEvidence(t.pack_hash ?? '', t.row_hash ?? '')} data-testid={`evidence-${t.id}`} hint="button.factory.evidence">
            Evidence
          </Button>
        )}
        {t.pr_url && (
          <Hint as="a" id="link.factory.pr" href={t.pr_url} className="text-xs" target="_blank" rel="noreferrer">
            PR ↗
          </Hint>
        )}
      </div>
      {sentence && (
        <div className="mt-2 flex flex-wrap items-center gap-2 rounded-[var(--radius-control)] border border-border bg-surface p-2 text-sm" data-testid={`refusal-${t.id}`}>
          <Hint as="p" id="banner.factory.refusal" className="m-0 flex-1 basis-[28em]">
            {sentence}
          </Hint>
          {canFreeze && (
            <Button size="sm" onClick={() => onFreeze(t.way_forward?.prefill ?? null)} hint="button.factory.freeze_revised">
              Freeze a revised backlog…
            </Button>
          )}
          <PrefilledEvolution t={t} />
        </div>
      )}
      {narrow && (
        // J-FAC-14 — at phone width one line says where the item is; the six cards wait behind a Details
        <p className="m-0 mt-2 flex flex-wrap items-center gap-1.5 text-xs" data-testid={`steps-compact-${t.id}`}>
          <Pill tone={STEP_DISPLAY[current.status].tone} glyph={STEP_DISPLAY[current.status].glyph} size="xs" label={`${current.title}: ${STEP_DISPLAY[current.status].label}`} hint="pill.factory.step_current">
            {STEP_DISPLAY[current.status].label}
          </Pill>
          <span className="font-semibold">{current.title}</span>
          <span className="text-on-surface-muted">
            step {currentIndex} of {steps.length}
          </span>
        </p>
      )}
      {narrow ? (
        <Details summary={`All ${steps.length} steps`} className="mb-0 mt-2 text-sm">
          <StepGrid t={t} steps={steps} />
        </Details>
      ) : (
        <StepGrid t={t} steps={steps} />
      )}
      {t.dor_gaps.length > 0 && canSign && <GapForm repo={repo} task={t} />}
      {t.dor_gaps.length > 0 && !canSign && <p className="m-0 mt-2 text-xs text-on-surface-muted">An approver signs the structural gap(s); a value gap is never signed — it routes test-first.</p>}
    </li>
  )
}

/**
 * G-904 — the replacement item, already drafted. A stopped item's way forward is not only a
 * route: the API serves the superseding item pre-filled from the item that stopped and from
 * the stop's own reason (for a weak-test stop, the review's finding), so the next step is a
 * read of a draft rather than retyping what the product already knows. Nothing is registered
 * here — the draft is shown, and the operator posts it from the freeze form or the API.
 */
function PrefilledEvolution({ t }: { t: FactoryTask }) {
  const wf = t.way_forward
  const pre = wf?.prefill
  if (!wf || !pre) return null
  return (
    <div className="basis-full" data-testid={`prefill-${t.id}`}>
      <Hint as="p" id="banner.factory.what_to_change" className="m-0 mb-1 text-xs">
        {wf.what_to_change}
        {wf.needs_authored_test ? ' Attach the failing test with the item.' : ''}
      </Hint>
      <Details summary="The replacement item, drafted" className="mb-0 text-sm">
        <Hint as="div" id="item.factory.prefill" className="min-w-0">
          <p className="m-0">
            <span className="font-mono text-xs">{pre.id}</span> supersedes <span className="font-mono text-xs">{pre.supersedes}</span> · {pre.capability_class} · {pre.size_estimate} · {pre.kind}
          </p>
          <p className="m-0 mt-1 font-semibold">{pre.title}</p>
          <p className="m-0 mt-1 whitespace-pre-wrap break-words text-xs text-on-surface-muted">{pre.description}</p>
          {pre.structural_facts.length > 0 && (
            <ul className="m-0 mt-1 list-disc pl-5 text-xs text-on-surface-muted">
              {pre.structural_facts.map((f) => (
                <li key={f} className="break-words">
                  {f}
                </li>
              ))}
            </ul>
          )}
        </Hint>
      </Details>
    </div>
  )
}

/** The six step cards: pill, title and the detail from the chain. */
function StepGrid({ t, steps }: { t: FactoryTask; steps: Step[] }) {
  return (
    <ol className="m-0 mt-2 grid list-none grid-cols-2 gap-2 p-0 sm:grid-cols-6" aria-label={`Steps for ${t.id}`}>
      {steps.map((s) => {
        const d = STEP_DISPLAY[s.status]
        return (
          // the card is the tab stop (what the step is); the state pill, six per item, opens on hover and tap only
          <Hint as="li" key={s.id} id={STEP_HINT[s.id]} className="min-w-0 rounded-[var(--radius-control)] border border-border p-2" data-testid={`step-${t.id}-${s.id}`}>
            <div className="flex flex-wrap items-center gap-1.5">
              <Pill tone={d.tone} glyph={d.glyph} size="xs" label={`${s.title}: ${d.label}`} hint="pill.factory.step_state" tabStop={false}>
                {d.label}
              </Pill>
              <span className="text-xs font-semibold leading-tight">{s.title}</span>
            </div>
            <div className="mt-1 break-words text-[11px] leading-snug text-on-surface-muted">{s.detail}</div>
          </Hint>
        )
      })}
    </ol>
  )
}

/** J-FAC-16 — sign one structural gap: the catalogue's question as the label, the signer and time on success. */
function GapForm({ repo, task: t }: { repo: string; task: FactoryTask }) {
  const sign = useSignGap()
  const catalogue = useFactoryCatalogue(true)
  const [slot, setSlot] = useState(t.dor_gaps[0] ?? '')
  const [answer, setAnswer] = useState('')
  const questions = new Map((catalogue.data?.classes.find((c) => c.capability_class === t.capability_class)?.slots ?? []).map((s) => [s.name, s.question]))
  const question = questions.get(slot)
  return (
    <form
      className="mt-2 flex flex-wrap items-end gap-2 rounded-[var(--radius-control)] border border-border p-2"
      onSubmit={(e) => {
        e.preventDefault()
        if (slot && answer.trim()) sign.mutate({ repo, itemId: t.id, slot, answer: answer.trim() }, { onSuccess: () => setAnswer('') })
      }}
      aria-label={`Sign a structural gap for ${t.id}`}
    >
      {/* a select is as wide as its longest option (the catalogue's question): the label must be
          allowed to shrink (min-w-0) and the select to fill it, or the page scrolls sideways at 375 px */}
      <Hint as="label" id="field.factory.gap" className="min-w-0 flex-1 basis-[30ch] text-xs">
        Gap
        <select className="mt-1 block w-full rounded border border-border bg-surface px-1 py-1 text-xs" value={slot} onChange={(e) => setSlot(e.target.value)}>
          {t.dor_gaps.map((g) => (
            <option key={g} value={g}>
              {questions.get(g) ? `${questions.get(g)} (${g})` : g}
            </option>
          ))}
        </select>
      </Hint>
      <TextField
        label="Your answer (the structural fact)"
        hint="field.factory.gap_answer"
        value={answer}
        onChange={(e) => setAnswer(e.target.value)}
        className="min-w-[24ch] flex-1"
        required
        description={question ? `${question} As a reviewer could check it, for example “GET /v1/orders/{id}”.` : 'The structural fact, as a reviewer could check it.'}
      />
      <Button type="submit" size="sm" variant="filled" disabled={sign.isPending || !answer.trim()} hint="button.factory.sign_gap">
        Sign the gap
      </Button>
      {sign.isError && <ErrorState compact error={sign.error} />}
      {sign.isSuccess && (
        <span className="text-xs text-status-green">
          Signed by {String((sign.data as { verifier?: string })?.verifier ?? 'you')} at {fmtDate((sign.data as { signed_at?: string })?.signed_at)} — on the chain
        </span>
      )}
    </form>
  )
}

/** How many items sit in a cell this deployment would deliver from — the WHOLE gate the server
 * computed (route + signed cell under the deployment's posture, ADR-0018), never half of it. */
export function deliverableCount(tasks: FactoryTask[]): number {
  return tasks.filter((t) => t.cell_route?.deliverable).length
}

/**
 * F28 / J-FAC-14 — the item's cell route BEFORE the run, from the same signed map the
 * delivery gate reads: "routes deliver" (green), "routes calibrate · withheld" (amber),
 * or "not measured · withheld" (grey). The pill is short; the n · point [interval] ·
 * apparatus follow in a span that wraps at phone width (the aria-label carries them all).
 * Never a guess: `route: ''` means nobody has measured the cell.
 */
function CellRoutePill({ t }: { t: FactoryTask }) {
  const r = t.cell_route
  if (!r || !r.route) {
    return (
      <Pill tone="muted" glyph="○" size="xs" label={`Cell ${t.capability_class} × ${t.size} is not measured on this repository: delivery would be withheld`} hint="factory.cell_route.unmeasured" data-testid={`cell-route-${t.id}`}>
        not measured · withheld
      </Pill>
    )
  }
  // every number carries its n, its interval and its apparatus
  const prov = `n = ${r.n} · ${pct(r.point)} [${pct(r.ci_low)}, ${pct(r.ci_high)}] · apparatus ${r.apparatus_versions.join(', ') || '—'}`
  return (
    <>
      {r.deliverable ? (
        <Pill tone="green" glyph="✓" size="xs" label={`Cell ${t.capability_class} × ${t.size} routes deliver${r.signed ? ' and a person has signed it off' : ''} — ${prov}: a clean build may open a pull request`} hint="factory.cell_route.deliverable" data-testid={`cell-route-${t.id}`}>
          routes deliver
        </Pill>
      ) : (
        <Pill tone="amber" glyph="⊘" size="xs" label={`Cell ${t.capability_class} × ${t.size} routes ${r.route} (${r.reason_code}) — ${prov}: delivery would be withheld — ${withheldWhy(r)}`} hint="factory.cell_route.withheld" data-testid={`cell-route-${t.id}`}>
          routes {r.route} · withheld
        </Pill>
      )}
      <Hint id="item.factory.cell_prov" tabStop={false} className="font-mono text-[11px] text-on-surface-muted" aria-hidden data-testid={`cell-route-${t.id}-prov`}>
        {prov}
      </Hint>
    </>
  )
}

/** Which clause of the delivery gate holds this cell back (ADR-0018) — the route, or the
 * missing signature. Said in the reader's words, never as a code on its own. */
function withheldWhy(r: NonNullable<FactoryTask['cell_route']>): string {
  return r.route === 'deliver' && r.signed === false ? 'nobody has signed this cell off, and a signed cell is what licenses a pull request here' : r.reason
}

function pct(x: number): string {
  return `${(x * 100).toFixed(0)} %`
}

interface DraftItem {
  id: string
  title: string
  capability_class: string
  size_estimate: string
  kind: string
  level: string
  description: string
  depends_on: string
  /** slot name → the fact, for the chosen class's structural slots */
  facts: Record<string, string>
}

/** The next `I-n` no current item uses (removing a middle item must not recycle its id). */
export function nextId(items: DraftItem[]): string {
  const taken = new Set(items.map((d) => d.id.trim()))
  let n = items.length + 1
  while (taken.has(`I-${n}`)) n += 1
  return `I-${n}`
}

const emptyItem = (id: string, cat: FactoryCatalogue | undefined): DraftItem => ({
  id,
  title: '',
  capability_class: cat?.classes[0]?.capability_class ?? 'bug.fix',
  size_estimate: 'XS',
  kind: cat?.kinds[0] ?? 'code',
  level: cat?.levels[0] ?? 'L1',
  description: '',
  depends_on: '',
  facts: {},
})

/** J-FAC-15 — the active backlog's item as a draft, so one item can be edited and the rest kept. */
/**
 * The active backlog with the drafted replacement item in it: the predecessor it supersedes is
 * replaced in place (so the list reads as the revision it is), and an item the backlog does
 * not hold is appended. With no backlog to revise, the draft alone is the backlog.
 *
 * A successor takes its predecessor's place in the GRAPH as well as in the list: an item that
 * depended on the item being replaced is re-pointed at the replacement. Leaving it pointing at
 * an id the revised backlog no longer holds is not a smaller change — the freeze is refused
 * 422 (`item I-2 depends on unknown item 'I-1'`, src/crb/factory/backlog.py `_check_items`)
 * naming an item the operator never touched. Nothing is written: this is the form's starting
 * point, and every dependency stays editable in it.
 */
export function withEvolution(from: FactoryBacklog | null, pre: FactoryEvolutionPrefill): FactoryBacklog {
  const drafted: FactoryBacklogItem = {
    id: pre.id,
    title: pre.title,
    kind: pre.kind,
    capability_class: pre.capability_class,
    size: pre.size_estimate,
    level: pre.level,
    depends_on: [...pre.depends_on],
    structural_facts: [...pre.structural_facts],
    has_authored_test: false,
    description: pre.description,
  }
  const base: FactoryBacklog = from ?? { repo: '', hash: '', frozen_at: null, items: [] }
  const at = base.items.findIndex((i) => i.id === pre.supersedes || i.id === pre.id)
  const replaced = at >= 0 ? base.items[at] : undefined
  const placed = replaced ? base.items.map((i, j) => (j === at ? drafted : i)) : [...base.items, drafted]
  // Only a REPLACEMENT under a new id moves the edges: revising an item in place (same id)
  // and appending one the backlog does not hold leave every dependency exactly as it was.
  const stale = replaced && replaced.id !== drafted.id ? replaced.id : ''
  const items = stale
    ? placed.map((i) => (i.id !== drafted.id && i.depends_on.includes(stale) ? { ...i, depends_on: i.depends_on.map((d) => (d === stale ? drafted.id : d)) } : i))
    : placed
  return { ...base, items }
}

function draftFrom(i: FactoryBacklogItem): DraftItem {
  const facts: Record<string, string> = {}
  for (const line of i.structural_facts) {
    const at = line.indexOf(':')
    if (at > 0) facts[line.slice(0, at).trim()] = line.slice(at + 1).trim()
  }
  return {
    id: i.id,
    title: i.title,
    capability_class: i.capability_class,
    size_estimate: i.size,
    kind: i.kind,
    level: i.level,
    description: i.description ?? '',
    depends_on: i.depends_on.join(', '),
    facts,
  }
}

/** The request body the form produces: `structural_facts` are `slot: text` lines (readiness.py). */
export function draftToBody(items: DraftItem[]): {
  items: Array<Record<string, unknown>>
} {
  return {
    items: items.map((d) => ({
      id: d.id.trim(),
      title: d.title.trim(),
      kind: d.kind,
      level: d.level,
      description: d.description.trim(),
      capability_class: d.capability_class,
      size_estimate: d.size_estimate,
      structural_facts: Object.entries(d.facts)
        .filter(([, v]) => v.trim().length > 0)
        .map(([k, v]) => `${k}: ${v.trim()}`),
      depends_on: d.depends_on
        .split(',')
        .map((x) => x.trim())
        .filter(Boolean),
    })),
  }
}

/**
 * F24 — the backlog as a person writes it: one card per item with the class's structural
 * questions from the readiness catalogue as the fields (an unanswered structural slot is
 * exactly the gap the run will stop on), plus an "advanced" JSON view for a prepared file.
 * `from` prefills the form from the active backlog (J-FAC-15: revise one item, keep the rest).
 */
function RegisterBacklogDialog({ open, repo, from, onClose }: { open: boolean; repo: string; from: FactoryBacklog | null; onClose: () => void }) {
  const register = useRegisterBacklog()
  const catalogue = useFactoryCatalogue(open)
  const [mode, setMode] = useState<'form' | 'json'>('form')
  const [items, setItems] = useState<DraftItem[]>(() => (from && from.items.length > 0 ? from.items.map(draftFrom) : [emptyItem('I-1', undefined)]))
  const [text, setText] = useState('{\n  "items": [\n    {"id": "I-1", "title": "…", "capability_class": "bug.fix", "size_estimate": "XS", "structural_facts": []}\n  ]\n}')
  const [parseError, setParseError] = useState('')
  const cat = catalogue.data
  const slotsFor = (cls: string) => cat?.classes.find((c) => c.capability_class === cls)?.slots ?? []
  const update = (i: number, patch: Partial<DraftItem>) => setItems((xs) => xs.map((x, j) => (j === i ? { ...x, ...patch } : x)))
  const setFact = (i: number, slot: string, value: string) => setItems((xs) => xs.map((x, j) => (j === i ? { ...x, facts: { ...x.facts, [slot]: value } } : x)))
  // the form can only ask the class's questions once the catalogue answered: until then a
  // freeze would record gaps the operator never saw (JSON mode stays the explicit fallback)
  const formValid = catalogue.data !== undefined && items.every((d) => d.id.trim() && d.title.trim())

  const submit = () => {
    let body: unknown
    if (mode === 'json') {
      try {
        body = JSON.parse(text)
        setParseError('')
      } catch (e) {
        setParseError(`not JSON: ${(e as Error).message}`)
        return
      }
    } else {
      body = draftToBody(items)
    }
    register.mutate({ repo, body }, { onSuccess: onClose })
  }
  return (
    <Dialog
      open={open}
      title={from ? 'Freeze a revised backlog' : 'Freeze a backlog'}
      onClose={onClose}
      width="lg"
      footer={
        <>
          <Button variant="ghost" onClick={() => setMode(mode === 'form' ? 'json' : 'form')} hint="button.factory.freeze_mode">
            {mode === 'form' ? 'Advanced: paste JSON instead' : 'Back to the form'}
          </Button>
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="filled" disabled={register.isPending || (mode === 'form' && !formValid)} onClick={submit} hint="button.factory.freeze_submit">
            Freeze {mode === 'form' ? `${items.length} item${items.length === 1 ? '' : 's'}` : ''}
          </Button>
        </>
      }
    >
      <p className="mt-0 text-sm text-on-surface-body">
        The items are validated, hashed and recorded as the first event of the chain. Each class asks for the facts a good test needs; a <strong>structural</strong> fact left empty is the gap the run will stop on until an approver signs it.
        Refused with 409 while a factory run is active.
        {from ? ' This form starts from the active backlog: change what you need and keep the rest; the freeze records a new hash and the old chain stays.' : ''}
      </p>
      {mode === 'json' ? (
        <>
          <TextArea
            label="Backlog JSON"
            hint="field.factory.backlog_json"
            value={text}
            onChange={(e) => setText(e.target.value)}
            rows={12}
            className="font-mono text-xs"
            error={parseError || undefined}
            description={
              <>
                Shape as the API's Factory section: items[] with id, title, capability_class, size_estimate, structural_facts; optional authored tests. See{' '}
                <DocLink to="ONBOARDING-A-REPO#step-8--forward-mode-when-a-cell-is-trusted">Forward mode</DocLink>.
              </>
            }
          />
        </>
      ) : (
        <div className="space-y-4" data-testid="backlog-form">
          {catalogue.isPending && <p className="m-0 text-sm text-on-surface-muted">Loading the questions each class asks…</p>}
          {catalogue.isError && <ErrorState compact error={catalogue.error} onRetry={() => void catalogue.refetch()} title="The catalogue did not load — the form cannot ask the right questions; retry, or paste JSON" />}
          {items.map((d, i) => {
            const slots = slotsFor(d.capability_class)
            return (
              <fieldset key={i} className="m-0 rounded-[var(--radius-control)] border border-border p-3" data-testid={`backlog-item-${i}`}>
                <legend className="px-1 text-xs font-semibold text-on-surface-muted">Item {i + 1}</legend>
                <div className="grid gap-3 sm:grid-cols-[10ch_1fr]">
                  <TextField label="Id" required value={d.id} onChange={(e) => update(i, { id: e.target.value })} description="letters, digits, . _ -" hint="field.factory.item_id" />
                  <TextField label="Title" required value={d.title} onChange={(e) => update(i, { title: e.target.value })} hint="field.factory.item_title" />
                </div>
                <div className="mt-3 grid gap-3 sm:grid-cols-4">
                  <SelectField label="Class" hint="field.factory.item_class" value={d.capability_class} onChange={(e) => update(i, { capability_class: e.target.value, facts: {} })}>
                    {(cat?.classes ?? [{ capability_class: d.capability_class, slots: [] }]).map((c) => (
                      <option key={c.capability_class} value={c.capability_class}>
                        {c.capability_class}
                      </option>
                    ))}
                  </SelectField>
                  <SelectField label="Size" hint="field.factory.item_size" value={d.size_estimate} onChange={(e) => update(i, { size_estimate: e.target.value })}>
                    {(cat?.sizes ?? ['XS', 'S', 'M', 'L', 'XL']).map((sz) => (
                      <option key={sz} value={sz}>
                        {sz}
                      </option>
                    ))}
                  </SelectField>
                  <SelectField label="Kind" hint="field.factory.item_kind" value={d.kind} onChange={(e) => update(i, { kind: e.target.value })}>
                    {(cat?.kinds ?? ['code']).map((k) => (
                      <option key={k} value={k}>
                        {k}
                      </option>
                    ))}
                  </SelectField>
                  <SelectField label="Level" hint="field.factory.item_level" value={d.level} onChange={(e) => update(i, { level: e.target.value })}>
                    {(cat?.levels ?? ['L1']).map((l) => (
                      <option key={l} value={l}>
                        {l}
                      </option>
                    ))}
                  </SelectField>
                </div>
                <div className="mt-3">
                  <TextArea label="Description" hint="field.factory.item_description" rows={2} value={d.description} onChange={(e) => update(i, { description: e.target.value })} description="What and why, as the issue would say it. Never a diff." />
                </div>
                {slots.length > 0 && (
                  <div className="mt-3 space-y-2" data-testid={`backlog-item-${i}-facts`}>
                    <p className="m-0 text-xs font-semibold text-on-surface-muted">What a good test for {d.capability_class} needs to know</p>
                    {slots.map((sl) => (
                      <TextField
                        key={sl.name}
                        hint="field.factory.item_fact"
                        label={`${sl.question}${sl.kind === 'structural' ? '' : ' (value — optional)'}`}
                        value={d.facts[sl.name] ?? ''}
                        onChange={(e) => setFact(i, sl.name, e.target.value)}
                        description={sl.kind === 'structural' ? `structural · ${sl.name} — empty = a gap the run stops on` : `value · ${sl.name} — routes, never blocks`}
                      />
                    ))}
                  </div>
                )}
                {slots.length === 0 && cat && <p className="mt-3 text-xs text-on-surface-muted">{d.capability_class} declares no structural facts: the run assesses readiness from the description alone.</p>}
                <div className="mt-3 flex flex-wrap items-end gap-3">
                  <TextField label="Depends on" hint="field.factory.item_depends" value={d.depends_on} onChange={(e) => update(i, { depends_on: e.target.value })} description="item ids, comma-separated" className="min-w-[20ch]" />
                  {items.length > 1 && (
                    <Button size="sm" variant="ghost" onClick={() => setItems((xs) => xs.filter((_, j) => j !== i))} hint="button.factory.item_remove">
                      Remove item
                    </Button>
                  )}
                </div>
              </fieldset>
            )
          })}
          <Button size="sm" onClick={() => setItems((xs) => [...xs, emptyItem(nextId(xs), cat)])} hint="button.factory.item_add">
            Add another item
          </Button>
        </div>
      )}
      {register.isError && <ErrorState compact error={register.error} />}
    </Dialog>
  )
}

export default FactoryPage
