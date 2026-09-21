/**
 * Presentation helpers — ONE source of truth for how a route, a run status,
 * a belt, and an oracle band are labelled, toned and glyphed. Pure: no React.
 *
 * STANDARD law 2: colour is never the only signal. Every tone carries a glyph
 * and a label so the state survives monochrome, colour-blindness and screen
 * readers.
 *
 * Navigation
 * ----------
 * What it is:   The label / tone / glyph tables (`routeDisplay`, `runStatusDisplay`,
 *               `stepStatusDisplay`, `probeDisplay`, `bandDisplay`, `gateDisplay`,
 *               `tierDisplay`, `beltDisplay`), the Tailwind classes per tone, and
 *               `ACTION_HELP` / `actionHelp` — one plain sentence per event action.
 * What it does: Gives every state a glyph and a screen-reader sentence as well as a colour, so
 *               a verdict survives monochrome, colour-blindness and assistive technology; an
 *               unknown value from a newer server renders as a muted `?` with the raw string,
 *               never as a fabricated known state. A belt that is `null` is "not recorded"
 *               (or "not evaluated" for belt 5), never a fail. Every sentence says what the
 *               policy licenses — deliver and a strong oracle license a branch and pull request
 *               under review, never a merge (docs/EVIDENCE-AND-CLAIMS.md §7) — and the human
 *               route names all three causes the rule has. `actionHelp` explains a live-log
 *               line to a reader who has not read the loop's source, falling back to a generic
 *               sentence for an action this version does not know.
 * How:          One `Record<Value, Display>` per vocabulary with a lookup function that falls
 *               back to the muted default; `ACTION_HELP` is keyed by the full action string,
 *               grouped by stage in source order.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0003-one-routing-rule.md, docs/adr/0011-repo-lint-belt.md
 * Works with:   ui/src/components/Pill.tsx (renders a `Display`), ui/src/components/VerdictPill.tsx
 *               (route / status pills), ui/src/components/BeltPills.tsx (`beltDisplay`,
 *               `BELT_LABELS`), ui/src/components/LiveLog.tsx (`actionHelp` on each row),
 *               ui/src/api/types.ts (the vocabularies these tables cover),
 *               ui/src/index.css (the tone tokens the classes name)
 * Tested by:    ui/src/lib/verdict.test.ts (the copy and every action), ui/src/components/VerdictPill.test.tsx,
 *               ui/src/components/BeltPills.test.tsx
 * Touch when:   a route, run status, belt, band or tier is added on the server (an apparatus or
 *               policy change with its ADR) — add the row here and the type in
 *               ui/src/api/types.ts; an event action is added in src/crb (add its sentence to
 *               `ACTION_HELP`); never for a new repository.
 */

import type { CellVerdict, OracleBand, OracleGate, ProbeStatus, RunStatus, StepStatus, VerificationTier } from '../api/types'
import { NOT_YET_MEASURED } from '../api/types'

/** The seven colour families the tokens define; `muted` is the "no claim" tone (unmeasured, not recorded). */
export type Tone = 'green' | 'amber' | 'red' | 'primary' | 'blue' | 'violet' | 'muted'

/** One state, fully described: label for sighted readers, tone for colour, glyph for monochrome, sentence for screen readers. */
export interface Display {
  label: string
  tone: Tone
  glyph: string
  /** Screen-reader sentence, e.g. "Route: deliver — auto-deliver as a branch + PR". */
  describe: string
}

/** Tailwind classes per tone: soft fill + strong ink, AA on both themes. */
export const TONE_CLASSES: Record<Tone, string> = {
  green: 'bg-status-green-soft text-status-green border-status-green/40',
  amber: 'bg-status-amber-soft text-status-amber border-status-amber/40',
  red: 'bg-status-red-soft text-status-red border-status-red/40',
  primary: 'bg-primary-container text-primary border-primary/40',
  blue: 'bg-status-blue-soft text-status-blue border-status-blue/40',
  violet: 'bg-status-violet-soft text-status-violet border-status-violet/40',
  muted: 'bg-transparent text-on-surface-muted border-border border-dashed',
}

