/**
 * The A2 additions to the capability / routing contract (docs/API.md, review action #4):
 * the `failure_kind` split, `model_point` next to the all-rows point, the repo's
 * negative-controls verdict and the decision's `reason_code`.
 *
 * Lives beside the screens (not in `api/types.ts` / `api/hooks.ts`, which another
 * workstream owns in this wave) — fold it in when the wave merges. Every field here is
 * `@contract` with `crb.server.schemas_capability`.
 */

import { useQuery, type UseQueryResult } from '@tanstack/react-query'
import { api, qs, type ApiError } from '../../api/client'
import { useCapabilityMap, useRoutes } from '../../api/hooks'
import type { CapabilityCell, CapabilityMap, CellField, RouteDecision, RoutesResponse, RoutingPolicy } from '../../api/types'
import type { Tone } from '../../lib/verdict'

// ---------------------------------------------------------------------------
// Vocabulary (crb.core.ledger.FAILURE_KINDS / crb.core.routing)
// ---------------------------------------------------------------------------

/** `crb.core.ledger.GradeRow.failure_kind` — `''` is clean; `lint` = belts 1–4 held, belt 5 rejected (ADR-0011). */
export type FailureKind = '' | 'builder_red' | 'lint' | 'budget' | 'protocol' | 'harness' | 'outage' | 'disqualified'

/** `crb.core.routing.REASON_CODES`, in evaluation order. */
export type ReasonCode =
  | 'false_q1'
  | 'granularize'
  | 'controls_failed'
  | 'n_below_min'
  | 'oracle_weak'
  | 'controls_escapes'
  | 'point_below_bar'
  | 'ci_low_below_bar'
  | 'controls_unmeasured'
  | 'controls_thin'
  | 'deliver'

/** `crb.core.routing.CONTROLS_STATES` — the pill word. */
export type ControlsState = 'passed' | 'failed' | 'thin' | 'escaped' | 'unmeasured'

/** `ControlsVerdict.to_dict()` + `state`. `measured: false` only when the repo has no report. */
export interface ControlsVerdict {
  measured: boolean
  passed: boolean
  complete: boolean
  constructible: number
  total: number
  share: number
  escapes: number
  run_id: string
  created: string
  state: ControlsState
}

/** Counts by failure kind; `builder_red + lint + budget + protocol + harness + clean == n`. */
export interface FailureSplit {
  builder_red: number
  /** Belts 1–4 held; the repository's own linter rejected the changed files (belt 5). */
  lint?: number
  budget: number
  protocol: number
  harness: number
  disqualified: number
  /** How many of the n rows carried belt 5 at all — the denominator `lint` needs. */
  lint_evaluated?: number
  /** Provider outages (usage limit / 429 / dead credential): the call never happened; outside n. */
  outage?: number
}

export interface RoutingPolicyWithControls extends RoutingPolicy {
  min_controls_share: number
  max_controls_escapes: number
  controls_version: string
}

/** A measured cell + the split, the model point (with n and interval) and the reason code. */
export interface CapabilityCellSplit extends CapabilityCell {
  reason_code: ReasonCode
  n_builder_red: number
  n_lint?: number
  n_budget: number
  n_protocol: number
  n_harness: number
  n_disqualified: number
  n_lint_evaluated?: number
  model_n: number
  /** clean / (clean + builder_red); `null` when no fair, finished attempt exists. */
  model_point: number | null
  model_ci_low: number
  model_ci_high: number
  failure_split: FailureSplit
}

export interface CapabilityMapWithControls extends Omit<CapabilityMap, 'cells' | 'policy'> {
  cells: CapabilityCellSplit[]
  policy: RoutingPolicyWithControls
  /** Always present — `state: 'unmeasured'` when the repo never ran controls. */
  controls: ControlsVerdict
}

export interface RouteDecisionWithControls extends RouteDecision {
  reason_code: ReasonCode
  /** `controls-gate.v1` when the verdict was evaluated (the server always does). */
  controls_policy: string
  controls: ControlsVerdict | null
  model_n: number
  model_point: number | null
  failure_split: FailureSplit
}

export interface RoutesWithControls extends Omit<RoutesResponse, 'decisions' | 'policy'> {
  decisions: RouteDecisionWithControls[]
  policy: RoutingPolicyWithControls
  controls: ControlsVerdict
}

/** `GET /failure-split?repo=&run_id=` — `FailureSplit.to_dict()` over a repo or one run. */
export interface FailureSplitReport extends FailureSplit {
  repo: string
  run_id: string
  n: number
  clean: number
  rows: number
  point: number
  ci_low: number
  ci_high: number
  model_n: number
  model_point: number
  model_ci_low: number
  model_ci_high: number
  cost_known: number
  cost_unknown: number
  kinds: FailureKind[]
}

// ---------------------------------------------------------------------------
// Hooks — the base hooks re-typed to the extended shapes (one cast point)
// ---------------------------------------------------------------------------

