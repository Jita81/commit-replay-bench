/**
 * Deployment posture — "About this deployment", the printable page for an architecture review board.
 *
 * Navigation
 * ----------
 * What it is:   The screen at /posture: four summary lists — build and apparatus, identity
 *               and access, execution and egress, data and audit — read from `/version`,
 *               `/health` and (for admins) `/settings`. Secret values never appear: what is
 *               shown is the reference the deployment resolves at run time, and whether it
 *               is configured.
 * What it does: Answers the review board's questions on one page that prints: which
 *               instrument, which policies, how people sign in, where tests run, what leaves
 *               the tenant, what is retained, whether the ledger verifies. Rows an
 *               unprivileged viewer cannot see say so rather than guess.
 * How:          `useVersion`, `useHealth`, `useSettings(can('admin'))`, `useLedgerVerify`,
 *               `useGitHubApp`; every row is a fact from one of them.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0005-fail-closed-docker-sandbox.md, docs/adr/0006-zero-raw-retention-and-evidence-packs.md
 * Works with:   ui/src/components/govuk.tsx (SummaryList), ui/src/screens/Settings/SettingsPage.tsx,
 *               docs/SECURITY.md §2 (the trust boundaries these rows describe), docs/DEPLOYMENT.md
 * Tested by:    ui/src/components/govuk.test.tsx (the page is covered there)
 * Touch when:   a deployment fact is added to `/settings` that a review board would ask for.
 */

import type { ReactNode } from 'react'
import { useGitHubApp, useHealth, useLedgerVerify, useSettings, useVersion } from '../../api/hooks'
import { InsetText, Kicker, PageTitle, SummaryList, type SummaryRow } from '../../components/govuk'
import { useAuth } from '../../lib/auth'

export function PosturePage() {
  const { can } = useAuth()
  const version = useVersion()
  const health = useHealth()
  const settings = useSettings(can('admin'))
  const verify = useLedgerVerify()
  const gh = useGitHubApp()
  const probe = (name: string) => health.data?.probes.find((p) => p.name === name)
  const s = settings.data
  const adminOnly = (v: unknown): ReactNode => (can('admin') ? String(v ?? '—') : 'shown to admins')

  const groups: Array<{ name: string; rows: SummaryRow[] }> = [
    {
      name: 'Build and apparatus',
      rows: [
        { key: 'Version', value: version.data ? `crb ${version.data.crb}` : '…' },
        { key: 'Apparatus', value: version.data ? `${version.data.apparatus} · belt set v5 · routing ${version.data.policy}` : '…' },
        { key: 'Policies in force', value: `${version.data?.policy ?? '…'} (routing) · signoff-policy.v2` },
        { key: 'Licence', value: 'Apache-2.0' },
      ],
    },
    {
      name: 'Identity and access',
      rows: [
        { key: 'Sign-in', value: version.data ? (version.data.oidc_enabled ? 'OpenID Connect (organisation account) + local accounts' : 'Local accounts only') : '…' },
        { key: 'Roles', value: 'viewer · operator · approver · admin' },
        { key: 'Separation of duties', value: 'Sign-off needs the approver role and an attestation naming the diff read; keeping operator and approver on two people is the deployment’s policy (not enforced at write yet — backlog F7b)' },
        { key: 'Source control', value: !gh.data ? (gh.isError ? 'GitHub App status unavailable' : '…') : gh.data.configured ? `GitHub App ${gh.data.app_slug} · ${gh.data.installations.length} installation(s) · installation tokens minted per use, never stored` : 'GitHub App not configured — repositories connect by URL' },
      ],
    },
    {
      name: 'Execution and egress',
      rows: [
        { key: 'Test executor', value: s ? `${s.sandbox_mode}${s.sandbox_mode === 'docker' ? ' (sealed)' : ' — host posture: a development reading, not evidence'}` : `${probe('sandbox')?.status ?? '…'} (sandbox probe)` },
        { key: 'Builder posture', value: s ? adminOnly((s as unknown as { builder?: { executor?: string } }).builder?.executor ?? s.sandbox_mode) : adminOnly(undefined) },
        { key: 'Toolchains', value: probe('toolchains')?.detail ?? '…' },
        { key: 'Secrets', value: 'Read from the environment or mounted files; never persisted, never returned by the API' },
      ],
    },
    {
      name: 'Data and audit',
      rows: [
        { key: 'Raw retention', value: 'Zero by default. Worktrees and transcripts are opt-in per run.' },
        { key: 'Ledger', value: verify.data ? `Append-only, hash-chained · ${verify.data.rows} rows · ${verify.data.ok ? 'chain intact' : `chain broken at ${verify.data.broken_at ?? '?'}`} · false-Q1 ${verify.data.false_q1_total}` : (probe('ledger')?.detail ?? '…') },
        { key: 'Append-only triggers', value: probe('append_only')?.detail ?? '…' },
        { key: 'Export', value: 'JSONL export and evidence packs by hash' },
      ],
    },
  ]

  return (
    <>
      <div>
        <Kicker>For an architecture review board · printable</Kicker>
      </div>
      <PageTitle>About this deployment</PageTitle>
      {groups.map((g) => (
        <section key={g.name} className="mb-8 max-w-[60em]">
          <h2 className="mb-2 text-[24px] font-bold leading-[1.3]">{g.name}</h2>
          <SummaryList rows={g.rows} label={g.name} />
        </section>
      ))}
      <InsetText>
        <p className="m-0">Secret values are never shown, here or anywhere else in this interface. What is shown is the reference the deployment resolves at run time, and whether it is configured.</p>
      </InsetText>
    </>
  )
}