/** Text-only colour per tone (for inline numbers and glyphs). */
export const TONE_TEXT: Record<Tone, string> = {
  green: 'text-status-green',
  amber: 'text-status-amber',
  red: 'text-status-red',
  primary: 'text-primary',
  blue: 'text-status-blue',
  violet: 'text-status-violet',
  muted: 'text-on-surface-muted',
}

/** The five routes of ADR-0003 plus `NOT_YET_MEASURED`, which is the ABSENCE of a cell — muted, never zero. */
const ROUTE_DISPLAY: Record<CellVerdict, Display> = {
  deliver: { label: 'Deliver', tone: 'green', glyph: '✓', describe: 'Route: deliver — the factory may open a branch and pull request under review; never a claim the change is safe to merge' },
  calibrate: { label: 'Calibrate', tone: 'primary', glyph: '◐', describe: 'Route: calibrate — not enough evidence yet, or under the bar; more attempts or the controls run can change it' },
  granularize: { label: 'Granularize', tone: 'blue', glyph: '⋮', describe: 'Route: granularize — split before attempting' },
  human: { label: 'Human', tone: 'amber', glyph: '☺', describe: 'Route: human — a green cannot license delivery here: the tests are too weak, the controls gate failed, or a cheat graded clean' },
  do_not_ship: { label: 'Do not ship', tone: 'red', glyph: '✗', describe: 'Route: do not ship — false-Q1 in cell, evidence untrusted' },
  [NOT_YET_MEASURED]: { label: 'Not yet measured', tone: 'muted', glyph: '·', describe: 'Not yet measured — no evidence for this cell' },
}

/** A route (or absence) → its display; an unknown string is shown raw in muted `?`, never mapped to a known route. */
export function routeDisplay(route: CellVerdict | string | null | undefined): Display {
  if (!route) return ROUTE_DISPLAY[NOT_YET_MEASURED]
  return ROUTE_DISPLAY[route as CellVerdict] ?? { label: route, tone: 'muted', glyph: '?', describe: `Route: ${route}` }
}

const RUN_STATUS_DISPLAY: Record<RunStatus, Display> = {
  queued: { label: 'Queued', tone: 'muted', glyph: '…', describe: 'Status: queued' },
  running: { label: 'Running', tone: 'primary', glyph: '●', describe: 'Status: running' },
  succeeded: { label: 'Succeeded', tone: 'green', glyph: '✓', describe: 'Status: succeeded' },
  failed: { label: 'Failed', tone: 'red', glyph: '✗', describe: 'Status: failed' },
  cancelled: { label: 'Cancelled', tone: 'amber', glyph: '⊘', describe: 'Status: cancelled' },
}

/** A run status → its display. */
export function runStatusDisplay(status: RunStatus | string): Display {
  return RUN_STATUS_DISPLAY[status as RunStatus] ?? { label: status, tone: 'muted', glyph: '?', describe: `Status: ${status}` }
}

const STEP_STATUS_DISPLAY: Record<StepStatus, Display> = {
  ok: { label: 'ok', tone: 'green', glyph: '✓', describe: 'ok' },
  error: { label: 'error', tone: 'red', glyph: '✗', describe: 'error' },
  invalid: { label: 'invalid', tone: 'amber', glyph: '⚠', describe: 'invalid' },
  skipped: { label: 'skipped', tone: 'muted', glyph: '–', describe: 'skipped' },
  in_progress: { label: 'in progress', tone: 'primary', glyph: '●', describe: 'in progress' },
}

/** A StepEvent status → its display (the live log's per-line tone). */
export function stepStatusDisplay(status: StepStatus | string): Display {
  return STEP_STATUS_DISPLAY[status as StepStatus] ?? { label: status, tone: 'muted', glyph: '?', describe: status }
}

