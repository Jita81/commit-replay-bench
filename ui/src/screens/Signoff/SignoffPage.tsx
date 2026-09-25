/**
 * Sign-off — a human attestation that a cell's evidence is trusted; a policy decision refused at
 * write (/signoff).
 *
 * Navigation
 * ----------
 * What it is:   The screen at /signoff: the gate (criteria derived from the server's preview),
 *               the evidence panel (what you would be signing), the attestation form (name an
 *               accepted row, affirm you read it, a statement) and the table of recorded
 *               attestations with their snapshots. The header says in two sentences what the
 *               screen is for; the refusal clauses sit behind a Details ("Why a sign-off can
 *               be refused") with each term defined, because the gate and the refusal list
 *               below already explain every clause with observed vs threshold.
 * What it does: Shows the bar before the approver tries: the preview's refusals become the
 *               gate's check-rows with observed vs threshold, and non-overridable clauses
 *               (false-Q1, oracle unmeasured, attestation missing, same actor) are marked so —
 *               the *Signed by a second person* row is pending (○), not satisfied, until a row
 *               is named, because the attested row is judged only then; the action is
 *               disabled until the preview says `signable` AND the approver has named a
 *               row, ticked "I have read this accepted diff" and written a statement. Every
 *               recorded sign-off carries a `verifier_kind` tag next to the approver (local
 *               account / identity provider / service — delegated, not a person / kind not
 *               recorded) with its meaning on hover. A 409
 *               from the POST renders as a REFUSED gate with the clauses (the false-Q1 floor
 *               points at the ledger); a pre-policy record is listed honestly without a
 *               fabricated snapshot; an approver can revoke — Revoke opens a confirmation that
 *               takes focus (its reason field) and, left by Cancel, gives focus back to the
 *               Revoke button that opened it (G-905). A reader without the approver
 *               role gets the gate, the evidence and the attestations and never the form —
 *               an inset says who can sign and that reading changes nothing. Reached without
 *               `?repo=`, the screen chooses the most recently updated repository itself;
 *               with no repository at all the exit is Connect. Every element a reader meets
 *               — the Details, the gate and each of its clauses, each refusal and its
 *               non-overridable mark, the four evidence tiles and the three evidence blocks,
 *               every field of the form, the diff block and its two doors, the confirmation
 *               panel, every column of the attestations table, each status pill and the
 *               revoke flow — is a hint trigger (`details.signoff.*`, `gate.signoff.*`,
 *               `tile.signoff.*`, `pill.signoff.*`, `stat.signoff.*`, `field.signoff.*`,
 *               `button.signoff.*`, `banner.signoff.*`, `col.signoff.*`); no native `title`
 *               remains (the attestation statement is shown under its row, not on hover).
 * How:          `useCapabilityMapWithControls` lists the measured cells → `useSignoffPreview`
 *               re-fetches as cell / row change (the named row and affirmation reset when the
 *               cell changes) → `criteriaFor(preview)` → `GateBanner`;
 *               `useCreateSignoffWithAttestation`
 *               posts; `useSignoffs` lists.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0003-one-routing-rule.md,
 *               docs/adr/0001-four-belts-and-false-q1-at-write.md
 * Works with:   ui/src/screens/Signoff/contract.ts (preview, policy, refusal vocabulary,
 *               the 409 shape), ui/src/components/GateBanner.tsx (the gate),
 *               ui/src/components/RepoPicker.tsx (`defaultToLatest`),
 *               ui/src/components/Help.tsx (`Term` in the refusal clauses),
 *               ui/src/help/hints.ts (the `*.signoff.*` copy; the trigger is `Hint`),
 *               ui/src/screens/Capability/FailureSplit.tsx (the controls pill and the split),
 *               ui/src/api/hooks.ts (`useSignoffs`, `useRevokeSignoff`),
 *               src/crb/server/routes/signoffs.py (the server's decision this screen
 *               previews and submits; the core rule it applies is the policy module it names)
 * Tested by:    ui/src/screens/Signoff/SignoffPage.test.tsx, ui/src/help/hints-ratchet.test.tsx
 *               (every element resolves to a registry id), ui/e2e/walkthrough/08-signoff.spec.ts
 *               (a thin cell refused with observed vs threshold; a policy-clearing cell
 *               signed with an attestation), ui/e2e/walkthrough/05-replay-fake.spec.ts
 * Touch when:   a refusal clause or a policy threshold is added (src/crb/core/signoff.py) —
 *               add the gate row in `criteriaFor` and the vocabulary in
 *               ui/src/screens/Signoff/contract.ts; never for a new repository.
 * Claims:       A sign-off lifts the verification tier, never the route; it is refused
 *               outright on any false-Q1 row
 *               (docs/EVIDENCE-AND-CLAIMS.md#6a-what-a-signed-cell-may-be-claimed-to-mean-signoff-policyv2).
 */
