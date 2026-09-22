/**
 * Settings — instrument health, the Claude Code login, non-secret configuration and users
 * (/settings).
 *
 * Navigation
 * ----------
 * What it is:   The screen at /settings: `HealthCard` (every probe with its verdict and the
 *               versions), the Claude Code login card, and for admins the redacted
 *               configuration (`GET /settings`) and `UsersCard` (list, role change, create a
 *               local account).
 * What it does: Describes the instrument honestly and never leaks a secret: a builder is
 *               reported as configured or not, the retention settings are shown as returned,
 *               sandbox mode / ledger backend / apparatus / policy are named. Non-admins see
 *               health and the login status and an "admin only" note for the rest — the
 *               admin queries are not even issued for them.
 * How:          `useHealth` / `useVersion`; `useSettings(admin)` and `useUsers(admin)` gated
 *               by `can('admin')`; role changes and user creation through their mutations.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/api/hooks.ts (`useHealth`, `useVersion`, `useSettings`, `useUsers`,
 *               `useCreateUser`, `useSetUserRole`), ui/src/api/types.ts (`Settings`, `User`,
 *               `Probe`), ui/src/screens/Settings/ClaudeCodeLoginCard.tsx,
 *               ui/src/screens/Settings/GitHubAppCard.tsx, ui/src/components/Help.tsx
 *               (`DocLink` — the roles guide), src/crb/server/routes/admin.py (settings and users),
 *               src/crb/observability/probes.py
 *               (the probes the health card lists)
 * Tested by:    ui/src/screens/Settings/SettingsPage.test.tsx (the roles guide link, the
 *               eyebrow), ui/e2e/walkthrough/07-settings-and-a11y.spec.ts (builders as
 *               configured yes / no, sandbox mode, versions; axe),
 *               ui/e2e/walkthrough/01-login.spec.ts (the health probes it relies on)
 * Touch when:   `GET /settings` gains a non-secret field (src/crb/server/routes/admin.py
 *               `get_settings_view`, docs/API.md "Admin") — type it in ui/src/api/types.ts
 *               and add its `<dt>`; never for a new repository.
 */
import { useMemo, useState, type FormEvent } from 'react'
import { useCreateUser, useHealth, useSetUserRole, useSettings, useUsers, useVersion } from '../../api/hooks'
import { ROLE_ORDER, type Role, type User } from '../../api/types'
import { Button } from '../../components/Button'
import { Card } from '../../components/Card'
import { DataTable, type Column } from '../../components/DataTable'
import { EmptyState } from '../../components/EmptyState'
import { ErrorState } from '../../components/ErrorState'
import { SelectField, TextField } from '../../components/Field'
import { DocLink } from '../../components/Help'
import { Hint } from '../../components/Hint'
import { JsonView } from '../../components/JsonView'
import { PageHeader } from '../../components/PageHeader'
import { Pill } from '../../components/Pill'
import { QueryBoundary } from '../../components/QueryBoundary'
import { useAuth } from '../../lib/auth'
import { fmtDate } from '../../lib/format'
import { probeDisplay } from '../../lib/verdict'
import { ClaudeCodeLoginCard } from './ClaudeCodeLoginCard'
import { GitHubAppCard } from './GitHubAppCard'

/** Every probe from `GET /health` with its verdict, plus the versions. */
function HealthCard() {
  const health = useHealth()
  const version = useVersion()
  return (
    <Card title="Instrument health" eyebrow="probes · version">
      <QueryBoundary query={health} loading="Probing…">
        {(h) => {
          const d = probeDisplay(h.status)
          return (
            <div className="space-y-3">
              <div className="flex flex-wrap items-center gap-2">
                <Pill tone={d.tone} glyph={d.glyph} label={d.describe} hint="pill.settings.health">
                  {d.label}
                </Pill>
                {version.data && (
                  <Hint id="stat.settings.version" className="num font-mono text-xs text-on-surface-muted">
                    crb {version.data.crb} · apparatus {version.data.apparatus} · policy {version.data.policy}
                  </Hint>
                )}
              </div>
              <ul className="m-0 grid list-none gap-2 p-0 sm:grid-cols-2 lg:grid-cols-3">
                {h.probes.map((p) => {
                  const pd = probeDisplay(p.status)
                  return (
                    <li key={p.name} className="flex items-start gap-2 rounded-[var(--radius-control)] border border-border px-3 py-2 text-sm">
                      <Pill tone={pd.tone} glyph={pd.glyph} size="xs" label={`${p.name}: ${pd.label}`} hint="pill.settings.probe">
                        {pd.label}
                      </Pill>
                      <span className="min-w-0">
                        <span className="font-semibold">{p.name}</span>
                        <span className="block text-xs text-on-surface-muted">{p.detail}</span>
                      </span>
                    </li>
                  )
                })}
              </ul>
            </div>
          )
        }}
      </QueryBoundary>
    </Card>
  )
}

