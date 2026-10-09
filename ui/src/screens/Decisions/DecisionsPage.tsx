/**
 * Decisions — the inbox of every point where a human's sign-off or judgement is due.
 *
 * Navigation
 * ----------
 * What it is:   The screen at /decisions: across every connected repository, the cells whose
 *               attestation is due, held by their tests or measured on an earlier apparatus,
 *               the cells the rule sent to a human, the cells that must not ship, and the
 *               factory items blocked on a structural gap, not built, routed to a human, asked
 *               for rework or withheld by the route gate — one list, ordered by what blocks
 *               what, each row linking to the surface where the act is recorded.
 * What it does: Answers "what needs me, now?" for an approver, and "what is waiting on a
 *               person?" for everyone else — and, since G-516, for HOW LONG: each row carries
 *               the moment it first became due, from the server's own clock, so a decision
 *               nobody has looked at for eleven days says eleven days. The rows are served by
 *               `GET /decisions` (F6), each with the act this person's role may take; the
 *               screen never decides anything and never hides a row a viewer may read — the
 *               verb is `Read` and the role that acts is named, on the stale rows too. A read
 *               that fails, or a repository the server could not read, is shown with its
 *               status and code, says the count is incomplete and offers Retry (G-134). The
 *               one line of evidence is readable without a guide: the reason code is a term
 *               with its meaning beside it, and the kicker names the apparatus as a term.
 *               Every element a reader meets — the kicker, the count pill, each row's kind
 *               tag, evidence line, act or Read button and the role that acts, and each stale
 *               row and its button — is a hint trigger (`stat.decisions.*`,
 *               `pill.decisions.kind`, `button.decisions.*`, `tile.decisions.stale`), so what
 *               a row means opens on hover, focus and tap.
 * How:          `useDecisions` (one `GET /decisions`) → one card per repository with rows; the
 *               `signoff_stale` rows in their own section; the counts roll up into the header.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0003-one-routing-rule.md
 * Works with:   ui/src/screens/Decisions/decisions.ts (the labels, `evidenceStats`),
 *               ui/src/screens/Decisions/useDecisionCount.ts (the reading),
 *               ui/src/screens/Capability/contract.ts (`REASON_DISPLAY`),
 *               ui/src/components/Help.tsx (`Term`), ui/src/components/Hint.tsx +
 *               ui/src/help/hints.ts (the triggers and copy),
 *               ui/src/screens/Signoff/SignoffPage.tsx (Attest → the cell preselected),
 *               ui/src/screens/Factory/FactoryPage.tsx (Sign a gap → the item),
 *               ui/src/screens/Routing/RoutingPage.tsx (Read why)
 * Tested by:    ui/src/screens/Decisions/DecisionsPage.test.tsx, ui/src/help/hints-ratchet.test.tsx
 *               (every element resolves to a registry id)
 * Touch when:   never for a new repository; a human act is added to the product
 *               (src/crb/server/decisions.py first, then its label and tag here and in
 *               decisions.ts).
 */

import { type Signoff, approverName, signoffStaleWhy } from '../../api/types'
import { LinkButton } from '../../components/Button'
import { Card } from '../../components/Card'
import { EmptyState } from '../../components/EmptyState'
import { ErrorState } from '../../components/ErrorState'
import { Kicker, Lede, PageTitle, SecondaryButton, StartButton, Tag, type TagTone } from '../../components/govuk'
import { Term } from '../../components/Help'
import { Hint } from '../../components/Hint'
import { Pill } from '../../components/Pill'
import { useAuth } from '../../lib/auth'
import { REASON_DISPLAY, type ReasonCode } from '../Capability/contract'
import { type DecisionKind, KIND_LABEL, evidenceStats, waitedFor } from './decisions'
import { useApparatus, useDecisions } from './useDecisionCount'

const KIND_TAG: Record<DecisionKind, TagTone> = {
  do_not_ship: 'red',
  gap_unsigned: 'amber',
  not_built: 'amber',
  signoff_due: 'blue',
  signoff_stale: 'amber',
  strengthen: 'amber',
  remeasure: 'pale',
  rework: 'grey',
  delivery_withheld: 'grey',
  prevention: 'amber',
  entry_to_sign: 'blue',
  entry_stale: 'amber',
  entry_retired: 'grey',
  item_human: 'grey',
  routed_human: 'pale',
}

