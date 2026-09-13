import { useEffect, useMemo, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Link, useParams } from 'react-router'
import { useCancelRun, useRun, useRunEvents, useRunTasks } from '../../api/hooks'
import type { EventSourceFactory } from '../../api/sse'
import { isRunTerminal, type Run, type RunTaskRow } from '../../api/types'
import { BeltPills } from '../../components/BeltPills'
import { Button } from '../../components/Button'
import { Card } from '../../components/Card'
import { DataTable, type Column } from '../../components/DataTable'
import { EmptyState } from '../../components/EmptyState'
import { ErrorState } from '../../components/ErrorState'
import { LiveLog } from '../../components/LiveLog'
import { PageHeader } from '../../components/PageHeader'
import { Pill } from '../../components/Pill'
import { QueryBoundary } from '../../components/QueryBoundary'
import { StatTile } from '../../components/StatTile'
import { useAuth } from '../../lib/auth'
import { fmtDate, fmtInt, fmtPct, fmtSeconds, fmtUsd, shortId, wilson } from '../../lib/format'
import { runStatusDisplay } from '../../lib/verdict'
import { EvidenceDrawer } from './EvidenceDrawer'
import { Progress } from './RunsPage'

const SIZE_ORDER = ['XS', 'S', 'M', 'L', 'XL']

function Header({ run }: { run: Run }) {
  const { can } = useAuth()
  const cancel = useCancelRun()
  const d = runStatusDisplay(run.status)
  return (
    <PageHeader
      eyebrow={`Runs · ${run.repo} · ${run.kind}`}
      title={`Run ${shortId(run.id, 8)}`}
      purpose={
        <span className="inline-flex flex-wrap items-center gap-2">
          <Pill tone={d.tone} glyph={d.glyph} label={d.describe}>
            <span className={run.status === 'running' ? 'crb-pulse' : ''}>{d.label}</span>
          </Pill>
          {run.cancel_requested && !isRunTerminal(run.status) && (
            <Pill tone="amber" glyph="⊘" size="xs" label="Cancel requested; the worker stops between tasks">
              cancel requested
            </Pill>
          )}
          <span className="font-mono text-xs">
            {run.kind === 'replay' || run.kind === 'blind' ? `${run.mode} · ${run.builder || '—'}${run.model ? ` · ${run.model}` : ''}${run.provider ? ` · ${run.provider}` : ''} · ladder ${run.ladder.join(',') || 'r1'}` : run.kind}
          </span>
          <span className="text-xs text-on-surface-muted">
            created {fmtDate(run.created)}
            {run.started ? ` · started ${fmtDate(run.started)}` : ''}
            {run.finished ? ` · finished ${fmtDate(run.finished)}` : ''}
          </span>
        </span>
      }
      actions={
        <>
          <Link to={`/repos/${encodeURIComponent(run.repo)}`} className="text-sm">
            {run.repo}
          </Link>
          {can('operator') && !isRunTerminal(run.status) && !run.cancel_requested && (
            <Button variant="danger" size="sm" onClick={() => cancel.mutate(run.id)} disabled={cancel.isPending}>
              {cancel.isPending ? 'Requesting…' : 'Cancel run'}
            </Button>
          )}
        </>
      }
    />
  )
}

function Tiles({ run }: { run: Run }) {
  const c = run.counts
  const graded = c.tasks
  const cleanCi = graded > 0 ? wilson(c.clean, graded) : null
  const fpCi = graded > 0 ? wilson(c.first_pass_clean, graded) : null
  const app = `apparatus ${run.apparatus_version || '—'} · Wilson 95%`
  return (
    <div className="flex flex-wrap gap-3">
      <StatTile label="Clean (any rung)" value={graded ? fmtPct(c.clean / graded) : '—'} n={graded} ci={cleanCi} apparatus={app} tone={graded ? 'green' : undefined} data-testid="tile-clean" />
      <StatTile label="First-pass clean (r1)" value={graded ? fmtPct(c.first_pass_clean / graded) : '—'} n={graded} ci={fpCi} apparatus={app} />
      <StatTile label="Disqualified" value={fmtInt(c.disqualified)} n={graded} apparatus="tamper or malformed oracle — excluded, not counted" tone={c.disqualified ? 'amber' : undefined} />
      <StatTile label="Errors" value={fmtInt(c.errors)} n={graded} apparatus="harness/sandbox errors — fail closed" tone={c.errors ? 'red' : undefined} />
      <StatTile label="Ledger rows" value={fmtInt(c.rows)} n={c.rows} apparatus="one row per attempt (trial r1, r2 …)" />
      <StatTile label="Cost" value={fmtUsd(run.cost_usd)} n={graded} apparatus="builder-reported USD, summed" />
    </div>
  )
}

