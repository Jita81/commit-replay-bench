/**
 * The connection journey as data: which stage a repository is at and what comes next.
 *
 * Navigation
 * ----------
 * What it is:   `stagesFor` — the six stages between "a GitHub URL" and "a results page"
 *               (register → probe → mine → oracle → controls → first measurement), each with
 *               a status derived from what the API already knows about the repository, so
 *               the guided walk resumes where the repository actually is and never keeps
 *               its own progress state.
 * What it does: Turns `RepoSummary` (+ the oracle and controls reports when they exist,
 *               + the repo's last run) into a task list the Connect screen renders: `done`
 *               with the evidence line, `running` with the run to watch, `todo` with the
 *               action, `failed` with the detail, `blocked` when an earlier stage is not done.
 *               Also `stageSummary` — the one-word stage for the repositories table.
 * How:          Pure functions over the API types; no fetching. Statuses in order; a
 *               `running`/`queued` last run of a stage's kind marks that stage running.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/screens/Connect/ConnectPage.tsx (renders it), ui/src/api/types.ts
 *               (`RepoSummary`, `OracleReport`, `ControlsReport`), docs/ONBOARDING-A-REPO.md
 *               (the same six steps for a developer at the CLI)
 * Tested by:    ui/src/screens/Connect/connection.test.ts
 * Touch when:   a stage is added to onboarding (add it here and in ONBOARDING-A-REPO.md);
 *               the API exposes a stamp that answers a stage better than the proxy used.
 */

import type { ControlsReport, OracleReport, RepoSummary, RunKind, RunStatus } from '../../api/types'

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

/** The six stages with their statuses, in order; a stage after a not-done stage is `blocked`. */
export function stagesFor(input: StageInputs): Stage[] {
  const { repo } = input
  const out: Stage[] = []
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
          ? 'probing…'
          : probeStatus === 'failed'
            ? firstLine(repo.probe.detail) || 'the probe found the toolchain missing'
            : 'run the probe (a few seconds; no model involved)',
    runKind: 'probe',
    runId: probeRun?.id ?? null,
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
          ? 'mining…'
          : mineStatus === 'failed'
            ? 'the last mine run failed — open it for the reason'
            : 'mine the history (minutes; no model involved)',
    runKind: 'mine',
    runId: mineRun?.id ?? null,
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
          ? 'scoring…'
          : oracleStatus === 'failed'
            ? 'the last oracle run failed — open it for the reason'
            : 'score the oracle (minutes to an hour; no model involved)',
    runKind: 'oracle',
    runId: oracleRun?.id ?? null,
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
        ? 'running the controls…'
        : controlsStatus === 'failed'
          ? 'the last controls run failed — open it for the reason'
          : 'run the controls (minutes to an hour; no model involved)',
    runKind: 'controls',
    runId: controlsRun?.id ?? null,
    spends: false,
  })

  const replayRun = lastRunOf(repo, 'replay')
  // an active run outranks "done": the operator who just pressed "spend" must see it
  const measureStatus: StageStatus =
    replayRun && ACTIVE.includes(replayRun.status)
      ? 'running'
      : (input.measuredRows ?? 0) > 0
        ? 'done'
        : 'todo'
  push({
    id: 'measure',
    title: 'First measurement',
    why: 'A sighted replay of a small slice puts the first rows on the map; every row costs the builder’s model budget.',
    status: measureStatus,
    detail:
      measureStatus === 'done'
        ? `${input.measuredRows} rows on the current apparatus`
        : measureStatus === 'running'
          ? `measuring… (${input.measuredRows ?? 0} rows already on the current apparatus)`
          : 'start a small sighted replay (spends model budget)',
    runKind: 'replay',
    runId: replayRun?.id ?? null,
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
