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
 *               item is at, why it is there (the gap slots, the route, the verdict), and what
 *               the route gate withheld. Every act goes through the API under its role; the
 *               chain (`/factory/{repo}/evidence`) is the record, and this screen renders the
 *               folded view of it (`task_views`).
 * How:          `useFactoryBacklog` + `useFactoryTasks` → `stepsFor(task)` → `<StepList>`;
 *               `useSignGap` (POST signoff-gap), `useRegisterBacklog` (POST backlog, JSON in
 *               a dialog), `useCreateRun` (kind `factory`, `deliver` toggle; `deliver_override`
 *               for an approver). A 404 = no backlog registered: the instruction, not an error.
 *               `?item=` scrolls to and highlights one item (the Decisions inbox links here).
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0003-one-routing-rule.md (amendment 2026-09-16: the route gate)
 * Works with:   ui/src/api/hooks.ts (`useFactoryBacklog`, `useFactoryTasks`, `useSignGap`,
 *               `useRegisterBacklog`, `useCreateRun`), ui/src/api/types.ts (`FactoryTask`),
 *               src/crb/server/routes/factory.py, src/crb/server/factory_state.py
 *               (`task_views`), src/crb/factory/loop.py (the process itself),
 *               ui/src/screens/Decisions/decisions.ts (the inbox rows that link here),
 *               docs/API.md "Factory"
 * Tested by:    ui/src/screens/Factory/FactoryPage.test.tsx
 * Touch when:   a step is added to the loop (add it to `stepsFor` and the loop's docstring);
 *               a field is added to `FactoryTaskOut`.
 */

import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router'
import { useCreateRun, useFactoryBacklog, useFactoryTasks, useRegisterBacklog, useSignGap } from '../../api/hooks'
import type { FactoryTask } from '../../api/types'
import { Button, LinkButton } from '../../components/Button'
import { Card } from '../../components/Card'
import { Dialog } from '../../components/Dialog'
import { EmptyState } from '../../components/EmptyState'
import { ErrorState } from '../../components/ErrorState'
import { TextArea, TextField } from '../../components/Field'
import { PageHeader } from '../../components/PageHeader'
import { Pill } from '../../components/Pill'
import { RepoPicker, useRepoParam } from '../../components/RepoPicker'
import { useAuth } from '../../lib/auth'
import { fmtDate, fmtInt, shortId } from '../../lib/format'
import type { Tone } from '../../lib/verdict'

type StepStatus = 'done' | 'current' | 'todo' | 'failed' | 'skipped'

interface Step {
  id: 'readiness' | 'red' | 'build' | 'delivery' | 'review' | 'outcome'
  title: string
  status: StepStatus
  detail: string
}

const STEP_DISPLAY: Record<StepStatus, { tone: Tone; glyph: string; label: string }> = {
  done: { tone: 'green', glyph: '✓', label: 'done' },
  current: { tone: 'blue', glyph: '◐', label: 'here' },
  todo: { tone: 'muted', glyph: '○', label: 'not yet' },
  failed: { tone: 'red', glyph: '✕', label: 'failed' },
  skipped: { tone: 'muted', glyph: '–', label: 'skipped' },
}

/** The six steps of the loop for one item, from the folded task view. */
export function stepsFor(t: FactoryTask): Step[] {
  const gaps = t.dor_gaps.length
  const readiness: Step =
    gaps > 0
      ? { id: 'readiness', title: 'Readiness', status: 'current', detail: `${gaps} structural gap${gaps === 1 ? '' : 's'} unsigned: ${t.dor_gaps.join(', ')}` }
      : t.route_hint === 'human' && t.status === 'routed_human'
        ? { id: 'readiness', title: 'Readiness', status: 'failed', detail: 'routed to a human — the loop stops here' }
        : t.route_hint === ''
          ? // no route event yet: the factory run has not assessed this item
            { id: 'readiness', title: 'Readiness', status: 'current', detail: 'not assessed — a factory run assesses readiness first' }
          : { id: 'readiness', title: 'Readiness', status: 'done', detail: `route ${t.route_hint}` }
  const afterReadiness = readiness.status === 'done'
  const red: Step =
    t.red_proof === true
      ? { id: 'red', title: 'RED proof', status: 'done', detail: 'the authored test fails before the change' }
      : t.red_proof === false
        ? { id: 'red', title: 'RED proof', status: 'failed', detail: 'the test did not fail at the parent — refused' }
        : { id: 'red', title: 'RED proof', status: afterReadiness ? 'current' : 'todo', detail: 'not run' }
  const buildDone = t.build_status === 'clean'
  const build: Step = buildDone
    ? { id: 'build', title: 'Build under the belts', status: 'done', detail: 'clean' }
    : t.build_status === 'not_built' || t.build_status === 'not_started' || !t.build_status
      ? // the API folds "no build event" as `not_built` (factory_state.task_views)
        { id: 'build', title: 'Build under the belts', status: red.status === 'done' ? 'current' : 'todo', detail: 'not started' }
      : { id: 'build', title: 'Build under the belts', status: 'failed', detail: t.build_status.replace(/_/g, ' ') }
  const withheld = buildDone && !t.pr_url && t.last_event === 'delivery.refused'
  const delivery: Step = t.pr_url
    ? { id: 'delivery', title: 'Delivery', status: 'done', detail: 'branch + pull request opened' }
    : withheld
      ? { id: 'delivery', title: 'Delivery', status: 'skipped', detail: 'withheld — the route gate or delivery opt-in (see the chain)' }
      : { id: 'delivery', title: 'Delivery', status: buildDone ? 'current' : 'todo', detail: buildDone ? 'pending' : 'not yet' }
  const review: Step = t.review_verdict
    ? {
        id: 'review',
        title: 'Independent review',
        status: t.review_verdict === 'accept' ? 'done' : t.review_verdict === 'reject' ? 'failed' : 'current',
        detail: t.review_verdict.replace(/_/g, ' '),
      }
    : { id: 'review', title: 'Independent review', status: buildDone ? 'current' : 'todo', detail: 'not yet' }
  const outcome: Step =
    t.status === 'accepted'
      ? { id: 'outcome', title: 'Outcome', status: 'done', detail: 'accepted' }
      : ['rejected', 'rework_exhausted', 'disqualified', 'delivery_failed', 'error', 'not_clean'].includes(t.status)
        ? { id: 'outcome', title: 'Outcome', status: 'failed', detail: t.status.replace(/_/g, ' ') }
        : { id: 'outcome', title: 'Outcome', status: 'todo', detail: t.status.replace(/_/g, ' ') }
  return [readiness, red, build, delivery, review, outcome]
}

const noBacklog = (e: unknown) => e !== null && typeof e === 'object' && 'status' in e && (e as { status: number }).status === 404

export function FactoryPage() {
  const [repo, setRepo] = useRepoParam()
  const [params] = useSearchParams()
  const focus = params.get('item') ?? ''
  const { can } = useAuth()
  const backlog = useFactoryBacklog(repo)
  const tasks = useFactoryTasks(repo)
  const run = useCreateRun()
  const [registerOpen, setRegisterOpen] = useState(false)
  const [deliver, setDeliver] = useState(false)
  const [override, setOverride] = useState(false)

  useEffect(() => {
    if (focus) document.getElementById(`item-${focus}`)?.scrollIntoView?.({ block: 'center' })
  }, [focus, tasks.data])

  const startRun = () =>
    run.mutate({ repo, kind: 'factory', deliver, ...(deliver && override ? { deliver_override: true } : {}) })

  return (
    <>
      <PageHeader
        eyebrow="Journey · 4 of 4"
        title="Factory"
        purpose="New work under the same governance as replay: a frozen backlog, structural gaps signed by an approver, a RED proof before any build, a build under the belts, a branch and pull request only where the map routes deliver, an independent review — every step on the evidence chain."
        actions={<RepoPicker value={repo} onChange={setRepo} />}
      />
      {!repo && <EmptyState title="Choose a repository" reason="The factory works one repository at a time." action={<LinkButton to="/connect">Connect one</LinkButton>} />}
      {repo && (
        <>
          <Card
            title="Backlog"
            eyebrow="frozen · hashed · the first event of the chain"
            actions={
              can('operator') ? (
                <div className="flex flex-wrap gap-2">
                  <Button size="sm" onClick={() => setRegisterOpen(true)}>
                    Freeze a backlog…
                  </Button>
                </div>
              ) : undefined
            }
          >
            {backlog.isPending && <p className="text-sm text-on-surface-muted">Loading…</p>}
            {backlog.isError &&
              (noBacklog(backlog.error) ? (
                <EmptyState
                  glyph="⚙"
                  title="No backlog registered for this repository"
                  reason="Freeze one: the items are validated, hashed and recorded as the first event of the evidence chain; a factory run then works them in dependency order."
                  action={can('operator') ? <Button variant="filled" onClick={() => setRegisterOpen(true)}>Freeze a backlog…</Button> : undefined}
                  data-testid="factory-no-backlog"
                />
              ) : (
                <ErrorState error={backlog.error} onRetry={() => void backlog.refetch()} />
              ))}
            {backlog.data && (
              <div className="space-y-3">
                <div className="flex flex-wrap items-center gap-2 text-sm">
                  <Pill tone={backlog.data.frozen_at ? 'primary' : 'amber'} glyph={backlog.data.frozen_at ? '❄' : '○'} size="xs" label={backlog.data.frozen_at ? `Frozen at ${fmtDate(backlog.data.frozen_at)}` : 'Not frozen'}>
                    {backlog.data.frozen_at ? 'frozen' : 'not frozen'}
                  </Pill>
                  <span className="font-mono text-xs" title={backlog.data.hash}>
                    hash {shortId(backlog.data.hash, 16)}
                  </span>
                  <span className="text-xs text-on-surface-muted">{fmtInt(backlog.data.items.length)} items</span>
                </div>
                {can('operator') && (
                  <div className="flex flex-wrap items-center gap-3 rounded-[var(--radius-control)] border border-border p-3 text-sm" data-testid="factory-run-controls">
                    <label className="flex items-center gap-2">
                      <input type="checkbox" checked={deliver} onChange={(e) => setDeliver(e.target.checked)} />
                      Open pull requests where the map routes <code>deliver</code>
                    </label>
                    {deliver && can('approver') && (
                      <label className="flex items-center gap-2" title="Recorded on the chain as your override of the route gate">
                        <input type="checkbox" checked={override} onChange={(e) => setOverride(e.target.checked)} />
                        Override the route gate (approver — recorded)
                      </label>
                    )}
                    <Button variant="filled" size="sm" disabled={run.isPending} onClick={startRun}>
                      Run the factory
                    </Button>
                    {run.data && (
                      <LinkButton size="sm" to={`/runs/${run.data.id}`}>
                        run {shortId(run.data.id)}
                      </LinkButton>
                    )}
                    <span className="text-xs text-on-surface-muted">spends model budget</span>
                  </div>
                )}
                {run.isError && <ErrorState compact error={run.error} />}
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
                  <ItemRow key={t.id} repo={repo} task={t} focused={t.id === focus} canSign={can('approver')} />
                ))}
              </ul>
            )}
          </Card>
        </>
      )}
      <RegisterBacklogDialog open={registerOpen} repo={repo} onClose={() => setRegisterOpen(false)} />
    </>
  )
}

