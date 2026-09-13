import { useMemo, useState } from 'react'
import { Link, useParams } from 'react-router'
import { useTask } from '../../api/hooks'
import { beltsOf, type GradeRow } from '../../api/types'
import { BeltPills } from '../../components/BeltPills'
import { Card } from '../../components/Card'
import { DataTable, type Column } from '../../components/DataTable'
import { EmptyState } from '../../components/EmptyState'
import { JsonView } from '../../components/JsonView'
import { PageHeader } from '../../components/PageHeader'
import { Pill } from '../../components/Pill'
import { Provenance } from '../../components/Provenance'
import { QueryBoundary } from '../../components/QueryBoundary'
import { fmtDate, fmtSeconds, fmtUsd, shortId } from '../../lib/format'
import { EvidenceDrawer } from './EvidenceDrawer'

/** `GET /tasks/{repo}/{task_id}` — the spec and every grade row for it. */
export function TaskDetailPage() {
  const { repo = '', taskId = '' } = useParams()
  const q = useTask(repo, taskId)
  const [pack, setPack] = useState<string | null>(null)

  const columns = useMemo<Column<GradeRow>[]>(
    () => [
      { key: 'created', header: 'Created', sortValue: (r) => r.created, cell: (r) => <span className="text-xs text-on-surface-muted">{fmtDate(r.created)}</span> },
      { key: 'run', header: 'Run', mono: true, sortValue: (r) => r.run_id, cell: (r) => (r.run_id ? <Link to={`/runs/${encodeURIComponent(r.run_id)}`}>{shortId(r.run_id, 8)}</Link> : '—') },
      { key: 'trial', header: 'Trial', mono: true, sortValue: (r) => r.trial, cell: (r) => `${r.mode} · ${r.trial || 'r1'}` },
      { key: 'builder', header: 'Builder', mono: true, sortValue: (r) => r.builder, cell: (r) => (r.builder ? `${r.builder}${r.model ? ` · ${r.model}` : ''}` : '—') },
      {
        key: 'clean',
        header: 'Clean',
        sortValue: (r) => Number(r.clean),
        cell: (r) => (r.clean ? <Pill tone="green" glyph="✓" size="xs" label="Clean">clean</Pill> : r.disqualified ? <Pill tone="amber" glyph="⊘" size="xs" label={`Disqualified: ${r.dq_reason}`}>DQ</Pill> : <Pill tone="red" glyph="✗" size="xs" label={r.error || 'Not clean'}>no</Pill>),
      },
      { key: 'belts', header: 'Belts', cell: (r) => <BeltPills belts={beltsOf(r)} showNames={false} /> },
      { key: 'cost', header: 'Cost', numeric: true, sortValue: (r) => r.cost_usd, cell: (r) => fmtUsd(r.cost_usd) },
      { key: 'latency', header: 'Latency', numeric: true, sortValue: (r) => r.latency_s, cell: (r) => fmtSeconds(r.latency_s) },
      { key: 'prov', header: 'Provenance', cell: (r) => <Provenance apparatus={r.apparatus_version} beltSet={r.belt_set} provenance={r.provenance} />, hideBelowMd: true },
      {
        key: 'pack',
        header: 'Evidence',
        cell: (r) =>
          r.evidence_pack_hash ? (
            <button type="button" className="font-mono text-xs text-primary underline-offset-2 hover:underline" onClick={() => setPack(r.evidence_pack_hash)} title={r.evidence_pack_hash}>
              {shortId(r.evidence_pack_hash, 10)}
            </button>
          ) : (
            <span className="text-xs text-on-surface-muted">no pack</span>
          ),
      },
    ],
    [],
  )

  return (
    <>
      <PageHeader eyebrow={`Tasks · ${repo}`} title={`Task ${shortId(taskId)}`} purpose="One replayable commit: its spec (the oracle, the source files, the belt scope) and every graded trial against it." />
      <QueryBoundary query={q} loading="Loading the task…">
        {(t) => (
          <div className="space-y-6">
            <Card title={t.spec.subject} eyebrow={`${t.spec.capability_class} · ${t.spec.size} · ${t.spec.pool} · ${t.spec.language || '—'}`}>
              <dl className="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
                <div>
                  <dt className="label">Commit</dt>
                  <dd className="font-mono text-xs">{t.spec.task_id}</dd>
                </div>
                <div>
                  <dt className="label">Authored</dt>
                  <dd>{fmtDate(t.spec.authored)}</dd>
                </div>
                <div>
                  <dt className="label">Target tests</dt>
                  <dd className="font-mono text-xs">{t.spec.target_tests.join(', ') || '—'}</dd>
                </div>
                <div>
                  <dt className="label">Belt scope</dt>
                  <dd className="font-mono text-xs">{t.spec.belt_scope.length ? t.spec.belt_scope.join(', ') : 'BARE'}</dd>
                </div>
                <div>
                  <dt className="label">Test files</dt>
                  <dd className="font-mono text-xs">{t.spec.test_files.join(', ')}</dd>
                </div>
                <div>
                  <dt className="label">Source files</dt>
                  <dd className="font-mono text-xs">{t.spec.src_files.join(', ')}</dd>
                </div>
                <div>
                  <dt className="label">RED-checked · gold</dt>
                  <dd>
                    {t.spec.red_checked ? '✓ RED at parent' : '— not checked'} · {t.spec.gold_clean === null ? 'gold unchecked' : t.spec.gold_clean ? '✓ gold clean' : `✗ gold failed (${t.spec.gold_note})`}
                  </dd>
                </div>
              </dl>
              <details className="mt-3 text-xs">
                <summary className="cursor-pointer text-on-surface-muted">Full spec</summary>
                <div className="mt-2">
                  <JsonView value={t.spec} label="Task spec" />
                </div>
              </details>
            </Card>
            <Card padded={false} title="Grade rows">
              <DataTable rows={t.grades} columns={columns} rowKey={(r) => r.row_id} caption="Grade rows for this task" dense initialSort={{ key: 'created', dir: 'desc' }} empty={<EmptyState compact title="Not graded yet" reason="No run has replayed this task." />} />
            </Card>
          </div>
        )}
      </QueryBoundary>
      <EvidenceDrawer packHash={pack} onClose={() => setPack(null)} />
    </>
  )
}

export default TaskDetailPage
