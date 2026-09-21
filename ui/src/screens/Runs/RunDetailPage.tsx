/**
 * Run detail — one run's status, counts, live event stream and per-task table (/runs/:id).
 *
 * Navigation
 * ----------
 * What it is:   The run-detail screen: header with status and cancel, the Progress card (bar,
 *               the "Now" line, the queue position, the current stage, the worker heartbeat, a
 *               container whose kill the worker could not confirm — until it is reaped,
 *               the terms), headline tiles, the failure split, the live StepEvent log (SSE)
 *               and the per-task outcome table with the evidence drawer.
 * What it does: Renders GET /runs/{id}, /runs/{id}/tasks and the SSE stream; every number
 *               carries its n and apparatus (StatTile), a non-build run shows its own
 *               counters (counts.detail, nested counters flattened one level); a factory
 *               run's header names builder, model, ladder and the delivery switch with its
 *               override; the Progress card says when the run started, what it has spent,
 *               how long is likely left and on what basis (mean latency of the finished
 *               tasks × remaining — a planning estimate), which stage the last event puts it
 *               in, whether the worker is alive against the /health worker probe's limit,
 *               and — queued — its position and what is ahead. A field an older server does
 *               not send reads as absent, never as a zero. Cancelling asks the API, never
 *               the worker.
 * How:          TanStack Query hooks for the run, its tasks (the finished latencies) and
 *               /health (the worker probe's `stale_after_s` and queued count); an
 *               EventSource for the stream (refetch on the server's `done` event; the last
 *               event feeds the stage line); a one-second clock while the run is live
 *               (`clock` is a test seam, like `eventSourceFactory`); the sentences come from
 *               ui/src/screens/Runs/telemetry.ts; DataTable columns per RunTaskRow; the
 *               drawer loads an evidence pack by hash on demand.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0006-zero-raw-retention-and-evidence-packs.md
 * Works with:   ui/src/api/hooks.ts (the queries), ui/src/api/types.ts (Run, RunTaskRow —
 *               the shapes the API doc states), ui/src/screens/Runs/telemetry.ts (the Now,
 *               stage, heartbeat, queue and factory lines), ui/src/screens/Runs/EvidenceDrawer.tsx
 *               (the pack view), ui/src/components/LiveLog.tsx (the stream; its last event
 *               is the stage line), ui/src/components/Help.tsx (`Term` on the Progress card),
 *               ui/src/screens/Capability/FailureSplit.tsx (the split pills),
 *               ui/src/components/StatTile.tsx (value + n + CI + apparatus, always)
 * Tested by:    ui/src/screens/Runs/RunDetailPage.test.tsx, ui/e2e/walkthrough/05-replay-fake.spec.ts,
 *               ui/e2e/walkthrough/06-cancel.spec.ts
 * Touch when:   a field is added to GET /runs/{id} or /runs/{id}/tasks (docs/API.md) — update
 *               ui/src/api/types.ts first, then the tile or column here; never for a new
 *               repository.
 */
import { useEffect, useMemo, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Link, useParams } from 'react-router'
import { useCancelRun, useHealth, useRun, useRunEvents, useRunTasks } from '../../api/hooks'
import type { EventSourceFactory } from '../../api/sse'
import { isRunTerminal, ladderEntryLabel, type Health, type Run, type RunTaskRow, type StepEvent, type WorkerProbeData } from '../../api/types'
import { BeltPills } from '../../components/BeltPills'
import { Button } from '../../components/Button'
import { Card } from '../../components/Card'
import { DataTable, type Column } from '../../components/DataTable'
import { EmptyState } from '../../components/EmptyState'
import { ErrorState } from '../../components/ErrorState'
import { Term } from '../../components/Help'
import { LiveLog } from '../../components/LiveLog'
import { PageHeader } from '../../components/PageHeader'
import { Pill } from '../../components/Pill'
import { QueryBoundary } from '../../components/QueryBoundary'
import { StatTile } from '../../components/StatTile'
import { useAuth } from '../../lib/auth'
import { fmtDate, fmtInt, fmtPct, fmtSeconds, fmtUsd, shortId, wilson } from '../../lib/format'
import { runStatusDisplay } from '../../lib/verdict'
import { useFailureSplit } from '../Capability/contract'
import { FailureSplitPills } from '../Capability/FailureSplit'
import { EvidenceDrawer } from './EvidenceDrawer'
import { Progress } from './RunsPage'
import { containerLine, factoryLine, heartbeatLine, nowLine, queueLine, stageLine } from './telemetry'

