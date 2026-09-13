import { fmtPct } from '../lib/format'

interface CiBarProps {
  point: number
  low: number
  high: number
  n: number
  /** Policy thresholds drawn as ticks (point bar ≥ min_point; lower bound ≥ min_ci_low). */
  minPoint?: number
  minCiLow?: number
  width?: number
}

/**
 * A tiny inline Wilson-interval bar: the [low, high] band, the point as a
 * mark, optional policy ticks. Always paired with the numbers in text — the
 * bar is a glance aid, never the only carrier of the value.
 */
export function CiBar({ point, low, high, n, minPoint, minCiLow, width = 96 }: CiBarProps) {
  const clamp = (v: number) => Math.max(0, Math.min(1, Number.isFinite(v) ? v : 0))
  const p = clamp(point)
  const l = clamp(low)
  const h = clamp(high)
  const label = `point ${fmtPct(p)}, 95% CI ${fmtPct(l)} to ${fmtPct(h)}, n = ${n}`
  const hgt = 10
  return (
    <svg
      role="img"
      aria-label={label}
      width={width}
      height={hgt}
      viewBox={`0 0 ${width} ${hgt}`}
      className="inline-block align-middle"
      data-testid="ci-bar"
    >
      <title>{label}</title>
      <rect x={0} y={hgt / 2 - 1} width={width} height={2} fill="var(--line)" />
      <rect x={l * width} y={hgt / 2 - 3} width={Math.max(1, (h - l) * width)} height={6} fill="var(--trust-soft)" stroke="var(--trust)" strokeWidth={1} />
      <rect x={p * width - 1} y={0} width={2} height={hgt} fill="var(--trust)" />
      {typeof minPoint === 'number' && (
        <line x1={minPoint * width} x2={minPoint * width} y1={0} y2={hgt} stroke="var(--muted)" strokeDasharray="1 1" />
      )}
      {typeof minCiLow === 'number' && (
        <line x1={minCiLow * width} x2={minCiLow * width} y1={0} y2={hgt} stroke="var(--muted)" strokeDasharray="2 1" />
      )}
    </svg>
  )
}
