/**
 * The prevention register on the Learn page — every bug class, the change that should remove
 * it, and whether the change worked (ADR-0020).
 *
 * Navigation
 * ----------
 * What it is:   `PreventionSection`: the first card of /learn, over `GET /learn/register`.
 * What it does: Shows the register's tiles (classes by status, closed and the share closed by
 *               process, the playbook in force against its caps, the switch with who threw it,
 *               when and why), one table row per class (class, seen, lever and level, applied,
 *               before → after with both n and the bar, status with qualifiers, next) and, per
 *               class, what changed, the evidence, the records and the filed items. An operator
 *               gets the controls — the switch (with a reason), Run the loop now, Revert (with a
 *               reason) and Register — and each reports what it wrote in a status line; a viewer
 *               sees every change and no control. `?class=` opens that class's details.
 * How:          `useLearnRegister` → tiles + `DataTable` + `<details>` per class; the four
 *               mutations invalidate the register; the server re-derives everything, so the
 *               card never computes a verdict of its own.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0020-a-bug-is-closed-by-prevention.md
 * Works with:   ui/src/screens/Learn/LearnPage.tsx (the page this card heads),
 *               ui/src/api/hooks.ts (`useLearnRegister` and the four mutations),
 *               ui/src/api/types.ts (`PreventionRegister`), src/crb/server/routes/prevention.py
 *               (the routes), ui/src/screens/Decisions/decisions.ts (the `prevention` rows that
 *               link here with `?class=`), docs/LEARNING-LOOP.md (§7, what the columns mean)
 * Tested by:    ui/src/screens/Learn/LearnPage.test.tsx, ui/src/help/hints-ratchet.test.tsx
 * Touch when:   the register gains a field (mirror it in ui/src/api/types.ts) or the loop gains
 *               an operator act (a control here, with its status line and its hint).
 */
import { useMemo, useState, type FormEvent } from 'react'
import { Link } from 'react-router'
import type { ApiError } from '../../api/client'
import { useLearnRegister, useLearnSwitch, useLearnTick, useRegisterPreventionItem, useRevertPreventionChange } from '../../api/hooks'
import type { PreventionEntry, PreventionProposal, PreventionStatus, PreventionSwitch } from '../../api/types'
import { Button } from '../../components/Button'
import { DataTable, type Column } from '../../components/DataTable'
import { EmptyState } from '../../components/EmptyState'
import { ErrorState } from '../../components/ErrorState'
import { SelectField, TextField } from '../../components/Field'
import { Pill } from '../../components/Pill'
import { StatTile } from '../../components/StatTile'
import { useAuth } from '../../lib/auth'
import { fmtDate, fmtInt, fmtPct, fmtUsd } from '../../lib/format'
import type { Tone } from '../../lib/verdict'

const STATUS_TONE: Record<PreventionStatus, Tone> = {
  open: 'muted',
  applied: 'blue',
  closed: 'green',
  retired: 'amber',
  escalated: 'violet',
}

const LEVEL_TONE: Record<string, Tone> = {
  construction: 'green',
  gate: 'blue',
  'mistake-proofing': 'violet',
  advisory: 'amber',
}

const enc = encodeURIComponent

/** Who a change was applied by: the loop on the switch-thrower's behalf, or a person. */
function appliedBy(e: PreventionEntry): string {
  const c = e.change
  if (!c) return '—'
  const who = c.applied_by === 'loop' ? `loop for ${c.on_behalf_of || 'the switch'}` : c.applied_by
  return `${fmtDate(c.applied_at)} by ${who}`
}

/** `k0/n0 → k1/n1`, or a dash when nothing is applied. */
function beforeAfter(e: PreventionEntry): string {
  const m = e.measurement
  if (!m) return '—'
  return `${m.before.k}/${m.before.n} → ${m.exposed.k}/${m.exposed.n}`
}

function StatusPills({ e }: { e: PreventionEntry }) {
  return (
    <span className="inline-flex flex-wrap items-center gap-1">
      <Pill tone={STATUS_TONE[e.status]} size="xs" hint="pill.learn.status" tabStop={false}>
        {e.status}
      </Pill>
      {e.qualifiers.map((q) => (
        <Pill key={q} tone="muted" size="xs" hint="pill.learn.qualifier" tabStop={false}>
          {q}
        </Pill>
      ))}
    </span>
  )
}