const SIZE_ORDER = ['XS', 'S', 'M', 'L', 'XL']

/** The kinds whose rows come from a builder attempt (the mode and ladder mean something). */
const BUILD_KINDS = new Set(['replay', 'blind', 'factory'])

/** The production clock; a stable reference so the tick effect never re-subscribes. */
const systemClock = () => Date.now()

/** The current time in ms, re-read every second while `live`; `clock` is the test seam. */
function useNow(clock: () => number, live: boolean): number {
  const [now, setNow] = useState(clock)
  useEffect(() => {
    setNow(clock())
    if (!live) return
    const t = setInterval(() => setNow(clock()), 1000)
    return () => clearInterval(t)
  }, [clock, live])
  return now
}

/** The /health worker probe's data (`WorkerProbeData`): how long a RUN's heartbeat may be silent, and the queue depth. `null` = not read. */
function workerProbe(health: Health | undefined): { staleAfterS: number | null; queued: number | null } {
  // the probe boundary is untyped on the wire (`Probe.data`), so each field is still checked
  const data = health?.probes.find((p) => p.name === 'worker')?.data as Partial<WorkerProbeData> | undefined
  const stale = data?.stale_after_s
  const queued = data?.queued
  return {
    staleAfterS: typeof stale === 'number' && Number.isFinite(stale) ? stale : null,
    queued: typeof queued === 'number' && Number.isFinite(queued) ? queued : null,
  }
}

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
          <Pill tone={d.tone} glyph={d.glyph} label={d.describe} data-testid="run-status">
            <span className={run.status === 'running' ? 'crb-pulse' : ''}>{d.label}</span>
          </Pill>
          {run.cancel_requested && !isRunTerminal(run.status) && (
            <Pill tone="amber" glyph="⊘" size="xs" label="Cancel requested; the worker stops between tasks">
              cancel requested
            </Pill>
          )}
          <span className="font-mono text-xs" data-testid="run-identity">
            {run.kind === 'factory' ? factoryLine(run) : run.kind === 'replay' || run.kind === 'blind' ? `${run.mode} · ${run.builder || '—'}${run.model ? ` · ${run.model}` : ''}${run.provider ? ` · ${run.provider}` : ''} · ladder ${run.ladder.map(ladderEntryLabel).join(',') || 'r1'}` : run.kind}
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

/**
 * A mine / setup / label / oracle / controls run's own counters (`counts.detail`), served
 * verbatim; a nested counter object (a label run's `usage.cost_usd`) is flattened one
 * level as "usage · cost usd". Anything that is not a number or a string is not a tile.
 */
function DetailTiles({ detail }: { detail: Record<string, unknown> }) {
  const entries: Array<[string, number | string]> = []
  for (const [k, v] of Object.entries(detail)) {
    if (typeof v === 'number' || typeof v === 'string') entries.push([k, v])
    else if (v && typeof v === 'object' && !Array.isArray(v)) {
      for (const [k2, v2] of Object.entries(v as Record<string, unknown>)) {
        if (typeof v2 === 'number' || typeof v2 === 'string') entries.push([`${k} · ${k2}`, v2])
      }
    }
  }
  if (!entries.length) return null
  const examined = typeof detail.examined === 'number' ? detail.examined : null
  return (
    <div className="flex flex-wrap gap-3" data-testid="tiles-detail">
      {entries.map(([k, v]) => (
        <StatTile
          key={k}
          label={k.replace(/_/g, ' ')}
          value={typeof v === 'number' ? fmtInt(v) : String(v)}
          n={typeof v === 'number' ? (examined ?? v) : null}
          apparatus="this run kind's own counter · n = candidates examined"
        />
      ))}
    </div>
  )
}