function pct(x: number): string {
  return `${(x * 100).toFixed(0)}%`
}

/** "alpha is" / "alpha and beta are" / "alpha, beta, gamma and 2 more are" — names, never a bare count. */
function listNames(names: string[]): string {
  if (names.length === 1) return `${names[0]} is`
  const shown = names.slice(0, 3)
  const rest = names.length - shown.length
  const head = shown.length > 1 ? `${shown.slice(0, -1).join(', ')} and ${shown[shown.length - 1]}` : shown[0]
  return rest > 0 ? `${shown.join(', ')} and ${rest} more are` : `${head} are`
}

/** What a failed read leaves unknown, said the same way for the whole inbox and for one repository. */
const INCOMPLETE = 'The count above is incomplete until a retry succeeds.'

export function DecisionsPage() {
  const { can } = useAuth()
  const d = useDecisions()
  const apparatus = useApparatus()
  const total = d.decisions.length + d.stale.length
  const repos = Object.keys(d.byRepo)
  const withRows = repos.length
  // the reading answered, even if a repository in it could not be read (then the count is incomplete)
  const answered = d.error === null && (d.ready || d.repoErrors.length > 0)

  return (
    <>
      <div>
        {apparatus ? (
          <Hint id="stat.decisions.apparatus">
            <Kicker>
              Under <Term id="apparatus">apparatus</Term> {apparatus}
            </Kicker>
          </Hint>
        ) : (
          <Kicker>{''}</Kicker>
        )}
      </div>
      <PageTitle>Your decisions</PageTitle>
      <Lede>
        Only decisions that are ready appear here. A cell the policy would refuse anyway is never sent to you — it stays on the map with its reason code. The instrument measured; a person decides.
      </Lede>
      {/* the page-level readiness marker the walkthrough's axe sweep waits on: true only when the reading answered and every repository in it was read */}
      <div className="mb-6" data-testid="decisions-count" data-ready={d.ready ? 'true' : 'false'}>
        {/* the count across repositories: each card's eyebrow carries its own, so the pill names the spread rather than repeating one card's number */}
        <Pill tone={total > 0 ? 'primary' : 'green'} size="sm" label={`${total} decisions waiting`} hint="stat.decisions.count">
          {answered ? `${total} waiting${withRows > 0 ? ` across ${withRows} ${withRows === 1 ? 'repository' : 'repositories'}` : ''}` : d.error ? 'not known' : 'counting…'}
        </Pill>
      </div>
      {d.error && (
        <ErrorState compact error={d.error} title="The decisions could not be read" onRetry={d.refetch}>
          <p className="text-sm">{INCOMPLETE}</p>
        </ErrorState>
      )}
      {d.repoErrors.map(({ repo, error }) => (
        <ErrorState key={repo} compact error={error} title={`The decisions for ${repo} could not be read`} onRetry={d.refetch}>
          <p className="text-sm">{INCOMPLETE}</p>
        </ErrorState>
      ))}
      {d.ready && d.connected.length === 0 && (
        <EmptyState glyph="⎇" title="No repository connected" reason="Decisions appear once a repository has been measured." action={<LinkButton to="/connect">Connect a repository</LinkButton>} />
      )}
      {d.ready && d.connected.length > 0 && d.measured.length === 0 && total === 0 && (
        <EmptyState glyph="◌" title="Nothing measured yet" reason={`${listNames(d.connected)} connected but no capability map exists yet. Decisions appear once a measurement has run.`} action={<LinkButton to="/connect">Go to the connection walk</LinkButton>} />
      )}
      {repos.map((repo) => {
        const rows = d.byRepo[repo] ?? []
        if (rows.length === 0) return null
        return (
          <Card key={repo} title={repo} eyebrow={`${rows.length} waiting`} eyebrowHint="stat.decisions.repo_count" id={`decisions-${repo}`}>
            <ul className="m-0 list-none border-t-2 border-on-surface p-0" aria-label={`Decisions for ${repo}`}>
              {rows.map((row, i) => {
                // the server says whether this person can take the act (F6); a row it did not serve is judged here
                const allowed = row.canAct ?? (row.role === 'viewer' || can(row.role))
                return (
                  <li key={`${row.kind}-${i}`} className="grid grid-cols-[minmax(0,1fr)_auto] items-start gap-6 border-b border-border py-5">
                    <div>
                      <Tag tone={KIND_TAG[row.kind]} hint="pill.decisions.kind">
                        {KIND_LABEL[row.kind]}
                      </Tag>
                      <h3 className="mb-1 mt-2 text-[24px] font-bold leading-[1.3]">{row.title}</h3>
                      {waitedFor(row.ageS) && (
                        <Hint id="stat.decisions.waiting" className="mb-1 block text-[16px] text-on-surface-muted" data-testid={`decision-age-${row.kind}-${row.key}`}>
                          Waiting {waitedFor(row.ageS)} — since {row.dueSince?.slice(0, 10)}
                        </Hint>
                      )}
                      <Hint as="p" id="stat.decisions.evidence" className="m-0 font-mono text-[16px] leading-[1.5] text-on-surface-muted">
                        {evidenceStats(row)}
                        {row.reasonCode && (
                          <>
                            {' · '}
                            <Term id="reason_code">{row.reasonCode}</Term>
                            {row.reasonCode in REASON_DISPLAY && <span className="font-sans"> — {REASON_DISPLAY[row.reasonCode as ReasonCode]}</span>}
                          </>
                        )}
                      </Hint>
                    </div>
                    <div className="text-right">
                      {allowed && row.role !== 'viewer' ? (
                        <StartButton to={row.href} hint="button.decisions.act">
                          {row.act}
                        </StartButton>
                      ) : (
                        <SecondaryButton to={row.href} hint="button.decisions.read">
                          {allowed ? row.act : 'Read'}
                        </SecondaryButton>
                      )}
                      {!allowed && (
                        <Hint id="stat.decisions.who_acts" className="mt-1 block text-[13px] text-on-surface-muted">
                          {row.role} acts
                        </Hint>
                      )}
                    </div>
                  </li>
                )
              })}
            </ul>
          </Card>
        )
      })}
      {d.ready && total === 0 && d.measured.length > 0 && (
        <EmptyState glyph="✓" title="Nothing is waiting on a person" reason="Every measured cell is either signed or routed without a decision pending, and no factory item is blocked." />
      )}
      {d.stale.length > 0 && (
        <section aria-labelledby="stale-heading" className="mt-10">
          <h2 id="stale-heading" className="mb-2 text-[32px] font-bold leading-[1.25]">
            Signed cells now stale
          </h2>
          <Lede className="mb-4">Evidence expires when the instrument changes — the apparatus, or the checks arm a repository grades under. These cells were signed on an earlier one and no longer license a claim — they lift nothing until re-signed or revoked.</Lede>
          <ul className="m-0 max-w-[60em] list-none border-t-2 border-on-surface p-0" aria-label="Stale sign-offs">
            {d.stale.flatMap(({ repo, signoff }) => (signoff ? [{ repo, signoff }] : [])).map(({ repo, signoff }: { repo: string; signoff: Signoff }) => (
              <li key={signoff.id} className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-6 border-b border-border py-5">
                <div>
                  <Hint as="h3" id="tile.decisions.stale" className="mb-1 text-[19px] font-bold leading-[1.4]">
                    <code>
                      {signoff.cell.capability_class} × {signoff.cell.size}
                    </code>{' '}
                    on {repo} —{' '}
                    {signoffStaleWhy(signoff, apparatus)}
                  </Hint>
                  <p className="m-0 font-mono text-[16px] leading-[1.5] text-on-surface-muted">
                    signed {signoff.created.slice(0, 10)} by {approverName(signoff)} · n={signoff.evidence.n} · {pct(signoff.evidence.point)} [{pct(signoff.evidence.ci_low)}, …]
                  </p>
                </div>
                <div className="text-right">
                  <SecondaryButton to={`/signoff?repo=${encodeURIComponent(repo)}&cell=${encodeURIComponent(`${signoff.cell.capability_class}|${signoff.cell.size}`)}`} hint={can('approver') ? 'button.decisions.resign' : 'button.decisions.read'}>
                    {can('approver') ? 'Revoke or re-sign' : 'Read'}
                  </SecondaryButton>
                  {!can('approver') && (
                    <Hint id="stat.decisions.who_acts" className="mt-1 block text-[13px] text-on-surface-muted">
                      approver acts
                    </Hint>
                  )}
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}
    </>
  )
}