export function useCapabilityMapWithControls(repo: string, by: CellField[]): UseQueryResult<CapabilityMapWithControls, ApiError> {
  return useCapabilityMap(repo, by) as unknown as UseQueryResult<CapabilityMapWithControls, ApiError>
}

export function useRoutesWithControls(repo: string): UseQueryResult<RoutesWithControls, ApiError> {
  return useRoutes(repo) as unknown as UseQueryResult<RoutesWithControls, ApiError>
}

export function useFailureSplit(repo: string, runId = ''): UseQueryResult<FailureSplitReport, ApiError> {
  return useQuery({
    queryKey: ['failure-split', repo, runId] as const,
    queryFn: () => api<FailureSplitReport>(`/failure-split${qs({ repo, run_id: runId || undefined })}`),
    enabled: repo.length > 0,
    retry: false,
    staleTime: 15_000,
  })
}

// ---------------------------------------------------------------------------
// Display vocabulary
// ---------------------------------------------------------------------------

export interface KindDisplay {
  key: 'builder_red' | 'lint' | 'budget' | 'protocol' | 'harness' | 'outage' | 'disqualified'
  short: string
  long: string
  tone: Tone
}

/** The split in the order it is always shown: red · lint · budget · protocol · harness · DQ. */
export const KIND_DISPLAY: readonly KindDisplay[] = [
  { key: 'builder_red', short: 'red', long: 'builder red — the model finished and the belts failed it (target not green, a regression, no source change)', tone: 'red' },
  { key: 'lint', short: 'lint', long: "lint — the code worked (belts 1–4 held) but the repository's own formatter/linter rejected the changed files (belt 5)", tone: 'amber' },
  { key: 'budget', short: 'budget', long: 'budget — the builder hit its own cap (wall clock, turns, tool calls, tokens or cost) before it finished', tone: 'amber' },
  { key: 'protocol', short: 'protocol', long: 'protocol — a guard refused the builder (tamper / archaeology / network); an instrument decision', tone: 'violet' },
  { key: 'harness', short: 'harness', long: 'harness — executor / sandbox / parse / timeout / setup / model-API error; the instrument, not the model', tone: 'violet' },
  { key: 'outage', short: 'outage', long: 'outage — the model provider refused the call (usage limit, 429, dead credential); nothing was observed; outside n', tone: 'muted' },
  { key: 'disqualified', short: 'DQ', long: 'disqualified — tamper or malformed oracle; excluded, not counted either way', tone: 'muted' },
]

export interface ControlsDisplay {
  label: string
  tone: Tone
  glyph: string
  describe: string
}

/** The controls pill: passed / FAILED / thin k of N / escaped / unmeasured. */
export function controlsDisplay(v: ControlsVerdict | null | undefined): ControlsDisplay {
  if (!v || !v.measured) {
    return { label: 'controls: unmeasured', tone: 'muted', glyph: '·', describe: 'Negative controls: never run for this repo — deliver is withheld until a controls run passes.' }
  }
  const kn = `${v.constructible} of ${v.total}`
  const run = v.run_id ? ` (run ${v.run_id.slice(0, 8)})` : ''
  const partial = v.complete ? '' : ' — the run was cancelled part-way'
  switch (v.state) {
    case 'failed':
      return { label: 'controls: FAILED', tone: 'red', glyph: '✗', describe: `Negative controls: the gate FAILED — an instrument defect on this repo; every cell routes human${run}${partial}.` }
    case 'escaped':
      return { label: `controls: ${v.escapes} escape${v.escapes === 1 ? '' : 's'}`, tone: 'amber', glyph: '⚠', describe: `Negative controls: passed, but ${v.escapes} measurement control(s) graded clean — the oracle cannot tell an implementation from a cheat; deliver withheld until re-measured${run}${partial}.` }
    case 'thin':
      return { label: `controls: thin ${kn}`, tone: 'amber', glyph: '◐', describe: `Negative controls: passed, but only ${kn} control rows were constructible (${Math.round(v.share * 100)}% < 50%) — the load-bearing ones never ran; deliver withheld${run}${partial}.` }
    default:
      return { label: `controls: passed ${kn}`, tone: 'green', glyph: '✓', describe: `Negative controls: passed, ${kn} constructible, ${v.escapes} escape(s)${run}${partial}.` }
  }
}

/** One line per reason code — what the route is waiting on. */
export const REASON_DISPLAY: Record<ReasonCode, string> = {
  false_q1: 'false-Q1 in cell — evidence untrusted',
  granularize: 'XL is split before it is attempted',
  controls_failed: 'negative-controls gate FAILED on this repo',
  n_below_min: 'not enough evidence (n below the bar)',
  oracle_weak: 'oracle too weak to license auto-delivery',
  controls_escapes: 'a measurement control escaped the oracle',
  point_below_bar: 'point estimate below the bar',
  ci_low_below_bar: 'Wilson lower bound below the bar',
  controls_unmeasured: 'negative controls never run',
  controls_thin: 'fewer than half the controls were constructible',
  deliver: 'every bar cleared',
}
