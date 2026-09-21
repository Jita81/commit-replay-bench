/**
 * Run telemetry lines — what a run is doing now, derived client-side from what the API
 * already serves. Pure: no React, no fetch.
 *
 * Navigation
 * ----------
 * What it is:   `nowLine` (elapsed · done · spend · a remaining estimate with its basis),
 *               `stageLine` (the last StepEvent as task · stage · detail), `heartbeatLine`
 *               (worker liveness against the worker probe's limit), `queueLine` (position and
 *               what is ahead), `factoryLine` (a factory run's identity and delivery switch),
 *               `packHeadline` (one sentence for an evidence pack) and `fmtDurationWords`;
 *               the age formatter is ui/src/lib/format.ts's `fmtAgo`, shared with the
 *               Connection walk so the two never disagree on a started-at stamp.
 * What it does: Turns fields the run page already holds into one honest sentence each. Every
 *               estimate names its basis and its n ("the mean of the 3 done") and calls
 *               itself a planning estimate; a field an older server does not send reads as
 *               absent ("this server does not report the position"), never as a zero; a
 *               heartbeat is only "stale" against a limit the /health worker probe stated.
 * How:          String builders over `Run`, `StepEvent` and `GradeResult`; the caller passes
 *               `nowMs` so elapsed and ages are deterministic in tests. Belt order for the
 *               headline is `beltNamesFor` (belt 5 only when the pack recorded it).
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0001-four-belts-and-false-q1-at-write.md (the belt order and what a
 *               failed belt means), docs/adr/0006-zero-raw-retention-and-evidence-packs.md
 * Works with:   ui/src/screens/Runs/RunDetailPage.tsx (the Progress card and header render
 *               these), ui/src/screens/Runs/EvidenceDrawer.tsx (`packHeadline` above the
 *               pills), ui/src/api/types.ts (`Run`, `StepEvent`, `GradeResult`, `beltNamesFor`),
 *               ui/src/lib/format.ts (`fmtInt`, `fmtUsd`, `fmtSeconds`, `fmtAge`, `fmtAgo`), ui/src/lib/verdict.ts
 *               (`BELT_LABELS` — the belt numbering the headline names)
 * Tested by:    ui/src/screens/Runs/telemetry.test.ts (every line's copy and its absent
 *               cases), ui/src/screens/Runs/RunDetailPage.test.tsx (as rendered),
 *               ui/src/screens/Runs/ReviewPanel.test.tsx (the drawer headline as rendered)
 * Touch when:   a field is added to GET /runs/{id} (docs/API.md) that a watcher should read
 *               as a sentence — extend `Run` in ui/src/api/types.ts first; a belt is added
 *               (extend `BELT_CAUSE`); never for a new repository.
 * Claims:       The remaining-time line is a planning estimate and says so; no line here is
 *               a measurement of the builder (docs/EVIDENCE-AND-CLAIMS.md#7-what-must-never-be-said).
 */
import { beltNamesFor, isRunTerminal, ladderEntryLabel, type BeltName, type GradeResult, type Run, type StepEvent } from '../../api/types'
import { DASH, fmtAge, fmtAgo, fmtInt, fmtSeconds, fmtUsd } from '../../lib/format'

/** Parse an ISO timestamp to ms, or `null` when absent or unreadable. */
function ms(iso: string | null | undefined): number | null {
  if (!iso) return null
  const t = Date.parse(iso)
  return Number.isFinite(t) ? t : null
}

/** A duration in words for a forecast: "under a minute", "about 28 minutes", "about 1 hour 5 minutes"; the dash for a non-finite value. */
export function fmtDurationWords(seconds: number): string {
  if (!Number.isFinite(seconds)) return DASH
  if (seconds < 60) return 'under a minute'
  const m = Math.round(seconds / 60)
  if (m < 60) return `about ${m} minute${m === 1 ? '' : 's'}`
  const h = Math.floor(m / 60)
  const rest = m - h * 60
  return `about ${h} hour${h === 1 ? '' : 's'}${rest ? ` ${rest} minute${rest === 1 ? '' : 's'}` : ''}`
}

/**
 * The "Now" line under the progress bar. `finishedLatencies` are the per-task latencies
 * (seconds) of the tasks that have finished — the basis of the remaining-time estimate,
 * which is mean latency × tasks remaining and is named as a planning estimate. No
 * finished task means no estimate; a terminal run reads as a record, not a forecast.
 */