/** The switch: its state, who threw it and why; for an operator, the form that throws it. */
function SwitchControl({ repo, sw, operator }: { repo: string; sw: PreventionSwitch; operator: boolean }) {
  const set = useLearnSwitch()
  const [mode, setMode] = useState<PreventionSwitch['auto_apply']>(sw.auto_apply)
  const [reason, setReason] = useState('')
  const [done, setDone] = useState('')
  if (!operator) return null
  const submit = (ev: FormEvent) => {
    ev.preventDefault()
    setDone('')
    set.mutate(
      { repo, auto_apply: mode, reason: reason.trim() },
      {
        onSuccess: (r) => {
          setDone(`Switch set to ${r.switch.auto_apply} by ${r.record.actor}; record ${r.record.row_hash.slice(0, 12)}.`)
          setReason('')
        },
      },
    )
  }
  return (
    <form onSubmit={submit} className="grid gap-3 sm:grid-cols-[10rem_1fr_auto] sm:items-end" aria-label="Throw the learning switch">
      <SelectField label="Learning switch" hint="field.learn.switch_mode" value={mode} onChange={(ev) => setMode(ev.target.value as PreventionSwitch['auto_apply'])}>
        <option value="off">off</option>
        <option value="context">context</option>
        <option value="config">config</option>
      </SelectField>
      <TextField label="Reason" hint="field.learn.switch_reason" required value={reason} maxLength={500} onChange={(ev) => setReason(ev.target.value)} />
      <Button type="submit" variant="filled" hint="button.learn.switch" disabled={set.isPending || !reason.trim()}>
        Throw the switch
      </Button>
      {done && (
        <p role="status" className="m-0 text-sm text-status-green sm:col-span-3">
          {done}
        </p>
      )}
      {set.isError && (
        <p role="alert" className="m-0 text-sm text-status-red sm:col-span-3">
          {(set.error as ApiError).message}
        </p>
      )}
    </form>
  )
}

/** Revert one change in force (operator), with a reason; reports the record it wrote. */
function RevertControl({ repo, changeId }: { repo: string; changeId: string }) {
  const revert = useRevertPreventionChange()
  const [reason, setReason] = useState('')
  const [done, setDone] = useState('')
  const submit = (ev: FormEvent) => {
    ev.preventDefault()
    revert.mutate(
      { repo, change_id: changeId, reason: reason.trim() },
      { onSuccess: (r) => setDone(`Reverted ${r.lever_id} by ${r.record.actor}; the loop will not re-apply it. Record ${r.record.row_hash.slice(0, 12)}.`) },
    )
  }
  return (
    <form onSubmit={submit} className="grid gap-2 sm:grid-cols-[1fr_auto] sm:items-end" aria-label={`Revert change ${changeId}`}>
      <TextField label="Why revert" hint="field.learn.revert_reason" required value={reason} maxLength={500} onChange={(ev) => setReason(ev.target.value)} />
      <Button type="submit" variant="danger" hint="button.learn.revert" disabled={revert.isPending || !reason.trim()}>
        Revert
      </Button>
      {done && (
        <p role="status" className="m-0 text-sm text-status-green sm:col-span-2">
          {done}
        </p>
      )}
      {revert.isError && (
        <p role="alert" className="m-0 text-sm text-status-red sm:col-span-2">
          {(revert.error as ApiError).message}
        </p>
      )}
    </form>
  )
}

/** One filed item: what it is and, for an operator, Register (never for a product item). */
function ProposalRow({ repo, p, operator }: { repo: string; p: PreventionProposal; operator: boolean }) {
  const register = useRegisterPreventionItem()
  const [done, setDone] = useState('')
  const registered = p.registered ? String(p.registered['registered_id'] ?? p.item_id) : ''
  return (
    <li className="space-y-1">
      <p className="m-0 text-sm">
        <span className="font-mono text-xs">{p.item_id}</span> — {p.title}{' '}
        <Pill tone={LEVEL_TONE[p.level] ?? 'muted'} size="xs" hint="pill.learn.level" tabStop={false}>
          {p.level}
        </Pill>
      </p>
      <p className="m-0 text-xs text-on-surface-muted">{p.description}</p>
      {registered ? (
        <p className="m-0 text-xs">Registered as {registered} on the factory backlog.</p>
      ) : p.scope === 'product' ? (
        <p className="m-0 text-xs text-on-surface-muted">A change to this product’s own code: served for the maintainers, never put on this repository’s backlog.</p>
      ) : operator ? (
        <>
          <Button
            size="sm"
            hint="button.learn.register_item"
            disabled={register.isPending}
            onClick={() =>
              register.mutate(
                { repo, item_id: p.item_id },
                { onSuccess: (r) => setDone(`Registered ${r.registered_id} (${r.how}) by ${r.record.actor}; record ${r.record.row_hash.slice(0, 12)}.`) },
              )
            }
          >
            Register
          </Button>
          {done && (
            <p role="status" className="m-0 text-sm text-status-green">
              {done}
            </p>
          )}
          {register.isError && (
            <p role="alert" className="m-0 text-sm text-status-red">
              {(register.error as ApiError).message}
            </p>
          )}
        </>
      ) : null}
    </li>
  )
}

