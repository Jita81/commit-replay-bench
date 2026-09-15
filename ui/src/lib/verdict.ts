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
 *               `tierDisplay`, `beltDisplay`) and the Tailwind classes per tone.
 * What it does: Gives every state a glyph and a screen-reader sentence as well as a colour, so
 *               a verdict survives monochrome, colour-blindness and assistive technology; an
 *               unknown value from a newer server renders as a muted `?` with the raw string,
 *               never as a fabricated known state. A belt that is `null` is "not recorded"
 *               (or "not evaluated" for belt 5), never a fail.
 * How:          One `Record<Value, Display>` per vocabulary with a lookup function that falls
 *               back to the muted default.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0003-one-routing-rule.md, docs/adr/0011-repo-lint-belt.md
 * Works with:   ui/src/components/Pill.tsx (renders a `Display`), ui/src/components/VerdictPill.tsx
 *               (route / status pills), ui/src/components/BeltPills.tsx (`beltDisplay`,
 *               `BELT_LABELS`), ui/src/api/types.ts (the vocabularies these tables cover),
 *               ui/src/index.css (the tone tokens the classes name)
 * Tested by:    ui/src/components/VerdictPill.test.tsx, ui/src/components/BeltPills.test.tsx
 * Touch when:   a route, run status, belt, band or tier is added on the server (an apparatus or
 *               policy change with its ADR) — add the row here and the type in
 *               ui/src/api/types.ts; never for a new repository.
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
  deliver: { label: 'Deliver', tone: 'green', glyph: '✓', describe: 'Route: deliver — auto-deliver as a branch and PR' },
  calibrate: { label: 'Calibrate', tone: 'primary', glyph: '◐', describe: 'Route: calibrate — more evidence needed before the bar is met' },
  granularize: { label: 'Granularize', tone: 'blue', glyph: '⋮', describe: 'Route: granularize — split before attempting' },
  human: { label: 'Human', tone: 'amber', glyph: '☺', describe: 'Route: human — oracle too weak to license auto-delivery' },
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
  strong: { label: 'Strong', tone: 'green', glyph: '✓', describe: 'Oracle strength: strong — licenses auto-ship' },
  adequate: { label: 'Adequate', tone: 'primary', glyph: '◐', describe: 'Oracle strength: adequate — review-gated' },
  weak: { label: 'Weak', tone: 'amber', glyph: '⚠', describe: 'Oracle strength: weak — a green is low confidence' },
  unscoreable: { label: 'Unscoreable', tone: 'muted', glyph: '·', describe: 'Oracle strength: unscoreable — no mutants' },
}

/** An oracle-strength band → its display. */
export function bandDisplay(band: OracleBand | string): Display {
  return BAND_DISPLAY[band as OracleBand] ?? { label: band, tone: 'muted', glyph: '?', describe: `Oracle band: ${band}` }
}

const GATE_DISPLAY: Record<OracleGate, Display> = {
  auto_ship: { label: 'Auto-ship', tone: 'green', glyph: '✓', describe: 'Gate: auto-ship' },
  human_review: { label: 'Human review', tone: 'amber', glyph: '☺', describe: 'Gate: human review' },
  needs_human: { label: 'Needs human', tone: 'red', glyph: '✗', describe: 'Gate: needs human' },
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