export function nowLine(run: Run, finishedLatencies: readonly number[], nowMs: number): string {
  const started = ms(run.started)
  if (started === null) return 'Not started yet.'
  const { done, total } = run.progress
  const doneOf = `${fmtInt(done)} of ${fmtInt(total)} tasks done`
  if (isRunTerminal(run.status)) {
    const finished = ms(run.finished) ?? nowMs
    return `Finished after ${fmtSeconds((finished - started) / 1000)} · ${doneOf} · ${fmtUsd(run.cost_usd)} spent.`
  }
  const parts = [`Started ${fmtAge((nowMs - started) / 1000)} ago`, doneOf, `${fmtUsd(run.cost_usd)} so far`]
  const remaining = Math.max(0, total - done)
  const lat = finishedLatencies.filter((v) => Number.isFinite(v) && v >= 0)
  if (remaining > 0) {
    if (lat.length === 0) {
      parts.push('no time estimate yet: no task has finished')
    } else {
      const mean = lat.reduce((a, b) => a + b, 0) / lat.length
      parts.push(
        `${fmtDurationWords(mean * remaining)} left if the ${fmtInt(remaining)} remaining take the mean of the ${fmtInt(lat.length)} done (${fmtSeconds(mean)} each) — a planning estimate, not a measurement`,
      )
    }
  }
  return `${parts.join(' · ')}.`
}

/** The payload's `key` as a string when it is a string or number, else `null`. */
function field(p: Record<string, unknown>, key: string): string | null {
  const v = p[key]
  return typeof v === 'string' || typeof v === 'number' ? String(v) : null
}

/** The detail after the stage for the actions a watcher waits on; anything else reads as its action name. */
function stageDetail(ev: StepEvent, run: Run): string {
  const p = ev.payload
  switch (ev.action) {
    case 'build.turn': {
      const turn = field(p, 'turn')
      const cap = run.budget?.max_turns
      return turn ? `turn ${turn}${cap ? ` of ${fmtInt(cap)}` : ''}` : ev.action
    }
    case 'prep.start':
    case 'build.start':
    case 'build.attempt': {
      const trial = field(p, 'trial') ?? field(p, 'attempt')
      const rung = field(p, 'rung')
      return `attempt${trial ? ` ${trial}` : ''}${rung ? ` (rung ${rung})` : ''}`
    }
    case 'grade.belt': {
      const belt = field(p, 'belt') ?? '?'
      const v = p.value
      return `belt ${belt}${v === true ? ' ✓' : v === false ? ' ✗' : ''}`
    }
    case 'ledger.append':
      return 'row appended'
    default:
      return ev.action
  }
}

/**
 * The current stage as one line from the last streamed event: "Task 4 of 12 · build ·
 * turn 7" (a factory run names the item instead). `null` when there is no event to read
 * or the run is over — the line never guesses.
 */
export function stageLine(ev: StepEvent | undefined, run: Run): string | null {
  if (!ev || isRunTerminal(run.status)) return null
  const { done, total } = run.progress
  const who = run.kind === 'factory' ? `Item ${ev.task_id || DASH}` : total > 0 ? `Task ${fmtInt(Math.min(done + 1, total))} of ${fmtInt(total)}` : 'Task'
  return `${who} · ${ev.stage} · ${stageDetail(ev, run)}`
}

/**
 * Worker liveness for a running run: the last heartbeat's age, and "stale" only when the
 * age is over the limit the /health worker probe stated (`staleAfterS`; `null` = the
 * probe was not read, so no claim). `null` when the server sends no worker fields or the
 * run is not running.
 */
export function heartbeatLine(run: Run, staleAfterS: number | null, nowMs: number): { text: string; stale: boolean } | null {
  if (run.status !== 'running') return null
  if (run.worker_id === undefined && run.heartbeat === undefined) return null
  const worker = run.worker_id || DASH
  const ago = fmtAgo(run.heartbeat, nowMs)
  if (ago === null) return { text: `Worker ${worker} has not checked in yet.`, stale: false }
  const age = (nowMs - (ms(run.heartbeat) ?? nowMs)) / 1000
  if (staleAfterS !== null && age > staleAfterS) {
    return { text: `Worker ${worker} last checked in ${ago} — over the ${fmtSeconds(staleAfterS)} limit. The queue will hand the run to another worker.`, stale: true }
  }
  return { text: `Worker ${worker} last checked in ${ago}.`, stale: false }
}

/**
 * A queued run's place: "Queued — position 3 of 7 · ahead of it: 2 replay, 1 mine."
 * `queuedTotal` is the /health worker probe's queued count (`null` = not read → no
 * "of n"). A server that does not send `queue_position` gets no invented position.
 */