import { useEffect, useId, useMemo, useRef, useState, type FormEvent } from 'react'
import { Link, useSearchParams } from 'react-router'
import { useEvidence, useRevokeSignoff, useSignoffs } from '../../api/hooks'
import { PatchView } from '../Runs/EvidenceDrawer'
import { useRetainedPatch } from '../Runs/contract'
import type { AcceptedRow } from './contract'
import { approverName, NOT_YET_MEASURED } from '../../api/types'
import { Button, LinkButton } from '../../components/Button'
import { Card } from '../../components/Card'
import { CiBar } from '../../components/CiBar'
import { DataTable, type Column } from '../../components/DataTable'
import { EmptyState } from '../../components/EmptyState'
import { ErrorState } from '../../components/ErrorState'
import { SelectField, TextArea } from '../../components/Field'
import { GateBanner, type GateCriterion } from '../../components/GateBanner'
import { ConfirmationPanel, Details, InsetText, SecondaryButton, SummaryList, WarningButton, WarningCallout } from '../../components/govuk'
import { Term } from '../../components/Help'
import { Hint } from '../../components/Hint'
import { PageHeader } from '../../components/PageHeader'
import { Pill } from '../../components/Pill'
import { Provenance } from '../../components/Provenance'
import { QueryBoundary } from '../../components/QueryBoundary'
import { RepoPicker, useRepoParam } from '../../components/RepoPicker'
import { StatTile } from '../../components/StatTile'
import { VerdictPill } from '../../components/VerdictPill'
import { useAuth } from '../../lib/auth'
import { fmtDate, fmtInt, fmtPct, fmtRatio, shortId } from '../../lib/format'
import { controlsDisplay, useCapabilityMapWithControls, type CapabilityCellSplit } from '../Capability/contract'
import { ControlsPill, FailureSplitPills, ModelPointLine } from '../Capability/FailureSplit'
import {
  REFUSAL_DISPLAY,
  SIGNOFF_POLICY_VERSION,
  fmtBound,
  isSignoffRefused,
  refusalFamily,
  useCreateSignoffWithAttestation,
  useSignoffPreview,
  type SignoffPreview,
  type SignoffRefusal,
  type SignoffWithPolicy,
} from './contract'

/** `class · size[ · language · model]`, skipping `*` (unprojected) fields. */
const cellLabel = (c: Record<string, string>) => [c.capability_class, c.size, c.language, c.model].filter((v) => v && v !== '*').join(' · ')

/** The gate's check-rows, derived from the preview's refusals — never asserted. */
function criteriaFor(preview: SignoffPreview | undefined, cellChosen: boolean, attested: boolean): GateCriterion[] {
  if (!preview) {
    return [
      { label: 'Cell is measured', ok: null, detail: cellChosen ? 'evaluating…' : 'choose a measured cell', hint: 'gate.signoff.measured' },
      { label: 'false-Q1 = 0', ok: null, hint: 'gate.signoff.false_q1' },
      { label: `Evidence meets ${SIGNOFF_POLICY_VERSION}`, ok: null, hint: 'gate.signoff.thin_cell' },
      { label: 'Negative controls passed', ok: null, hint: 'gate.signoff.controls' },
      { label: 'Route = deliver', ok: null, hint: 'gate.signoff.route' },
      { label: 'Accepted row read and affirmed', ok: null, hint: 'gate.signoff.attestation' },
      { label: 'Signed by a second person', ok: null, hint: 'gate.signoff.second_person' },
    ]
  }
  const fam = new Set(preview.refusals.map((r) => refusalFamily(r.code)))
  const p = preview.policy
  const ev = preview.evidence
  const c = preview.controls
  const cd = controlsDisplay(c, p.min_constructible_share)
  const oracle = ev.oracle_strength
  const scored = ev.oracle ? `${ev.oracle.scored} of ${ev.oracle.tasks} task(s) scored` : ''
  return [
    { label: 'Cell is measured', ok: ev.measured, detail: `n = ${fmtInt(ev.n)}`, hint: 'gate.signoff.measured' },
    { label: 'false-Q1 = 0', ok: !fam.has('false_q1') && ev.false_q1 === 0, detail: `false_q1 = ${ev.false_q1}`, hint: 'gate.signoff.false_q1' },
    { label: `n ≥ ${p.n_min}`, ok: !fam.has('thin_cell'), detail: `n = ${fmtInt(ev.n)} · point ${fmtPct(ev.point)} · Wilson lower ${fmtPct(ev.ci_low)}`, hint: 'gate.signoff.thin_cell' },
    {
      label: `Negative controls passed, ≤ ${p.max_controls_escapes} escape(s), ≥ ${fmtPct(p.min_constructible_share, 0)} constructible`,
      ok: !fam.has('controls_unmeasured') && !fam.has('controls_failed') && !fam.has('controls_escapes') && !fam.has('controls_thin'),
      detail: c.measured ? `${cd.label} · ${c.constructible} of ${c.total} · ${c.escapes} escape(s) · run ${shortId(c.run_id)} · ${fmtDate(c.created)}` : 'never run for this repo',
      hint: 'gate.signoff.controls',
    },
    {
      label: `Oracle strength measured and ≥ ${fmtRatio(p.min_oracle_strength)}`,
      ok: !fam.has('oracle_unmeasured') && !fam.has('oracle_weak'),
      detail: oracle === null ? `unmeasured — no task of this cell has a mutation score (${scored || 'none'}); run an oracle run — non-overridable` : `strength ${fmtRatio(oracle)}${scored ? ` · ${scored}` : ''}`,
      hint: 'gate.signoff.oracle',
    },
    { label: 'Route = deliver', ok: !fam.has('route_not_deliver'), detail: `${preview.route.route}${preview.route.reason_code ? ` (${preview.route.reason_code})` : ''}`, hint: 'gate.signoff.route' },
    { label: 'Accepted row read and affirmed', ok: !fam.has('attestation_missing') && attested, detail: preview.attestation ? `${shortId(preview.attestation.reviewed_row_hash)} · ${preview.attestation.subject || preview.attestation.reviewed_task_id}` : 'pick a row below and tick “I have read this accepted diff”', hint: 'gate.signoff.attestation' },
    {
      label: 'Signed by a second person',
      hint: 'gate.signoff.second_person',
      // a refusal is a fact either way; a pass is only a fact once the row is named — until
      // then the preview has judged the cell's evidence (ground 2), not the attested row
      ok: fam.has('same_actor') ? false : preview.attestation ? true : null,
      detail: fam.has('same_actor') ? 'you produced this evidence — a second approver must sign; non-overridable' : preview.attestation ? 'you did not queue the run behind the attested row, and someone else is behind the cell' : 'someone else is behind the cell; the attested row is judged once you name the row you read',
    },
  ]
}

