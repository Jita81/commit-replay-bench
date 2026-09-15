/**
 * Sign-off — a human attestation that a cell's evidence is trusted; a policy decision refused at
 * write (/signoff).
 *
 * Navigation
 * ----------
 * What it is:   The screen at /signoff: the gate (criteria derived from the server's preview),
 *               the evidence panel (what you would be signing), the attestation form (name an
 *               accepted row, affirm you read it, a statement) and the table of recorded
 *               attestations with their snapshots.
 * What it does: Shows the bar before the approver tries: the preview's refusals become the
 *               gate's check-rows with observed vs threshold, and non-overridable clauses
 *               (false-Q1, oracle unmeasured, attestation missing) are marked so; the action
 *               is disabled until the preview says `signable` AND the approver has named a
 *               row, ticked "I have read this accepted diff" and written a statement. A 409
 *               from the POST renders as a REFUSED gate with the clauses (the false-Q1 floor
 *               points at the ledger); a pre-policy record is listed honestly without a
 *               fabricated snapshot; an approver can revoke.
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
 *               ui/src/screens/Capability/contract.ts and
 *               ui/src/screens/Capability/FailureSplit.tsx
 *               (the cells, the controls pill and the split), ui/src/api/hooks.ts
 *               (`useSignoffs`, `useRevokeSignoff`), src/crb/server/routes/signoffs.py (the
 *               server's decision this screen previews and submits), src/crb/core/signoff.py
 * Tested by:    ui/src/screens/Signoff/SignoffPage.test.tsx, ui/e2e/walkthrough/08-signoff.spec.ts
 *               (a thin cell refused with observed vs threshold; a policy-clearing cell
 *               signed with an attestation), ui/e2e/walkthrough/05-replay-fake.spec.ts
 * Touch when:   a refusal clause or a policy threshold is added (src/crb/core/signoff.py) —
 *               add the gate row in `criteriaFor` and the vocabulary in
 *               ui/src/screens/Signoff/contract.ts; never for a new repository.
 * Claims:       A sign-off lifts the verification tier, never the route; it is refused
 *               outright on any false-Q1 row
 *               (docs/EVIDENCE-AND-CLAIMS.md#6a-what-a-signed-cell-may-be-claimed-to-mean-signoff-policyv2).
 */
import { useEffect, useId, useMemo, useState, type FormEvent } from 'react'
import { Link } from 'react-router'
import { useRevokeSignoff, useSignoffs } from '../../api/hooks'
import { NOT_YET_MEASURED } from '../../api/types'
import { Button, LinkButton } from '../../components/Button'
import { Card } from '../../components/Card'
import { CiBar } from '../../components/CiBar'
import { DataTable, type Column } from '../../components/DataTable'
import { EmptyState } from '../../components/EmptyState'
import { ErrorState } from '../../components/ErrorState'
import { SelectField, TextArea } from '../../components/Field'
import { GateBanner, type GateCriterion } from '../../components/GateBanner'
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
      { label: 'Cell is measured', ok: null, detail: cellChosen ? 'evaluating…' : 'choose a measured cell' },
      { label: 'false-Q1 = 0', ok: null },
      { label: `Evidence meets ${SIGNOFF_POLICY_VERSION}`, ok: null },
      { label: 'Negative controls passed', ok: null },
      { label: 'Route = deliver', ok: null },
      { label: 'Accepted row read and affirmed', ok: null },
    ]
  }
  const fam = new Set(preview.refusals.map((r) => refusalFamily(r.code)))
  const p = preview.policy
  const ev = preview.evidence
  const c = preview.controls
  const cd = controlsDisplay(c)
  const oracle = ev.oracle_strength
  const scored = ev.oracle ? `${ev.oracle.scored} of ${ev.oracle.tasks} task(s) scored` : ''
  return [
    { label: 'Cell is measured', ok: ev.measured, detail: `n = ${fmtInt(ev.n)}` },
    { label: 'false-Q1 = 0', ok: !fam.has('false_q1') && ev.false_q1 === 0, detail: `false_q1 = ${ev.false_q1}` },
    { label: `n ≥ ${p.n_min}`, ok: !fam.has('thin_cell'), detail: `n = ${fmtInt(ev.n)} · point ${fmtPct(ev.point)} · Wilson lower ${fmtPct(ev.ci_low)}` },
    {
      label: `Negative controls passed, ≤ ${p.max_controls_escapes} escape(s), ≥ ${fmtPct(p.min_constructible_share, 0)} constructible`,
      ok: !fam.has('controls_unmeasured') && !fam.has('controls_failed') && !fam.has('controls_escapes') && !fam.has('controls_thin'),
      detail: c.measured ? `${cd.label} · ${c.constructible} of ${c.total} · ${c.escapes} escape(s) · run ${shortId(c.run_id)} · ${fmtDate(c.created)}` : 'never run for this repo',
    },
    {
      label: `Oracle strength measured and ≥ ${fmtRatio(p.min_oracle_strength)}`,
      ok: !fam.has('oracle_unmeasured') && !fam.has('oracle_weak'),
      detail: oracle === null ? `unmeasured — no task of this cell has a mutation score (${scored || 'none'}); run an oracle run — non-overridable` : `strength ${fmtRatio(oracle)}${scored ? ` · ${scored}` : ''}`,
    },
    { label: 'Route = deliver', ok: !fam.has('route_not_deliver'), detail: `${preview.route.route}${preview.route.reason_code ? ` (${preview.route.reason_code})` : ''}` },
    { label: 'Accepted row read and affirmed', ok: !fam.has('attestation_missing') && attested, detail: preview.attestation ? `${shortId(preview.attestation.reviewed_row_hash)} · ${preview.attestation.subject || preview.attestation.reviewed_task_id}` : 'pick a row below and tick “I have read this accepted diff”' },
  ]
}

