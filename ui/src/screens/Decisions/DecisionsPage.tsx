/**
 * Decisions — the inbox of every point where a human's sign-off or judgement is due.
 *
 * Navigation
 * ----------
 * What it is:   The screen at /decisions: across every connected repository, the cells whose
 *               attestation is due, the cells the rule sent to a human, the cells that must
 *               not ship, and the factory items blocked on a structural gap, routed to a
 *               human, asked for rework or withheld by the route gate — one list, ordered by
 *               what blocks what, each row linking to the surface where the act is recorded.
 * What it does: Answers "what needs me, now?" for an approver, and "what is waiting on a
 *               person?" for everyone else. The rows are facts from the map, the sign-offs
 *               and the factory chain (`decisionsFor`); the screen never decides anything
 *               and never hides a row a viewer may read — it only changes the verb.
 * How:          `useAllRepos` → one `<RepoDecisions>` per repository, each with
 *               `useCapabilityMap` + `useSignoffs` + `useFactoryTasks` (a 404 on the factory
 *               = no backlog, no rows); the counts roll up into the header.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0003-one-routing-rule.md
 * Works with:   ui/src/screens/Decisions/decisions.ts (the derivation),
 *               ui/src/screens/Signoff/SignoffPage.tsx (Attest → the cell preselected),
 *               ui/src/screens/Factory/FactoryPage.tsx (Sign a gap → the item),
 *               ui/src/screens/Routing/RoutingPage.tsx (Read why)
 * Tested by:    ui/src/screens/Decisions/DecisionsPage.test.tsx
 * Touch when:   a human act is added to the product (decisions.ts first).
 */

import { useEffect, useRef, useState } from 'react'
import { useAllRepos, useCapabilityMap, useFactoryTasks, useSignoffs } from '../../api/hooks'
import { isApiError } from '../../api/client'
import { LinkButton } from '../../components/Button'
import { Card } from '../../components/Card'
import { EmptyState } from '../../components/EmptyState'
import { ErrorState } from '../../components/ErrorState'
import { PageHeader } from '../../components/PageHeader'
import { Pill } from '../../components/Pill'
import { useAuth } from '../../lib/auth'
import type { Tone } from '../../lib/verdict'
import { type Decision, type DecisionKind, KIND_LABEL, decisionsFor } from './decisions'

const KIND_TONE: Record<DecisionKind, Tone> = {
  do_not_ship: 'red',
  gap_unsigned: 'amber',
  signoff_due: 'primary',
  rework: 'amber',
  delivery_withheld: 'blue',
  item_human: 'violet',
  routed_human: 'muted',
}

export function DecisionsPage() {
  const repos = useAllRepos()
  const [counts, setCounts] = useState<Record<string, number>>({})
  const total = Object.values(counts).reduce((a, b) => a + b, 0)
  const loaded = repos.data ? Object.keys(counts).length >= repos.data.items.length : false

  return (
    <>
      <PageHeader
        eyebrow="Journey · 3 of 4"
        title="Decisions"
        purpose="Every point where a person's sign-off or judgement is due, across the connected repositories — ordered by what blocks what. The instrument measured; a human decides."
        actions={
          <Pill tone={total > 0 ? 'primary' : 'green'} size="sm" label={`${total} decisions waiting`}>
            {loaded ? `${total} waiting` : 'counting…'}
          </Pill>
        }
      />
      {repos.isError && <ErrorState error={repos.error} onRetry={() => void repos.refetch()} />}
      {repos.data && repos.data.items.length === 0 && (
        <EmptyState glyph="⎇" title="No repository connected" reason="Decisions appear once a repository has been measured." action={<LinkButton to="/connect">Connect a repository</LinkButton>} />
      )}
      {repos.data?.items.map((r) => (
        <RepoDecisions key={r.name} repo={r.name} onCount={(n) => setCounts((c) => (c[r.name] === n ? c : { ...c, [r.name]: n }))} />
      ))}
      {loaded && total === 0 && repos.data && repos.data.items.length > 0 && (
        <EmptyState glyph="✓" title="Nothing is waiting on a person" reason="Every measured cell is either signed or routed without a decision pending, and no factory item is blocked." />
      )}
    </>
  )
}

function RepoDecisions({ repo, onCount }: { repo: string; onCount: (n: number) => void }) {
  const { can } = useAuth()
  const map = useCapabilityMap(repo, ['capability_class', 'size'])
  const signoffs = useSignoffs(repo)
  const tasks = useFactoryTasks(repo)
  const tasksReady = tasks.data !== undefined || (tasks.isError && isApiError(tasks.error) && tasks.error.status === 404)
  const ready = map.data !== undefined && signoffs.data !== undefined && tasksReady
  const rows: Decision[] = ready ? decisionsFor({ repo, cells: map.data?.cells ?? [], signoffs: signoffs.data?.items ?? [], tasks: tasks.data ?? [] }) : []
  // report the count after render, never during it (the parent owns that state)
  const report = useRef(onCount)
  report.current = onCount
  const n = rows.length
  useEffect(() => {
    if (ready) report.current(n)
  }, [ready, n])

  if (map.isError) return <ErrorState error={map.error} onRetry={() => void map.refetch()} title={`${repo}: the map could not be read`} compact />
  if (!ready || rows.length === 0) return null
  return (
    <Card title={repo} eyebrow={`${rows.length} waiting`} id={`decisions-${repo}`}>
      <ul className="m-0 list-none divide-y divide-border p-0" aria-label={`Decisions for ${repo}`}>
        {rows.map((d, i) => {
          const allowed = d.role === 'viewer' || can(d.role)
          return (
            <li key={`${d.kind}-${i}`} className="grid grid-cols-[auto_1fr_auto] items-start gap-3 py-3 first:pt-0 last:pb-0">
              <Pill tone={KIND_TONE[d.kind]} size="xs" label={KIND_LABEL[d.kind]}>
                {KIND_LABEL[d.kind]}
              </Pill>
              <div className="min-w-0">
                <div className="text-sm font-semibold">{d.title}</div>
                <div className="num mt-0.5 font-mono text-xs text-on-surface-muted">{d.evidence}</div>
              </div>
              <div className="text-right">
                <LinkButton size="sm" variant={allowed && d.role !== 'viewer' ? 'filled' : 'outlined'} to={d.href}>
                  {allowed ? d.act : 'View'}
                </LinkButton>
                {!allowed && <div className="mt-1 text-[11px] text-on-surface-muted">{d.role} acts</div>}
              </div>
            </li>
          )
        })}
      </ul>
    </Card>
  )
}