/** The kind of account that signed (F34, hash-covered) as a tag with its meaning on hover; `""` is a row written before the field existed. */
const VERIFIER_KIND_DISPLAY: Record<string, { text: string; label: string }> = {
  local: { text: 'local account', label: 'Signed by a local (password) account of this deployment — verifier_kind: local' },
  oidc: { text: 'identity provider', label: 'Signed by an account an identity provider owns (OIDC) — verifier_kind: oidc' },
  service: { text: 'service — delegated, not a person', label: 'Signed by a delegated service signature, not a person — verifier_kind: service (reserved; this API never mints it)' },
}
function VerifierKindTag({ kind }: { kind: string | undefined }) {
  const d = kind ? VERIFIER_KIND_DISPLAY[kind] : undefined
  if (!d) return <Pill tone="muted" size="xs" hint="pill.signoff.verifier_kind" tabStop={false} label="This record was written before the kind of the signing account was recorded (pre-F34); it is not known" data-testid="verifier-kind">kind not recorded</Pill>
  return <Pill tone={kind === 'service' ? 'amber' : 'muted'} size="xs" hint="pill.signoff.verifier_kind" tabStop={false} label={d.label} data-testid="verifier-kind">{d.text}</Pill>
}

/** Every failing clause with its code, one-line meaning, observed vs threshold and the non-overridable mark. */
function RefusalList({ refusals, testId = 'signoff-refusals' }: { refusals: SignoffRefusal[]; testId?: string }) {
  if (refusals.length === 0) return null
  return (
    <ul data-testid={testId} className="mt-3 list-none space-y-1.5 p-0">
      {refusals.map((r) => (
        <Hint as="li" id="tile.signoff.refusal" key={r.code} data-testid={`refusal-${r.code}`} data-code={r.code} className="rounded-[var(--radius-control)] border border-status-red/40 bg-surface-container px-3 py-2 text-sm">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-xs font-semibold text-status-red">{r.code}</span>
            <span className="text-on-surface">{REFUSAL_DISPLAY[refusalFamily(r.code)] ?? r.message}</span>
            {!r.overridable && (
              <Pill tone="red" size="xs" glyph="⛔" label="This clause cannot be relaxed by any deployment setting" hint="pill.signoff.non_overridable">
                non-overridable
              </Pill>
            )}
          </div>
          <div className="num mt-0.5 text-xs text-on-surface-muted">
            observed <span className="font-semibold text-on-surface">{fmtBound(r.observed)}</span> · threshold <span className="font-semibold text-on-surface">{fmtBound(r.threshold)}</span> — {r.message}
          </div>
        </Hint>
      ))}
    </ul>
  )
}