/** Every failing clause with its code, one-line meaning, observed vs threshold and the non-overridable mark. */
function RefusalList({ refusals, testId = 'signoff-refusals' }: { refusals: SignoffRefusal[]; testId?: string }) {
  if (refusals.length === 0) return null
  return (
    <ul data-testid={testId} className="mt-3 list-none space-y-1.5 p-0">
      {refusals.map((r) => (
        <li key={r.code} data-testid={`refusal-${r.code}`} data-code={r.code} className="rounded-[var(--radius-control)] border border-status-red/40 bg-surface-container px-3 py-2 text-sm">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-xs font-semibold text-status-red">{r.code}</span>
            <span className="text-on-surface">{REFUSAL_DISPLAY[refusalFamily(r.code)] ?? r.message}</span>
            {!r.overridable && (
              <Pill tone="red" size="xs" glyph="⛔" label="This clause cannot be relaxed by any deployment setting">
                non-overridable
              </Pill>
            )}
          </div>
          <div className="num mt-0.5 text-xs text-on-surface-muted">
            observed <span className="font-semibold text-on-surface">{fmtBound(r.observed)}</span> · threshold <span className="font-semibold text-on-surface">{fmtBound(r.threshold)}</span> — {r.message}
          </div>
        </li>
      ))}
    </ul>
  )
}

/** "What you would be signing": the tiles, the controls verdict, the route and the split — the snapshot the record will carry. */
function EvidencePanel({ preview }: { preview: SignoffPreview }) {
  const ev = preview.evidence
  const c = preview.controls
  const apparatus = `apparatus ${ev.apparatus_versions.join('/') || '—'} · belt set ${ev.belt_sets.join('/') || '—'} · Wilson 95%`
  return (
    <Card title="What you would be signing" id="signoff-evidence">
      <div className="flex flex-wrap gap-3" data-testid="signoff-evidence">
        <StatTile label="Pass rate" value={fmtPct(ev.point)} n={ev.n} ci={ev.ci_low === null || ev.ci_high === null ? null : { low: ev.ci_low, high: ev.ci_high }} apparatus={`${fmtInt(ev.clean)} clean of ${fmtInt(ev.n)} eligible · ${apparatus}`} data-testid="signoff-tile-point" />
        <StatTile label="Wilson lower" value={fmtPct(ev.ci_low)} n={ev.n} apparatus={`the bound the routing rule reads · ≥ 80% for deliver`} data-testid="signoff-tile-ci-low" />
        <StatTile label="false-Q1" value={ev.measured ? String(ev.false_q1) : '—'} n={ev.n} apparatus="clean rows with a failed belt — must be 0" tone={ev.false_q1 > 0 ? 'red' : 'green'} data-testid="signoff-tile-false-q1" />
        <StatTile label="Oracle strength" value={fmtRatio(ev.oracle_strength)} n={ev.oracle?.scored ?? ev.n} apparatus={`mean mutation kill-rate of the cell's tasks' oracles${ev.oracle ? ` · ${ev.oracle.scored} of ${ev.oracle.tasks} task(s) scored` : ''} · unmeasured is a refusal, never a pass`} data-testid="signoff-tile-oracle" />
      </div>
      <div className="mt-3 grid gap-3 text-sm sm:grid-cols-2">
        <div data-testid="signoff-controls" className="space-y-1">
          <div className="label">Negative controls</div>
          <ControlsPill verdict={c} />
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
        </div>
        <div data-testid="signoff-route" className="space-y-1">
          <div className="label">Route</div>
          <VerdictPill route={preview.route.route} reason={preview.route.reason} />
          <p className="num text-xs text-on-surface-muted">
            {preview.route.reason_code && <span className="font-mono">{preview.route.reason_code}</span>}
            {preview.route.reason_code && ' — '}
            {preview.route.reason}
          </p>
        </div>
        <div className="space-y-1 sm:col-span-2">
          <div className="label">Failure split</div>
          <div className="flex flex-wrap items-center gap-3">
            {ev.point !== null && ev.ci_low !== null && ev.ci_high !== null && <CiBar point={ev.point} low={ev.ci_low} high={ev.ci_high} n={ev.n} minPoint={0.9} minCiLow={0.8} width={140} />}
            <ModelPointLine modelPoint={ev.model_point} modelN={ev.model_n} clean={ev.clean} size="sm" />
            <FailureSplitPills split={ev.failure_split} size="sm" data-testid="signoff-split" />
          </div>
        </div>
      </div>
    </Card>
  )
}