function ItemRow({ repo, task: t, focused, canSign }: { repo: string; task: FactoryTask; focused: boolean; canSign: boolean }) {
  const steps = stepsFor(t)
  const sign = useSignGap()
  const [slot, setSlot] = useState(t.dor_gaps[0] ?? '')
  const [answer, setAnswer] = useState('')
  return (
    <li id={`item-${t.id}`} className={`py-3 ${focused ? 'rounded-[var(--radius-control)] bg-primary-container/30 px-2' : ''}`} data-testid={`factory-item-${t.id}`}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-xs text-on-surface-muted">{t.id}</span>
        <span className="font-semibold">{t.title}</span>
        <span className="font-mono text-xs text-on-surface-muted">
          {t.capability_class} · {t.size} · {t.kind}
        </span>
        <span className="ml-auto font-mono text-xs" title="item status">
          {t.status} · {t.route_hint}
        </span>
        {t.pr_url && (
          <a href={t.pr_url} className="text-xs" target="_blank" rel="noreferrer">
            PR ↗
          </a>
        )}
      </div>
      <ol className="m-0 mt-2 grid list-none gap-2 p-0 sm:grid-cols-6" aria-label={`Steps for ${t.id}`}>
        {steps.map((s) => {
          const d = STEP_DISPLAY[s.status]
          return (
            <li key={s.id} className="min-w-0 rounded-[var(--radius-control)] border border-border p-2" data-testid={`step-${t.id}-${s.id}`}>
              <div className="flex flex-wrap items-center gap-1.5">
                <Pill tone={d.tone} glyph={d.glyph} size="xs" label={`${s.title}: ${d.label}`}>
                  {d.label}
                </Pill>
                <span className="text-xs font-semibold leading-tight">{s.title}</span>
              </div>
              <div className="mt-1 text-[11px] leading-snug text-on-surface-muted">{s.detail}</div>
            </li>
          )
        })}
      </ol>
      {t.dor_gaps.length > 0 && canSign && (
        <form
          className="mt-2 flex flex-wrap items-end gap-2 rounded-[var(--radius-control)] border border-border p-2"
          onSubmit={(e) => {
            e.preventDefault()
            if (slot && answer.trim()) sign.mutate({ repo, itemId: t.id, slot, answer: answer.trim() }, { onSuccess: () => setAnswer('') })
          }}
          aria-label={`Sign a structural gap for ${t.id}`}
        >
          <label className="text-xs">
            Gap
            <select className="ml-1 rounded border border-border bg-surface px-1 py-1 text-xs" value={slot} onChange={(e) => setSlot(e.target.value)}>
              {t.dor_gaps.map((g) => (
                <option key={g} value={g}>
                  {g}
                </option>
              ))}
            </select>
          </label>
          <TextField label="Your answer (the structural fact)" value={answer} onChange={(e) => setAnswer(e.target.value)} className="min-w-[24ch] flex-1" required />
          <Button type="submit" size="sm" variant="filled" disabled={sign.isPending || !answer.trim()}>
            Sign the gap
          </Button>
          {sign.isError && <ErrorState compact error={sign.error} />}
          {sign.isSuccess && <span className="text-xs text-status-green">signed — on the chain</span>}
        </form>
      )}
      {t.dor_gaps.length > 0 && !canSign && <p className="m-0 mt-2 text-xs text-on-surface-muted">An approver signs the structural gap(s); a value gap is never signed — it routes test-first.</p>}
    </li>
  )
}

