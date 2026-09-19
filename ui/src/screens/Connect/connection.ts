/**
 * The connection journey as data: which stage a repository is at and what comes next.
 *
 * Navigation
 * ----------
 * What it is:   `stagesFor` — the six stages between "a GitHub URL" and "the baseline"
 *               (register → probe → mine → oracle → controls → first measurement), each with
 *               a status derived from what the API already knows about the repository, so
 *               the guided walk resumes where the repository actually is and never keeps
 *               its own progress state.
 * What it does: Turns `RepoSummary` (+ the oracle and controls reports when they exist,
 *               + the repo's last run, + the polled `Run` while one is in flight) into a task
 *               list the Connect screen renders: `done` with the evidence line, `running`
 *               with the run to watch and its live line (`runningDetail`: k of n, the kind's
 *               own counters, spend so far, or "Queued — n runs ahead of it"), `todo` with
 *               the action, `failed` with the detail (the measure stage too: a failed or
 *               cancelled spend never reads as "not started"), `blocked` when an earlier
 *               stage is not done. Also `stageSummary` — the one-word stage for the
 *               repositories table.
 * How:          Pure functions over the API types; no fetching. Statuses in order; a
 *               `running`/`queued` last run of a stage's kind marks that stage running, and
 *               `queued` is carried on the stage so the screen can label it as such.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/screens/Connect/ConnectPage.tsx (renders it and passes the polled
 *               run), ui/src/screens/Home/HomePage.tsx (task 4 and 5 statuses),
 *               ui/src/api/types.ts (`RepoSummary`, `OracleReport`, `ControlsReport`, `Run`),
 *               docs/ONBOARDING-A-REPO.md (the same six steps for a developer at the CLI)
 * Tested by:    ui/src/screens/Connect/connection.test.ts
 * Touch when:   a stage is added to onboarding (add it here and in ONBOARDING-A-REPO.md);
 *               the API exposes a stamp that answers a stage better than the proxy used.
 */

import type { ControlsReport, OracleReport, RepoSummary, Run, RunKind, RunStatus } from '../../api/types'

export type StageId = 'register' | 'probe' | 'mine' | 'oracle' | 'controls' | 'measure'
export type StageStatus = 'done' | 'running' | 'todo' | 'failed' | 'blocked'

export interface Stage {
  id: StageId
  title: string
  /** What this stage proves — the sentence a governance reader needs. */
  why: string
  status: StageStatus
  /** One line of evidence (done), progress (running), instruction (todo) or the failure. */
  detail: string
  /** The run kind the action queues (probe has its own route; register has none). */
  runKind: RunKind | null
  /** The run to watch while `running`. */
  runId: string | null
  /** True while `running` and the run has not been claimed by a worker yet. */
  queued: boolean
  /** True when the action spends the operator's model budget (the first measurement). */
  spends: boolean
}

export interface StageInputs {
  repo: RepoSummary
  /** `undefined` = not loaded yet; `null` = the API said 404 (never run). */
  oracle?: OracleReport | null
  controls?: ControlsReport | null
  /** Rows measured on the current apparatus (the map's `n_total`); `undefined` = unknown. */
  measuredRows?: number
  /** The polled run behind the running stage (the screen's `useRun`); `undefined` = not loaded. */
  watched?: Run
  /** Queued runs created before the watched one (FIFO); `undefined` = not known. */
  queuedAhead?: number
  /** The clock for "started 40 s ago"; defaults to `Date.now()`. */
  now?: number
}

const ACTIVE: readonly RunStatus[] = ['queued', 'running']

/** The probe's detail can be a whole test-runner transcript; the stage line keeps its head. */
function firstLine(text: string, max = 160): string {
  const line = text.split('\n').find((l) => l.trim()) ?? ''
  return line.length > max ? `${line.slice(0, max)}…` : line
}

function lastRunOf(repo: RepoSummary, kind: RunKind): { id: string; status: RunStatus } | null {
  const lr = repo.last_run
  return lr && lr.kind === kind ? { id: lr.id, status: lr.status } : null
}

/** "40 s ago" / "3 min ago" / "2 h ago" — the elapsed since an ISO stamp, for the live line. */
export function elapsed(iso: string, now: number): string {
  const s = Math.max(0, Math.round((now - Date.parse(iso)) / 1000))
  if (s < 60) return `${s} s ago`
  if (s < 3600) return `${Math.round(s / 60)} min ago`
  return `${Math.round(s / 360) / 10} h ago`
}

/**
 * The live line for a running stage, from the polled run: queued → its place in the queue;
 * running → the kind's own progress (probe: elapsed; mine: found / examined / target from
 * `counts.detail` and `limit`; oracle and controls: task k of n; measure: attempt k of n and
 * the builder-reported spend). Falls back to the stage's static ellipsis line until the run
 * has loaded, so the person never sees a blank.
 */
