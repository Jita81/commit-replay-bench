/**
 * Users — the admin's account lifecycle on the screen, not only at the API (F23).
 *
 * Navigation
 * ----------
 * What it is:   The Users card on /settings: every account as a row (sign-in name, display
 *               name, email, where it is issued, role, active, last sign-in), the acts an
 *               admin takes on one — change the role, turn the account off and on, set a new
 *               password — the account's own audit trail, and the form that creates a local
 *               account.
 * What it does: Closes the half of recover-an-account that had no screen: `PUT
 *               /users/{id}/active` behind a toggle that is DISABLED for the last active
 *               admin (with the reason as its hint, so the person meets the rule before the
 *               409, not after it), `PUT /users/{id}/password` behind a dialog, and `GET
 *               /users/{id}/events` under each row, so an auditor reads in the product who
 *               reset or disabled which account. Every mutation has a success sentence that
 *               names the account. An account issued by the organisation's identity provider
 *               has no password to set here and says so.
 * How:          `useUsers` / `useSetUserRole` / `useSetUserActive` / `useCreateUser` /
 *               `useUserEvents`; `lastActiveAdmin` derives the guarded row from the list the
 *               screen already holds (the same rule the server takes under its lock — the
 *               screen never decides, it only stops an act it knows will be refused).
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/screens/Settings/SettingsPage.tsx (mounts it for admins),
 *               ui/src/screens/Settings/SetPasswordDialog.tsx (the password act),
 *               ui/src/api/hooks.ts (`useUsers`, `useCreateUser`, `useSetUserRole`,
 *               `useSetUserActive`, `useUserEvents`), ui/src/api/types.ts (`User`,
 *               `ROLE_ORDER`), ui/src/components/DataTable.tsx (the table),
 *               ui/src/help/hints.ts (every element's sentence, including the last-admin
 *               reason and the 12-character floor), src/crb/server/routes/admin.py (the
 *               routes and the last-admin guard), docs/OPERATOR.md#9-users (the host door,
 *               for when no admin can sign in at all)
 * Tested by:    ui/src/screens/Settings/UsersCard.test.tsx,
 *               ui/e2e/walkthrough/07-settings-and-a11y.spec.ts (an admin sets a persona's
 *               password, that persona signs in, then deactivate and reactivate)
 * Touch when:   a `user.*` act is added at the API — it needs a control here, a hint, and a
 *               line in the audit trail's empty state; never for a new repository.
 */
import { useEffect, useMemo, useState, type FormEvent } from 'react'
import { useCreateUser, useSetUserActive, useSetUserRole, useUserEvents, useUsers } from '../../api/hooks'
import { ROLE_ORDER, type Role, type User } from '../../api/types'
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
import { fmtAgo, fmtDate } from '../../lib/format'
import { SetPasswordDialog } from './SetPasswordDialog'

/** The issuer a local account carries (`src/crb/server/auth.py` `LOCAL_ISSUER`). */
const LOCAL_ISSUER = 'local'

/** `true` when this deployment holds the account's password (and so can set it). */
export function isLocalAccount(u: User): boolean {
  return !u.issuer || u.issuer === LOCAL_ISSUER
}

/**
 * The id of the one account the last-admin guard protects, or `''`.
 *
 * The server decides this under the users lock on re-read rows; this is the SAME rule applied
 * to the list the screen already holds, so the control is disabled before it is used instead
 * of the page reporting a 409 after the fact. When the rule and the server disagree (a second
 * admin was activated in another browser), the server is the one that decides: the screen only
 * ever stops an act, never permits one.
 */
export function lastActiveAdmin(users: readonly User[]): string {
  const admins = users.filter((u) => u.role === 'admin' && u.active)
  return admins.length === 1 ? (admins[0]?.id ?? '') : ''
}

/** The sentence the disabled controls carry, the same words as the hint and the API's refusal. */
const LAST_ADMIN_REASON = 'This is the last active admin. Deactivating or demoting it would leave nobody who can manage accounts — activate or create a second admin first.'

