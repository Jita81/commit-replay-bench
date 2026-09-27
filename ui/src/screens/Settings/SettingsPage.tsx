/**
 * Settings — instrument health, the Claude Code login, non-secret configuration, the
 * reader's own password and, for admins, accounts (/settings).
 *
 * Navigation
 * ----------
 * What it is:   The screen at /settings: `HealthCard` (every probe with its verdict and the
 *               versions), the Claude Code login card, the GitHub App card, "Change my
 *               password" for the account the reader is signed in as, and for admins the
 *               redacted configuration (`GET /settings`) and the Users card (the account
 *               lifecycle: role, active, password, audit trail, create).
 * What it does: Describes the instrument honestly and never leaks a secret: a builder is
 *               reported as configured or not, the retention settings are shown as returned,
 *               sandbox mode / ledger backend / apparatus / policy are named. Non-admins see
 *               health, the login status, their own password card and an "admin only" note
 *               for the rest — the admin queries are not even issued for them.
 * How:          `useHealth` / `useVersion`; `useSettings(admin)` gated by `can(\'admin\')`; the
 *               two account cards are their own files, so this one stays the page's layout.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/api/hooks.ts (`useHealth`, `useVersion`, `useSettings`),
 *               ui/src/api/types.ts (`Settings`, `Probe`),
 *               ui/src/screens/Settings/ClaudeCodeLoginCard.tsx,
 *               ui/src/screens/Settings/GitHubAppCard.tsx,
 *               ui/src/screens/Settings/UsersCard.tsx (the admin\'s account lifecycle),
 *               ui/src/screens/Settings/ChangeMyPasswordCard.tsx (the self-service door),
 *               src/crb/server/routes/admin.py (settings and users),
 *               src/crb/observability/probes.py (the probes the health card lists)
 * Tested by:    ui/src/screens/Settings/SettingsPage.test.tsx (the roles guide link, the
 *               eyebrow), ui/e2e/walkthrough/07-settings-and-a11y.spec.ts (builders as
 *               configured yes / no, sandbox mode, versions; axe; the recovery acts),
 *               ui/e2e/walkthrough/01-login.spec.ts (the health probes it relies on)
 * Touch when:   `GET /settings` gains a non-secret field (src/crb/server/routes/admin.py
 *               `get_settings_view`, docs/API.md "Admin") — type it in ui/src/api/types.ts
 *               and add its `<dt>`; never for a new repository.
 */
import { useHealth, useSettings, useVersion } from '../../api/hooks'
import { Card } from '../../components/Card'
import { EmptyState } from '../../components/EmptyState'
import { Hint } from '../../components/Hint'
import { JsonView } from '../../components/JsonView'
import { PageHeader } from '../../components/PageHeader'
import { Pill } from '../../components/Pill'
import { QueryBoundary } from '../../components/QueryBoundary'
import { useAuth } from '../../lib/auth'
import { probeDisplay } from '../../lib/verdict'
import { ChangeMyPasswordCard } from './ChangeMyPasswordCard'
import { ClaudeCodeLoginCard } from './ClaudeCodeLoginCard'
import { GitHubAppCard } from './GitHubAppCard'
import { UsersCard } from './UsersCard'

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

/** The screen; admin-only queries are gated by the role, not merely hidden. */
export function SettingsPage() {
  const { can } = useAuth()
  const admin = can('admin')
  const settings = useSettings(admin)

  return (
    <>
      <PageHeader eyebrow="Instrument · Settings" title="Settings" purpose="Non-secret configuration, the instrument's health, your own password and — for admins — accounts. Secrets are never returned by the API and never shown here; a builder is reported as configured or not, nothing more — the Claude Code login card reports at most the last four characters of a stored token, and a password is sent once and never shown back." />
      <HealthCard />
      <ChangeMyPasswordCard />
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