const PROBE_DISPLAY: Record<ProbeStatus | 'not_probed', Display> = {
  ok: { label: 'OK', tone: 'green', glyph: '✓', describe: 'Probe: ok' },
  degraded: { label: 'Degraded', tone: 'amber', glyph: '⚠', describe: 'Probe: degraded' },
  down: { label: 'Down', tone: 'red', glyph: '✗', describe: 'Probe: down' },
  skipped: { label: 'Skipped', tone: 'muted', glyph: '–', describe: 'Probe: skipped for this process role (never lowers the aggregate)' },
  not_probed: { label: 'Not probed', tone: 'muted', glyph: '·', describe: 'Probe: not yet run' },
}

/** A health / repo probe status → its display; `skipped` never lowers the aggregate. */
export function probeDisplay(status: ProbeStatus | 'not_probed' | string): Display {
  return PROBE_DISPLAY[status as ProbeStatus] ?? { label: status, tone: 'muted', glyph: '?', describe: `Probe: ${status}` }
}

const BAND_DISPLAY: Record<OracleBand, Display> = {
  strong: { label: 'Strong', tone: 'green', glyph: '✓', describe: 'Oracle strength: strong — the tests notice a wrong patch; clears the deliver bar' },
  adequate: { label: 'Adequate', tone: 'primary', glyph: '◐', describe: 'Oracle strength: adequate — clears the bar; every change still goes to review' },
  weak: { label: 'Weak', tone: 'amber', glyph: '⚠', describe: 'Oracle strength: weak — a green is low confidence; the cell routes to a human' },
  unscoreable: { label: 'Unscoreable', tone: 'muted', glyph: '·', describe: 'Oracle strength: unscoreable — no mutants' },
}

/** An oracle-strength band → its display. */
export function bandDisplay(band: OracleBand | string): Display {
  return BAND_DISPLAY[band as OracleBand] ?? { label: band, tone: 'muted', glyph: '?', describe: `Oracle band: ${band}` }
}

/** The API's enum values stay (`auto_ship`); the words say what the policy licenses — a branch and PR under review, never a merge. */
const GATE_DISPLAY: Record<OracleGate, Display> = {
  auto_ship: { label: 'Clears the bar', tone: 'green', glyph: '✓', describe: 'Gate: clears the oracle bar for deliver — a branch and pull request under review, never a merge' },
  human_review: { label: 'Review-gated', tone: 'amber', glyph: '☺', describe: 'Gate: review-gated — a green needs a person’s review before anything is opened' },
  needs_human: { label: 'Needs a human', tone: 'red', glyph: '✗', describe: 'Gate: needs a human — the tests are too weak for a green to mean anything' },
}

/** An oracle gate (what a clean grade licenses) → its display. */
export function gateDisplay(gate: OracleGate | string): Display {
  return GATE_DISPLAY[gate as OracleGate] ?? { label: gate, tone: 'muted', glyph: '?', describe: `Gate: ${gate}` }
}

const TIER_DISPLAY: Record<Exclude<VerificationTier, ''>, Display> = {
  'human-verified': { label: 'Human-verified', tone: 'green', glyph: '✓', describe: 'Verification tier: human-verified' },
  'ab-confirmed': { label: 'A/B-confirmed', tone: 'green', glyph: '✓', describe: 'Verification tier: A/B-confirmed' },
  'automated-pass': { label: 'Automated pass', tone: 'amber', glyph: '◐', describe: 'Verification tier: automated pass — asserted, not yet earned' },
  untrusted: { label: 'Untrusted', tone: 'red', glyph: '✗', describe: 'Verification tier: untrusted' },
}

/** A verification tier → its display, or `null` for the empty tier (no pill is rendered). */
export function tierDisplay(tier: VerificationTier | string): Display | null {
  if (!tier) return null
  return TIER_DISPLAY[tier as Exclude<VerificationTier, ''>] ?? { label: tier, tone: 'muted', glyph: '?', describe: `Tier: ${tier}` }
}

