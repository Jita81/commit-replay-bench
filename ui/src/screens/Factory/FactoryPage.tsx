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
 * Touch when:   a step or a stop status is added to the loop (add it to `stepsFor` and the
 *               loop's docstring); a field is added to `FactoryTaskOut`.
 */

import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router'
import { useCreateRun, useFactoryBacklog, useFactoryCatalogue, useFactoryTasks, useRegisterBacklog, useSignGap } from '../../api/hooks'
import type { FactoryCatalogue, FactoryTask } from '../../api/types'
import { Button, LinkButton } from '../../components/Button'
import { Card } from '../../components/Card'
import { Dialog } from '../../components/Dialog'
import { EmptyState } from '../../components/EmptyState'
import { ErrorState } from '../../components/ErrorState'
import { SelectField, TextArea, TextField } from '../../components/Field'
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
    ? // `delivery.updated` = a rework re-pointed the branch on the SAME pull request (DL-045)
      { id: 'delivery', title: 'Delivery', status: 'done', detail: t.last_event === 'delivery.updated' ? 'pull request updated by a rework' : 'branch + pull request opened' }
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
      : t.status === 'oracle_needs_strengthening'
        ? // DL-045 rule 3: the reviewer asked for a stronger TEST and no changed oracle could be
          // had (no test author, or the same bytes back) — the loop refused to rebuild against
          // the same oracle and routed the item to a human; the chain's reason says which
          { id: 'outcome', title: 'Outcome', status: 'failed', detail: `the reviewer found the oracle weak and no stronger test could be had — the loop did not rebuild against the same one: strengthen the test and register a superseding item${t.outcome_reason ? ` (${t.outcome_reason})` : ''}` }
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
                    {tasks.data && (
                      <span className="text-xs text-on-surface-muted" data-testid="factory-deliverable-count">
                        {deliverableCount(tasks.data)} of {tasks.data.length} items sit in a cell that routes <code>deliver</code> today; the rest cannot be delivered under the current route (readiness, a dependency or the RED proof may stop them earlier)
                      </span>
                    )}
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
        <CellRoutePill t={t} />
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

/** How many items sit in a cell the map routes `deliver` — what a run could actually deliver. */
export function deliverableCount(tasks: FactoryTask[]): number {
  return tasks.filter((t) => t.cell_route?.deliverable).length
}

/**
 * F28 — the item's cell route BEFORE the run, from the same signed map the delivery gate
 * reads: "routes deliver" (green), "routes calibrate — delivery will be withheld" (amber),
 * or "cell not measured — delivery will be withheld" (grey). Never a guess: `route: ''`
 * means nobody has measured the cell.
 */
function CellRoutePill({ t }: { t: FactoryTask }) {
  const r = t.cell_route
  if (!r || !r.route) {
    return (
      <Pill tone="muted" glyph="○" size="xs" label={`Cell ${t.capability_class} × ${t.size} is not measured on this repository: delivery would be withheld`} data-testid={`cell-route-${t.id}`}>
        cell not measured · delivery withheld
      </Pill>
    )
  }
  // every number carries its n, its interval and its apparatus
  const prov = `n=${r.n} · ${pct(r.point)} [${pct(r.ci_low)}, ${pct(r.ci_high)}] · app ${r.apparatus_versions.join(', ') || '—'}`
  if (r.deliverable) {
    return (
      <Pill tone="green" glyph="✓" size="xs" label={`Cell ${t.capability_class} × ${t.size} routes deliver — ${prov}: a clean build may open a pull request`} data-testid={`cell-route-${t.id}`}>
        routes deliver · {prov}
      </Pill>
    )
  }
  return (
    <Pill tone="amber" glyph="⊘" size="xs" label={`Cell ${t.capability_class} × ${t.size} routes ${r.route} (${r.reason_code}) — ${prov}: delivery would be withheld — ${r.reason}`} data-testid={`cell-route-${t.id}`}>
      routes {r.route} · {r.reason_code} · {prov} · delivery withheld
    </Pill>
  )
}

function pct(x: number): string {
  return `${(x * 100).toFixed(0)}%`
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

/** The request body the form produces: `structural_facts` are `slot: text` lines (readiness.py). */
export function draftToBody(items: DraftItem[]): { items: Array<Record<string, unknown>> } {
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
 */
function RegisterBacklogDialog({ open, repo, onClose }: { open: boolean; repo: string; onClose: () => void }) {
  const register = useRegisterBacklog()
  const catalogue = useFactoryCatalogue(open)
  const [mode, setMode] = useState<'form' | 'json'>('form')
  const [items, setItems] = useState<DraftItem[]>([emptyItem('I-1', undefined)])
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
      title="Freeze a backlog"
      onClose={onClose}
      width="lg"
      footer={
        <>
          <Button variant="ghost" onClick={() => setMode(mode === 'form' ? 'json' : 'form')}>
            {mode === 'form' ? 'Advanced: paste JSON instead' : 'Back to the form'}
          </Button>
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="filled" disabled={register.isPending || (mode === 'form' && !formValid)} onClick={submit}>
            Freeze {mode === 'form' ? `${items.length} item${items.length === 1 ? '' : 's'}` : ''}
          </Button>
        </>
      }
    >
      <p className="mt-0 text-sm text-on-surface-body">
        The items are validated, hashed and recorded as the first event of the chain. Each class asks for the facts a good test needs; a <strong>structural</strong> fact left empty is the gap the run will stop on until an approver signs it. Refused with 409 while a factory run is active.
      </p>
      {mode === 'json' ? (
        <>
          <TextArea label="Backlog JSON" value={text} onChange={(e) => setText(e.target.value)} rows={12} className="font-mono text-xs" error={parseError || undefined} hint={'Shape as docs/API.md "Factory": items[] with id, title, capability_class, size_estimate, structural_facts; optional authored tests.'} />
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
                  <TextField label="Id" required value={d.id} onChange={(e) => update(i, { id: e.target.value })} hint="letters, digits, . _ -" />
                  <TextField label="Title" required value={d.title} onChange={(e) => update(i, { title: e.target.value })} />
                </div>
                <div className="mt-3 grid gap-3 sm:grid-cols-4">
                  <SelectField label="Class" value={d.capability_class} onChange={(e) => update(i, { capability_class: e.target.value, facts: {} })}>
                    {(cat?.classes ?? [{ capability_class: d.capability_class, slots: [] }]).map((c) => (
                      <option key={c.capability_class} value={c.capability_class}>
                        {c.capability_class}
                      </option>
                    ))}
                  </SelectField>
                  <SelectField label="Size" value={d.size_estimate} onChange={(e) => update(i, { size_estimate: e.target.value })}>
                    {(cat?.sizes ?? ['XS', 'S', 'M', 'L', 'XL']).map((sz) => (
                      <option key={sz} value={sz}>
                        {sz}
                      </option>
                    ))}
                  </SelectField>
                  <SelectField label="Kind" value={d.kind} onChange={(e) => update(i, { kind: e.target.value })}>
                    {(cat?.kinds ?? ['code']).map((k) => (
                      <option key={k} value={k}>
                        {k}
                      </option>
                    ))}
                  </SelectField>
                  <SelectField label="Level" value={d.level} onChange={(e) => update(i, { level: e.target.value })}>
                    {(cat?.levels ?? ['L1']).map((l) => (
                      <option key={l} value={l}>
                        {l}
                      </option>
                    ))}
                  </SelectField>
                </div>
                <div className="mt-3">
                  <TextArea label="Description" rows={2} value={d.description} onChange={(e) => update(i, { description: e.target.value })} hint="What and why, as the issue would say it. Never a diff." />
                </div>
                {slots.length > 0 && (
                  <div className="mt-3 space-y-2" data-testid={`backlog-item-${i}-facts`}>
                    <p className="m-0 text-xs font-semibold text-on-surface-muted">What a good test for {d.capability_class} needs to know</p>
                    {slots.map((sl) => (
                      <TextField
                        key={sl.name}
                        label={`${sl.question}${sl.kind === 'structural' ? '' : ' (value — optional)'}`}
                        value={d.facts[sl.name] ?? ''}
                        onChange={(e) => setFact(i, sl.name, e.target.value)}
                        hint={sl.kind === 'structural' ? `structural · ${sl.name} — empty = a gap the run stops on` : `value · ${sl.name} — routes, never blocks`}
                      />
                    ))}
                  </div>
                )}
                {slots.length === 0 && cat && (
                  <p className="mt-3 text-xs text-on-surface-muted">
                    {d.capability_class} declares no structural facts: the run assesses readiness from the description alone.
                  </p>
                )}
                <div className="mt-3 flex flex-wrap items-end gap-3">
                  <TextField label="Depends on" value={d.depends_on} onChange={(e) => update(i, { depends_on: e.target.value })} hint="item ids, comma-separated" className="min-w-[20ch]" />
                  {items.length > 1 && (
                    <Button size="sm" variant="ghost" onClick={() => setItems((xs) => xs.filter((_, j) => j !== i))}>
                      Remove item
                    </Button>
                  )}
                </div>
              </fieldset>
            )
          })}
          <Button size="sm" onClick={() => setItems((xs) => [...xs, emptyItem(nextId(xs), cat)])}>
            Add another item
          </Button>
        </div>
      )}
      {register.isError && <ErrorState compact error={register.error} />}
    </Dialog>
  )
}

export default FactoryPage