/** One account's `user.*` events, newest first, as the Configuration tab renders a repo's trace. */
function AccountHistory({ user }: { user: User }) {
  const events = useUserEvents(user.id, { limit: 50 })
  const name = user.username || user.display_name || user.id
  return (
    <div className="rounded-[var(--radius-control)] border border-border p-3" data-testid="account-history">
      <Hint as="div" id="tile.settings.account_history" className="label mb-2">
        History for {name}
      </Hint>
      <QueryBoundary query={events} loading="Loading the account history…">
        {(page) =>
          page.items.length === 0 ? (
            <EmptyState compact title="No recorded changes" reason="Every change to an account — created, role set, password set, deactivated, reactivated — is one event with the actor who made it. This account has none on record." />
          ) : (
            <ol className="m-0 list-none space-y-2 p-0" data-testid="account-history-list">
              {page.items.map((ev) => (
                <li key={ev.event_id} className="flex flex-wrap items-center gap-2 text-sm" data-testid="account-history-event" data-action={ev.action}>
                  <Pill tone="primary" size="xs" label={`Action: ${ev.action}`} hint="pill.settings.account_event" tabStop={false}>
                    {ev.action}
                  </Pill>
                  <span className="text-xs text-on-surface-muted">{fmtDate(ev.timestamp)}</span>
                  {ev.actor && (
                    <span className="text-xs text-on-surface-muted">
                      by <span className="font-mono">{ev.actor}</span>
                    </span>
                  )}
                  {typeof ev.payload.by === 'string' && <span className="text-xs text-on-surface-muted">({ev.payload.by})</span>}
                  {typeof ev.payload.from_role === 'string' && (
                    <span className="text-xs text-on-surface-muted">
                      was <span className="font-mono">{ev.payload.from_role}</span>
                    </span>
                  )}
                </li>
              ))}
            </ol>
          )
        }
      </QueryBoundary>
      {events.data && events.data.total > events.data.items.length && (
        <p className="mt-2 text-xs text-on-surface-muted">
          Showing the {events.data.items.length} most recent of {events.data.total} recorded changes.
        </p>
      )}
    </div>
  )
}

/**
 * The card: the table with the acts, the account history, and the create-local-account form.
 * Every act names its outcome; nothing here echoes a password.
 */