/** One class's details: what changed, the evidence, the records, the filed items and the controls. */
function ClassDetails({ repo, e, operator, open }: { repo: string; e: PreventionEntry; operator: boolean; open: boolean }) {
  const m = e.measurement
  const c = e.change
  return (
    <details open={open} className="rounded-[var(--radius-card)] border border-border p-3" data-class={e.signature}>
      <summary className="cursor-pointer text-sm font-semibold">
        <span className="font-mono">{e.signature}</span> — {e.status}
      </summary>
      <div className="mt-2 space-y-2 text-sm">
        <p className="m-0">{e.next}</p>
        <p className="m-0 text-xs text-on-surface-muted">
          Evidence: {fmtInt(e.refs_total)} row(s), first seen {fmtDate(e.first_seen)}, last seen {fmtDate(e.last_seen)} —{' '}
          <Link to={`/ledger?repo=${enc(repo)}`}>read them in the ledger</Link>.
        </p>
        {c && (
          <p className="m-0 text-xs">
            Change {c.change_id.slice(0, 12)}: {c.lever_id} ({c.level}), {c.state === 'in_force' ? 'in force' : c.state}; {JSON.stringify(c.what['text'] ?? c.what)}.
          </p>
        )}
        {m && (
          <p className="m-0 text-xs text-on-surface-muted">
            Before: {m.before.k} of {m.before.n} first attempts (p0 {m.before.p0.toFixed(3)}). Exposed: {m.exposed.k} of {m.exposed.n}; unexposed {m.unexposed_n}; runs that opted out {m.concurrent.k} of {m.concurrent.n} (for reading, not deciding). {m.bar}.
          </p>
        )}
        {e.recommendation.passed_over.length > 0 && (
          <p className="m-0 text-xs text-on-surface-muted">
            Passed over: {e.recommendation.passed_over.map((x) => `${x.lever_id} (${x.why_not})`).join('; ')}.
          </p>
        )}
        {e.history.length > 0 && (
          <p className="m-0 font-mono text-xs text-on-surface-muted">
            Records: {e.history.map((h) => `${h.kind} ${h.row_hash.slice(0, 8)}`).join(' · ')}
          </p>
        )}
        {e.proposals.length > 0 && <ul className="m-0 list-none space-y-2 p-0">{e.proposals.map((p) => <ProposalRow key={p.item_id} repo={repo} p={p} operator={operator} />)}</ul>}
        {operator && c && c.state === 'in_force' && <RevertControl repo={repo} changeId={c.change_id} />}
      </div>
    </details>
  )
}

