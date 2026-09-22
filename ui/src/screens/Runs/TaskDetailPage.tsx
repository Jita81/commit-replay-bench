/**
 * Task detail — one replayable commit: its spec and every graded trial against it
 * (/tasks/:repo/:taskId).
 *
 * Navigation
 * ----------
 * What it is:   The screen at /tasks/:repo/:taskId.
 * What it does: Renders `GET /tasks/{repo}/{task_id}`: the spec (target tests, belt scope,
 *               test and source files, RED-checked, gold status, the full JSON behind a
 *               disclosure) and every grade row in chain order — clean / DQ / error, belts,
 *               cost, latency, provenance, the STANDING review verdict per row (the latest
 *               review wins) and the evidence link that opens the drawer on that row. A task
 *               the factory built (`labels.process === 'factory'`) is introduced as one
 *               factory item — in the header's purpose sentence and the card alike — with its
 *               backlog id, and its id explained (the authored test's sha), so it is not read
 *               as a commit (J-FAC-18).
 * How:          `useTask` + `useReviews({repo, task_id})` → a `Map` of row hash → latest review
 *               → `DataTable`; the drawer is opened with both the pack hash and the row hash
 *               so the Patch / Review tabs need no resolution.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/api/hooks.ts (`useTask`), ui/src/api/types.ts (`TaskSpec`, `GradeRow`,
 *               `beltsOf`), ui/src/screens/Runs/contract.ts (`useReviews`),
 *               ui/src/screens/Runs/EvidenceDrawer.tsx and ui/src/screens/Runs/ReviewPanel.tsx
 *               (`VerdictPill`), src/crb/server/routes/grades.py (the task route),
 *               src/crb/core/spec.py (`TaskSpec`), src/crb/factory/build.py (the labels a
 *               factory task carries: `item_id`, `process`, `red_proof`)
 * Tested by:    ui/src/screens/Runs/TaskDetailPage.test.tsx (a factory item is named as one;
 *               a commit keeps the commit wording), ui/e2e/walkthrough/09-review.spec.ts (the
 *               task page shows the recorded verdict)
 * Touch when:   `TaskSpec` gains a field worth showing (src/crb/core/spec.py, then
 *               ui/src/api/types.ts); never for a new repository.
 */
import { useMemo, useState } from 'react'
import { Link, useParams } from 'react-router'
import { useTask } from '../../api/hooks'
import { beltsOf, type GradeRow, type TaskSpec } from '../../api/types'
import { BeltPills } from '../../components/BeltPills'
import { Card } from '../../components/Card'
import { DataTable, type Column } from '../../components/DataTable'
import { EmptyState } from '../../components/EmptyState'
import { Hint } from '../../components/Hint'
import { JsonView } from '../../components/JsonView'
import { PageHeader } from '../../components/PageHeader'
import { Pill } from '../../components/Pill'
import { Provenance } from '../../components/Provenance'
import { QueryBoundary } from '../../components/QueryBoundary'
import { ShortId } from '../../components/ShortId'
import { fmtDate, fmtSeconds, fmtUsd, shortId } from '../../lib/format'
import { useReviews, type Review } from './contract'
import { EvidenceDrawer } from './EvidenceDrawer'
import { VerdictPill } from './ReviewPanel'

/** `GET /tasks/{repo}/{task_id}` — the spec and every grade row for it. */
/** A task the factory built rather than a mined commit (`labels.process`, src/crb/factory/build.py). */
function isFactory(spec: TaskSpec): boolean {
  return spec.labels.process === 'factory'
}