export function UsersCard() {
  const users = useUsers(true)
  const create = useCreateUser()
  const setRole = useSetUserRole()
  const setActive = useSetUserActive()
  const [username, setUsername] = useState('')
  const [display, setDisplay] = useState('')
  const [email, setEmail] = useState('')
  const [role, setRoleNew] = useState<Role>('viewer')
  const [password, setPassword] = useState('')
  const [created, setCreated] = useState('')
  const [said, setSaid] = useState('')
  const [pwFor, setPwFor] = useState<User | null>(null)
  const [historyFor, setHistoryFor] = useState<string>('')
  // What the admin last ASKED for, per account: the toggle is a controlled checkbox, so without
  // this the browser's own flip is overwritten by the row still in the cache and the control
  // visibly snaps back until the refetch lands (Playwright's `uncheck` called that a click that
  // did not change the state — and the account it had in fact deactivated stayed deactivated).
  // An entry is dropped as soon as the served row agrees (below) or the server refuses, so the
  // screen shows an intention only while it is still in flight and the API stays the authority.
  const [asked, setAsked] = useState<Record<string, boolean>>({})

  const items = users.data?.items
  const rows = items ?? []
  const guarded = lastActiveAdmin(rows)
  const shown = rows.find((u) => u.id === historyFor)
  /** `active` as the screen shows it: what was asked for while the served row still disagrees. */
  const activeOf = (u: User) => asked[u.id] ?? u.active
  const forget = (id: string) =>
    setAsked((prev) => {
      if (!(id in prev)) return prev
      const next = { ...prev }
      delete next[id]
      return next
    })

  // the served list has caught up: hand authority back to it
  useEffect(() => {
    if (!items) return
    setAsked((prev) => {
      const next: Record<string, boolean> = {}
      let changed = false
      for (const [id, want] of Object.entries(prev)) {
        if (items.some((u) => u.id === id && u.active === want)) changed = true
        else next[id] = want
      }
      return changed ? next : prev
    })
  }, [items])

  const submit = (e: FormEvent) => {
    e.preventDefault()
    create.mutate(
      { username, display_name: display, email, role, password },
      {
        onSuccess: (u) => {
          setCreated(`Account ${u.username || u.display_name} created as ${u.role}. It can sign in now with the password you typed.`)
          setUsername('')
          setDisplay('')
          setEmail('')
          setPassword('')
          setRoleNew('viewer')
        },
      },
    )
  }

  const columns = useMemo<Column<User>[]>(
    () => [
      { key: 'username', header: 'Username', hint: 'col.settings.users', mono: true, sortValue: (u) => u.username, cell: (u) => u.username },
      { key: 'display', header: 'Name', hint: 'col.settings.users', sortValue: (u) => u.display_name, cell: (u) => u.display_name },
      { key: 'email', header: 'Email', hint: 'col.settings.users', sortValue: (u) => u.email, cell: (u) => u.email, hideBelowMd: true },
      {
        key: 'kind',
        header: 'Kind',
        hint: 'col.settings.account_kind',
        // below md the table drops what a phone reader can do without (accessibility: a phone
        // never pans sideways to reach an act): kind and the last sign-in go, the acts stay
        hideBelowMd: true,
        sortValue: (u) => (isLocalAccount(u) ? 'local' : 'oidc'),
        cell: (u) => (
          <Pill tone={isLocalAccount(u) ? 'muted' : 'primary'} size="xs" label={isLocalAccount(u) ? `${u.username}: local account` : `${u.username}: managed by your identity provider`} hint="pill.settings.account_kind" tabStop={false}>
            {isLocalAccount(u) ? 'local' : 'oidc'}
          </Pill>
        ),
      },
      {
        key: 'role',
        header: 'Role',
        hint: 'col.settings.role',
        sortValue: (u) => ROLE_ORDER.indexOf(u.role),
        cell: (u) => (
          <Hint
            as="select"
            id="field.settings.user_role"
            aria-label={u.id === guarded ? `Role for ${u.username} — ${LAST_ADMIN_REASON}` : `Role for ${u.username}`}
            data-testid={`user-role-${u.username}`}
            disabled={u.id === guarded}
            value={u.role}
            onChange={(e: { target: { value: string } }) => {
              const next = e.target.value as Role
              setRole.mutate(
                { id: u.id, role: next },
                { onSuccess: (x) => setSaid(`Role of ${x.username || x.display_name} is now ${x.role}.`) },
              )
            }}
            className="h-8 rounded-[var(--radius-control)] border border-border bg-surface-container px-2 text-xs disabled:opacity-60"
          >
            {ROLE_ORDER.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </Hint>
        ),
      },
      {
        key: 'active',
        header: 'Active',
        hint: 'col.settings.active',
        sortValue: (u) => activeOf(u),
        // a plain checkbox, not `role="switch"`: the native `checked` is the state either way, and a
        // switch without an explicit `aria-checked` is an axe risk this would earn nothing for
        cell: (u) => (
          <Hint
            as="input"
            id="toggle.settings.user_active"
            type="checkbox"
            aria-label={u.id === guarded ? `Active for ${u.username} — ${LAST_ADMIN_REASON}` : `Active for ${u.username}`}
            data-testid={`user-active-${u.username}`}
            disabled={u.id === guarded}
            checked={activeOf(u)}
            onChange={(e: { target: { checked: boolean } }) => {
              const next = e.target.checked
              setAsked((prev) => ({ ...prev, [u.id]: next }))
              setActive.mutate(
                { id: u.id, active: next },
                {
                  onSuccess: (x) =>
                    setSaid(
                      next
                        ? `${x.username || x.display_name} is active again and can sign in. Sessions it held less than the session lifetime ago work again — set a password to end them.`
                        : `${x.username || x.display_name} is deactivated and is refused on its very next request.`,
                    ),
                  // the server is the one that decides: a refusal puts the control back
                  onError: () => forget(u.id),
                },
              )
            }}
            className="size-4 accent-[var(--color-primary)] disabled:opacity-60"
          />
        ),
      },
      {
        key: 'last_login',
        header: 'Last sign-in',
        hint: 'col.settings.last_login',
        hideBelowMd: true,
        sortValue: (u) => u.last_login,
        cell: (u) => (
          <Hint id="stat.settings.last_login" className="text-xs text-on-surface-muted" data-testid={`user-last-login-${u.username}`} tabStop={false}>
            {fmtAgo(u.last_login, Date.now()) ?? 'Never'}
          </Hint>
        ),
      },
      {
        key: 'actions',
        header: 'Account',
        hint: 'col.settings.account_actions',
        cell: (u) => (
          <div className="flex flex-wrap gap-1">
            <Button size="sm" hint="button.settings.set_password" disabled={!isLocalAccount(u)} data-testid={`user-set-password-${u.username}`} onClick={() => setPwFor(u)}>
              Set password
            </Button>
            <Button size="sm" variant="ghost" hint="button.settings.account_history" data-testid={`user-history-${u.username}`} aria-expanded={historyFor === u.id} onClick={() => setHistoryFor(historyFor === u.id ? '' : u.id)}>
              History
            </Button>
          </div>
        ),
      },
      { key: 'created', header: 'Created', hint: 'col.settings.users', sortValue: (u) => u.created, cell: (u) => <span className="text-xs text-on-surface-muted">{fmtDate(u.created)}</span>, hideBelowMd: true },
    ],
    [setRole, setActive, guarded, historyFor, asked],
  )

  return (
    <Card title="Users" eyebrow="admin">
      <div className="space-y-4">
        <p className="m-0 text-sm text-on-surface-muted">
          Roles are a ladder: viewer, operator, approver, admin. An approver account is what sign-off needs; local accounts are for bootstrap and air-gapped installs. Guide: <DocLink to="SECURITY#34-authentication-and-authorisation--crbserverauth">How sign-in and roles work</DocLink>.
        </p>
        <p className="m-0 text-sm text-on-surface-muted" data-testid="users-not-here">
          Not here: there is no email reset, no self-service unlock and no security questions. A person who cannot sign in asks an admin to set a new password; an account issued by your identity provider has its password and its disabling there, not here; and when no admin can sign in at all, the way back is <code className="font-mono">crb users</code> on the API host — <DocLink to="OPERATOR#9-users">Users, and what to do when nobody can sign in</DocLink>.
        </p>
        <QueryBoundary query={users} loading="Loading users…">
          {(page) => <DataTable rows={page.items} columns={columns} rowKey={(u) => u.id} caption="Users" dense empty={<EmptyState compact title="No users" reason="Create the first local account below." />} />}
        </QueryBoundary>
        {said && (
          <p role="status" className="m-0 text-sm" data-testid="users-said">
            {said}
          </p>
        )}
        {setRole.isError && <ErrorState compact error={setRole.error} />}
        {setActive.isError && <ErrorState compact error={setActive.error} />}
        {shown && <AccountHistory user={shown} />}
        <form onSubmit={submit} className="grid gap-3 border-t border-border pt-4 sm:grid-cols-3">
          <TextField label="Username" hint="field.settings.new_username" required value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="off" />
          <TextField label="Display name" hint="field.settings.new_display" required value={display} onChange={(e) => setDisplay(e.target.value)} />
          <TextField label="Email" hint="field.settings.new_email" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
          <SelectField label="Role" hint="field.settings.new_role" value={role} onChange={(e) => setRoleNew(e.target.value as Role)}>
            {ROLE_ORDER.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </SelectField>
          <TextField label="Initial password" hint="field.settings.new_password" type="password" required minLength={12} value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="new-password" />
          <div className="flex items-end">
            <Button type="submit" variant="filled" disabled={create.isPending} hint="button.settings.create_user">
              {create.isPending ? 'Creating…' : 'Create local user'}
            </Button>
          </div>
          {created && (
            <p role="status" className="m-0 text-sm sm:col-span-3" data-testid="users-created">
              {created}
            </p>
          )}
          {create.isError && (
            <div className="sm:col-span-3">
              <ErrorState compact error={create.error} />
            </div>
          )}
        </form>
      </div>
      <SetPasswordDialog user={pwFor} onClose={() => setPwFor(null)} />
    </Card>
  )
}
