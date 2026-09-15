/**
 * CiBar — an inline Wilson-interval bar: the [low, high] band, the point, optional policy ticks.
 *
 * Navigation
 * ----------
 * What it is:   The `CiBar` SVG: a 96 px glance aid for one rate's interval.
 * What it does: Draws the interval band, the point mark and the routing policy's thresholds
 *               (`min_point`, `min_ci_low`) as dashed ticks so a reader sees at once whether
 *               the lower bound clears the bar. It is always paired with the numbers in text
 *               and carries them in its `aria-label` — the bar is never the only carrier of
 *               the value; non-finite inputs are clamped to 0 rather than drawn as `NaN`.
 * How:          Clamp to [0, 1] → rects positioned as fractions of `width` → `<title>` and
 *               `aria-label` from `fmtPct`.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0003-one-routing-rule.md
 * Works with:   ui/src/lib/format.ts (`fmtPct`), ui/src/screens/Capability/CapabilityPage.tsx
 *               and ui/src/screens/Routing/RoutingPage.tsx (a bar per cell next to the interval
 *               text), ui/src/screens/Signoff/SignoffPage.tsx (the evidence tiles),
 *               ui/src/api/types.ts (`RoutingPolicy` — where the tick values come from)
 * Tested by:    ui/src/screens/Capability/CapabilityPage.test.tsx and
 *               ui/src/screens/Routing/RoutingPage.test.tsx (rendered per cell,
 *               `data-testid="ci-bar"`)
 * Touch when:   the routing policy gains a threshold worth a tick
 *               (docs/adr/0003-one-routing-rule.md);
 *               never for a new repository.
 * Claims:       A rate is shown with n and its interval, never alone
 *               (docs/EVIDENCE-AND-CLAIMS.md#3-every-number-carries-its-method).
 */
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
