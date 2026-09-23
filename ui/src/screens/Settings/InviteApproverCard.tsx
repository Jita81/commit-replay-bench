/**
 * Invite an approver — the admin's half of the second person (Settings).
 *
 * Navigation
 * ----------
 * What it is:   The card on /settings that invites the second person: the deployment's
 *               two-person readiness, the invite form, the one-time link shown once, and the
 *               table of invitations with their state.
 * What it does: Replaces the out-of-band act — an admin typing a password on somebody else's
 *               behalf — with a recorded one. The reading at the top says whether a sign-off
 *               the two-person rule would accept is possible at all, in the server's own
 *               words. Inviting creates an inactive account and a link that expires; the link
 *               is shown ONCE, with a copy button and the plain warning that it cannot be
 *               recovered, and the person redeems it themselves at /invite. Each row says
 *               where its invitation stands (pending, accepted, expired, withdrawn) and, once
 *               accepted, whether that account has ever signed in — the thing an admin's
 *               presence could never tell you.
 * How:          `useTwoPersonReadiness`, `useInvitations(admin)`, `useInvite`,
 *               `useRevokeInvitation`; the created link lives in component state only (never a
 *               cache, never storage) and is cleared when another invitation is made.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0016-two-person-rule-is-a-policy-clause-not-an-apparatus-move.md
 * Works with:   ui/src/api/hooks.ts (the four hooks), ui/src/api/types.ts (`Invitation`,
 *               `TwoPersonReadiness`), ui/src/screens/Settings/SettingsPage.tsx (mounts it),
 *               ui/src/screens/Invite/AcceptInvitePage.tsx (where the link lands),
 *               ui/src/screens/Home/HomePage.tsx (task 7 reads the same readiness),
 *               src/crb/server/routes/invitations.py (the routes)
 * Tested by:    ui/src/screens/Settings/InviteApproverCard.test.tsx
 * Touch when:   an invitation state is added (a pill tone here and the server's own word);
 *               never for a new repository.
 */
import { useMemo, useState, type FormEvent } from 'react'
import { useInvitations, useInvite, useRevokeInvitation, useTwoPersonReadiness } from '../../api/hooks'
import type { Invitation, InvitationCreated, InvitationState, Role } from '../../api/types'
import { Button } from '../../components/Button'
import { Card } from '../../components/Card'
import { DataTable, type Column } from '../../components/DataTable'
import { EmptyState } from '../../components/EmptyState'
import { ErrorState } from '../../components/ErrorState'
import { SelectField, TextField } from '../../components/Field'
import { DocLink } from '../../components/Help'
import { Hint } from '../../components/Hint'
import { Pill } from '../../components/Pill'
import { QueryBoundary } from '../../components/QueryBoundary'
import { fmtDate } from '../../lib/format'

/** The roles worth an invitation — the server refuses any other (`INVITABLE_ROLES`). */
const INVITABLE: Role[] = ['approver', 'admin']

const STATE_TONE: Record<InvitationState, 'green' | 'blue' | 'amber' | 'muted'> = {
  accepted: 'green',
  pending: 'blue',
  expired: 'amber',
  revoked: 'muted',
}

const STATE_LABEL: Record<InvitationState, string> = {
  accepted: 'accepted',
  pending: 'waiting',
  expired: 'expired',
  revoked: 'withdrawn',
}

/** What each state means for the person reading the row, in one sentence. */
export function stateMeaning(inv: Invitation): string {
  switch (inv.state) {
    case 'accepted':
      return inv.last_login ? `accepted and signed in (last ${fmtDate(inv.last_login)})` : 'accepted, but this account has never signed in'
    case 'pending':
      return `waiting — the link works until ${fmtDate(inv.expires)}`
    case 'expired':
      return `the link expired on ${fmtDate(inv.expires)}; invite again`
    case 'revoked':
      return inv.revoked_reason ? `withdrawn: ${inv.revoked_reason}` : 'withdrawn'
  }
}