/** The screen; `?repo=` from the URL, the chosen cell and the attestation draft are local. */
export function SignoffPage() {
  const [repo, setRepo] = useRepoParam()
  const { can, me } = useAuth()
  const signoffs = useSignoffs(repo)
  const map = useCapabilityMapWithControls(repo, ['capability_class', 'size'])
  const create = useCreateSignoffWithAttestation()
  const revoke = useRevokeSignoff()
  const [cellKey, setCellKey] = useState('')
  const [rowHash, setRowHash] = useState('')
  const [read, setRead] = useState(false)
  const [statement, setStatement] = useState('')
  const [note, setNote] = useState('')
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
      { key: 'cell', header: 'Cell', mono: true, sortValue: (s) => cellLabel(s.cell), cell: (s) => cellLabel(s.cell) },
      {
        key: 'status',
        header: 'Status',
        sortValue: (s) => Number(s.revoked),
        cell: (s) =>
          s.revoked ? (
            <Pill tone="amber" glyph="⊘" size="xs" label={`Revoked by ${s.revoked_by ?? '—'} at ${fmtDate(s.revoked_at)}`}>revoked</Pill>
          ) : s.active ? (
            <Pill tone="green" glyph="✓" size="xs" label="Active attestation">active</Pill>
          ) : (
            <Pill tone="red" glyph="✗" size="xs" label={`Invalidated: the cell now has false_q1 = ${s.current_false_q1}`}>invalidated</Pill>
          ),
      },
      { key: 'approver', header: 'Approver', sortValue: (s) => s.approver, cell: (s) => s.approver },
      { key: 'created', header: 'Signed', sortValue: (s) => s.created, cell: (s) => <span className="text-xs text-on-surface-muted">{fmtDate(s.created)}</span> },
      {
        key: 'evidence',
        header: 'Evidence at signing',
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
        cell: (s) =>
          s.policy_version ? (
            <span className="num text-xs" data-testid="signoff-row-policy">
              <span className="font-mono">{s.policy_version}</span> · {s.route.route}
              {s.route.reason_code ? ` (${s.route.reason_code})` : ''} · controls {s.controls.verdict || '—'} {s.controls.total ? `${s.controls.k}/${s.controls.total}` : ''} esc {s.controls.escapes}
              {s.controls.run_id ? ` · run ${shortId(s.controls.run_id)}` : ''}
            </span>
          ) : (
            <span className="text-xs text-on-surface-muted" title="Signed before signoff-policy.v1: no policy snapshot was recorded">
              pre-policy record
            </span>
          ),
        hideBelowMd: true,
      },
      {
        key: 'attestation',
        header: 'Attestation',
        cell: (s) =>
          s.attestation ? (
            <span className="text-xs" data-testid="signoff-row-attestation" title={s.attestation.statement}>
              <span className="font-mono">{shortId(s.attestation.reviewed_row_hash)}</span> · {s.attestation.subject || shortId(s.attestation.reviewed_task_id)}
            </span>
          ) : (
            <span className="text-xs text-on-surface-muted">—</span>
          ),
      },
      { key: 'note', header: 'Note', cell: (s) => <span className="text-xs text-on-surface-muted">{s.note}</span>, hideBelowMd: true },
      {
        key: 'actions',
        header: '',
        cell: (s) =>
          !s.revoked && can('approver') ? (
            <Button size="sm" variant="danger" onClick={() => revoke.mutate({ id: s.id, repo: s.repo })} disabled={revoke.isPending}>
              Revoke
            </Button>
          ) : null,
      },
    ],
    [can, revoke],
  )

  const policyVersion = previewData?.policy.policy_version ?? SIGNOFF_POLICY_VERSION
  const relaxed = previewData?.policy.relaxed

  return (
    <>
      <PageHeader
        eyebrow="Sign-off"
        title="Sign-off"
        purpose="A human attestation that a cell's evidence has been reviewed and is trusted. A sign-off is a policy decision, refused at write: false-Q1 > 0, a thin cell, a negative-controls gate that failed / never ran / let a control escape, an oracle never measured on the cell's tasks or too weak, a route other than deliver, or no attestation that you read an accepted diff — the refusal is a gate, not an error."
        actions={<RepoPicker value={repo} onChange={setRepo} />}
      />

      {!repo && <EmptyState title="Choose a repo to review attestations" action={<LinkButton to="/repos">Go to repos</LinkButton>} />}

      {repo && (
        <>
          <GateBanner
            title={cell ? `Attest ${cell.capability_class} × ${cell.size}` : 'Attest a cell'}
            eyebrow={`policy ${policyVersion}${relaxed ? ' (relaxed by this deployment)' : ''}`}
            criteria={criteria}
            refused={refusal}
            data-testid="signoff-gate"
            action={
              can('approver') ? (
                <Button type="submit" form="signoff-form" variant="filled" disabled={!signable || !cell || create.isPending || previewFailed}>
                  {create.isPending ? 'Recording…' : 'Sign off'}
                </Button>
              ) : (
                <span className="text-xs text-on-surface-muted">Requires the approver role{me ? ` (you are ${me.role})` : ''}.</span>
              )
            }
          />
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

          {previewData && <EvidencePanel preview={previewData} />}

          <Card title="Approver form">
            <form id="signoff-form" onSubmit={submit} className="grid gap-4 sm:grid-cols-2">
              <SelectField label="Cell" required value={cellKey} onChange={(e) => setCellKey(e.target.value)} hint={map.isPending ? 'Loading measured cells…' : `${measured.length} measured cell(s)`}>
                <option value="">Choose a measured cell…</option>
                {measured.map((c) => (
                  <option key={`${c.capability_class}|${c.size}`} value={`${c.capability_class}|${c.size}`}>
                    {c.capability_class} · {c.size} — {c.route}, n={c.n}, {fmtPct(c.point, 0)}
                  </option>
                ))}
              </SelectField>
              <div className="flex items-end">
                {cell && (
                  <div className="space-y-1 text-xs">
                    <VerdictPill route={cell.route} reason={cell.reason} />
                    <p className="text-on-surface-muted">{cell.reason}</p>
                    <Provenance apparatus={cell.apparatus_versions} beltSet={cell.belt_set ?? null} />
                  </div>
                )}
              </div>
              <SelectField
                label="Accepted row"
                required
                value={rowHash}
                onChange={(e) => {
                  setRowHash(e.target.value)
                  setRead(false)
                }}
                disabled={!previewData}
                hint={previewData ? `${previewData.accepted_rows.length} accepted (clean) row(s) in this cell — name the one whose diff you read` : 'choose a cell first'}
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
                <label htmlFor={readId} className="flex items-start gap-2 text-sm text-on-surface">
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
                </label>
              </div>
              <div className="sm:col-span-2">
                <TextArea label="Attestation statement" required rows={2} value={statement} onChange={(e) => setStatement(e.target.value)} hint="What you read in that diff and why it is acceptable. Recorded verbatim, append-only, redacted." data-testid="attest-statement" />
              </div>
              <div className="sm:col-span-2">
                <TextArea label="Note" rows={2} value={note} onChange={(e) => setNote(e.target.value)} hint="Optional: what else you reviewed (packs, refusals, the oracle). Recorded verbatim." />
              </div>
              {create.isError && !refusal && (
                <div className="sm:col-span-2">
                  <ErrorState compact error={create.error} />
                </div>
              )}
              {create.isSuccess && (
                <p className="text-sm text-status-green sm:col-span-2" role="status" data-testid="signoff-recorded">
                  ✓ Attestation recorded under <span className="font-mono">{create.data.policy_version}</span> — row <span className="font-mono">{shortId(create.data.row_hash)}</span>.
                </p>
              )}
            </form>
          </Card>

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
            {revoke.isError && (
              <div className="p-3">
                <ErrorState compact error={revoke.error} />
              </div>
            )}
          </Card>
        </>
      )}
    </>
  )
}

export default SignoffPage