/** "What you would be signing": the tiles, the controls verdict, the route and the split — the snapshot the record will carry. */
/** `bars` are the routing policy the capability map serves (`min_point`, `min_ci_low`) — read from the API, never a UI constant (CodeRabbit on PR #6). */
function EvidencePanel({ preview, bars }: { preview: SignoffPreview; bars?: { min_point: number; min_ci_low: number } }) {
  const ev = preview.evidence
  const c = preview.controls
  const apparatus = `apparatus ${ev.apparatus_versions.join('/') || '—'} · belt set ${ev.belt_sets.join('/') || '—'} · Wilson 95%`
  return (
    <Card title="What you would be signing" id="signoff-evidence">
      <div className="flex flex-wrap gap-3" data-testid="signoff-evidence">
        <StatTile label="Pass rate" value={fmtPct(ev.point)} n={ev.n} ci={ev.ci_low === null || ev.ci_high === null ? null : { low: ev.ci_low, high: ev.ci_high }} apparatus={`${fmtInt(ev.clean)} clean of ${fmtInt(ev.n)} eligible · ${apparatus}`} hint="stat.signoff.point" data-testid="signoff-tile-point" />
        <StatTile label="Wilson lower" value={fmtPct(ev.ci_low)} n={ev.n} apparatus={`the bound the routing rule reads · ${bars ? `≥ ${fmtPct(bars.min_ci_low, 0)} for deliver` : 'bar: see the policy in force'}`} hint="stat.signoff.ci_low" data-testid="signoff-tile-ci-low" />
        <StatTile label="false-Q1" value={ev.measured ? String(ev.false_q1) : '—'} n={ev.n} apparatus="clean rows with a failed belt — must be 0" tone={ev.false_q1 > 0 ? 'red' : 'green'} hint="stat.signoff.false_q1" data-testid="signoff-tile-false-q1" />
        <StatTile label="Oracle strength" value={fmtRatio(ev.oracle_strength)} n={ev.oracle?.scored ?? ev.n} apparatus={`mean mutation kill-rate of the cell's tasks' oracles${ev.oracle ? ` · ${ev.oracle.scored} of ${ev.oracle.tasks} task(s) scored` : ''} · unmeasured is a refusal, never a pass`} hint="stat.signoff.oracle" data-testid="signoff-tile-oracle" />
      </div>
      <div className="mt-3 grid gap-3 text-sm sm:grid-cols-2">
        <Hint as="div" id="tile.signoff.controls" data-testid="signoff-controls" className="space-y-1">
          <div className="label">Negative controls</div>
          <ControlsPill verdict={c} minShare={preview.policy.min_constructible_share} />
          <p className="num text-xs text-on-surface-muted">
            {c.measured ? (
              <>
                {c.constructible} of {c.total} constructible · {c.escapes} escape(s) · run <span className="font-mono">{shortId(c.run_id)}</span> · {fmtDate(c.created)}
                {!c.complete && ' · cancelled part-way'}
              </>
            ) : (
              'never run — a controls run must pass before anything here can be signed'
            )}
          </p>
        </Hint>
        <Hint as="div" id="tile.signoff.route" data-testid="signoff-route" className="space-y-1">
          <div className="label">Route</div>
          <VerdictPill route={preview.route.route} reason={preview.route.reason} />
          <p className="num text-xs text-on-surface-muted">
            {preview.route.reason_code && <span className="font-mono">{preview.route.reason_code}</span>}
            {preview.route.reason_code && ' — '}
            {preview.route.reason}
          </p>
        </Hint>
        <Hint as="div" id="tile.signoff.failure_split" className="space-y-1 sm:col-span-2">
          <div className="label">Failure split</div>
          <div className="flex flex-wrap items-center gap-3">
            {ev.point !== null && ev.ci_low !== null && ev.ci_high !== null && <CiBar point={ev.point} low={ev.ci_low} high={ev.ci_high} n={ev.n} minPoint={bars?.min_point} minCiLow={bars?.min_ci_low} width={140} provenance={apparatus} />}
            <ModelPointLine modelPoint={ev.model_point} modelN={ev.model_n} clean={ev.clean} ciLow={ev.model_ci_low ?? null} ciHigh={ev.model_ci_high ?? null} apparatus={ev.apparatus_versions} size="sm" />
            <FailureSplitPills split={ev.failure_split} size="sm" data-testid="signoff-split" />
          </div>
        </Hint>
      </div>
    </Card>
  )
}