export function InviteApproverCard() {
  const readiness = useTwoPersonReadiness()
  const invitations = useInvitations(true)
  const invite = useInvite()
  const revoke = useRevokeInvitation()
  const [username, setUsername] = useState('')
  const [display, setDisplay] = useState('')
  const [email, setEmail] = useState('')
  const [role, setRole] = useState<Role>('approver')
  const [hours, setHours] = useState('72')
  const [made, setMade] = useState<InvitationCreated | null>(null)
  const [copied, setCopied] = useState(false)

  const submit = (e: FormEvent) => {
    e.preventDefault()
    setMade(null)
    setCopied(false)
    invite.mutate(
      { username, role, display_name: display, email, expires_hours: Number(hours) || 72 },
      {
        onSuccess: (created) => {
          setMade(created)
          setUsername('')
          setDisplay('')
          setEmail('')
        },
      },
    )
  }

  const copy = () => {
    if (!made) return
    void navigator.clipboard?.writeText(made.accept_url).then(
      () => setCopied(true),
      () => setCopied(false),
    )
  }

  const columns: Column<Invitation>[] = useMemo(
    () => [
      { key: 'username', header: 'Account', hint: 'col.invitations.account', sortValue: (i) => i.username, cell: (i) => <span className="font-mono text-xs">{i.username}</span> },
      { key: 'role', header: 'Role', hint: 'col.invitations.role', sortValue: (i) => i.role, cell: (i) => i.role },
      {
        key: 'state',
        header: 'State',
        hint: 'col.invitations.state',
        sortValue: (i) => i.state,
        cell: (i) => (
          <Pill tone={STATE_TONE[i.state]} size="xs" label={stateMeaning(i)} hint="col.invitations.state" data-testid={`invitation-state-${i.username}`}>
            {STATE_LABEL[i.state]}
          </Pill>
        ),
      },
      { key: 'invited', header: 'Invited', hint: 'col.invitations.invited', sortValue: (i) => i.created, cell: (i) => <span className="text-xs text-on-surface-muted">{fmtDate(i.created)}</span>, hideBelowMd: true },
      {
        key: 'act',
        header: 'Act',
        hint: 'col.invitations.act',
        cell: (i) =>
          i.state === 'pending' || i.state === 'expired' ? (
            <Button
              variant="outlined"
              size="sm"
              hint="button.invitations.revoke"
              data-testid={`revoke-${i.username}`}
              disabled={revoke.isPending}
              onClick={() => revoke.mutate({ id: i.id, reason: `withdrawn by an admin on the Settings screen` })}
            >
              Withdraw
            </Button>
          ) : (
            <span className="text-xs text-on-surface-muted">—</span>
          ),
      },
    ],
    [revoke],
  )

  return (
    <Card title="Invite an approver" eyebrow="admin · the second person">
      <div className="space-y-4">
        <QueryBoundary query={readiness} loading="Reading this deployment…">
          {(r) => (
            <div className="flex flex-wrap items-start gap-2">
              <Pill tone={r.ready ? 'green' : 'blue'} glyph={r.ready ? '✓' : '!'} label={r.reason} hint="pill.invitations.two_person" data-testid="two-person-readiness">
                {r.ready ? 'two-person ready' : 'not two-person ready'}
              </Pill>
              <Hint id="stat.invitations.two_person" className="block text-sm text-on-surface-muted" data-testid="two-person-reason">
                {r.reason}. {r.approvers_signed_in} of {r.approvers_active} account{r.approvers_active === 1 ? '' : 's'} that can sign have signed in; {r.invitations_pending} invitation{r.invitations_pending === 1 ? '' : 's'} waiting.
              </Hint>
            </div>
          )}
        </QueryBoundary>
        <p className="m-0 text-sm text-on-surface-muted">
          A sign-off needs a second person: the API refuses one from whoever produced the evidence (<code>same_actor</code>), and no setting waives it. An invitation creates the account inactive and sends nobody an email — you pass the link on yourself, it works once, and the person chooses their own password. Guide:{' '}
          <DocLink to="OPERATOR#9-users">Users and roles</DocLink>.
        </p>
        {made && (
          <div className="rounded-[var(--radius-control)] border border-border p-4" data-testid="invitation-link">
            <Hint as="p" id="stat.invitations.link" className="m-0 mb-2 text-[16px]">
              <strong>{made.invitation.username}</strong> is invited as <strong>{made.invitation.role}</strong>. This link is shown once and cannot be recovered — pass it on now. It stops working on {fmtDate(made.invitation.expires)}.
            </Hint>
            <code className="block break-all rounded-[4px] bg-surface p-2 text-xs" data-testid="invitation-url">
              {made.accept_url}
            </code>
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <Button variant="outlined" size="sm" hint="button.invitations.copy" onClick={copy} data-testid="copy-invitation">
                {copied ? 'Copied' : 'Copy the link'}
              </Button>
              {made.public_url_missing && <span className="text-xs text-status-amber">This deployment has no public address configured, so the link above is a path: put this deployment's address in front of it.</span>}
            </div>
          </div>
        )}
        <QueryBoundary query={invitations} loading="Loading invitations…">
          {(page) => (
            <DataTable
              rows={page.items}
              columns={columns}
              rowKey={(i) => i.id}
              caption="Invitations"
              dense
              empty={<EmptyState compact title="No invitations yet" reason="Invite the person who will sign off what this deployment measures." />}
            />
          )}
        </QueryBoundary>
        {revoke.isError && <ErrorState compact error={revoke.error} />}
        <form onSubmit={submit} className="grid gap-3 border-t border-border pt-4 sm:grid-cols-3" aria-label="Invite an approver">
          <TextField label="Username" hint="field.invitations.username" required value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="off" />
          <TextField label="Display name" hint="field.invitations.display" value={display} onChange={(e) => setDisplay(e.target.value)} />
          <TextField label="Email" hint="field.invitations.email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
          <SelectField label="Role" hint="field.invitations.role" value={role} onChange={(e) => setRole(e.target.value as Role)}>
            {INVITABLE.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </SelectField>
          <TextField label="Link expires in (hours)" hint="field.invitations.expires" type="number" min={1} max={336} value={hours} onChange={(e) => setHours(e.target.value)} />
          <div className="flex items-end">
            <Button type="submit" variant="filled" disabled={invite.isPending} hint="button.invitations.invite">
              {invite.isPending ? 'Inviting…' : 'Invite'}
            </Button>
          </div>
          {invite.isError && (
            <div className="sm:col-span-3">
              <ErrorState compact error={invite.error} />
            </div>
          )}
        </form>
      </div>
    </Card>
  )
}

export default InviteApproverCard