/** Belt names → short labels for pills. */
export const BELT_LABELS: Record<string, { short: string; long: string }> = {
  tests_unmodified: { short: 'B1 tests', long: 'Belt 1 — tests unmodified' },
  target_green: { short: 'B2 target', long: 'Belt 2 — target green' },
  no_new_failures: { short: 'B3 no new', long: 'Belt 3 — no new failures' },
  source_changed: { short: 'B4 source', long: 'Belt 4 — source changed' },
  repo_lint_clean: { short: 'B5 lint', long: "Belt 5 — repo's own lint clean" },
}

/** A belt value → its display: `true` held, `false` failed, `null` not recorded (belt 5: not evaluated — no linter configured). A missing belt is NEVER rendered as failed. */
export function beltDisplay(value: boolean | null | undefined, name?: string): Display {
  if (value === true) return { label: 'pass', tone: 'green', glyph: '✓', describe: 'held' }
  if (value === false) return { label: 'fail', tone: 'red', glyph: '✗', describe: 'failed' }
  if (name === 'repo_lint_clean') return { label: 'n/a', tone: 'muted', glyph: '—', describe: 'not evaluated — no linter configured for this repository' }
  return { label: 'n/a', tone: 'muted', glyph: '—', describe: 'not recorded' }
}

/**
 * One plain sentence per event action the worker and the factory loop emit (the live log's
 * vocabulary), grouped by stage. The live log renders it as the row's explanation so a reader
 * does not need the loop's source to follow a run. The keys are exactly the actions in
 * docs/API.md#event-vocabulary, which tests/test_event_vocabulary.py keeps equal to what the
 * code emits — ui/src/lib/verdict.test.ts reads that table, so a sentence for an action
 * nothing emits, or an emitted action with no sentence, fails the suite. A builder's own
 * `build.*` events reach a replay trace prefixed `builder.build.*` and a factory trace
 * unprefixed: `actionHelp` strips the prefix, so the sentence is written once.
 */