/** The screen; `?repo=` from the URL, the chosen cell and the attestation draft are local. */
export function SignoffPage() {
  const [repo, setRepo] = useRepoParam({ defaultToLatest: true })
  const { can, me } = useAuth()
  const approver = can('approver')
  const signoffs = useSignoffs(repo, { includeRevoked: true })
  const map = useCapabilityMapWithControls(repo, ['capability_class', 'size'])
  const create = useCreateSignoffWithAttestation()
  const revoke = useRevokeSignoff()
  const [params] = useSearchParams()
  // `?cell=class|size` preselects the cell (the Decisions inbox links here with it)
  const [cellKey, setCellKey] = useState(params.get('cell') ?? '')
  const [rowHash, setRowHash] = useState('')
  const [read, setRead] = useState(false)
  const [statement, setStatement] = useState('')
  const [note, setNote] = useState('')
  // the attestation whose revocation is being confirmed, and the reason that will be recorded
  const [revoking, setRevoking] = useState<SignoffWithPolicy | null>(null)
  const [revokeReason, setRevokeReason] = useState('')
  // the attestation whose Revoke button opened the confirmation: focus goes back there when it
  // closes, so a keyboard person is not dropped at the top of the page (G-905)
  const revokeOpener = useRef<string | null>(null)
  useEffect(() => {
    if (revoking !== null || revokeOpener.current === null) return
    const id = revokeOpener.current
    revokeOpener.current = null
    // gone after a successful revoke: the row can no longer be revoked, and focus stays where the browser puts it
    document.querySelector<HTMLElement>(`button[data-revoke-id="${id}"]`)?.focus()
  }, [revoking])
  const readId = useId()

  const measured = useMemo(() => (map.data?.cells ?? []).filter((c) => c.route !== NOT_YET_MEASURED && c.n > 0), [map.data])
  const cell: CapabilityCellSplit | null = measured.find((c) => `${c.capability_class}|${c.size}` === cellKey) ?? null
  const cellDict = useMemo(() => (cell ? { capability_class: cell.capability_class, size: cell.size } : null), [cell])
  const preview = useSignoffPreview(repo, cellDict, rowHash)

  // A different cell has different accepted rows: the named row and the affirmation reset.
  useEffect(() => {
    setRowHash('')
    setRead(false)
  }, [cellKey])

  const previewData = preview.data
  const attested = read && rowHash.length > 0 && statement.trim().length > 0
  const criteria = criteriaFor(previewData, cell !== null, attested)
  const refusals = previewData?.refusals ?? []
  const signable = Boolean(previewData?.signable) && attested
  const previewFailed = preview.isError

  const refusal = useMemo(() => {
    if (!create.isError) return undefined
    const err = create.error
    if (isSignoffRefused(err)) {
      const isFloor = err.code === 'false_q1_refused'
      return {
        title: isFloor ? 'Sign-off refused: false-Q1 invariant' : `Sign-off refused: ${err.detail.code ?? 'policy'}`,
        message: (
          <>
            The server refused to attest this cell (<span className="font-mono">{err.code}</span>
            {err.detail.code ? <> · <span className="font-mono">{String(err.detail.code)}</span></> : null}). {err.message} Nothing was recorded.
            {isFloor && (
              <>
                {' '}
                Audit the ledger before trying again — <Link to="/ledger">verify chain</Link>.
              </>
            )}
            <RefusalList refusals={err.detail.refusals ?? []} testId="signoff-refused-list" />
          </>
        ),
      }
    }
    return undefined
  }, [create.isError, create.error])

  const submit = (e: FormEvent) => {
    e.preventDefault()
    if (!cell || !signable) return
    create.mutate(
      { repo, cell: { capability_class: cell.capability_class, size: cell.size }, note, attestation: { reviewed_row_hash: rowHash, statement: statement.trim() } },
      {
        onSuccess: () => {
          setNote('')
          setStatement('')
          setRead(false)
          setRowHash('')
        },
      },
    )
  }

  const columns = useMemo<Column<SignoffWithPolicy>[]>(
    () => [
      { key: 'cell', header: 'Cell', mono: true, sortValue: (s) => cellLabel(s.cell), cell: (s) => cellLabel(s.cell), hint: 'col.signoff.cell' },
      {
        key: 'status',
        header: 'Status',
        hint: 'col.signoff.status',
        sortValue: (s) => (s.revoked ? 3 : s.active ? 0 : s.stale ? 1 : 2),
        cell: (s) =>
          s.revoked ? (
            <Pill tone="amber" glyph="⊘" size="xs" label={`Revoked by ${s.revoked_by_name || s.revoked_by || '—'} at ${fmtDate(s.revoked_at)}`} hint="pill.signoff.status">revoked</Pill>
          ) : s.active ? (
            <Pill tone="green" glyph="✓" size="xs" label="Active attestation" hint="pill.signoff.status">active</Pill>
          ) : s.stale ? (
            <Pill tone="amber" glyph="◷" size="xs" label={`Stale: signed at apparatus ${s.evidence.apparatus_versions.join(', ') || '?'}, the deployment now reads at ${s.apparatus_current || '?'} — lifts nothing until re-signed`} hint="pill.signoff.status">stale</Pill>
          ) : s.current_false_q1 > 0 ? (
            <Pill tone="red" glyph="✗" size="xs" label={`Invalidated: the cell now has false_q1 = ${s.current_false_q1}`} hint="pill.signoff.status">invalidated</Pill>
          ) : (
            <Pill tone="muted" glyph="○" size="xs" label="Superseded by a later attestation on the same scope" hint="pill.signoff.status">superseded</Pill>
          ),
      },
      {
        key: 'approver',
        header: 'Approver',
        hint: 'col.signoff.approver',
        sortValue: (s) => approverName(s),
        cell: (s) => (
          <span className="inline-flex flex-wrap items-center gap-1.5" data-testid="signoff-row-approver">
            {approverName(s)}
            <VerifierKindTag kind={s.verifier_kind} />
          </span>
        ),
      },
      { key: 'created', header: 'Signed', sortValue: (s) => s.created, cell: (s) => <span className="text-xs text-on-surface-muted">{fmtDate(s.created)}</span>, hint: 'col.signoff.signed' },
      {
        key: 'evidence',
        header: 'Evidence at signing',
        hint: 'col.signoff.evidence',
        cell: (s) => (
          <span className="num text-xs" data-testid="signoff-row-evidence">
            n={fmtInt(s.evidence.n)} · {fmtPct(s.evidence.point)} · lower {fmtPct(s.evidence.ci_low)} · fQ1 {s.evidence.false_q1} · oracle {fmtRatio(s.evidence.oracle_strength)}
            <Provenance apparatus={s.evidence.apparatus_versions} className="ml-2" />
          </span>
        ),
      },
      {
        key: 'policy',
        header: 'Policy · route · controls',
        hint: 'col.signoff.policy',
        cell: (s) =>
          s.policy_version ? (
            <span className="num text-xs" data-testid="signoff-row-policy">
              <span className="font-mono">{s.policy_version}</span> · {s.route.route}
              {s.route.reason_code ? ` (${s.route.reason_code})` : ''} · controls {s.controls.verdict || '—'} {s.controls.total ? `${s.controls.k}/${s.controls.total}` : ''} esc {s.controls.escapes}
              {s.controls.run_id ? ` · run ${shortId(s.controls.run_id)}` : ''}
            </span>
          ) : (
            <span className="text-xs text-on-surface-muted">pre-policy record</span>
          ),
        hideBelowMd: true,
      },
      {
        key: 'attestation',
        header: 'Attestation',
        hint: 'col.signoff.attestation',
        cell: (s) =>
          s.attestation ? (
            <span className="text-xs" data-testid="signoff-row-attestation">
              <span className="font-mono">{shortId(s.attestation.reviewed_row_hash)}</span> · {s.attestation.subject || shortId(s.attestation.reviewed_task_id)}
              {/* the statement is the governance record: shown under the row, never hover-only */}
              <span className="block max-w-[36ch] text-on-surface-muted">{s.attestation.statement}</span>
            </span>
          ) : (
            <span className="text-xs text-on-surface-muted">—</span>
          ),
      },
      { key: 'note', header: 'Note', cell: (s) => <span className="text-xs text-on-surface-muted">{s.note}</span>, hideBelowMd: true, hint: 'col.signoff.note' },
      {
        key: 'actions',
        header: '',
        cell: (s) =>
          !s.revoked && can('approver') ? (
            <Button size="sm" variant="danger" hint="button.signoff.revoke" onClick={() => { revokeOpener.current = s.id; setRevoking(s); setRevokeReason(''); revoke.reset() }} disabled={revoke.isPending} aria-haspopup="dialog" data-revoke-id={s.id}>
              Revoke
            </Button>
          ) : null,
      },
    ],
    [can, revoke],
  )

  const confirmRevoke = (e: FormEvent) => {
    e.preventDefault()
    if (!revoking || revokeReason.trim().length === 0) return
    revoke.mutate({ id: revoking.id, repo: revoking.repo, note: revokeReason.trim() }, { onSuccess: () => { setRevoking(null); setRevokeReason('') } })
  }

  const policyVersion = previewData?.policy.policy_version ?? SIGNOFF_POLICY_VERSION
  const relaxed = previewData?.policy.relaxed

  return (
    <>
      <PageHeader
        title="Sign-off"
        purpose="Record that you reviewed this cell’s evidence and read one accepted change. The server refuses a sign-off that does not meet the published policy; a refusal is the gate working, not an error."
        actions={<RepoPicker value={repo} onChange={setRepo} />}
      />
      {/* the Details' summary is a string, so the hint wraps the block; not a tab stop of its own (the summary is) */}
      <Hint as="div" id="details.signoff.why_refused" tabStop={false}>
        <Details summary="Why a sign-off can be refused" className="mt-4">
          <p className="mt-0">A sign-off is a policy decision, refused at write. The server refuses when any of these holds:</p>
          <ul className="mb-0 pl-6">
            <li>
              <Term id="false_q1">false-Q1</Term> above zero in the cell — this clause cannot be relaxed;
            </li>
            <li>
              a thin <Term id="cell">cell</Term> — fewer attempts than the policy’s minimum n;
            </li>
            <li>
              a <Term id="negative_controls">negative controls</Term> gate that failed, never ran, or let a <Term id="controls_escape">control escape</Term>;
            </li>
            <li>
              an <Term id="oracle_strength">oracle strength</Term> never measured on the cell’s tasks, or below the bar;
            </li>
            <li>
              a route other than <Term id="deliver">deliver</Term>;
            </li>
            <li>no attestation that you read an accepted diff — this clause cannot be relaxed.</li>
          </ul>
          <p className="mb-0">
            The gate below shows every clause with the observed value against the threshold, before you try. A <Term id="signoff">sign-off</Term> lifts the verification tier and never the route.
          </p>
        </Details>
      </Hint>

      {!repo && <EmptyState title="Choose a repository" reason="A sign-off is per repository and per cell." action={<LinkButton to="/connect">Connect a repository</LinkButton>} />}

      {repo && (
        <>
          {/* the banner's title is a string, so its hint wraps the gate; each clause inside carries its own (innermost wins) */}
          <Hint as="div" id="gate.signoff.banner" tabStop={false}>
            <GateBanner
              title={cell ? `Attest ${cell.capability_class} × ${cell.size}` : 'Attest a cell'}
              eyebrow={`policy ${policyVersion}${relaxed ? ' (relaxed by this deployment)' : ''}`}
              criteria={criteria}
              refused={refusal}
              data-testid="signoff-gate"
              action={
                approver ? (
                  <Button type="submit" form="signoff-form" variant="filled" hint="button.signoff.sign" disabled={!signable || !cell || create.isPending || previewFailed}>
                    {create.isPending ? 'Recording…' : 'Sign off'}
                  </Button>
                ) : (
                  <span className="text-xs text-on-surface-muted">Requires the approver role{me ? ` (you are ${me.role})` : ''}.</span>
                )
              }
            />
          </Hint>
          {cell && refusals.length > 0 && !refusal && (
            <div className="-mt-2" data-testid="signoff-refusal-block">
              <p className="text-xs text-on-surface-muted">The server would refuse this sign-off right now ({refusals.length} clause{refusals.length === 1 ? '' : 's'}):</p>
              <RefusalList refusals={refusals} />
            </div>
          )}
          {previewFailed && (
            <div className="-mt-2">
              <ErrorState compact error={preview.error} />
            </div>
          )}

          {previewData && <EvidencePanel preview={previewData} bars={map.data?.policy ? { min_point: map.data.policy.min_point, min_ci_low: map.data.policy.min_ci_low } : undefined} />}

          {/* a reader who cannot sign is shown no form: who acts, and a cell to read (the preview changes nothing on the server) */}
          {!approver && (
            <InsetText>
              <p className="m-0" data-testid="signoff-read-only">
                Only an approver can sign. You are signed in as {me?.role ?? 'a viewer'}: you can read the gate, the evidence and the attestations on this page, and nothing here changes because you read it.
              </p>
              <div className="mt-4 max-w-[28em]">
                <SelectField label="Cell to read" hint="field.signoff.cell_read" value={cellKey} onChange={(e) => setCellKey(e.target.value)} description={map.isPending ? 'Loading measured cells…' : `${measured.length} measured cell(s)`}>
                  <option value="">Choose a measured cell…</option>
                  {measured.map((c) => (
                    <option key={`${c.capability_class}|${c.size}`} value={`${c.capability_class}|${c.size}`}>
                      {c.capability_class} · {c.size} — {c.route}, n={c.n}, {fmtPct(c.point, 0)}
                    </option>
                  ))}
                </SelectField>
              </div>
            </InsetText>
          )}

          {approver && (
            <Card title="Approver form">
              <Hint as="div" id="banner.signoff.not_meaning">
                <WarningCallout title="What your signature does not mean">
                  <ul className="m-0 pl-6">
                    <li className="mb-2">It does not change the cell's route, its point estimate or its interval.</li>
                    <li className="mb-2">It does not vouch for any other class, size or repository.</li>
                    <li>It is invalidated at read if a false-Q1 row later appears in this cell, or when the apparatus changes.</li>
                  </ul>
                </WarningCallout>
              </Hint>
              <form id="signoff-form" onSubmit={submit} className="grid gap-4 sm:grid-cols-2">
                <SelectField label="Cell" hint="field.signoff.cell" required value={cellKey} onChange={(e) => setCellKey(e.target.value)} description={map.isPending ? 'Loading measured cells…' : `${measured.length} measured cell(s)`}>
                  <option value="">Choose a measured cell…</option>
                  {measured.map((c) => (
                    <option key={`${c.capability_class}|${c.size}`} value={`${c.capability_class}|${c.size}`}>
                      {c.capability_class} · {c.size} — {c.route}, n={c.n}, {fmtPct(c.point, 0)}
                    </option>
                  ))}
                </SelectField>
                <div className="flex items-end">
                  {cell && (
                    <Hint as="div" id="tile.signoff.cell_summary" className="space-y-1 text-xs">
                      <VerdictPill route={cell.route} reason={cell.reason} />
                      <p className="text-on-surface-muted">{cell.reason}</p>
                      <Provenance apparatus={cell.apparatus_versions} beltSet={cell.belt_set ?? null} />
                    </Hint>
                  )}
                </div>
                <SelectField
                  label="Accepted row"
                  hint="field.signoff.accepted_row"
                  required
                  value={rowHash}
                  onChange={(e) => {
                    setRowHash(e.target.value)
                    setRead(false)
                  }}
                  disabled={!previewData}
                  description={previewData ? `${previewData.accepted_rows.length} accepted (clean) row(s) in this cell — name the one whose diff you read` : 'choose a cell first'}
                  data-testid="attest-row"
                >
                  <option value="">Choose the accepted row you read…</option>
                  {(previewData?.accepted_rows ?? []).map((r) => (
                    <option key={r.row_hash} value={r.row_hash}>
                      {r.subject || shortId(r.task_id)} · {shortId(r.row_hash)} · {fmtDate(r.created)}
                    </option>
                  ))}
                </SelectField>
                <div className="flex items-end">
                  <Hint as="label" id="field.signoff.read_affirmation" htmlFor={readId} className="flex items-start gap-2 text-sm text-on-surface">
                    <input id={readId} type="checkbox" className="mt-0.5" checked={read} disabled={!rowHash} onChange={(e) => setRead(e.target.checked)} data-testid="attest-read" />
                    <span>
                      I have read this accepted diff
                      <span className="block text-xs text-on-surface-muted">
                        {rowHash ? (
                          <>
                            row <span className="font-mono">{shortId(rowHash)}</span> — the attestation names this row and is hash-chained with the sign-off
                          </>
                        ) : (
                          'pick a row first'
                        )}
                      </span>
                    </span>
                  </Hint>
                </div>
                {rowHash && previewData && (
                  <div className="sm:col-span-2">
                    <ReadTheDiff repo={repo} row={previewData.accepted_rows.find((r) => r.row_hash === rowHash)} />
                  </div>
                )}
                <div className="sm:col-span-2">
                  <TextArea label="Attestation statement" hint="field.signoff.statement" required rows={2} value={statement} onChange={(e) => setStatement(e.target.value)} description="What you read in that diff and why it is acceptable. Recorded verbatim, append-only, redacted." data-testid="attest-statement" />
                </div>
                <div className="sm:col-span-2">
                  <TextArea label="Note" hint="field.signoff.note" rows={2} value={note} onChange={(e) => setNote(e.target.value)} description="Optional: what else you reviewed (packs, refusals, the oracle). Recorded verbatim." />
                </div>
                {create.isError && !refusal && (
                  <div className="sm:col-span-2">
                    <ErrorState compact error={create.error} />
                  </div>
                )}
                {create.isSuccess && (
                  <div className="sm:col-span-2" role="status" data-testid="signoff-recorded">
                    <Hint as="div" id="banner.signoff.recorded">
                      <ConfirmationPanel title="Sign-off recorded" reference={`sgn_${shortId(create.data.row_hash)}`} />
                    </Hint>
                    <SummaryList
                      label="What was recorded"
                      rows={[
                        { key: 'Cell', value: <><code>{cellLabel(create.data.cell)}</code> on {create.data.repo}, route {create.data.route.route || '—'}</> },
                        { key: 'Row hash', value: <code className="break-all">{create.data.row_hash}</code> },
                        { key: 'Attested by', value: <>{approverName(create.data)} <VerifierKindTag kind={create.data.verifier_kind} /> at {create.data.created}</> },
                        { key: 'Policy', value: <><code>{create.data.policy_version}</code> · apparatus {create.data.evidence.apparatus_versions.join(', ') || '—'}</> },
                      ]}
                    />
                    <h3 className="mb-3 mt-6 text-[24px] font-bold leading-[1.3]">What happens next</h3>
                    <ul className="m-0 max-w-[44em] pl-6 text-[19px] leading-[1.47]">
                      <li className="mb-2">The factory may now open pull requests for items in this cell, on branches prefixed <code>crb/</code>, for review under the repository's own rules.</li>
                      <li className="mb-2">The cell's verification tier is lifted on the map. Its route, point and interval are unchanged.</li>
                      <li>If a false-Q1 row appears in this cell, or the apparatus changes, this sign-off stops counting at read and the cell returns to your decisions.</li>
                    </ul>
                  </div>
                )}
              </form>
            </Card>
          )}

          <Card padded={false} title="Attestations">
            <QueryBoundary query={signoffs} loading="Loading attestations…">
              {(page) => (
                <DataTable
                  rows={page.items as SignoffWithPolicy[]}
                  columns={columns}
                  rowKey={(s) => s.id}
                  caption={`Sign-offs for ${repo}`}
                  initialSort={{ key: 'created', dir: 'desc' }}
                  empty={<EmptyState title="No attestations yet" reason="An attestation records that a human reviewed a cell's evidence and read an accepted diff. Choose a cell above whose gate is open." />}
                />
              )}
            </QueryBoundary>
            {revoking && (
              <form onSubmit={confirmRevoke} className="border-t border-border p-4" role="dialog" aria-labelledby={`${readId}-revoke`} data-testid="revoke-confirm">
                <WarningCallout title="Are you sure you want to revoke this sign-off?">
                  <p id={`${readId}-revoke`} className="m-0">
                    <code>{cellLabel(revoking.cell)}</code> on {revoking.repo}, signed by {approverName(revoking)} on {fmtDate(revoking.created)}. Revoking appends a row to the ledger — the attestation stays on the record, marked revoked — and the cell returns to <em>sign-off due</em> on the map. The factory stops opening pull requests for it.
                  </p>
                </WarningCallout>
                <div className="max-w-[44em]">
                  {/* the confirmation takes focus when it opens: its one field is where the keyboard person starts */}
                  <TextArea autoFocus label="Why are you revoking it?" hint="field.signoff.revoke_reason" required rows={2} value={revokeReason} onChange={(e) => setRevokeReason(e.target.value)} description="Recorded verbatim on the revocation row, append-only. An auditor reads this next to the attestation it withdraws." data-testid="revoke-reason" />
                </div>
                {revoke.isError && (
                  <div className="mt-3">
                    <ErrorState compact error={revoke.error} />
                  </div>
                )}
                <div className="mt-4 flex flex-wrap items-center gap-3">
                  <WarningButton type="submit" hint="button.signoff.revoke_confirm" disabled={revoke.isPending || revokeReason.trim().length === 0}>Revoke sign-off</WarningButton>
                  <SecondaryButton onClick={() => { setRevoking(null); revoke.reset() }}>Cancel</SecondaryButton>
                </div>
              </form>
            )}
          </Card>
        </>
      )}
    </>
  )
}