export function runningDetail(id: StageId, run: Run | undefined, opts: { queuedAhead?: number; now?: number } = {}): string {
  const fallback: Record<StageId, string> = {
    register: '',
    probe: 'probing…',
    mine: 'mining…',
    oracle: 'scoring…',
    controls: 'running the controls…',
    measure: 'measuring…',
  }
  if (!run) return fallback[id]
  if (run.status === 'queued') {
    const ahead = opts.queuedAhead
    if (ahead === undefined) return 'Queued — waiting for a worker'
    return ahead === 0 ? 'Queued — next in line for a worker' : `Queued — ${ahead} ${ahead === 1 ? 'run' : 'runs'} ahead of it`
  }
  const now = opts.now ?? Date.now()
  const since = run.started ? ` (started ${elapsed(run.started, now)})` : ''
  const { done, total } = run.progress
  const kOfN = total > 0 ? `${Math.min(done + 1, total)} of ${total}` : null
  switch (id) {
    case 'probe':
      return `Probing — running the repository's own suite${since}`
    case 'mine': {
      const d = run.counts.detail ?? {}
      const found = typeof d.found === 'number' ? d.found : null
      const examined = typeof d.examined === 'number' ? d.examined : null
      if (found === null && examined === null) return `Mining — reading the history${since}`
      const parts = [`${found ?? 0} ${found === 1 ? 'task' : 'tasks'} found`, `${examined ?? 0} commits examined`]
      if (run.limit) parts.push(`target ${run.limit}`)
      return `Mining — ${parts.join(' · ')}`
    }
    case 'oracle':
      return kOfN ? `Scoring oracles — task ${kOfN}` : `Scoring oracles${since}`
    case 'controls':
      return kOfN ? `Running the controls — task ${kOfN}` : `Running the controls${since}`
    case 'measure':
      return `Measuring — ${kOfN ? `attempt ${kOfN}` : 'first attempt starting'} · $${run.cost_usd.toFixed(2)} so far, builder-reported`
    default:
      return fallback[id]
  }
}

