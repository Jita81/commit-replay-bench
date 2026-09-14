import { useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router'
import { apiUrl } from '../../api/client'
import { useGrades, useLedgerVerify } from '../../api/hooks'
import { beltsOf, type GradeListParams, type GradeRow } from '../../api/types'
import { BeltPills } from '../../components/BeltPills'
import { AnchorButton } from '../../components/Button'
import { Card } from '../../components/Card'
import { DataTable, type Column } from '../../components/DataTable'
import { EmptyState } from '../../components/EmptyState'
import { GateBanner } from '../../components/GateBanner'
import { InlineSelect } from '../../components/Field'
import { PageHeader } from '../../components/PageHeader'
import { Pill } from '../../components/Pill'
import { Provenance } from '../../components/Provenance'
import { QueryBoundary } from '../../components/QueryBoundary'
import { RepoPicker, useRepoParam } from '../../components/RepoPicker'
import { StatTile } from '../../components/StatTile'
import { useAuth } from '../../lib/auth'
import { fmtDate, fmtInt, fmtRatio, fmtSeconds, fmtUsd, shortId } from '../../lib/format'

const PAGE = 100
const FILTER_KEYS = ['run_id', 'task_id', 'clean', 'mode', 'builder', 'model', 'capability_class', 'size', 'language'] as const

export function LedgerPage() {
  const [repo, setRepo] = useRepoParam()
  const [params, setParams] = useSearchParams()
  const [offset, setOffset] = useState(0)
  const { can } = useAuth()
  const verify = useLedgerVerify()

  const filters: GradeListParams = { repo: repo || undefined, limit: PAGE, offset }
  for (const k of FILTER_KEYS) {
    const v = params.get(k)
    if (!v) continue
    if (k === 'clean') filters.clean = v === 'true'
    else if (k === 'mode') filters.mode = v as GradeListParams['mode']
    else filters[k] = v
  }
  const grades = useGrades(filters)

  const setFilter = (k: string, v: string) => {
    const next = new URLSearchParams(params)
    if (v) next.set(k, v)
    else next.delete(k)
    setParams(next, { replace: true })
    setOffset(0)
  }

  const columns = useMemo<Column<GradeRow>[]>(
    () => [
      { key: 'created', header: 'Created', sortValue: (r) => r.created, cell: (r) => <span className="text-xs text-on-surface-muted">{fmtDate(r.created)}</span> },
      { key: 'repo', header: 'Repo', sortValue: (r) => r.repo, cell: (r) => r.repo },
      { key: 'task', header: 'Task', mono: true, sortValue: (r) => r.task_id, cell: (r) => <Link to={`/tasks/${encodeURIComponent(r.repo)}/${r.task_id}`} title={r.task_id}>{shortId(r.task_id)}</Link> },
      { key: 'cell', header: 'Cell', mono: true, sortValue: (r) => `${r.capability_class}|${r.size}`, cell: (r) => `${r.capability_class} · ${r.size}` },
      { key: 'builder', header: 'Builder', mono: true, sortValue: (r) => r.builder, cell: (r) => (r.builder ? `${r.builder}${r.model ? ` · ${r.model}` : ''}` : '—'), hideBelowMd: true },
      { key: 'mode', header: 'Mode', sortValue: (r) => r.mode, cell: (r) => <span className="font-mono text-xs">{r.mode} · {r.trial || 'r1'}</span>, hideBelowMd: true },
      {
        key: 'clean',
        header: 'Clean',
        sortValue: (r) => Number(r.clean),
        cell: (r) =>
          r.clean ? (
            <Pill tone="green" glyph="✓" size="xs" label="Clean">clean</Pill>
          ) : r.disqualified ? (
            <Pill tone="amber" glyph="⊘" size="xs" label={`Disqualified: ${r.dq_reason}`}>DQ</Pill>
          ) : (
            <Pill tone="red" glyph="✗" size="xs" label={r.error ? `Error: ${r.error}` : 'Not clean'}>{r.error ? 'error' : 'no'}</Pill>
          ),
      },
      { key: 'belts', header: 'Belts', cell: (r) => <BeltPills belts={beltsOf(r)} beltSet={r.belt_set} showNames={false} /> },
      { key: 'cost', header: 'Cost', numeric: true, sortValue: (r) => r.cost_usd, cell: (r) => fmtUsd(r.cost_usd), hideBelowMd: true },
      { key: 'latency', header: 'Latency', numeric: true, sortValue: (r) => r.latency_s, cell: (r) => fmtSeconds(r.latency_s), hideBelowMd: true },
      { key: 'oracle', header: 'Oracle', numeric: true, sortValue: (r) => r.oracle_strength ?? -1, cell: (r) => fmtRatio(r.oracle_strength), hideBelowMd: true },
      { key: 'prov', header: 'Provenance', cell: (r) => <Provenance apparatus={r.apparatus_version} beltSet={r.belt_set} provenance={r.provenance} />, hideBelowMd: true },
      { key: 'hash', header: 'Row hash', mono: true, cell: (r) => <span title={r.row_hash}>{shortId(r.row_hash, 10)}</span>, hideBelowMd: true },
    ],
    [],
  )

  const exportQs = repo ? `&repo=${encodeURIComponent(repo)}` : ''

  return (
    <>
      <PageHeader
        eyebrow="Ledger"
        title="Ledger"
        purpose="Every graded trial, append-only and hash-chained. Verify proves nothing was edited, reordered or removed; false-Q1 total is the number everything else defends."
        actions={
          <>
            <RepoPicker value={repo} onChange={setRepo} />
            <AnchorButton size="sm" href={apiUrl(`/ledger/export?format=jsonl${exportQs}`)} download>
              Export JSONL
            </AnchorButton>
            <AnchorButton size="sm" href={apiUrl(`/ledger/export?format=csv${exportQs}`)} download>
              Export CSV
            </AnchorButton>
            {can('operator') && (
              <AnchorButton size="sm" href={apiUrl('/ledger/export/abstract')} download title="Abstract cells only — no code, no ids (federated, k-anonymous)">
                Export abstract
              </AnchorButton>
            )}
          </>
        }
      />

      <QueryBoundary query={verify} loading="Verifying the hash chain…">
        {(v) => (
          <GateBanner
            title="Chain verification"
            eyebrow="append-only · hash-chained"
            data-testid="ledger-gate"
            criteria={[
              { label: 'Hash chain verifies', ok: v.ok, detail: v.ok ? `${fmtInt(v.rows)} rows, every prev_hash and row_hash match` : `broken at row ${v.broken_at ?? '?'} of ${fmtInt(v.rows)}` },
              { label: 'false-Q1 total = 0', ok: v.false_q1_total === 0, detail: `false_q1_total = ${v.false_q1_total}` },
            ]}
          />
        )}
      </QueryBoundary>

      <div className="flex flex-wrap gap-3">
        <StatTile label="Rows" value={verify.data ? fmtInt(verify.data.rows) : '—'} n={verify.data?.rows ?? 0} apparatus="whole ledger, all repos" />
        <StatTile label="false-Q1 total" value={verify.data ? String(verify.data.false_q1_total) : '—'} n={verify.data?.rows ?? 0} apparatus="enforced at write; re-checked at read" tone={verify.data ? (verify.data.false_q1_total === 0 ? 'green' : 'red') : undefined} data-testid="tile-false-q1-total" />
        <StatTile label="Matching rows" value={grades.data ? fmtInt(grades.data.total) : '—'} n={grades.data?.total ?? 0} apparatus="current filters" />
      </div>

      <Card
        padded={false}
        title="Rows"
        actions={
          <>
            <InlineSelect label="Clean" value={params.get('clean') ?? ''} onChange={(e) => setFilter('clean', e.target.value)}>
              <option value="">all</option>
              <option value="true">clean</option>
              <option value="false">not clean</option>
            </InlineSelect>
            <InlineSelect label="Mode" value={params.get('mode') ?? ''} onChange={(e) => setFilter('mode', e.target.value)}>
              <option value="">all</option>
              <option value="sighted">sighted</option>
              <option value="blind">blind</option>
            </InlineSelect>
            <InlineSelect label="Size" value={params.get('size') ?? ''} onChange={(e) => setFilter('size', e.target.value)}>
              <option value="">all</option>
              {['XS', 'S', 'M', 'L', 'XL'].map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </InlineSelect>
            <label className="inline-flex items-center gap-2 text-xs text-on-surface-muted">
              Class
              <input
                aria-label="Filter by capability class"
                className="h-8 w-44 rounded-[var(--radius-control)] border border-border bg-surface-container px-2 font-mono text-xs"
                defaultValue={params.get('capability_class') ?? ''}
                onBlur={(e) => setFilter('capability_class', e.target.value.trim())}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') setFilter('capability_class', (e.target as HTMLInputElement).value.trim())
                }}
                placeholder="e.g. bug.fix"
              />
            </label>
            <label className="inline-flex items-center gap-2 text-xs text-on-surface-muted">
              Model
              <input
                aria-label="Filter by model"
                className="h-8 w-36 rounded-[var(--radius-control)] border border-border bg-surface-container px-2 font-mono text-xs"
                defaultValue={params.get('model') ?? ''}
                onBlur={(e) => setFilter('model', e.target.value.trim())}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') setFilter('model', (e.target as HTMLInputElement).value.trim())
                }}
              />
            </label>
          </>
        }
      >
        <QueryBoundary query={grades} loading="Loading ledger rows…">
          {(page) => (
            <>
              <DataTable
                rows={page.items}
                columns={columns}
                rowKey={(r) => r.row_id}
                caption="Ledger rows"
                dense
                initialSort={{ key: 'created', dir: 'desc' }}
                empty={<EmptyState title="No rows match" reason={repo || params.toString() ? 'Nothing in the ledger matches these filters.' : 'The ledger is empty. Every graded trial appends one row.'} />}
              />
              <div className="flex items-center justify-between px-3 py-2 text-xs text-on-surface-muted">
                <span className="num">
                  {page.total === 0 ? '0 rows' : `${fmtInt(page.offset + 1)}–${fmtInt(Math.min(page.offset + page.limit, page.total))} of ${fmtInt(page.total)}`}
                </span>
                <span className="flex gap-2">
                  <button type="button" className="rounded px-2 py-1 hover:bg-surface-high disabled:opacity-40" disabled={page.offset === 0} onClick={() => setOffset(Math.max(0, page.offset - page.limit))}>
                    ← Newer
                  </button>
                  <button type="button" className="rounded px-2 py-1 hover:bg-surface-high disabled:opacity-40" disabled={page.offset + page.limit >= page.total} onClick={() => setOffset(page.offset + page.limit)}>
                    Older →
                  </button>
                </span>
              </div>
            </>
          )}
        </QueryBoundary>
      </Card>
    </>
  )
}

export default LedgerPage