function Tiles({ run }: { run: Run }) {
  const c = run.counts
  if (c.detail && Object.keys(c.detail).length && !c.tasks && !c.rows) {
    return <DetailTiles detail={c.detail} />
  }
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
      <StatTile label="Ledger rows" value={fmtInt(c.rows)} n={c.rows} apparatus="one row per attempt (trial r1, r2 …)" data-testid="tile-rows" />
      <StatTile label="Cost" value={fmtUsd(run.cost_usd)} n={graded} apparatus="builder-reported USD, summed" data-testid="tile-cost" />
    </div>
  )
}

/**
 * The run's rows by `failure_kind` (GET /failure-split?repo=&run_id=): the all-rows
 * rate and the model rate on fair attempts side by side, and the split
 * red · budget · protocol · harness · DQ that separates them. Rendered only once the
 * split has loaded (a run with no rows yet shows an honest n = 0, never a zero rate).
 */
function SplitTiles({ repo, runId, poll }: { repo: string; runId: string; poll: boolean }) {
  const split = useFailureSplit(repo, runId)
  if (split.isError) {
    return (
      <p className="text-xs text-status-amber" role="status" data-testid="split-unavailable">
        Failure split unavailable: {split.error.message}
      </p>
    )
  }
  const d = split.data
  if (!d) return null
  const app = 'from the run\'s ledger rows · Wilson 95%'
  return (
    <Card title="Why not clean" eyebrow={`${fmtInt(d.rows)} ledger row${d.rows === 1 ? '' : 's'}${poll ? ' · updating' : ''}`}>
      <div className="flex flex-wrap gap-3">
        <StatTile label="Clean (all rows)" value={d.n ? fmtPct(d.point) : '—'} n={d.n} ci={d.n ? { low: d.ci_low, high: d.ci_high } : null} apparatus={`${fmtInt(d.clean)} clean of ${fmtInt(d.n)} eligible rows · ${app} · the rate that routes`} tone={d.n ? 'green' : undefined} data-testid="tile-split-point" />
        <StatTile label="Model rate (fair attempts)" value={d.model_point == null ? '—' : fmtPct(d.model_point)} n={d.model_n} ci={d.model_point == null || d.model_ci_low == null || d.model_ci_high == null ? null : { low: d.model_ci_low, high: d.model_ci_high }} apparatus={`${fmtInt(d.clean)} clean of ${fmtInt(d.model_n)} finished attempts (clean + red) · ${app} · diagnostic, not a gate`} data-testid="tile-split-model" />
        <StatTile label="Instrument (protocol + harness)" value={fmtInt(d.protocol + d.harness)} n={d.n} apparatus="rows the harness, not the model, failed — count against autonomy until fixed" tone={d.protocol + d.harness ? 'violet' : undefined} data-testid="tile-split-instrument" />
        <StatTile label="Budget-capped" value={fmtInt(d.budget)} n={d.n} apparatus="attempts cut short by their own cap (wall clock, turns, tool calls, tokens, cost)" tone={d.budget ? 'amber' : undefined} data-testid="tile-split-budget" />
        <StatTile label="Cost known" value={d.n ? `${fmtInt(d.cost_known)} / ${fmtInt(d.n)}` : '—'} n={d.n} apparatus="rows whose $ is a measurement (a true $0 counts); the rest carry no price" data-testid="tile-split-cost-known" />
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-3 text-xs">
        <span className="label">Split</span>
        <FailureSplitPills split={d} size="sm" data-testid="run-split" />
        <span className="text-on-surface-muted">n = clean + red + budget + protocol + harness; DQ sits outside n.</span>
      </div>
    </Card>
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
            <Pill tone="green" glyph="✓" size="xs" label="Clean: every recorded belt held">clean</Pill>
          ) : t.disqualified ? (
            <Pill tone="amber" glyph="⊘" size="xs" label="Disqualified — excluded from the denominator">DQ</Pill>
          ) : t.error ? (
            <Pill tone="red" glyph="✗" size="xs" label={`Error: ${t.error}`}>error</Pill>
          ) : (
            <Pill tone="red" glyph="✗" size="xs" label="Not clean">not clean</Pill>
          ),
      },
      { key: 'belts', header: 'Belts (last trial)', cell: (t) => <BeltPills belts={t.belts} beltSet={t.belt_set ?? null} showNames={false} /> },
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

