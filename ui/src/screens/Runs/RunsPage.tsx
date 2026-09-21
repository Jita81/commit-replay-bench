/**
 * Runs — every mine, replay, blind, oracle, controls and factory run: status, progress, counts (/runs).
 *
 * Navigation
 * ----------
 * What it is:   The screen at /runs (the list with repo / kind / status filters in the URL —
 *               the kind filter offers every kind a run can have, the dialog only the kinds
 *               it starts) and the `Progress` bar the run page reuses.
 * What it does: Lists `GET /runs` newest first with status, progress (done / total), clean /
 *               tasks, DQ / errors, builder, cost; polls only while a listed run is
 *               non-terminal; rows open the run page. `?new=<kind>` opens the run dialog
 *               pre-set to that kind (how "Start a replay run" links from empty states
 *               arrive here) only for a role that can start one; a viewer or approver
 *               reads who acts instead (J-FAC-12); operators get "Start run".
 * How:          `useRepoParam` + `useSearchParams` for the filters → `useRuns` → `DataTable`;
 *               `RunNewDialog` navigates to the new run on success.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/api/hooks.ts (`useRuns` and its polling rule), ui/src/api/types.ts
 *               (`Run`, `RUN_KINDS`), ui/src/screens/Runs/RunNewDialog.tsx,
 *               ui/src/screens/Runs/RunDetailPage.tsx (where a row leads; imports `Progress`),
 *               src/crb/server/routes/runs.py
 * Tested by:    ui/src/screens/Runs/RunsPage.test.tsx (the kind filter and the copy name every
 *               kind; ?new= opens the dialog for an operator only), ui/e2e/walkthrough/03-mine.spec.ts (the Runs list shows the run, the
 *               progress bar reports the run's own counts), ui/e2e/walkthrough/06-cancel.spec.ts,
 *               ui/e2e/walkthrough/07-settings-and-a11y.spec.ts
 * Touch when:   a run kind is added (src/crb/core/run.py, docs/API.md "Runs") — extend
 *               `RunKind` in ui/src/api/types.ts; never for a new repository.
 */
import { useMemo, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router'
import { useRuns } from '../../api/hooks'
import { RUN_KINDS, type Run, type RunKind, type RunStatus } from '../../api/types'
import { Button } from '../../components/Button'
import { Card } from '../../components/Card'
import { DataTable, type Column } from '../../components/DataTable'
import { EmptyState } from '../../components/EmptyState'
import { InlineSelect } from '../../components/Field'
import { PageHeader } from '../../components/PageHeader'
import { Pill } from '../../components/Pill'
import { QueryBoundary } from '../../components/QueryBoundary'
import { RepoPicker, useRepoParam } from '../../components/RepoPicker'
import { useAuth } from '../../lib/auth'
import { fmtDate, fmtInt, fmtPct, fmtUsd, shortId } from '../../lib/format'
import { runStatusDisplay } from '../../lib/verdict'
import { RunNewDialog } from './RunNewDialog'

/** The status filter's options. */
const STATUSES: RunStatus[] = ['queued', 'running', 'succeeded', 'failed', 'cancelled']
/** The kind filter's options: every kind a run can have, not only the kinds the dialog starts (a probe comes from the repo page, a label from the CLI, a factory run from /factory). */
const KIND_FILTERS: readonly RunKind[] = [...RUN_KINDS, 'probe', 'label', 'factory']

/** Done / total as a bar with `role="progressbar"`; red when failed, green when succeeded. */
export function Progress({ done, total, status }: { done: number; total: number; status: RunStatus }) {
  const pct = total > 0 ? done / total : 0
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-24 overflow-hidden rounded-full bg-surface-highest" role="progressbar" aria-valuemin={0} aria-valuemax={total} aria-valuenow={done} aria-label={`${done} of ${total} tasks`}>
        <div className={`h-full ${status === 'failed' ? 'bg-status-red' : status === 'succeeded' ? 'bg-status-green' : 'bg-primary'}`} style={{ width: `${pct * 100}%` }} />
      </div>
      <span className="num text-xs text-on-surface-muted">
        {fmtInt(done)}/{fmtInt(total)} · {fmtPct(pct, 0)}
      </span>
    </div>
  )
}