function TaskTable({ runId, poll, onOpenPack }: { runId: string; poll: boolean; onOpenPack: (hash: string) => void }) {
  const tasks = useRunTasks(runId, { poll })
  const columns = useMemo<Column<RunTaskRow>[]>(
    () => [
      { key: 'task', header: 'Task', mono: true, sortValue: (t) => t.task_id, cell: (t) => <span title={t.task_id}>{shortId(t.task_id)}</span> },
      { key: 'class', header: 'Class', mono: true, sortValue: (t) => t.capability_class, cell: (t) => t.capability_class },
      { key: 'size', header: 'Size', sortValue: (t) => SIZE_ORDER.indexOf(t.size), cell: (t) => <span className="font-mono text-xs">{t.size}</span> },
      { key: 'trials', header: 'Trials', numeric: true, sortValue: (t) => t.trials, cell: (t) => fmtInt(t.trials) },
      {
        key: 'clean',
        header: 'Outcome',
        sortValue: (t) => (t.clean ? 2 : t.disqualified ? 1 : 0),
        cell: (t) =>
          t.clean ? (
            <Pill tone="green" glyph="✓" size="xs" label="Clean: all four belts held">clean</Pill>
          ) : t.disqualified ? (
            <Pill tone="amber" glyph="⊘" size="xs" label="Disqualified — excluded from the denominator">DQ</Pill>
          ) : t.error ? (
            <Pill tone="red" glyph="✗" size="xs" label={`Error: ${t.error}`}>error</Pill>
          ) : (
            <Pill tone="red" glyph="✗" size="xs" label="Not clean">not clean</Pill>
          ),
      },
      { key: 'belts', header: 'Belts (last trial)', cell: (t) => <BeltPills belts={t.belts} showNames={false} /> },
      { key: 'cost', header: 'Cost', numeric: true, sortValue: (t) => t.cost_usd, cell: (t) => fmtUsd(t.cost_usd), hideBelowMd: true },
      { key: 'latency', header: 'Latency', numeric: true, sortValue: (t) => t.latency_s, cell: (t) => fmtSeconds(t.latency_s), hideBelowMd: true },
      {
        key: 'pack',
        header: 'Evidence',
        cell: (t) =>
          t.pack_hashes.length ? (
            <span className="inline-flex flex-wrap gap-1">
              {t.pack_hashes.map((h, i) => (
                <button
                  key={h}
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation()
                    onOpenPack(h)
                  }}
                  className="font-mono text-xs text-primary underline-offset-2 hover:underline"
                  title={h}
                >
                  r{i + 1} {shortId(h, 8)}
                </button>
              ))}
            </span>
          ) : (
            <span className="text-xs text-on-surface-muted">no pack</span>
          ),
      },
    ],
    [onOpenPack],
  )
  return (
    <QueryBoundary query={tasks} loading="Loading per-task outcomes…">
      {(page) => (
        <DataTable
          rows={page.items}
          columns={columns}
          rowKey={(t) => t.task_id}
          caption="Per-task outcomes"
          dense
          onRowClick={(t) => {
            const h = t.pack_hashes[t.pack_hashes.length - 1]
            if (h) onOpenPack(h)
          }}
          empty={<EmptyState compact title="No task outcomes yet" reason={poll ? 'Rows appear as each task is graded.' : 'This run graded no tasks.'} />}
        />
      )}
    </QueryBoundary>
  )
}

export interface RunDetailPageProps {
  /** Test seam: inject an EventSource implementation. */
  eventSourceFactory?: EventSourceFactory
}

export function RunDetailPage({ eventSourceFactory }: RunDetailPageProps = {}) {
  const { id = '' } = useParams()
  const run = useRun(id)
  const terminal = isRunTerminal(run.data?.status)
  const events = useRunEvents(id, { factory: eventSourceFactory })
  const [pack, setPack] = useState<string | null>(null)
  const qc = useQueryClient()
  // The server's `event: done` is authoritative: refetch the run (status, counts) and its
  // task table at once instead of waiting for the next poll — which is paused while the
  // tab is hidden.
  useEffect(() => {
    if (events.status === 'done') {
      void qc.invalidateQueries({ queryKey: ['runs'] })
    }
  }, [events.status, qc])

  return (
    <>
      {run.data ? <Header run={run.data} /> : <PageHeader eyebrow="Runs" title={`Run ${shortId(id, 8)}`} />}
      {run.isError && <ErrorState error={run.error} onRetry={() => void run.refetch()} />}
      {run.data && (
        <>
          <Card title="Progress">
            <Progress done={run.data.progress.done} total={run.data.progress.total} status={run.data.status} />
            {run.data.progress.current_task_id && !terminal && (
              <p className="num mt-2 font-mono text-xs text-on-surface-muted">current task {shortId(run.data.progress.current_task_id)}</p>
            )}
            {run.data.error && (
              <p className="mt-2 text-sm text-status-red" role="alert">
                {run.data.error}
              </p>
            )}
          </Card>
          <Tiles run={run.data} />
        </>
      )}
      <Card title="Live log" eyebrow="step events · SSE">
        <LiveLog events={events.events} status={events.status} reconnects={events.reconnects} dropped={events.dropped} error={events.error} />
      </Card>
      <Card title="Tasks" padded={false}>
        <TaskTable runId={id} poll={!terminal && run.isSuccess} onOpenPack={setPack} />
      </Card>
      <EvidenceDrawer packHash={pack} onClose={() => setPack(null)} />
    </>
  )
}

export default RunDetailPage