/**
 * The Progress card: the bar, then what a watcher asks — queued: where in the queue;
 * running: started when, spent what, how long left and on what basis, which stage the
 * last event puts the task in, is the worker alive; and the terms the card uses.
 */
function ProgressCard({ run, events, latencies, clock }: { run: Run; events: readonly StepEvent[]; latencies: readonly number[]; clock: () => number }) {
  const terminal = isRunTerminal(run.status)
  const now = useNow(clock, !terminal)
  const health = useHealth()
  const probe = workerProbe(health.data)
  const lastEvent = events[events.length - 1]
  const stage = stageLine(lastEvent, run)
  const hb = heartbeatLine(run, probe.staleAfterS, now)
  const container = containerLine(events)
  const build = BUILD_KINDS.has(run.kind)
  return (
    <Card title="Progress">
      <Progress done={run.progress.done} total={run.progress.total} status={run.status} />
      {run.status === 'queued' && (
        <p className="num mt-2 text-sm" data-testid="run-queue">
          {queueLine(run, probe.queued)}
        </p>
      )}
      <p className="num mt-2 text-sm text-on-surface-body" data-testid="run-now">
        {nowLine(run, latencies, now)}
      </p>
      {stage && (
        <p className="num mt-1 font-mono text-xs text-on-surface" data-testid="run-stage">
          {stage}
        </p>
      )}
      {!stage && run.progress.current_task_id && !terminal && (
        <p className="num mt-1 font-mono text-xs text-on-surface-muted">current task {shortId(run.progress.current_task_id)}</p>
      )}
      {hb &&
        (hb.stale ? (
          <p className="num mt-1 text-xs text-status-amber" role="status" data-testid="run-heartbeat">
            {hb.text}
          </p>
        ) : (
          <p className="num mt-1 text-xs text-on-surface-muted" data-testid="run-heartbeat">
            {hb.text}
          </p>
        ))}
      {container && (
        <p className={`num mt-1 text-xs ${container.failed ? 'text-status-red' : 'text-status-amber'}`} role="status" data-testid="run-container">
          {container.text}
        </p>
      )}
      {run.error && (
        <p className="mt-2 text-sm text-status-red" role="alert">
          {run.error}
        </p>
      )}
      <p className="mt-3 text-xs text-on-surface-muted" data-testid="progress-terms">
        {build && (
          <>
            This run grades in <Term id={run.mode === 'blind' ? 'blind' : 'sighted'} /> mode.{' '}
          </>
        )}
        A row is clean only when every <Term id="belt" /> holds; its <Term id="evidence_pack" /> is the row’s permanent reference.
      </p>
    </Card>
  )
}

export interface RunDetailPageProps {
  /** Test seam: inject an EventSource implementation. */
  eventSourceFactory?: EventSourceFactory
  /** Test seam: the clock the Progress card reads (`Date.now` in production). */
  clock?: () => number
}

export function RunDetailPage({ eventSourceFactory, clock = systemClock }: RunDetailPageProps = {}) {
  const { id = '' } = useParams()
  const run = useRun(id)
  const terminal = isRunTerminal(run.data?.status)
  const events = useRunEvents(id, { factory: eventSourceFactory })
  // The task table's query, shared: the finished tasks' latencies are the estimate's basis.
  const tasks = useRunTasks(id, { poll: !terminal && run.isSuccess })
  const latencies = useMemo(() => (tasks.data?.items ?? []).map((t) => t.latency_s).filter((v) => typeof v === 'number' && Number.isFinite(v) && v > 0), [tasks.data])
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
          <ProgressCard run={run.data} events={events.events} latencies={latencies} clock={clock} />
          <Tiles run={run.data} />
          <SplitTiles repo={run.data.repo} runId={run.data.id} poll={!terminal} />
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
