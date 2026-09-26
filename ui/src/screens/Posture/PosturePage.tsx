/**
 * Deployment posture — "About this deployment", the printable page for an architecture review board.
 *
 * Navigation
 * ----------
 * What it is:   The screen at /posture: five summary lists — build and apparatus, identity
 *               and access, execution and egress, delivery, data and audit — read from
 *               `/version`, `/health`, `/github/app` and (for admins) `/settings`. Secret
 *               values never appear: what is shown is the reference the deployment resolves
 *               at run time, and whether it is configured.
 * What it does: Answers the review board's questions on one page that prints: which
 *               instrument, which policies, how people sign in, where tests run, what leaves
 *               the tenant, what the factory may write to a repository and under which gate,
 *               what is retained, whether the ledger verifies. Rows an unprivileged viewer
 *               cannot see say so rather than guess. Every row whose value is not the
 *               production posture ends with the next step: admins are linked to Settings,
 *               everyone to the guide (J-FAC-10).
 * How:          `useVersion`, `useHealth`, `useSettings(can('admin'))`, `useLedgerVerify`,
 *               `useGitHubApp`; every row is a fact from one of them; `<Term>` on the
 *               apparatus and belt words, `<DocLink>` for the next step.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0005-fail-closed-docker-sandbox.md, docs/adr/0006-zero-raw-retention-and-evidence-packs.md
 * Works with:   ui/src/components/govuk.tsx (SummaryList), ui/src/components/Help.tsx (`Term`,
 *               `DocLink`), ui/src/screens/Settings/SettingsPage.tsx (where an admin acts),
 *               src/crb/server/worker.py (`_delivery_credentials` — what the Delivery rows
 *               describe), src/crb/factory/loop.py (the route gate and the override event),
 *               docs/SECURITY.md §2 (the trust boundaries these rows describe), docs/DEPLOYMENT.md
 * Tested by:    ui/src/components/govuk.test.tsx (the page is covered there)
 * Touch when:   a deployment fact is added to `/settings` that a review board would ask for;
 *               delivery grows a new write (add the row here and in docs/GITHUB-APP.md §5).
 */

import type { ReactNode } from 'react'
import { Link } from 'react-router'
import { useGitHubApp, useHealth, useLedgerVerify, useSettings, useVersion } from '../../api/hooks'
import { DocLink, Term } from '../../components/Help'
import { Hint } from '../../components/Hint'
import { InsetText, Kicker, PageTitle, SummaryList, type SummaryRow } from '../../components/govuk'
import { useAuth } from '../../lib/auth'

/** The next step after a value that is not the production posture: the sentence, the guide, and Settings for an admin. */
function NextStep({ children, admin, doc }: { children: ReactNode; admin: boolean; doc?: ReactNode }) {
  return (
    <span className="block text-[16px] leading-[1.5] text-on-surface-muted">
      {children}
      {doc ? <> ({doc})</> : null}
      {admin ? (
        <>
          {' '}
          ·{' '}
          <Hint as={Link} id="link.posture.settings" to="/settings">
            Settings
          </Hint>
        </>
      ) : null}
    </span>
  )
}