export default SignoffPage

/**
 * The diff the approver is about to affirm they read — on the screen that asks for the
 * affirmation, never a hunt through Runs. The retained patch (verified against the pack's
 * anchor) when the deployment kept it; otherwise the pack's file list and a link to the
 * task, and the affirmation still means what it says.
 */
function ReadTheDiff({ repo, row }: { repo: string; row: AcceptedRow | undefined }) {
  const evidence = useEvidence(row?.evidence_pack_hash ?? '')
  const patch = useRetainedPatch(row?.row_hash ?? '', Boolean(row))
  if (!row) return null
  const pack = evidence.data?.pack
  return (
    <Hint as="div" id="tile.signoff.read_diff" className="rounded-[var(--radius-control)] border border-border p-3" data-testid="read-the-diff">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="font-bold">Read the diff</span>
        <span className="font-mono text-xs text-on-surface-muted">
          {row.subject || row.task_id} · row {shortId(row.row_hash)} · run {shortId(row.run_id)} · {row.trial} · {row.builder}
          {row.model ? `/${row.model}` : ''}
        </span>
        <LinkButton size="sm" to={`/tasks/${encodeURIComponent(repo)}/${encodeURIComponent(row.task_id)}`} hint="button.signoff.task">
          The task and every attempt
        </LinkButton>
        <LinkButton size="sm" to={`/runs/${row.run_id}`} hint="button.signoff.run">
          The run
        </LinkButton>
      </div>
      {patch.isPending && <p className="mb-0 mt-2 text-xs text-on-surface-muted">Loading the retained patch…</p>}
      {patch.data && pack && (
        <div className="mt-3">
          <PatchView patch={patch.data} pack={pack} />
        </div>
      )}
      {patch.isError && (
        <p className="mb-0 mt-2 text-sm text-on-surface-body">
          The patch is not retained on this deployment (zero raw retention by default); the evidence pack records its hash
          {pack?.grade.diff ? ` and ${pack.grade.diff.files.length} file(s), +${pack.grade.diff.additions} −${pack.grade.diff.deletions}` : ''}. Read it from the task page, or re-run with worktrees retained.
        </p>
      )}
    </Hint>
  )
}