/** The six stages with their statuses, in order; a stage after a not-done stage is `blocked`. */
export function stagesFor(input: StageInputs): Stage[] {
  const { repo } = input
  const out: Stage[] = []
  const live = (id: StageId, run: { id: string; status: RunStatus } | null) =>
    runningDetail(id, input.watched && run && input.watched.id === run.id ? input.watched : undefined, { queuedAhead: input.queuedAhead, now: input.now })
  const queued = (run: { status: RunStatus } | null) => run?.status === 'queued'
  let gate = true // every earlier stage done

  const push = (s: Omit<Stage, 'status'> & { status: StageStatus }) => {
    const status: StageStatus = gate ? s.status : s.status === 'done' ? 'done' : 'blocked'
    out.push({ ...s, status })
    if (status !== 'done') gate = false
  }

  push({
    id: 'register',
    title: 'Repository registered',
    why: 'The product knows where the code is and how it tests; nothing is written to the repository.',
    status: 'done',
    detail: `${repo.url || repo.clone_path} · ${repo.language}${repo.runner ? ` / ${repo.runner}` : ''}`,
    runKind: null,
    runId: null,
    queued: false,
    spends: false,
  })

  const probeRun = lastRunOf(repo, 'probe')
  const probeStatus: StageStatus =
    repo.probe.status === 'ok' || repo.probe.status === 'degraded'
      ? 'done'
      : probeRun && ACTIVE.includes(probeRun.status)
        ? 'running'
        : repo.probe.status === 'down'
          ? 'failed'
          : 'todo'
  push({
    id: 'probe',
    title: 'Toolchain probed',
    why: 'The test runner and toolchain the repository needs are present, so a red test means the code, not the environment.',
    status: probeStatus,
    detail:
      probeStatus === 'done'
        ? `${repo.probe.status}${repo.probe.detail ? ` — ${firstLine(repo.probe.detail)}` : ''}`
        : probeStatus === 'running'
          ? live('probe', probeRun)
          : probeStatus === 'failed'
            ? firstLine(repo.probe.detail) || 'the probe found the toolchain missing'
            : 'run the probe (a few seconds; no model involved)',
    runKind: 'probe',
    runId: probeRun?.id ?? null,
    queued: probeStatus === 'running' && queued(probeRun),
    spends: false,
  })

  const tc = repo.task_counts
  const mineRun = lastRunOf(repo, 'mine')
  const mineStatus: StageStatus =
    mineRun && ACTIVE.includes(mineRun.status) ? 'running' : tc.total > 0 ? 'done' : mineRun?.status === 'failed' ? 'failed' : 'todo'
  push({
    id: 'mine',
    title: 'Commits mined into tasks',
    why: 'Real commits that couple a source change to a test change become the tasks; each is checked RED at the parent and GREEN with its own change.',
    status: mineStatus,
    detail:
      mineStatus === 'done'
        ? `${tc.total} tasks (${tc.gold_clean} gold-clean, ${tc.gold_failed} gold-failed, ${tc.unchecked} unchecked)`
        : mineStatus === 'running'
          ? live('mine', mineRun)
          : mineStatus === 'failed'
            ? 'the last mine run failed — open it for the reason'
            : 'mine the history (minutes; no model involved)',
    runKind: 'mine',
    runId: mineRun?.id ?? null,
    queued: mineStatus === 'running' && queued(mineRun),
    spends: false,
  })

  const oracleRun = lastRunOf(repo, 'oracle')
  const oracleStatus: StageStatus =
    input.oracle && input.oracle.tasks.length > 0
      ? 'done'
      : oracleRun && ACTIVE.includes(oracleRun.status)
        ? 'running'
        : oracleRun?.status === 'failed'
          ? 'failed'
          : 'todo'
  push({
    id: 'oracle',
    title: 'Oracle strength scored',
    why: 'Mutants planted on the changed lines tell you whether the tests would notice a wrong patch — a weak oracle routes to a human whatever the pass rate.',
    status: oracleStatus,
    detail:
      oracleStatus === 'done' && input.oracle
        ? `${input.oracle.tasks.length} tasks scored`
        : oracleStatus === 'running'
          ? live('oracle', oracleRun)
          : oracleStatus === 'failed'
            ? 'the last oracle run failed — open it for the reason'
            : 'score the oracle (minutes to an hour; no model involved)',
    runKind: 'oracle',
    runId: oracleRun?.id ?? null,
    queued: oracleStatus === 'running' && queued(oracleRun),
    spends: false,
  })

  const controlsRun = lastRunOf(repo, 'controls')
  const controlsStatus: StageStatus = input.controls
    ? input.controls.passed
      ? 'done'
      : 'failed'
    : controlsRun && ACTIVE.includes(controlsRun.status)
      ? 'running'
      : controlsRun?.status === 'failed'
        ? 'failed'
        : 'todo'
  push({
    id: 'controls',
    title: 'Negative controls passed',
    why: 'Seven deliberate cheats (no-op, stub, tamper, regression, hard-code, env poison, …) must all be caught before any pass rate means anything.',
    status: controlsStatus,
    detail: input.controls
      ? `${input.controls.passed ? 'passed' : 'FAILED'} · ${input.controls.n_rows} rows · ${input.controls.violations} violations · ${input.controls.escapes} escapes · ${input.controls.not_constructible} not constructible`
      : controlsStatus === 'running'
        ? live('controls', controlsRun)
        : controlsStatus === 'failed'
          ? 'the last controls run failed — open it for the reason'
          : 'run the controls (minutes to an hour; no model involved)',
    runKind: 'controls',
    runId: controlsRun?.id ?? null,
    queued: controlsStatus === 'running' && queued(controlsRun),
    spends: false,
  })

  const replayRun = lastRunOf(repo, 'replay')
  const rows = input.measuredRows ?? 0
  // an active run outranks "done": the operator who just pressed "spend" must see it; and a
  // failed or cancelled spend with no rows must never read as "not started" (J-ONR-6)
  const measureStatus: StageStatus =
    replayRun && ACTIVE.includes(replayRun.status)
      ? 'running'
      : rows > 0
        ? 'done'
        : replayRun?.status === 'failed'
          ? 'failed'
          : 'todo'
  const cancelled = measureStatus === 'todo' && replayRun?.status === 'cancelled'
  push({
    id: 'measure',
    title: 'First measurement',
    why: 'A sighted replay of a small slice puts the first rows on the map; every row costs the builder’s model budget.',
    status: measureStatus,
    detail:
      measureStatus === 'done'
        ? `${input.measuredRows} rows on the current apparatus`
        : measureStatus === 'running'
          ? `${live('measure', replayRun)} (${rows} rows already on the current apparatus)`
          : measureStatus === 'failed'
            ? 'the last measurement failed — open it for the reason before spending again'
            : cancelled
              ? `the last measurement was cancelled after ${rows} rows; start another when you are ready`
              : 'start a small sighted replay (spends model budget)',
    runKind: 'replay',
    runId: replayRun?.id ?? null,
    queued: measureStatus === 'running' && queued(replayRun),
    spends: true,
  })

  return out
}

/** The one-word stage for the repositories table: the first stage that is not done. */
export function stageSummary(stages: Stage[]): { label: string; status: StageStatus } {
  const next = stages.find((s) => s.status !== 'done')
  if (!next) return { label: 'measured', status: 'done' }
  return { label: next.title.toLowerCase(), status: next.status }
}

/** The GitHub URL → the repository name the product uses (`owner-repo`, lowercase). */
export function nameFromGitUrl(url: string): string {
  const m = url
    .trim()
    .replace(/\.git$/, '')
    .match(/(?:github\.com[/:]|gitlab\.com[/:]|dev\.azure\.com\/)([^/]+)\/(?:_git\/)?([^/]+)$/)
  if (!m) return ''
  return `${m[1]}-${m[2]}`.toLowerCase().replace(/[^a-z0-9._-]/g, '-').slice(0, 64)
}
