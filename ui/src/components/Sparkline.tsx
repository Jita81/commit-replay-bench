/**
 * Sparkline — STUB. No charts library for now: tables and grids with numeric
 * integrity beat charts on governance surfaces. This renders the series as a
 * text summary (min → max, n) so callers can already wire it; a real inline
 * SVG can replace the body without changing the signature.
 *
 * Navigation
 * ----------
 * What it is:   A placeholder `Sparkline` with the final signature (`values`, `label`).
 * What it does: Renders "min → max (n=k)" over the finite values, or a dash with an accessible
 *               "no data" label when there are none. No chart library is pulled in; the
 *               governance surfaces are tables with numeric integrity, and this stays a stub
 *               until a chart is shown to beat one. Currently unused by any screen.
 * How:          Filter to finite numbers → `Math.min` / `Math.max`.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/lib/format.ts (the same "absent → dash" rule), ui/src/components/CiBar.tsx
 *               (the one inline SVG that did earn its place), ui/README.md (the "Stack" note
 *               that explains the stub)
 * Tested by:    untested — a stub with no consumer; test it when a screen adopts it
 * Touch when:   a screen needs a real sparkline — replace the body, keep the signature and the
 *               no-data branch; never for a new repository.
 */
export function Sparkline({ values, label }: { values: readonly number[]; label: string }) {
  const finite = values.filter((v) => Number.isFinite(v))
  if (finite.length === 0) {
    return (
      <span className="num text-xs text-on-surface-muted" aria-label={`${label}: no data`}>
        —
      </span>
    )
  }
  const min = Math.min(...finite)
  const max = Math.max(...finite)
  return (
    <span className="num font-mono text-xs text-on-surface-muted" aria-label={`${label}: ${finite.length} points, from ${min} to ${max}`}>
      {min} → {max} (n={finite.length})
    </span>
  )
}
