/**
 * The economics tiles' reading of the served fold (F35): value, n, interval, apparatus.
 *
 * Navigation
 * ----------
 * What it is:   `economicsTile`, which turns the server's `Economics` block (a cell's or the
 *               whole map's) into the four things a `StatTile` needs for cost per attempt,
 *               cost per clean attempt or latency per attempt; `economicsSpoken`, the grid
 *               cell's spoken value or reason; and `measuredCostPerAttempt`,
 *               the map fold's cost per attempt the Measure and Factory spend estimates read.
 * What it does: Uses the server's own denominators (attempts and clean attempts with a KNOWN
 *               value), its interval and its method string, and the apparatus versions the
 *               rows came from with their posture class — nothing is recomputed or averaged in
 *               the browser; a fold the server refused to pool (apparatus, posture class or
 *               checks arm) is the dash with the server's reason. An unknown
 *               value is the dash with the server's reason, never `$0`; a value with no
 *               interval shows "95% CI —" and says why; a response with no economics block
 *               says the server did not send one. The spend estimates read the map's fold
 *               (its value over the KNOWN count), never the cells' flat means filtered by
 *               `> 0`, which dropped a known $0 and weighted by every attempt (P-131).
 * How:          A lookup of the figure's estimate and its counts; `fmtUsd` / `fmtSeconds`
 *               format the value and both ends of the interval.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   src/crb/core/economics.py (the fold this reads — method, reasons, counts),
 *               ui/src/api/types.ts (`Economics`, `EconomicsEstimate`),
 *               ui/src/components/StatTile.tsx (`ci` + `ciFormat` render the interval),
 *               ui/src/screens/Results/ResultsPage.tsx (the Baseline's three tiles),
 *               ui/src/screens/Capability/CapabilityPage.tsx (the open cell's two tiles and
 *               the grid cell's cost and latency), ui/src/screens/Connect/MeasurePage.tsx and
 *               ui/src/screens/Factory/FactoryPage.tsx (the spend estimates)
 * Tested by:    ui/src/lib/economics.test.ts, ui/src/screens/Results/ResultsPage.test.tsx,
 *               ui/src/screens/Capability/CapabilityPage.test.tsx
 * Touch when:   never for a new repository; the server adds an economics figure (add it to
 *               `EconomicsFigure` and its denominator sentence here).
 * Claims:       Every economics figure the UI shows carries n, an interval or the reason it
 *               has none, and the apparatus
 *               (docs/EVIDENCE-AND-CLAIMS.md#3-every-number-carries-its-method).
 */

import type { Economics } from '../api/types'
import { DASH, fmtInt, fmtSeconds, fmtUsd } from './format'

export type EconomicsFigure = 'cost_per_attempt' | 'cost_per_clean' | 'latency_per_attempt'

export interface EconomicsTile {
  /** The formatted value, or the dash when nothing is known. */
  value: string
  /** The figure's denominator: attempts (or clean attempts) with a known value. */
  n: number
  /** The served interval, or `null` ("95% CI —", with the reason in `apparatus`). */
  ci: { low: number; high: number } | null
  /** Formats both ends of `ci` in the figure's unit. */
  ciFormat: (v: number) => string
  /** Denominators · method or the reason there is no value / interval · apparatus. */
  apparatus: string
}

export const NO_ECONOMICS = 'not served: this server does not report cost and latency with their intervals'

function denominators(e: Economics, figure: EconomicsFigure): string {
  if (figure === 'cost_per_attempt') return `${fmtInt(e.cost_known)} of ${fmtInt(e.n_attempts)} attempts with a known cost`
  if (figure === 'cost_per_clean') return `${fmtInt(e.cost_known_clean)} clean of ${fmtInt(e.cost_known)} attempts with a known cost`
  return `${fmtInt(e.latency_known)} of ${fmtInt(e.n_attempts)} attempts with a known latency`
}

/**
 * The tile for one economics figure of a cell's or a map's `economics` block. `mapApparatus`
 * (`apparatus 2.3`) is named on the tile when the server serves no block, so a headline tile
 * still says what its page was graded under (PR #56 review).
 */
export function economicsTile(e: Economics | undefined, figure: EconomicsFigure, mapApparatus?: string): EconomicsTile {
  const format = figure === 'latency_per_attempt' ? fmtSeconds : fmtUsd
  if (!e) return { value: DASH, n: 0, ci: null, ciFormat: format, apparatus: mapApparatus ? `${NO_ECONOMICS} · ${mapApparatus}` : NO_ECONOMICS }
  const est = e[figure]
  const ci = est.value !== null && est.ci_low !== null && est.ci_high !== null ? { low: est.ci_low, high: est.ci_high } : null
  const posture = e.posture_classes.length ? ` · posture ${e.posture_classes.join(', ')}` : ''
  const apparatus = `apparatus ${e.apparatus_versions.join(', ') || DASH}${posture}`
  return {
    value: est.value === null ? DASH : format(est.value),
    n: est.n,
    ci,
    ciFormat: format,
    apparatus: `${denominators(e, figure)} · ${est.reason || est.method} · ${apparatus}`,
  }
}

/**
 * One figure as a screen reader hears it in the grid: the value, or "not shown:" and the
 * server's reason — so a dash in the grid carries its reason too, not only the open cell.
 */
export function economicsSpoken(e: Economics | undefined, figure: EconomicsFigure): string {
  if (!e) return 'not served'
  const est = e[figure]
  if (est.value === null) return `not shown: ${est.reason || e.pooled_reason}`
  return (figure === 'latency_per_attempt' ? fmtSeconds : fmtUsd)(est.value)
}

/** The repository's measured cost per attempt, as the spend estimates quote it. */
export interface MeasuredCost {
  /** The fold's mean over the attempts with a known cost (a known $0 counts as $0). */
  mean: number
  /** Its denominator: the attempts with a known cost, never every attempt. */
  n: number
  /** The apparatus versions the rows came from. */
  apparatus: string
}

/**
 * The map fold's cost per attempt for a spend estimate, or `null` when there is none (no
 * fold served, no known cost, or a pool the server refused). Nothing is averaged here.
 */
export function measuredCostPerAttempt(e: Economics | undefined): MeasuredCost | null {
  const est = e?.cost_per_attempt
  if (!e || !est || est.value === null) return null
  return { mean: est.value, n: est.n, apparatus: e.apparatus_versions.join(', ') }
}

/** Why there is no measured cost per attempt: nothing measured yet, or the server's reason. */
export function noMeasuredCostReason(e: Economics | undefined): string {
  if (!e || e.n_attempts === 0) return 'n = 0 on the current apparatus'
  return e.cost_per_attempt.reason || e.pooled_reason
}