export function queueLine(run: Run, queuedTotal: number | null): string {
  const pos = run.queue_position
  if (pos === undefined || pos === null) return 'Queued — waiting for a worker; this server does not report the position.'
  const of = queuedTotal !== null && queuedTotal >= pos ? ` of ${fmtInt(queuedTotal)}` : ''
  const ahead = run.queue_kinds_ahead ?? []
  if (ahead.length === 0) return `Queued — position ${fmtInt(pos)}${of} · next to run.`
  const counts = new Map<string, number>()
  for (const k of ahead) counts.set(k, (counts.get(k) ?? 0) + 1)
  const list = [...counts.entries()]
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .map(([k, n]) => `${fmtInt(n)} ${k}`)
    .join(', ')
  return `Queued — position ${fmtInt(pos)}${of} · ahead of it: ${list}.`
}

/**
 * A factory run's identity line: kind · mode · builder · model · provider · ladder, then
 * "delivery on/off (override by <name>)" when the server sends `factory`; nothing about
 * delivery when it does not (an older server), never a default.
 */
export function factoryLine(run: Run): string {
  const parts = [run.kind, run.mode, run.builder || DASH]
  if (run.model) parts.push(run.model)
  if (run.provider) parts.push(run.provider)
  parts.push(`ladder ${run.ladder.map(ladderEntryLabel).join(',') || 'r1'}`)
  const f = run.factory
  if (f) {
    const by = f.deliver_override_by_name || f.deliver_override_by
    parts.push(`delivery ${f.deliver ? 'on' : 'off'}${by ? ` (override by ${by})` : ''}`)
  }
  return parts.join(' · ')
}

/** Belt number and plain name for the headline, in belt order. */
const BELT_CAUSE: Record<BeltName, (g: GradeResult) => string> = {
  tests_unmodified: (g) => `belt 1 (the target test files) — changed by the build${g.tamper_files.length ? `: ${g.tamper_files.join(', ')}` : ''}`,
  target_green: (g) => {
    const r = g.target_run
    if (r?.timed_out) return 'belt 2 (the target test) — timed out'
    const rc = r ? ` (rc ${r.returncode})` : ''
    const failing = r?.failing.length ? `: ${r.failing.slice(0, 5).join(', ')}${r.failing.length > 5 ? ' …' : ''}` : ''
    return `belt 2 (the target test) — still red${rc}${failing}`
  },
  no_new_failures: (g) => {
    const n = g.new_failures.length
    if (n === 0) return 'belt 3 (the repository’s own suite) — new failures'
    return `belt 3 (the repository’s own suite) — ${fmtInt(n)} new failure${n === 1 ? '' : 's'}: ${g.new_failures.slice(0, 5).join(', ')}${n > 5 ? ' …' : ''}`
  },
  source_changed: () => 'belt 4 (source changed) — the build changed no source file, so the green proves nothing',
  repo_lint_clean: (g) => {
    const l = g.lint_run
    const tool = l?.detected || 'the linter'
    const files = new Set<string>()
    for (const s of l?.steps ?? []) if (s.verdict === false || s.rc !== 0) for (const f of s.files) files.add(f)
    const n = files.size || g.changed_files.length
    return `belt 5 (the repository’s linter) — ${tool} rejected ${fmtInt(n)} changed file${n === 1 ? '' : 's'}`
  },
}

/**
 * One sentence for an evidence pack, read before the pills: for a disqualified row its
 * reason; for a not-clean row the first failed belt by name and its cause (or the harness
 * error); for a clean row the belt count and what `verified` does and does not mean.
 */
export function packHeadline(g: GradeResult, verified: boolean): string {
  if (g.disqualified) return `Disqualified: ${g.dq_reason || 'reason not recorded'}. The row is excluded from every rate, never counted as a failure.`
  const names = beltNamesFor(undefined, g)
  const count = names.length === 5 ? 'five' : 'four'
  if (g.clean) {
    return verified
      ? `Clean: all ${count} belts held and the pack’s hash verifies. This says nothing about whether the change is mergeable.`
      : `Clean: all ${count} belts held, but the pack’s hash does not verify — treat this evidence as untrusted.`
  }
  const failed = names.find((n) => g[n] === false)
  if (failed) return `Not clean: ${BELT_CAUSE[failed](g)}.`
  if (g.error) return `Not clean: the harness errored — ${g.error}. This counts against the instrument, not the builder.`
  return `Not clean: no belt is recorded as failed${g.note ? ` — ${g.note}` : ''}.`
}