export const ACTION_HELP: Record<string, string> = {
  // system — the run itself, the clone and the probe
  'run.claimed': 'A worker took the run from the queue and will execute it.',
  'run.executor': 'The run states which test executor it uses (docker or local); only docker counts as evidence.',
  'run.error': 'The run stopped on an error; nothing already graded is lost.',
  'run.finish_refused': 'The run could not be marked finished because its state had changed underneath it.',
  'run.finished': 'The run reached its final status with its counts and duration.',
  'run.outage_stop': 'The run stopped because the sandbox or a service became unavailable; it can be started again later.',
  'run.skip': 'The run was skipped; the payload names why.',
  'run.start': 'The run started.',
  'run.done': 'The run completed its work.',
  'run.cancel_requested': 'Someone asked for the run to stop; it ends after the attempt in flight.',
  'run.reclaimed': 'A worker took over a run whose previous worker stopped answering.',
  'run.abandoned': 'The run was given up after its worker stopped answering too many times.',
  'repo.clone.start': 'The repository is being cloned; credentials are never written to the log.',
  'repo.clone.done': 'The clone finished at the recorded head commit.',
  'probe.start': 'The known-green test scope is being run to prove the toolchain works here.',
  'probe.done': 'The probe finished; green means the toolchain can run this repository’s tests.',
  // prep — the environment before any attempt
  'setup.auto': 'The runner prepared the environment on its own (install or build) because it was not ready.',
  'setup.start': 'Environment setup started; this is the only phase that may use the network.',
  'setup.step': 'One setup step (an install, a build or a download) ran.',
  'setup.done': 'Environment setup finished.',
  'prep.start': 'The worktree for this attempt is being prepared at the task’s parent commit.',
  // mine — turning commits into replayable tasks
  'mine.candidate': 'A commit is being examined as a possible task.',
  'mine.red': 'The commit’s test fails on the parent commit, so the task has a real failing test.',
  'mine.skip': 'The commit was not usable as a task; the payload names why.',
  'mine.gold': 'The commit’s own change passes its test in the sandbox, so the task is gold-clean.',
  'mine.done': 'Mining finished with the number of tasks found.',
  'mine.task': 'A task was recorded with its size, class and gold status.',
  'mine.cancelled': 'Mining stopped because the run was cancelled.',
  'label.task': 'A model labelled the task’s intent class; the label’s cost is recorded and never summed into a rate.',
  // build — the builder’s attempt
  'build.start': 'The builder started an attempt with the named model and budget.',
  'build.done': 'The attempt finished with its turns, tokens and builder-reported cost.',
  'build.attempt': 'One rung of the budget ladder started.',
  'build.applied': 'The builder’s patch was applied to the worktree.',
  'build.turn': 'One builder turn (a model call and its tool calls).',
  'build.tool': 'The builder called a tool.',
  'build.event': 'A builder event that has no closer name.',
  // the sealed container the builder works in (ADR-0012) and the belt-5 pre-flight — always
  // emitted under the builder prefix (builders/adapter.py)
  'builder.sealed': 'The builder’s worktree was sealed in a container with no network before any turn.',
  'builder.copy_back': 'The builder’s changes were copied back from the sealed container; the payload is the summary.',
  'builder.discard': 'The builder’s container and scratch files were discarded after the attempt.',
  'builder.discard.error': 'Discarding the builder’s container failed; the attempt’s grade is unaffected.',
  'builder.preflight.fixed': 'A formatting or lint problem in the patch was fixed before grading.',
  'builder.preflight.repaired': 'The patch was repaired by a bounded repair turn before grading.',
  'builder.preflight.rejected': 'The patch was rejected before grading; the payload names why.',
  'builder.preflight.error': 'The preflight step itself failed.',
  // grade — the belts
  'grade.belt': 'One belt was evaluated; the value says whether it held.',
  'grade.tamper': 'A test file was changed; the row is disqualified, not counted.',
  'grade.malformed_oracle': 'The task’s test could not be run as an oracle; the attempt is skipped, not failed.',
  'grade.error': 'Grading itself failed; the attempt is an instrument error, not a builder failure.',
  // ledger — the append
  'ledger.append': 'The graded row was appended to the hash-chained ledger.',
  'ledger.pack_missing': 'The row has no evidence pack, so it cannot be counted clean.',
  'ledger.pack_store_error': 'The evidence pack could not be stored; the row is not counted clean.',
  // oracle — mutation scoring and the negative controls
  'oracle.mutation.mutant': 'A fault was planted on the changed lines.',
  'oracle.mutation.scored': 'The planted fault was scored: killed if the tests noticed it.',
  'oracle.mutation.uncompilable': 'The planted fault did not compile, so it is excluded, never counted as killed.',
  'oracle.mutation.unscoreable': 'No fault could be planted on this task, so it carries no strength.',
  'oracle.mutation.error': 'Mutation scoring failed for this task.',
  'oracle.score': 'The task’s oracle strength was recorded: mutants killed over mutants planted.',
  'controls.control': 'One negative control (a deliberate cheat) was constructed.',
  'controls.row': 'A control was graded; a cheat that grades clean is an escape.',
  'controls.skip': 'A control could not be constructed for this task; it is counted as not constructible.',
  'controls.error': 'A control failed to run.',
  'controls.done': 'The controls run finished.',
  'controls.report': 'The controls verdict was recorded: constructed, caught, escaped.',
  // factory — the delivery loop
  'item.start': 'The factory started work on a backlog item.',
  'item.done': 'The item finished its loop.',
  'item.error': 'The item stopped on an error; its chain records where.',
  'item.blocked': 'The item is blocked on something a person must decide.',
  'readiness.assessed': 'The item’s readiness was assessed against the backlog’s gaps.',
  'readiness.refused': 'The item was refused before any spend because a readiness gap is open.',
  'route.decided': 'The item’s cell was routed by the published rule before any build was paid for.',
  'author.start': 'The factory started writing the item’s test.',
  'author.done': 'The item’s test was written.',
  'red.start': 'The new test is being run against the current code to prove it fails.',
  'red.proved': 'The new test failed on the current code, so the build may start.',
  'red.refused': 'The new test did not fail on the current code; no build.',
  'build.oracle_staged': 'The item’s test was staged as the oracle the build must satisfy.',
  'delivery.skipped': 'Delivery was skipped for this item; the payload names why.',
  'delivery.withheld': 'Built clean, but the map does not route deliver for this cell: no branch, no pull request; the measured route is on the chain.',
  'delivery.override': 'An approver overrode the route gate; the override is on the chain under their name.',
  'delivery.error': 'Opening the branch or pull request failed.',
  'delivery.opened': 'A branch and pull request were opened under review; never a merge.',
  'delivery.updated': 'A rework re-pointed the branch on the same pull request; the previous commit is named.',
  'delivery.comment_failed': 'The rework was pushed, but the note to the reviewer on the pull request could not be posted.',
  'review.start': 'A review of the delivered change started.',
  'review.probe': 'The review probed the delivered change.',
  'review.verdict': 'The review’s verdict was recorded; it is advisory to a person, never a route.',
  'review.recorded': 'The review was written to the chain.',
  'rework.start': 'The item went back for another build after a review finding.',
  'rework.refused': 'The reviewer asked for a stronger test and none could be had: no rebuild against the same test; the item goes to a person.',
  'horizon.checkpoint': 'The factory recorded a checkpoint of the whole backlog’s state.',
  // audit traces — out-of-band records, never rendered in the log but named for completeness
  'repo.created': 'The repository was registered.',
  'repo.updated': 'The repository’s configuration was changed; the diff is recorded.',
  'repo.github_linked': 'The repository was linked to a GitHub App installation; its clone URL changed and both URLs are recorded.',
  'github.installation.recorded': 'A GitHub App installation was recorded for this deployment.',
  'signoff.created': 'An approver signed off a cell; the attested row’s hash is recorded.',
  'signoff.refused': 'A sign-off was refused by the policy; the refusal names the clause.',
  'signoff.revoked': 'A sign-off was revoked.',
  'review.created': 'A human review of an accepted patch was recorded, anchored to the bytes read.',
  'review.refused': 'A review was refused because its patch hash did not match the pack.',
  // legacy — the CLI's ledger import, never on a run's live log
  'legacy.tasks': 'A legacy task file was read for import; the payload counts the tasks.',
  'legacy.skip': 'A legacy line was skipped on import; the payload names the reason.',
  'legacy.grade': 'A legacy grade was imported under the belt set it named.',
  'legacy.aggregate': 'Imported legacy grades were aggregated into a cell with the model and sample count recorded.',
}

/**
 * The sentence for an action. A builder's own `builder.build.*` event (a replay / blind trace
 * prefixes it; a factory trace does not) reads the `build.*` sentence; any other `builder.*`
 * event names its family; anything else gets a generic sentence naming the action.
 */
export function actionHelp(action: string): string {
  // own-property lookups: an event is unvalidated at this boundary, and an inherited key
  // (`constructor`, `__proto__`, `toString`) must not hand Object.prototype to JSX
  if (Object.hasOwn(ACTION_HELP, action)) return ACTION_HELP[action]!
  if (action.startsWith('builder.')) {
    const bare = action.slice('builder.'.length)
    return Object.hasOwn(ACTION_HELP, bare) ? ACTION_HELP[bare]! : 'A builder-level event, passed through from the builder.'
  }
  return `An event the loop emitted as “${action}”; this version of the UI has no sentence for it.`
}
