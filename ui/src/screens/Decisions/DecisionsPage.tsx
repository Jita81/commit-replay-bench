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

import { approverName } from '../../api/types'
import { LinkButton } from '../../components/Button'
import { Card } from '../../components/Card'
import { EmptyState } from '../../components/EmptyState'
import { ErrorState } from '../../components/ErrorState'
import { Kicker, Lede, PageTitle, SecondaryButton, StartButton, Tag, type TagTone } from '../../components/govuk'
import { Pill } from '../../components/Pill'
import { useAuth } from '../../lib/auth'
import { type DecisionKind, KIND_LABEL } from './decisions'
import { useApparatus, useDecisions } from './useDecisionCount'

const KIND_TAG: Record<DecisionKind, TagTone> = {
  do_not_ship: 'red',
  gap_unsigned: 'amber',
  signoff_due: 'blue',
  rework: 'grey',
  delivery_withheld: 'grey',
  item_human: 'grey',
  routed_human: 'pale',
}

function pct(x: number): string {
  return `${(x * 100).toFixed(0)}%`
}

export function DecisionsPage() {
  const { can } = useAuth()
  const d = useDecisions()
  const apparatus = useApparatus()
  const total = d.decisions.length + d.stale.length
  const repos = Object.keys(d.byRepo)

  return (
    <>
      <div>
        <Kicker>{apparatus ? `apparatus ${apparatus}` : ''}</Kicker>
      </div>
      <PageTitle>Your decisions</PageTitle>
      <Lede>
        Only decisions that are ready appear here. A cell the policy would refuse anyway is never sent to you — it stays on the map with its reason code. The instrument measured; a person decides.
      </Lede>
      <div className="mb-6">
        <Pill tone={total > 0 ? 'primary' : 'green'} size="sm" label={`${total} decisions waiting`}>
          {d.ready ? `${total} waiting` : 'counting…'}
        </Pill>
      </div>
      {d.errors.map((e) => (
        <ErrorState key={e} error={new Error(e)} compact />
      ))}
      {d.ready && repos.length === 0 && d.decisions.length === 0 && (
        <EmptyState glyph="⎇" title="No repository connected" reason="Decisions appear once a repository has been measured." action={<LinkButton to="/connect">Connect a repository</LinkButton>} />
      )}
      {repos.map((repo) => {
        const rows = d.byRepo[repo] ?? []
        if (rows.length === 0) return null
        return (
          <Card key={repo} title={repo} eyebrow={`${rows.length} waiting`} id={`decisions-${repo}`}>
            <ul className="m-0 list-none border-t-2 border-on-surface p-0" aria-label={`Decisions for ${repo}`}>
              {rows.map((row, i) => {
                const allowed = row.role === 'viewer' || can(row.role)
                return (
                  <li key={`${row.kind}-${i}`} className="grid grid-cols-[minmax(0,1fr)_auto] items-start gap-6 border-b border-border py-5">
                    <div>
                      <Tag tone={KIND_TAG[row.kind]}>{KIND_LABEL[row.kind]}</Tag>
                      <h3 className="mb-1 mt-2 text-[24px] font-bold leading-[1.3]">{row.title}</h3>
                      <p className="m-0 font-mono text-[16px] leading-[1.5] text-on-surface-muted">{row.evidence}</p>
                    </div>
                    <div className="text-right">
                      {allowed && row.role !== 'viewer' ? <StartButton to={row.href}>{row.act}</StartButton> : <SecondaryButton to={row.href}>{allowed ? row.act : 'Read'}</SecondaryButton>}
                      {!allowed && <div className="mt-1 text-[13px] text-on-surface-muted">{row.role} acts</div>}
                    </div>
                  </li>
                )
              })}
            </ul>
          </Card>
        )
      })}
      {d.ready && total === 0 && repos.length > 0 && (
        <EmptyState glyph="✓" title="Nothing is waiting on a person" reason="Every measured cell is either signed or routed without a decision pending, and no factory item is blocked." />
      )}
      {d.stale.length > 0 && (
        <section aria-labelledby="stale-heading" className="mt-10">
          <h2 id="stale-heading" className="mb-2 text-[32px] font-bold leading-[1.25]">
            Signed cells now stale
          </h2>
          <Lede className="mb-4">Evidence expires when the apparatus changes. These cells were signed under an earlier apparatus and no longer license a claim — they lift nothing until re-signed or revoked.</Lede>
          <ul className="m-0 max-w-[60em] list-none border-t-2 border-on-surface p-0" aria-label="Stale sign-offs">
            {d.stale.map(({ repo, signoff }) => (
              <li key={signoff.id} className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-6 border-b border-border py-5">
                <div>
                  <h3 className="mb-1 text-[19px] font-bold leading-[1.4]">
                    <code>
                      {signoff.cell.capability_class} × {signoff.cell.size}
                    </code>{' '}
                    on {repo} — signed at apparatus {signoff.evidence.apparatus_versions.join(', ') || '?'}, now reading at {signoff.apparatus_current || apparatus}
                  </h3>
                  <p className="m-0 font-mono text-[16px] leading-[1.5] text-on-surface-muted">
                    signed {signoff.created.slice(0, 10)} by {approverName(signoff)} · n={signoff.evidence.n} · {pct(signoff.evidence.point)} [{pct(signoff.evidence.ci_low)}, …]
                  </p>
                </div>
                <SecondaryButton to={`/signoff?repo=${encodeURIComponent(repo)}&cell=${encodeURIComponent(`${signoff.cell.capability_class}|${signoff.cell.size}`)}`}>Revoke or re-sign</SecondaryButton>
              </li>
            ))}
          </ul>
        </section>
      )}
    </>
  )
}