/** The register card's body (ADR-0020): tiles, the switch, the table and each class's details. */
export function PreventionSection({ repo, focus = '' }: { repo: string; focus?: string }) {
  const q = useLearnRegister(repo)
  const tick = useLearnTick()
  const [ticked, setTicked] = useState('')
  const { can } = useAuth()
  const operator = can('operator')
  const columns = useMemo<Column<PreventionEntry>[]>(
    () => [
      {
        key: 'class',
        header: 'Class',
        hint: 'col.learn_register.class',
        mono: true,
        sortValue: (e) => e.signature,
        cell: (e) => (
          <span className="block text-xs">
            {e.signature}
            <span className="mt-0.5 block font-sans text-on-surface-muted">{e.family}</span>
          </span>
        ),
      },
      {
        key: 'seen',
        header: 'Seen',
        hint: 'col.learn_register.seen',
        numeric: true,
        sortValue: (e) => e.first_attempts,
        cell: (e) => (
          <span className="text-xs">
            {e.stratum.k} of {e.stratum.n} {e.stratum.mode} · {fmtInt(e.tasks)} tasks · {fmtUsd(e.cost_usd)}
          </span>
        ),
      },
      {
        key: 'lever',
        header: 'Lever',
        hint: 'col.learn_register.lever',
        sortValue: (e) => e.change?.lever_id ?? e.recommendation.lever_id,
        cell: (e) => {
          const lever = e.change?.lever_id ?? e.recommendation.lever_id
          const level = e.change?.level ?? e.recommendation.level
          if (!lever) return <span className="text-xs text-on-surface-muted">{e.proposals.length ? 'a filed item' : '—'}</span>
          return (
            <span className="inline-flex flex-wrap items-center gap-1 text-xs">
              {lever}
              <Pill tone={LEVEL_TONE[level] ?? 'muted'} size="xs" hint="pill.learn.level" tabStop={false}>
                {level}
              </Pill>
            </span>
          )
        },
      },
      { key: 'applied', header: 'Applied', hint: 'col.learn_register.applied', cell: (e) => <span className="text-xs">{appliedBy(e)}</span>, hideBelowMd: true },
      {
        key: 'before_after',
        header: 'Before → after',
        hint: 'col.learn_register.before_after',
        cell: (e) => (
          <span className="block text-xs">
            {beforeAfter(e)}
            {e.measurement && <span className="mt-0.5 block text-on-surface-muted">{e.measurement.bar}</span>}
          </span>
        ),
      },
      { key: 'status', header: 'Status', hint: 'col.learn_register.status', sortValue: (e) => e.status, cell: (e) => <StatusPills e={e} /> },
      { key: 'next', header: 'Next', hint: 'col.learn_register.next', cell: (e) => <span className="text-xs">{e.next}</span>, hideBelowMd: true },
    ],
    [],
  )
  if (q.isPending)
    return (
      <p role="status" className="text-sm text-on-surface-muted">
        Deriving the prevention register…
      </p>
    )
  if (q.isError) return <ErrorState error={q.error} onRetry={() => void q.refetch()} />
  const r = q.data
  const total = r.entries.length
  const closed = r.counts.closed ?? 0
  const sw = r.switch
  return (
    <div className="space-y-4">
      <p className="m-0 text-sm text-on-surface-muted">
        Every failure class a builder showed on this repository, the strongest change that should remove it, and whether it did: a change is kept only when the attempts that saw it stop showing the class. The loop acts only under the switch below; it changes how a change is made, never how it is judged.
      </p>
      <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-5">
        <StatTile
          label="Bug classes"
          hint="stat.learn.register_classes"
          value={total ? fmtInt(total) : '—'}
          n={r.attempts['first_attempts'] ?? 0}
          apparatus={(['open', 'applied', 'closed', 'retired', 'escalated'] as const).map((s) => `${s} ${r.counts[s] ?? 0}`).join(' · ')}
        />
        <StatTile label="Closed" hint="stat.learn.register_closed" value={total ? `${closed} of ${total}` : '—'} n={total} apparatus={`${r.rules['decision'] ?? ''} · first attempts only`} tone={closed ? 'green' : undefined} />
        <StatTile
          label="Closed by process"
          hint="stat.learn.register_by_process"
          value={r.share_closed_by_process === null ? '—' : fmtPct(r.share_closed_by_process, 0)}
          n={closed}
          apparatus="switch or linked fix, not a playbook line"
        />
        <StatTile
          label="Playbook"
          hint="tile.learn.playbook"
          value={`${r.playbook.lines.length} of ${r.playbook.max_lines} lines`}
          n={r.playbook.lines.length}
          apparatus={`${fmtInt(r.playbook.chars)} of ${fmtInt(r.playbook.max_chars)} characters${r.playbook.sha256 ? ` · ${r.playbook.sha256.slice(0, 8)}` : ''}`}
        />
        <StatTile
          label="Switch"
          hint="switch.learn.auto_apply"
          value={sw.auto_apply}
          n={null}
          apparatus={sw.switched_by ? `thrown by ${sw.switched_by} on ${fmtDate(sw.switched_at)}: ${sw.reason}` : 'never thrown — off by default'}
          tone={sw.auto_apply === 'off' ? undefined : 'blue'}
        />
      </div>
      <SwitchControl key={`${repo}-${sw.record_id}`} repo={repo} sw={sw} operator={operator} />
      {operator && (
        <div className="flex flex-wrap items-center gap-3">
          <Button
            size="sm"
            hint="button.learn.tick"
            disabled={tick.isPending}
            onClick={() => tick.mutate({ repo }, { onSuccess: (t) => setTicked(`The loop ran: ${t.appended.length} record(s) appended${t.appended.length ? ` (${t.appended.map((a) => a.kind).join(', ')})` : ''}.`) })}
          >
            Run the loop now
          </Button>
          {ticked && (
            <p role="status" className="m-0 text-sm">
              {ticked}
            </p>
          )}
          {tick.isError && (
            <p role="alert" className="m-0 text-sm text-status-red">
              {(tick.error as ApiError).message}
            </p>
          )}
        </div>
      )}
      <DataTable
        rows={r.entries}
        columns={columns}
        rowKey={(e) => e.signature}
        caption="Bug classes and the change that removes them"
        dense
        empty={<EmptyState compact title="No bug classes" reason="No first attempt on this repository has failed in a way the loop can name yet." />}
      />
      {r.entries.length > 0 && (
        <div className="space-y-2">
          {r.entries.map((e) => (
            <ClassDetails key={e.signature} repo={repo} e={e} operator={operator} open={focus === e.signature} />
          ))}
        </div>
      )}
      {!r.chain.verified && (
        <p role="alert" className="text-sm text-status-red">
          The prevention chain does not verify: {r.chain.error}
        </p>
      )}
    </div>
  )
}
