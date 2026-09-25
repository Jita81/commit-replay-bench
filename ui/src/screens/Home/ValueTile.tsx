/**
 * ValueTile — the north star on Home: working changes per pound, blind, with its evidence.
 *
 * Navigation
 * ----------
 * What it is:   The one scorecard tile on Home (`/home`): working changes per pound spent on
 *               blind attempts, across every repository, from `GET /value`.
 * What it does: Shows the estimate with the blind valid attempts behind it (n), its interval in
 *               the same unit (pounds, not a percentage), the apparatus it was measured under
 *               and whether the precision came from reviews or the labelled proxy. While the
 *               number is unmeasured (no blind attempt, no precision) or the API refuses it, the
 *               tile is an honest empty tile with the reason, never a zero. The whole tile is the
 *               hint trigger (`stat.home.value`).
 * How:          `useValue()` → `StatTile` with `value` and `n`, the per-pound interval and the
 *               pounds-per-change reading in the footer (StatTile's CI line formats a rate as a
 *               percentage, so it is not used for a figure in pounds).
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/screens/Home/HomePage.tsx (where it stands), ui/src/components/StatTile.tsx
 *               (the tile anatomy), ui/src/api/hooks.ts (`useValue`), ui/src/help/hints.ts
 *               (`stat.home.value`), src/crb/server/routes/value.py (the route it reads)
 * Tested by:    ui/src/screens/Home/HomePage.test.tsx, ui/src/help/hints-ratchet.test.tsx
 * Touch when:   the scorecard's headline changes in src/crb/core/value.py (keep the unit, the
 *               n and the method in step).
 */

import { useValue } from '../../api/hooks'
import { StatTile } from '../../components/StatTile'

/** How the precision was measured, in words — the basis the API names. */
const BASIS: Record<string, string> = { review: 'reviews', review_pooled: 'reviews of every repository', proxy: 'proxy: lint and public interface' }

function fix(v: number | null | undefined, digits = 2): string {
  return typeof v === 'number' && Number.isFinite(v) ? v.toFixed(digits) : '—'
}

export function ValueTile() {
  const value = useValue()
  const ns = value.data?.north_star
  const measured = Boolean(ns && ns.per_pound !== null && ns.n_valid > 0)
  const apparatus = value.data
    ? `apparatus ${value.data.apparatus}${value.data.pooled ? ' (pooled)' : ''} · blind · estimate`
    : 'apparatus —'
  const basis = ns && ns.precision_basis in BASIS ? `${BASIS[ns.precision_basis]} (n = ${ns.precision.n})` : 'none yet'
  const footer = value.isError
    ? 'Not available: the API refused the scorecard.'
    : !value.data
      ? 'Loading.'
      : measured && ns
        ? `95% range ${fix(ns.per_pound_low)}–${fix(ns.per_pound_high)} per £ · about £${fix(ns.pounds_per_working)} per working change · precision from ${basis}`
        : 'No blind attempt with a precision yet, so there is no number to show.'
  return (
    <StatTile
      data-testid="tile-value"
      label="Working changes per £ (blind)"
      value={measured && ns ? `${fix(ns.per_pound)} per £` : '—'}
      n={value.data ? ns?.n_valid ?? 0 : undefined}
      apparatus={apparatus}
      hint="stat.home.value"
      footer={footer}
    />
  )
}
