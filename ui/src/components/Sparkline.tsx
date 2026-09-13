/**
 * Sparkline — STUB. No charts library for now: tables and grids with numeric
 * integrity beat charts on governance surfaces. This renders the series as a
 * text summary (min → max, n) so callers can already wire it; a real inline
 * SVG can replace the body without changing the signature.
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