/** The screen; filters live in the URL, `?new=<kind>` opens the dialog. */
export function RunsPage() {
  const [repo, setRepo] = useRepoParam()
  const [params, setParams] = useSearchParams()
  const kind = (params.get('kind') ?? '') as RunKind | ''
  const status = (params.get('status') ?? '') as RunStatus | ''
  const initialNew = params.get('new')
  const [starting, setStarting] = useState(initialNew !== null)
  const { can } = useAuth()
  const navigate = useNavigate()
  const runs = useRuns({ repo: repo || undefined, kind: kind || undefined, status: status || undefined, limit: 200 })

  const setFilter = (k: string, v: string) => {
    const next = new URLSearchParams(params)
    if (v) next.set(k, v)
    else next.delete(k)
    setParams(next, { replace: true })
  }

  const columns = useMemo<Column<Run>[]>(
    () => [
      { key: 'id', header: 'Run', mono: true, sortValue: (r) => r.id, cell: (r) => <Link to={`/runs/${encodeURIComponent(r.id)}`} title={r.id}>{shortId(r.id, 8)}</Link> },
      { key: 'repo', header: 'Repo', sortValue: (r) => r.repo, cell: (r) => r.repo },
      { key: 'kind', header: 'Kind', sortValue: (r) => r.kind, cell: (r) => <span className="font-mono text-xs">{r.kind}{r.kind === 'replay' || r.kind === 'blind' ? ` · ${r.mode}` : ''}</span> },
      {
        key: 'status',
        header: 'Status',
        sortValue: (r) => r.status,
        cell: (r) => {
          const d = runStatusDisplay(r.status)
          return (
            <Pill tone={d.tone} glyph={d.glyph} size="xs" label={d.describe + (r.cancel_requested ? ' (cancel requested)' : '')}>
              <span className={r.status === 'running' ? 'crb-pulse' : ''}>{d.label}</span>
            </Pill>
          )
        },
      },
      { key: 'progress', header: 'Progress', sortValue: (r) => (r.progress.total ? r.progress.done / r.progress.total : 0), cell: (r) => <Progress done={r.progress.done} total={r.progress.total} status={r.status} /> },
      { key: 'clean', header: 'Clean', numeric: true, sortValue: (r) => r.counts.clean, cell: (r) => `${fmtInt(r.counts.clean)}/${fmtInt(r.counts.tasks)}` },
      { key: 'dq', header: 'DQ / err', numeric: true, sortValue: (r) => r.counts.disqualified + r.counts.errors, cell: (r) => `${fmtInt(r.counts.disqualified)} / ${fmtInt(r.counts.errors)}`, hideBelowMd: true },
      { key: 'builder', header: 'Builder', sortValue: (r) => r.builder, cell: (r) => (r.builder ? <span className="font-mono text-xs">{r.builder}{r.model ? ` · ${r.model}` : ''}</span> : <span className="text-on-surface-muted">—</span>), hideBelowMd: true },
      { key: 'cost', header: 'Cost', numeric: true, sortValue: (r) => r.cost_usd, cell: (r) => fmtUsd(r.cost_usd), hideBelowMd: true },
      { key: 'created', header: 'Created', sortValue: (r) => r.created, cell: (r) => <span className="text-xs text-on-surface-muted">{fmtDate(r.created)}</span> },
    ],
    [],
  )

  return (
    <>
      <PageHeader
        eyebrow="Instrument · Runs"
        title="Runs"
        purpose="Every mine, replay, blind, oracle, controls and factory run: its status, progress and counts. A run's rows are what the ledger, the capability map and the factory's evidence are made of."
        actions={
          <>
            <RepoPicker value={repo} onChange={setRepo} />
            <InlineSelect label="Kind" value={kind} onChange={(e) => setFilter('kind', e.target.value)}>
              <option value="">all</option>
              {KIND_FILTERS.map((k) => (
                <option key={k} value={k}>
                  {k}
                </option>
              ))}
            </InlineSelect>
            <InlineSelect label="Status" value={status} onChange={(e) => setFilter('status', e.target.value)}>
              <option value="">all</option>
              {STATUSES.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </InlineSelect>
            {can('operator') && (
              <Button variant="filled" onClick={() => setStarting(true)}>
                Start run
              </Button>
            )}
          </>
        }
      />
      <Card padded={false}>
        <QueryBoundary query={runs} loading="Loading runs…">
          {(page) => (
            <DataTable
              rows={page.items}
              columns={columns}
              rowKey={(r) => r.id}
              caption="Runs"
              initialSort={{ key: 'created', dir: 'desc' }}
              onRowClick={(r) => navigate(`/runs/${encodeURIComponent(r.id)}`)}
              empty={
                <EmptyState
                  title="No runs match"
                  reason={
                    repo || kind || status
                      ? 'Nothing matches these filters yet.'
                      : can('operator')
                        ? 'A run is a mine, replay, blind, oracle, controls or factory job over one repo. Start one here to produce ledger rows; the factory is started from Factory.'
                        : 'A run is a mine, replay, blind, oracle, controls or factory job over one repo. An operator starts a run; it spends model budget. The factory is started from Factory.'
                  }
                  action={can('operator') ? <Button variant="filled" onClick={() => setStarting(true)}>Start a run</Button> : undefined}
                />
              }
            />
          )}
        </QueryBoundary>
      </Card>
      <RunNewDialog
        open={starting && can('operator')}
        onClose={() => {
          setStarting(false)
          if (initialNew !== null) setFilter('new', '')
        }}
        repo={repo || undefined}
        initialKind={(initialNew as RunKind) || 'replay'}
        onCreated={(run) => navigate(`/runs/${run.id}`)}
      />
    </>
  )
}

export default RunsPage