export function PosturePage() {
  const { can } = useAuth()
  const version = useVersion()
  const health = useHealth()
  const settings = useSettings(can('admin'))
  const verify = useLedgerVerify()
  const gh = useGitHubApp()
  const probe = (name: string) => health.data?.probes.find((p) => p.name === name)
  // a probe's sentence, or why there is none: "…" while loading, and the truth when the health
  // check itself could not be read (never a silent ellipsis)
  const probeText = (name: string) => (health.isError ? 'the health check could not be read' : (probe(name)?.detail ?? '…'))
  const s = settings.data
  const admin = can('admin')
  const adminOnly = (v: unknown): ReactNode => (admin ? String(v ?? '—') : 'shown to admins')

  // the executor as the deployment reports it: the admin's settings when they answer,
  // else the health probe's own `executor` (never a guess)
  const executor = s ? s.sandbox_mode : String(probe('sandbox')?.data?.executor ?? '')
  const executorKnown = s !== undefined || probe('sandbox') !== undefined
  const sandboxDoc = <DocLink to="DEPLOYMENT#34-the-workers-sandbox--choose-deliberately">Sandbox (DEPLOYMENT)</DocLink>
  const installations = gh.data?.installations ?? []
  const canDeliver = installations.filter((i) => i.can_deliver && !i.suspended).length

  const groups: Array<{ name: string; rows: SummaryRow[] }> = [
    {
      name: 'Build and apparatus',
      rows: [
        { key: 'Version', hint: 'summary.posture.version', value: version.data ? `crb ${version.data.crb}` : '…' },
        {
          key: <Term id="apparatus">Apparatus</Term>,
          hint: 'summary.posture.apparatus',
          value: version.data ? (
            <>
              {version.data.apparatus} · <Term id="belt">belt set</Term> v5 · routing {version.data.policy}
            </>
          ) : (
            '…'
          ),
        },
        { key: 'Policies in force', hint: 'summary.posture.policies', value: `${version.data?.policy ?? '…'} (routing) · signoff-policy.v3` },
        { key: 'Licence', hint: 'summary.posture.licence', value: 'Apache-2.0' },
      ],
    },
    {
      name: 'Identity and access',
      rows: [
        {
          key: 'Sign-in',
          hint: 'summary.posture.sign_in',
          value: !version.data ? (
            '…'
          ) : version.data.oidc_enabled ? (
            'OpenID Connect (organisation account) + local accounts'
          ) : (
            <>
              Local accounts only.{' '}
              <NextStep admin={admin} doc={<DocLink to="DEPLOYMENT#41-entra-id--crboidc">Entra ID (DEPLOYMENT)</DocLink>}>
                To sign people in with the organisation account configure OpenID Connect (<code>CRB_OIDC__*</code>) on the API.
              </NextStep>
            </>
          ),
        },
        { key: 'Roles', hint: 'summary.posture.roles', value: 'viewer · operator · approver · admin' },
        { key: 'Separation of duties', hint: 'summary.posture.separation', value: 'Enforced at write: the API refuses a sign-off (409 same_actor) when the approver queued the run that produced the attested row, or is the only person behind the cell — never overridable by any setting; every record says what kind of account signed (verifier_kind)' },
        {
          key: 'Source control',
          hint: 'summary.posture.source_control',
          value: !gh.data ? (
            gh.isError ? (
              'GitHub App status unavailable'
            ) : (
              '…'
            )
          ) : gh.data.configured ? (
            `GitHub App ${gh.data.app_slug} · ${installations.length} installation(s) · installation tokens minted per use, never stored`
          ) : (
            <>
              GitHub App not configured — repositories connect by URL.{' '}
              <NextStep admin={admin} doc={<DocLink to="GITHUB-APP#2-register-the-app-once-per-deployment">Register the app (GITHUB-APP)</DocLink>}>
                To clone private repositories and deliver pull requests register the app once for this deployment and install it on the organisation.
              </NextStep>
            </>
          ),
        },
      ],
    },
    {
      name: 'Execution and egress',
      rows: [
        {
          key: 'Test executor',
          hint: 'summary.posture.executor',
          value: !executorKnown ? (
            '…'
          ) : executor === 'docker' ? (
            'docker (sealed)'
          ) : executor === '' ? (
            // the probe answered without naming its executor (an API-role process): the
            // status is all this reader gets; the executor itself is in the admin's settings
            `${probe('sandbox')?.status ?? 'unknown'} (sandbox probe)${admin ? '' : ' — the executor is shown to admins'}`
          ) : (
            <>
              {executor} — a development reading, not evidence.{' '}
              <NextStep admin={admin} doc={sandboxDoc}>
                To count runs as evidence set <code className="break-all">CRB_SANDBOX_MODE=docker</code> on the worker; without a sealed executor nothing measured is evidence.
              </NextStep>
            </>
          ),
        },
        {
          key: 'Dependency provisioning',
          hint: 'summary.posture.provisioning',
          value: s
            ? adminOnly(
                s.raw?.provision?.enabled
                  ? 'on — each task’s dependencies are fetched outside the test container and mounted read-only'
                  : 'off — a repository whose tests need a third-party module cannot be qualified in the sealed sandbox, and the Posture panel says so instead of blaming the model',
              )
            : adminOnly(undefined),
        },
        { key: 'Builder posture', hint: 'summary.posture.builder', value: s ? adminOnly(s.raw?.builder?.executor ? `${s.raw.builder.executor}${s.raw.builder.egress_network ? ` · egress ${s.raw.builder.egress_network}` : ''}` : 'not reported by this deployment') : adminOnly(undefined) },
        { key: 'Toolchains', hint: 'summary.posture.toolchains', value: probeText('toolchains') },
        {
          key: 'Worker',
          hint: 'summary.posture.worker',
          // the worker probe's own sentence (queued runs, last check-in, a stopped worker):
          // degraded, never a 503 — the API pod's readiness is not the worker's liveness
          value: (
            <>
              {probeText('worker')}
              {probe('worker') && probe('worker')!.status !== 'ok' && (
                <>
                  {' '}
                  <NextStep admin={admin} doc={<DocLink to="DEPLOYMENT#9-observability">Observability (DEPLOYMENT)</DocLink>}>
                    Start a worker, or find why the running one stopped checking in; queued runs wait until one does.
                  </NextStep>
                </>
              )}
            </>
          ),
        },
        { key: 'Secrets', hint: 'summary.posture.secrets', value: 'Read from the environment or mounted files; never persisted, never returned by the API' },
      ],
    },
    {
      name: 'Delivery',
      rows: [
        { key: 'Writes', hint: 'summary.posture.writes', value: 'a branch named by the item and one pull request against the repository’s default branch; the factory never writes to the default branch' },
        {
          key: 'Permissions',
          hint: 'summary.posture.permissions',
          value: !gh.data ? (
            '…'
          ) : !gh.data.configured ? (
            <>
              the GitHub App installation must hold Contents: write and Pull requests: write; installations without them measure only. No app is configured, so no repository can deliver.{' '}
              <NextStep admin={admin} doc={<DocLink to="GITHUB-APP#5-what-happens-at-clone-and-at-delivery">What happens at delivery (GITHUB-APP)</DocLink>}>
                Register and install the app, then Sync installations.
              </NextStep>
            </>
          ) : (
            <>
              the GitHub App installation must hold Contents: write and Pull requests: write; installations without them measure only ({canDeliver} of {installations.length} installations can deliver).
              {canDeliver < installations.length ? (
                <>
                  {' '}
                  <NextStep admin={admin} doc={<DocLink to="GITHUB-APP#5-what-happens-at-clone-and-at-delivery">What happens at delivery (GITHUB-APP)</DocLink>}>
                    Grant both permissions on the installation in GitHub, then Sync installations.
                  </NextStep>
                </>
              ) : null}
            </>
          ),
        },
        { key: 'Route gate', hint: 'summary.posture.route_gate', value: `a pull request opens only for a cell the capability map routes deliver under ${version.data?.policy ?? '…'}` },
        { key: 'Override', hint: 'summary.posture.override', value: 'an approver may override the gate for one run; the override is an event on the chain naming the approver and the route it overrode' },
        { key: 'Credentials', hint: 'summary.posture.credentials', value: 'installation tokens minted per push, never stored' },
      ],
    },
    {
      name: 'Data and audit',
      rows: [
        { key: 'Raw retention', hint: 'summary.posture.retention', value: 'Zero by default. Worktrees and transcripts are opt-in per run.' },
        {
          key: 'Ledger',
          hint: 'summary.posture.ledger',
          value: !verify.data ? (
            probeText('ledger')
          ) : verify.data.ok ? (
            `Append-only, hash-chained · ${verify.data.rows} rows · chain intact · false-Q1 ${verify.data.false_q1_total}`
          ) : (
            <>
              Append-only, hash-chained · {verify.data.rows} rows · chain broken at {verify.data.broken_at ?? '?'} · false-Q1 {verify.data.false_q1_total}.{' '}
              <NextStep admin={admin} doc={<DocLink to="OPERATOR#6-export-and-verify-the-ledger">Export and verify the ledger (OPERATOR)</DocLink>}>
                Stop writing and verify the ledger from the export (<code>crb ledger verify</code>); a broken chain is a finding, never repaired in place.
              </NextStep>
            </>
          ),
        },
        { key: 'Append-only triggers', hint: 'summary.posture.append_only', value: probeText('append_only') },
        { key: 'Export', hint: 'summary.posture.export', value: 'JSONL export and evidence packs by hash' },
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
        <section key={g.name} className="mb-8 max-w-[60em]" aria-labelledby={`posture-${g.name.replace(/\s+/g, '-').toLowerCase()}`}>
          <h2 id={`posture-${g.name.replace(/\s+/g, '-').toLowerCase()}`} className="mb-2 text-[24px] font-bold leading-[1.3]">
            {g.name}
          </h2>
          <SummaryList rows={g.rows} label={g.name} />
        </section>
      ))}
      <InsetText>
        <p className="m-0">Secret values are never shown, here or anywhere else in this interface. What is shown is the reference the deployment resolves at run time, and whether it is configured.</p>
      </InsetText>
    </>
  )
}