export function TaskDetailPage() {
  const { repo = '', taskId = '' } = useParams()
  const q = useTask(repo, taskId)
  const [open, setOpen] = useState<{ pack: string; row: string } | null>(null)
  const reviews = useReviews({ repo, task_id: taskId }, repo.length > 0 && taskId.length > 0)
  // the standing (latest) review per graded row — chain order, last wins
  const standing = useMemo(() => {
    const m = new Map<string, Review>()
    for (const r of reviews.data?.items ?? []) m.set(r.grade_row_hash, r)
    return m
  }, [reviews.data])

  const columns = useMemo<Column<GradeRow>[]>(
    () => [
      { key: 'created', header: 'Created', hint: 'col.task.created', sortValue: (r) => r.created, cell: (r) => <span className="text-xs text-on-surface-muted">{fmtDate(r.created)}</span> },
      { key: 'run', header: 'Run', hint: 'col.task.run', mono: true, sortValue: (r) => r.run_id, cell: (r) => (r.run_id ? <Link to={`/runs/${encodeURIComponent(r.run_id)}`}>{shortId(r.run_id, 8)}</Link> : '—') },
      { key: 'trial', header: 'Trial', hint: 'col.task.trial', mono: true, sortValue: (r) => r.trial, cell: (r) => `${r.mode} · ${r.trial || 'r1'}` },
      { key: 'builder', header: 'Builder', hint: 'col.task.builder', mono: true, sortValue: (r) => r.builder, cell: (r) => (r.builder ? `${r.builder}${r.model ? ` · ${r.model}` : ''}` : '—') },
      {
        key: 'clean',
        header: 'Clean',
        hint: 'col.task.clean',
        sortValue: (r) => Number(r.clean),
        cell: (r) =>
          r.clean ? (
            <Pill tone="green" glyph="✓" size="xs" label="Clean" hint="pill.task.clean" tabStop={false}>
              clean
            </Pill>
          ) : r.disqualified ? (
            <Pill tone="amber" glyph="⊘" size="xs" label={`Disqualified: ${r.dq_reason}`} hint="pill.task.clean" tabStop={false}>
              DQ
            </Pill>
          ) : (
            <Pill tone="red" glyph="✗" size="xs" label={r.error || 'Not clean'} hint="pill.task.clean" tabStop={false}>
              no
            </Pill>
          ),
      },
      { key: 'belts', header: 'Belts', hint: 'col.task.belts', cell: (r) => <BeltPills belts={beltsOf(r)} beltSet={r.belt_set} showNames={false} /> },
      { key: 'cost', header: 'Cost', hint: 'col.task.cost_latency', numeric: true, sortValue: (r) => r.cost_usd, cell: (r) => fmtUsd(r.cost_usd) },
      { key: 'latency', header: 'Latency', hint: 'col.task.cost_latency', numeric: true, sortValue: (r) => r.latency_s, cell: (r) => fmtSeconds(r.latency_s) },
      { key: 'prov', header: 'Provenance', hint: 'col.task.provenance', cell: (r) => <Provenance apparatus={r.apparatus_version} beltSet={r.belt_set} provenance={r.provenance} />, hideBelowMd: true },
      {
        key: 'review',
        header: 'Review',
        hint: 'col.task.review',
        sortValue: (r) => standing.get(r.row_hash)?.verdict ?? '',
        cell: (r) => {
          const rev = standing.get(r.row_hash)
          return rev ? (
            <button type="button" className="inline-flex" onClick={() => setOpen({ pack: rev.evidence_pack_hash || r.evidence_pack_hash, row: r.row_hash })} data-testid="row-review">
              <VerdictPill verdict={rev.verdict} />
            </button>
          ) : (
            <span className="text-xs text-on-surface-muted" data-testid="row-unreviewed">
              not reviewed
            </span>
          )
        },
      },
      {
        key: 'pack',
        header: 'Evidence',
        hint: 'col.task.evidence',
        cell: (r) =>
          r.evidence_pack_hash ? (
            <button type="button" className="font-mono text-xs text-primary underline-offset-2 hover:underline" onClick={() => setOpen({ pack: r.evidence_pack_hash, row: r.row_hash })}>
              <ShortId value={r.evidence_pack_hash} n={10} />
            </button>
          ) : (
            <span className="text-xs text-on-surface-muted">no pack</span>
          ),
      },
    ],
    [standing],
  )

  // the header is the first sentence read: it must agree with the card below on what this is
  const factory = q.data ? isFactory(q.data.spec) : false
  const purpose = factory
    ? 'One factory item the loop built: its authored test (the RED proof), the spec it was built to and every graded trial against it.'
    : 'One replayable commit: its spec (the oracle, the source files, the belt scope) and every graded trial against it.'
  return (
    <>
      <PageHeader eyebrow={`Tasks · ${repo}`} title={`Task ${shortId(taskId)}`} purpose={purpose} />
      <QueryBoundary query={q} loading="Loading the task…">
        {(t) => (
          <div className="space-y-6">
            <Card title={t.spec.subject} eyebrow={`${t.spec.capability_class} · ${t.spec.size} · ${t.spec.pool} · ${t.spec.language || '—'}`}>
              {isFactory(t.spec) && (
                <p className="mb-3 text-sm text-on-surface-muted">
                  One factory item{t.spec.labels.item_id ? ` (${t.spec.labels.item_id})` : ''} — not a replayed commit: the id is the authored test's sha, the RED proof the factory wrote before building. Its graded trials sit in the same table as a commit's.
                </p>
              )}
              <dl className="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
                <div>
                  <Hint as="dt" id="tile.task.id" className="label">
                    {isFactory(t.spec) ? 'Factory item' : 'Commit'}
                  </Hint>
                  <dd className="font-mono text-xs">{t.spec.task_id}</dd>
                </div>
                <div>
                  <Hint as="dt" id="tile.task.authored" className="label">
                    Authored
                  </Hint>
                  <dd>{fmtDate(t.spec.authored)}</dd>
                </div>
                <div>
                  <Hint as="dt" id="tile.task.target_tests" className="label">
                    Target tests
                  </Hint>
                  <dd className="font-mono text-xs">{t.spec.target_tests.join(', ') || '—'}</dd>
                </div>
                <div>
                  <Hint as="dt" id="tile.task.belt_scope" className="label">
                    Belt scope
                  </Hint>
                  <dd className="font-mono text-xs">{t.spec.belt_scope.length ? t.spec.belt_scope.join(', ') : 'BARE'}</dd>
                </div>
                <div>
                  <Hint as="dt" id="tile.task.files" className="label">
                    Test files
                  </Hint>
                  <dd className="font-mono text-xs">{t.spec.test_files.join(', ')}</dd>
                </div>
                <div>
                  <Hint as="dt" id="tile.task.files" className="label">
                    Source files
                  </Hint>
                  <dd className="font-mono text-xs">{t.spec.src_files.join(', ')}</dd>
                </div>
                <div>
                  <Hint as="dt" id="tile.task.red_gold" className="label">
                    RED-checked · gold
                  </Hint>
                  <dd>
                    {t.spec.red_checked ? '✓ RED at parent' : '— not checked'} · {t.spec.gold_clean === null ? 'gold unchecked' : t.spec.gold_clean ? '✓ gold clean' : `✗ gold failed (${t.spec.gold_note})`}
                  </dd>
                </div>
              </dl>
              <Hint as="details" id="tile.task.full_spec" className="mt-3 text-xs">
                <summary className="cursor-pointer text-on-surface-muted">Full spec</summary>
                <div className="mt-2">
                  <JsonView value={t.spec} label="Task spec" />
                </div>
              </Hint>
            </Card>
            <Card padded={false} title="Grade rows">
              <DataTable rows={t.grades} columns={columns} rowKey={(r) => r.row_id} caption="Grade rows for this task" dense initialSort={{ key: 'created', dir: 'desc' }} empty={<EmptyState compact title="Not graded yet" reason={isFactory(t.spec) ? 'The factory has not built this item yet.' : 'No run has replayed this task.'} />} />
            </Card>
          </div>
        )}
      </QueryBoundary>
      <EvidenceDrawer packHash={open?.pack ?? null} rowHash={open?.row ?? null} onClose={() => setOpen(null)} />
    </>
  )
}

export default TaskDetailPage