function RegisterBacklogDialog({ open, repo, onClose }: { open: boolean; repo: string; onClose: () => void }) {
  const register = useRegisterBacklog()
  const [text, setText] = useState('{\n  "items": [\n    {"id": "I-1", "title": "…", "capability_class": "bug.fix", "size_estimate": "XS", "structural_facts": []}\n  ]\n}')
  const [parseError, setParseError] = useState('')
  const submit = () => {
    let body: unknown
    try {
      body = JSON.parse(text)
      setParseError('')
    } catch (e) {
      setParseError(`not JSON: ${(e as Error).message}`)
      return
    }
    register.mutate({ repo, body }, { onSuccess: onClose })
  }
  return (
    <Dialog
      open={open}
      title="Freeze a backlog"
      onClose={onClose}
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="filled" disabled={register.isPending} onClick={submit}>
            Freeze
          </Button>
        </>
      }
    >
      <p className="mt-0 text-sm text-on-surface-body">
        The items are validated, hashed and recorded as the first event of the chain. Shape as <code>docs/API.md</code> "Factory": <code>items[]</code> with <code>id</code>, <code>title</code>, <code>capability_class</code>, <code>size_estimate</code>, <code>structural_facts</code>; optional <code>authored</code> tests. Refused with 409 while a factory run is active.
      </p>
      <TextArea label="Backlog JSON" value={text} onChange={(e) => setText(e.target.value)} rows={12} className="font-mono text-xs" error={parseError || undefined} />
      {register.isError && <ErrorState compact error={register.error} />}
    </Dialog>
  )
}

export default FactoryPage