/** Admin: the user table with an inline role select, and the create-local-user form (the password field is never echoed). */
function UsersCard() {
  const users = useUsers(true)
  const create = useCreateUser()
  const setRole = useSetUserRole()
  const [username, setUsername] = useState('')
  const [display, setDisplay] = useState('')
  const [email, setEmail] = useState('')
  const [role, setRoleNew] = useState<Role>('viewer')
  const [password, setPassword] = useState('')

  const submit = (e: FormEvent) => {
    e.preventDefault()
    create.mutate(
      { username, display_name: display, email, role, password },
      {
        onSuccess: () => {
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
      { key: 'issuer', header: 'Issuer', hint: 'col.settings.users', sortValue: (u) => u.issuer, cell: (u) => <span className="font-mono text-xs">{u.issuer || 'local'}</span>, hideBelowMd: true },
      {
        key: 'role',
        header: 'Role',
        hint: 'col.settings.role',
        sortValue: (u) => ROLE_ORDER.indexOf(u.role),
        cell: (u) => (
          <Hint
            as="select"
            id="field.settings.user_role"
            aria-label={`Role for ${u.username}`}
            value={u.role}
            onChange={(e: { target: { value: string } }) => setRole.mutate({ id: u.id, role: e.target.value as Role })}
            className="h-8 rounded-[var(--radius-control)] border border-border bg-surface-container px-2 text-xs"
          >
            {ROLE_ORDER.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </Hint>
        ),
      },
      { key: 'created', header: 'Created', hint: 'col.settings.users', sortValue: (u) => u.created, cell: (u) => <span className="text-xs text-on-surface-muted">{fmtDate(u.created)}</span>, hideBelowMd: true },
    ],
    [setRole],
  )

  return (
    <Card title="Users" eyebrow="admin">
      <div className="space-y-4">
        <p className="m-0 text-sm text-on-surface-muted">
          Roles are a ladder: viewer, operator, approver, admin. An approver account is what sign-off needs; local accounts are for bootstrap and air-gapped installs. Guide: <DocLink to="SECURITY#34-authentication-and-authorisation--crbserverauth">How sign-in and roles work</DocLink>.
        </p>
        <QueryBoundary query={users} loading="Loading users…">
          {(page) => <DataTable rows={page.items} columns={columns} rowKey={(u) => u.id} caption="Users" dense empty={<EmptyState compact title="No users" reason="Create the first local account below." />} />}
        </QueryBoundary>
        {setRole.isError && <ErrorState compact error={setRole.error} />}
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
          <TextField label="Initial password" hint="field.settings.new_password" type="password" required value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="new-password" />
          <div className="flex items-end">
            <Button type="submit" variant="filled" disabled={create.isPending} hint="button.settings.create_user">
              {create.isPending ? 'Creating…' : 'Create local user'}
            </Button>
          </div>
          {create.isError && (
            <div className="sm:col-span-3">
              <ErrorState compact error={create.error} />
            </div>
          )}
        </form>
      </div>
    </Card>
  )
}

/** The screen; admin-only queries are gated by the role, not merely hidden. */
export function SettingsPage() {
  const { can } = useAuth()
  const admin = can('admin')
  const settings = useSettings(admin)

  return (
    <>
      <PageHeader eyebrow="Instrument · Settings" title="Settings" purpose="Non-secret configuration and the instrument's health. Secrets are never returned by the API and never shown here; a builder is reported as configured or not, nothing more — the Claude Code login card reports at most the last four characters of a stored token." />
      <HealthCard />
      <ClaudeCodeLoginCard />
      <GitHubAppCard />
      {admin ? (
        <>
          <Card title="Configuration" eyebrow="non-secret · redacted">
            <QueryBoundary query={settings} loading="Loading settings…">
              {(s) => (
                <div className="space-y-4">
                  <dl className="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-2 lg:grid-cols-4">
                    <div>
                      <Hint as="dt" id="tile.settings.sandbox_mode" className="label">
                        Sandbox mode
                      </Hint>
                      <dd className="font-mono" data-testid="settings-sandbox-mode">
                        {s.sandbox_mode || '—'}
                      </dd>
                    </div>
                    <div>
                      <Hint as="dt" id="tile.settings.ledger_backend" className="label">
                        Ledger backend
                      </Hint>
                      <dd className="font-mono" data-testid="settings-ledger-backend">
                        {s.ledger_backend || '—'}
                      </dd>
                    </div>
                    <div>
                      <Hint as="dt" id="tile.settings.apparatus_policy" className="label">
                        Apparatus
                      </Hint>
                      <dd className="font-mono" data-testid="settings-apparatus">
                        {s.apparatus_version || '—'}
                      </dd>
                    </div>
                    <div>
                      <Hint as="dt" id="tile.settings.apparatus_policy" className="label">
                        Policy
                      </Hint>
                      <dd className="font-mono" data-testid="settings-policy">
                        {s.policy_version || '—'}
                      </dd>
                    </div>
                    <div>
                      <Hint as="dt" id="tile.settings.oidc" className="label">
                        OIDC
                      </Hint>
                      <dd>{s.oidc_enabled ? 'enabled' : 'disabled'}</dd>
                    </div>
                  </dl>
                  <div>
                    <div className="label mb-1">Builders</div>
                    {s.builders.length === 0 ? (
                      <p className="text-sm text-on-surface-muted">No builders registered.</p>
                    ) : (
                      <ul className="m-0 flex list-none flex-wrap gap-2 p-0" data-testid="settings-builders">
                        {s.builders.map((b) => (
                          <li key={b.name}>
                            <Pill tone={b.configured ? 'green' : 'muted'} glyph={b.configured ? '✓' : '–'} size="xs" label={`${b.name}: ${b.configured ? 'configured' : 'not configured'}`} hint="pill.settings.builder">
                              {b.name} · {b.configured ? 'configured' : 'not configured'}
                            </Pill>
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                  <div>
                    <Hint as="div" id="tile.settings.retention" className="label mb-1">
                      Retention
                    </Hint>
                    <JsonView value={s.retention} initiallyOpen label="Retention settings" />
                  </div>
                </div>
              )}
            </QueryBoundary>
          </Card>
          <UsersCard />
        </>
      ) : (
        <Card title="Configuration">
          <EmptyState compact title="Admin only" reason="Settings and user management require the admin role. Your session can still see instrument health above." />
        </Card>
      )}
    </>
  )
}

export default SettingsPage
