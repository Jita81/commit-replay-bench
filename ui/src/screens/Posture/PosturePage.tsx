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
 *               instrument, which policies, how people sign in, where tests and the builder
 *               run and whether production runs unsealed under CRB_ALLOW_UNSEALED_PROD
 *               (ADR-0023, from `/health`, to every viewer), what leaves
 *               the tenant, what the factory may write to a repository and under which gate,
 *               what is retained, whether the ledger verifies. Rows an unprivileged viewer
 *               cannot see say so rather than guess. Every row whose value is not the
 *               production posture ends with the next step: admins are linked to Settings,
 *               everyone to the guide (J-FAC-10).
 * How:          `useVersion`, `useHealth`, `useSettings(can('admin'))`, `useLedgerVerify`,
 *               `useGitHubApp`; every row is a fact from one of them; `<Term>` on the
 *               apparatus and belt words, `<DocLink>` for the next step.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0005-fail-closed-docker-sandbox.md,
 *               docs/adr/0006-zero-raw-retention-and-evidence-packs.md,
 *               docs/adr/0023-production-refuses-the-unsealed-posture.md
 * Works with:   ui/src/components/govuk.tsx (SummaryList), ui/src/components/Help.tsx (`Term`,
 *               `DocLink`), ui/src/screens/Settings/SettingsPage.tsx (where an admin acts),
 *               src/crb/server/worker.py (`_delivery_credentials` — what the Delivery rows
 *               describe), src/crb/factory/loop.py (the route gate, the sign-off clause of
 *               ADR-0018 and the override event),
 *               ui/src/components/FlowPanel.tsx (the platform stream's own recovery lead time),
 *               docs/SECURITY.md §2 (the trust boundaries these rows describe), docs/DEPLOYMENT.md
 * Tested by:    ui/src/components/govuk.test.tsx (the page is covered there)
 * Touch when:   never for a new repository; a deployment fact is added to `/settings` that a review
 *               board would ask for; delivery grows a new write (add the row here and in
 *               docs/GITHUB-APP.md §5).
 */

import type { ReactNode } from 'react'
import { Link } from 'react-router'
import { useAllRepos, useGitHubApp, useHealth, useLedgerVerify, useSettings, useVersion } from '../../api/hooks'
import type { DeploymentPosture } from '../../api/types'
import { Button } from '../../components/Button'
import { FlowPanel } from '../../components/FlowPanel'
import { DocLink, Term } from '../../components/Help'
import { Hint } from '../../components/Hint'
import { InsetText, Kicker, PageTitle, SummaryList, type SummaryRow } from '../../components/govuk'
import { useAuth } from '../../lib/auth'
import { deployEyebrow } from '../../lib/deployJourney'
import { GoLiveList } from './GoLiveList'

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

const POSTURE_DOC = <DocLink to="DEPLOYMENT#21-environment-reference">Environment reference (DEPLOYMENT)</DocLink>

/**
 * Where each row's value comes from (G-212): a live read of the API, or — for a row that states
 * a rule — the code that enforces it, so a review board can check every line of the statement.
 */
const SRC = {
  version: 'Source: GET /version, read now',
  health: 'Source: GET /health, read now',
  settings: 'Source: GET /settings, read now (admins only)',
  github: 'Source: GET /github/app, read now',
  ledger: 'Source: GET /ledger/verify, read now',
  licence: 'Source: GET /version — the package’s licence in pyproject.toml',
  roles: 'Source: the role ladder in the code (src/crb/server/settings.py, ROLE_LADDER), enforced on every route',
  separation: 'Source: the sign-off policy in the code (src/crb/core/signoff.py), refused at write',
  secrets: 'Source: the settings and secrets code (src/crb/server/settings.py, src/crb/server/secrets.py)',
  delivery: 'Source: the delivery code (src/crb/server/worker.py and docs/GITHUB-APP.md §5)',
  override: 'Source: the route gate in the code (src/crb/factory/loop.py), each override an event',
  retention: 'Source: the retention settings (docs/DATA-RETENTION.md §2, ADR-0006)',
  export: 'Source: the ledger routes (src/crb/server/routes/ledger.py)',
} as const

/**
 * What happens to a factory run (ADR-0023), said after a sealed posture: a factory build runs
 * the builder on the host and is never sealed, so production refuses it unless the override
 * is set — and then every factory run's apparatus carries it.
 */
function factoryClause(p: DeploymentPosture): string {
  if (p.factory_builds === 'refused')
    return '; in production factory runs are refused, because factory builds run the builder on the host and are not sealed yet'
  if (p.factory_builds === 'host' && p.env === 'prod')
    return "; factory builds run on the host under CRB_ALLOW_UNSEALED_PROD=1, and every factory run's apparatus carries the override"
  if (p.factory_builds === 'host') return '; factory builds run on the host'
  return ''
}

/**
 * The production posture row (ADR-0023), from `/health` so every viewer sees it: sealed, a
 * development reading in dev, or production running unsealed under the override — never
 * silent about the override, because every run's apparatus carries it.
 */
function postureValue(p: DeploymentPosture | undefined, failed: boolean, admin: boolean): ReactNode {
  if (!p) return failed ? 'the health check could not be read' : 'not reported by this deployment'
  if (p.sealed) return `sealed — tests and the builder run in docker${factoryClause(p)}`
  const where = `tests run ${p.sandbox_executor}, the builder runs ${p.builder_executor}`
  if (p.unsealed_prod_override) {
    return (
      <>
        unsealed in production under CRB_ALLOW_UNSEALED_PROD=1 — {where}; every run's apparatus carries the override, and what it measures is a development reading, not evidence.{' '}
        <NextStep admin={admin} doc={POSTURE_DOC}>
          Remove CRB_ALLOW_UNSEALED_PROD and set both executors to docker on the API and the worker.
        </NextStep>
      </>
    )
  }
  return (
    <>
      development ({p.env}) — {where}: a development reading, not evidence.{' '}
      <NextStep admin={admin} doc={POSTURE_DOC}>
        To count runs as evidence run with CRB_ENV=prod, where both executors default to docker.
      </NextStep>
    </>
  )
}

export function PosturePage() {
  const { can } = useAuth()
  const version = useVersion()
  const health = useHealth()
  const settings = useSettings(can('admin'))
  const verify = useLedgerVerify()
  const gh = useGitHubApp()
  // any connected repository keys the flow reading; the platform stream's figures are the
  // deployment's own, so which one it is does not change them
  const anyRepo = useAllRepos().data?.items[0]?.name ?? ''
  const probe = (name: string) => health.data?.probes.find((p) => p.name === name)
  // a probe's sentence, or why there is none: "…" while loading, and the truth when the health
  // check itself could not be read (never a silent ellipsis)
  const probeText = (name: string) => (health.isError ? 'the health check could not be read' : (probe(name)?.detail ?? '…'))
  // a version value, or why there is none: "…" while loading, and a sentence when /version
  // itself could not be read (G-212 — never a silent ellipsis for ever)
  const v = (value: string | undefined): string =>
    value !== undefined ? value : version.isError ? 'the version could not be read' : version.data ? 'not reported by this deployment' : '…'
  const s = settings.data
  const admin = can('admin')
  // ADR-0018 — the delivery licence posture, from the deployment's own settings; `undefined`
  // when this reader is not an admin (the settings query is not even issued for them)
  const signedCellRequired = s?.raw?.factory?.require_signed_cell
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
        { key: 'Version', hint: 'summary.posture.version', value: version.data ? `crb ${version.data.crb}` : v(undefined), note: SRC.version },
        {
          key: <Term id="apparatus">Apparatus</Term>,
          hint: 'summary.posture.apparatus',
          value: version.data ? (
            <>
              {version.data.apparatus} · <Term id="belt">belt set</Term> {v(version.data.belt_set)} · routing {version.data.policy}
            </>
          ) : (
            v(undefined)
          ),
          note: SRC.version,
        },
        { key: 'Policies in force', hint: 'summary.posture.policies', value: `${v(version.data?.policy)} (routing) · ${v(version.data?.signoff_policy)}`, note: SRC.version },
        { key: 'Licence', hint: 'summary.posture.licence', value: v(version.data?.licence), note: SRC.licence },
      ],
    },
    {
      name: 'Identity and access',
      rows: [
        {
          key: 'Sign-in',
          hint: 'summary.posture.sign_in',
          note: SRC.version,
          value: !version.data ? (
            v(undefined)
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
        { key: 'Roles', hint: 'summary.posture.roles', value: 'viewer · operator · approver · admin', note: SRC.roles },
        { key: 'Separation of duties', hint: 'summary.posture.separation', value: 'Enforced at write: the API refuses a sign-off (409 same_actor) when the approver queued the run that produced the attested row, or is the only person behind the cell — never overridable by any setting; every record says what kind of account signed (verifier_kind)', note: SRC.separation },
        {
          key: 'Source control',
          hint: 'summary.posture.source_control',
          note: SRC.github,
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
          note: s ? SRC.settings : SRC.health,
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
          key: 'Production posture',
          hint: 'summary.posture.production',
          note: SRC.health,
          value: postureValue(health.data?.posture, health.isError, admin),
        },
        {
          key: 'Dependency provisioning',
          hint: 'summary.posture.provisioning',
          note: SRC.settings,
          value: s
            ? adminOnly(
                s.raw?.provision?.enabled
                  ? 'on — each task’s dependencies are fetched outside the test container and mounted read-only'
                  : 'off — a repository whose tests need a third-party module cannot be qualified in the sealed sandbox, and the Posture panel says so instead of blaming the model',
              )
            : adminOnly(undefined),
        },
        { key: 'Builder posture', hint: 'summary.posture.builder', note: SRC.settings, value: s ? adminOnly(s.raw?.builder?.executor ? `${s.raw.builder.executor}${s.raw.builder.egress_network ? ` · egress ${s.raw.builder.egress_network}` : ''}` : 'not reported by this deployment') : adminOnly(undefined) },
        { key: 'Toolchains', hint: 'summary.posture.toolchains', value: probeText('toolchains'), note: SRC.health },
        {
          key: 'Worker',
          hint: 'summary.posture.worker',
          note: SRC.health,
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
        { key: 'Secrets', hint: 'summary.posture.secrets', value: 'Read from the environment or mounted files; never persisted, never returned by the API', note: SRC.secrets },
      ],
    },
    {
      name: 'Delivery',
      rows: [
        { key: 'Writes', hint: 'summary.posture.writes', value: 'a branch named by the item and one pull request against the repository’s default branch; the factory never writes to the default branch', note: SRC.delivery },
        {
          key: 'Permissions',
          hint: 'summary.posture.permissions',
          note: SRC.github,
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
        { key: 'Route gate', hint: 'summary.posture.route_gate', value: `a pull request opens only for a cell the capability map routes deliver under ${v(version.data?.policy)}`, note: SRC.version },
        // ADR-0018 — the second clause of the same gate. Admins read the deployment's own
        // setting; everyone else reads the default, which is what a deployment that has not
        // changed it is running. Never presented as "on" without having read it.
        {
          key: 'Delivery licence',
          hint: 'summary.posture.delivery_licence',
          note: SRC.settings,
          // no bare environment-variable token in a viewer's row: an unbreakable name this
          // long sets the summary list's min-content width and the page scrolls sideways at
          // 375 px (J-FAC-14). The admin's row prints it with break-all, as the sandbox row does.
          value: signedCellRequired === undefined ? (admin ? '…' : 'a signed cell as well as a deliver route, unless this deployment has turned that off — the setting itself is shown to admins') : signedCellRequired ? 'a signed cell as well as a deliver route: the factory does not build an item until a person has signed off its cell’s proven standard, on the current apparatus (a sign-off expires with the apparatus)' : (
            <>
              the route alone — this deployment has turned the sign-off clause off (<code className="break-all">CRB_FACTORY__REQUIRE_SIGNED_CELL=false</code>), so a measured cell licenses a pull request with no human attestation.{' '}
              <NextStep admin={admin} doc={<DocLink to="ONBOARDING-A-REPO#step-7--sign-off-approver">Sign off (ONBOARDING)</DocLink>}>
                To require a person before any pull request, unset it.
              </NextStep>
            </>
          ),
        },
        { key: 'Override', hint: 'summary.posture.override', value: 'a second approver — never the person who queued the run — may lift the sign-off clause for one run, and never the route; the override is an event on the chain naming the approver and the clause. It licenses one run and is never an attestation of the cell', note: SRC.override },
        { key: 'Credentials', hint: 'summary.posture.credentials', value: 'installation tokens minted per push, never stored', note: SRC.delivery },
      ],
    },
    {
      name: 'Data and audit',
      rows: [
        { key: 'Raw retention', hint: 'summary.posture.retention', value: 'Zero by default. Worktrees and transcripts are opt-in per run.', note: SRC.retention },
        {
          key: 'Ledger',
          hint: 'summary.posture.ledger',
          note: SRC.ledger,
          value: !verify.data ? (
            probeText('ledger')
          ) : verify.data.ok ? (
            `Append-only, hash-chained · ${verify.data.rows} rows · chain intact · false-Q1 ${verify.data.false_q1_total}`
          ) : (
            <>
              Append-only, hash-chained · {verify.data.rows} rows · {verify.data.chain_ok ? 'chain intact' : `chain broken at ${verify.data.broken_at ?? '?'}`} · false-Q1 {verify.data.false_q1_total}
              {verify.data.events.chain_ok ? '' : ` · audit trail broken at event ${verify.data.events.broken_at ?? '?'}`}
              {verify.data.clean_without_pack > 0 ? ` · ${verify.data.clean_without_pack} clean rows without a pack` : ''}.{' '}
              <NextStep admin={admin} doc={<DocLink to="OPERATOR#6-export-and-verify-the-ledger">Export and verify the ledger (OPERATOR)</DocLink>}>
                {verify.data.events.chain_ok ? (
                  <>Stop writing and verify the ledger from the export (<code>crb ledger verify</code>); a broken chain is a finding, never repaired in place.</>
                ) : (
                  <>Stop writing and verify the store itself (<code>crb ledger verify --store</code>): the export holds the grades only, so it cannot show a break in the audit trail. A broken chain is a finding, never repaired in place.</>
                )}
              </NextStep>
            </>
          ),
        },
        { key: 'Append-only triggers', hint: 'summary.posture.append_only', value: probeText('append_only'), note: SRC.health },
        { key: 'Export', hint: 'summary.posture.export', value: 'JSONL export and evidence packs by hash', note: SRC.export },
      ],
    },
  ]

  return (
    <>
      <Hint as="div" id="nav.deploy_position" className="label">
        {deployEyebrow('/posture')}
      </Hint>
      <div className="flex flex-wrap items-center gap-4">
        <Kicker>For an architecture review board · printable</Kicker>
        <Button size="sm" variant="outlined" className="print:hidden" hint="button.posture.print" onClick={() => window.print()} data-testid="posture-print">
          Print this page
        </Button>
      </div>
      <PageTitle>About this deployment</PageTitle>
      <GoLiveList admin={admin} />
      {groups.map((g) => (
        <section key={g.name} className="mb-8 max-w-[60em]" aria-labelledby={`posture-${g.name.replace(/\s+/g, '-').toLowerCase()}`}>
          <h2 id={`posture-${g.name.replace(/\s+/g, '-').toLowerCase()}`} className="mb-2 text-[24px] font-bold leading-[1.3]">
            {g.name}
          </h2>
          <SummaryList rows={g.rows} label={g.name} />
        </section>
      ))}
      {/* The platform stream's own numbers (docs/dod/streams/run-the-platform.md MEASURE).
          They are the DEPLOYMENT's — accounts and recoveries, not one repository's — but the
          reading is keyed by a repository because the other five streams are, so this uses any
          connected one; with none connected there is nothing yet to read. */}
      <FlowPanel stream="run-the-platform" repo={anyRepo} title="How this flows: running the platform" />
      <InsetText>
        <p className="m-0">Secret values are never shown, here or anywhere else in this interface. What is shown is the reference the deployment resolves at run time, and whether it is configured.</p>
      </InsetText>
    </>
  )
}
