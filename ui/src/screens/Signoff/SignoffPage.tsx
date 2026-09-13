import { useMemo, useState, type FormEvent } from 'react'
import { Link } from 'react-router'
import { ApiError } from '../../api/client'
import { useCapabilityMap, useCreateSignoff, useRevokeSignoff, useSignoffs } from '../../api/hooks'
import { NOT_YET_MEASURED, type CapabilityCell, type Signoff } from '../../api/types'
import { Button, LinkButton } from '../../components/Button'
import { Card } from '../../components/Card'
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
import { VerdictPill } from '../../components/VerdictPill'
import { useAuth } from '../../lib/auth'
import { fmtDate, fmtInt, fmtPct } from '../../lib/format'

const cellLabel = (c: Record<string, string>) => [c.capability_class, c.size, c.language, c.model].filter(Boolean).join(' · ')

function criteriaFor(cell: CapabilityCell | null, policy: { min_n: number; min_point: number; min_ci_low: number } | undefined): GateCriterion[] {
  if (!cell || cell.route === NOT_YET_MEASURED) {
    return [
      { label: 'Cell is measured', ok: cell ? false : null, detail: 'choose a measured cell' },
      { label: 'false-Q1 = 0', ok: null },
      { label: 'Evidence meets the policy bar', ok: null },
    ]
  }
  const p = policy ?? { min_n: 10, min_point: 0.9, min_ci_low: 0.8 }
  return [
    { label: 'Cell is measured', ok: cell.n > 0, detail: `n = ${fmtInt(cell.n)}` },
    { label: 'false-Q1 = 0', ok: cell.false_q1 === 0, detail: `false_q1 = ${cell.false_q1}` },
    { label: `n ≥ ${p.min_n}`, ok: cell.n >= p.min_n, detail: `n = ${fmtInt(cell.n)}` },
    { label: `point ≥ ${fmtPct(p.min_point, 0)}`, ok: cell.point >= p.min_point, detail: `point = ${fmtPct(cell.point)}` },
    { label: `Wilson lower ≥ ${fmtPct(p.min_ci_low, 0)}`, ok: cell.ci_low >= p.min_ci_low, detail: `lower = ${fmtPct(cell.ci_low)}` },
  ]
}

export function SignoffPage() {
  const [repo, setRepo] = useRepoParam()
  const { can, me } = useAuth()
  const signoffs = useSignoffs(repo)
  const map = useCapabilityMap(repo, ['capability_class', 'size'])
  const create = useCreateSignoff()
  const revoke = useRevokeSignoff()
  const [cellKey, setCellKey] = useState('')
  const [note, setNote] = useState('')

  const measured = useMemo(() => (map.data?.cells ?? []).filter((c) => c.route !== NOT_YET_MEASURED && c.n > 0), [map.data])
  const cell = measured.find((c) => `${c.capability_class}|${c.size}` === cellKey) ?? null
  const criteria = criteriaFor(cell, map.data?.policy)
  const allOk = criteria.every((c) => c.ok === true)

  const refusal =
    create.isError && create.error instanceof ApiError && create.error.isFalseQ1Refused
      ? {
          title: 'Sign-off refused: false-Q1 invariant',
          message: (
            <>
              The server refused to attest this cell because its evidence violates the honesty floor (<span className="font-mono">false_q1_refused</span>). {create.error.message} Nothing was recorded. Audit the ledger before trying again —{' '}
              <Link to="/ledger">verify chain</Link>.
            </>
          ),
        }
      : undefined

  const submit = (e: FormEvent) => {
    e.preventDefault()
    if (!cell) return
    create.mutate(
      { repo, cell: { capability_class: cell.capability_class, size: cell.size }, note },
      {
        onSuccess: () => {
          setNote('')
        },
      },
    )
  }

  const columns = useMemo<Column<Signoff>[]>(
    () => [
      { key: 'cell', header: 'Cell', mono: true, sortValue: (s) => cellLabel(s.cell), cell: (s) => cellLabel(s.cell) },
      {
        key: 'status',
        header: 'Status',
        sortValue: (s) => Number(s.revoked),
        cell: (s) =>
          s.revoked ? (
            <Pill tone="amber" glyph="⊘" size="xs" label={`Revoked by ${s.revoked_by ?? '—'} at ${fmtDate(s.revoked_at)}`}>revoked</Pill>
          ) : (
            <Pill tone="green" glyph="✓" size="xs" label="Active attestation">active</Pill>
          ),
      },
      { key: 'approver', header: 'Approver', sortValue: (s) => s.approver, cell: (s) => s.approver },
      { key: 'created', header: 'Signed', sortValue: (s) => s.created, cell: (s) => <span className="text-xs text-on-surface-muted">{fmtDate(s.created)}</span> },
      {
        key: 'evidence',
        header: 'Evidence at signing',
        cell: (s) => (
          <span className="num text-xs">
            n={fmtInt(s.evidence.n)} · {fmtPct(s.evidence.point)} · lower {fmtPct(s.evidence.ci_low)} · fQ1 {s.evidence.false_q1}
            <Provenance apparatus={s.evidence.apparatus_versions} className="ml-2" />
          </span>
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

  return (
    <>
      <PageHeader
        eyebrow="Sign-off"
        title="Sign-off"
        purpose="A human attestation that a cell's evidence has been reviewed and is trusted for auto-delivery. The server refuses (409) any attestation over evidence with false-Q1 > 0 — the refusal is a gate, not an error."
        actions={<RepoPicker value={repo} onChange={setRepo} />}
      />

      {!repo && <EmptyState title="Choose a repo to review attestations" action={<LinkButton to="/repos">Go to repos</LinkButton>} />}

      {repo && (
        <>
          <GateBanner
            title={cell ? `Attest ${cell.capability_class} × ${cell.size}` : 'Attest a cell'}
            eyebrow={`policy ${map.data?.policy?.version ?? '—'}`}
            criteria={criteria}
            refused={refusal}
            data-testid="signoff-gate"
            action={
              can('approver') ? (
                <Button type="submit" form="signoff-form" variant="filled" disabled={!allOk || !cell || create.isPending || !note.trim()}>
                  {create.isPending ? 'Recording…' : 'Sign off'}
                </Button>
              ) : (
                <span className="text-xs text-on-surface-muted">Requires the approver role{me ? ` (you are ${me.role})` : ''}.</span>
              )
            }
          />

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
              <div className="sm:col-span-2">
                <TextArea label="Attestation note" required rows={3} value={note} onChange={(e) => setNote(e.target.value)} hint="What you reviewed and why this evidence is trusted. Recorded verbatim, append-only." />
              </div>
              {create.isError && !refusal && (
                <div className="sm:col-span-2">
                  <ErrorState compact error={create.error} />
                </div>
              )}
              {create.isSuccess && (
                <p className="text-sm text-status-green sm:col-span-2" role="status">
                  ✓ Attestation recorded.
                </p>
              )}
            </form>
          </Card>

          <Card padded={false} title="Attestations">
            <QueryBoundary query={signoffs} loading="Loading attestations…">
              {(page) => (
                <DataTable
                  rows={page.items}
                  columns={columns}
                  rowKey={(s) => s.id}
                  caption={`Sign-offs for ${repo}`}
                  initialSort={{ key: 'created', dir: 'desc' }}
                  empty={<EmptyState title="No attestations yet" reason="An attestation records that a human reviewed a cell's evidence. Choose a cell above whose gate is open." />}
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
