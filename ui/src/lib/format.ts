/**
 * Number and date formatting with compute-guards (STANDARD law 1: `NaN`,
 * `Infinity` and `undefined` must be impossible in render). Every formatter
 * returns the em-dash for an absent value rather than a fabricated zero.
 *
 * Navigation
 * ----------
 * What it is:   The formatters every screen renders numbers through (`fmtPct`, `fmtInt`,
 *               `fmtUsd`, `fmtSeconds`, `fmtMs`, `fmtRatio`, `fmtCi`, `fmtDate`, `fmtTime`,
 *               `shortId`) and the client-side Wilson interval.
 * What it does: Guarantees `NaN`, `Infinity` and `undefined` cannot reach the page: an absent
 *               or non-finite value renders as the em-dash, never as a fabricated `0` or
 *               `0.0%`. `wilson` reproduces `crb.core.stats.wilson_interval` (95 %, same z) so
 *               a tile can show an interval for a count the API did not pre-compute.
 * How:          One `finite()` guard at the top of every formatter; fixed en-GB locale so the
 *               output is the same in tests and in production.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/components/StatTile.tsx (value + n + interval, always through these),
 *               ui/src/components/CiBar.tsx (the interval bar), src/crb/core/stats.py (the
 *               Wilson formula this file mirrors — keep the two identical),
 *               ui/src/screens/Runs/RunDetailPage.tsx (a heavy user of every formatter)
 * Tested by:    ui/src/components/StatTile.test.tsx (the dash for an absent value and the
 *               interval text), ui/src/screens/Capability/CapabilityPage.test.tsx (percentages
 *               and intervals as rendered)
 * Touch when:   the Wilson z or method changes in src/crb/core/stats.py (an apparatus change —
 *               docs/EVIDENCE-AND-CLAIMS.md#4-the-apparatus-stamp--evidence-expires); never for a
 *               new repository.
 * Claims:       Every rate the UI shows is accompanied by n and a Wilson interval
 *               (docs/EVIDENCE-AND-CLAIMS.md#3-every-number-carries-its-method).
 */

export const DASH = '—'

/** The render guard: only a finite number is ever formatted; everything else is the dash. */
function finite(n: unknown): n is number {
  return typeof n === 'number' && Number.isFinite(n)
}

/** 0..1 → "84.4%"; absent → "—". */
export function fmtPct(v: number | null | undefined, digits = 1): string {
  if (!finite(v)) return DASH
  return `${(v * 100).toFixed(digits)}%`
}

/** Integer with thousands separators. */
export function fmtInt(v: number | null | undefined): string {
  if (!finite(v)) return DASH
  return Math.round(v).toLocaleString('en-GB')
}

/** USD with sensible precision: < $1 → 4 dp, otherwise 2 dp. */
export function fmtUsd(v: number | null | undefined): string {
  if (!finite(v)) return DASH
  if (v === 0) return '$0.00'
  return `$${v.toFixed(Math.abs(v) < 1 ? 4 : 2)}`
}

/** Seconds → "12.3 s" / "4 min 2 s". */
export function fmtSeconds(v: number | null | undefined): string {
  if (!finite(v)) return DASH
  if (v < 60) return `${v.toFixed(v < 10 ? 1 : 0)} s`
  const m = Math.floor(v / 60)
  const s = Math.round(v - m * 60)
  return `${m} min ${s} s`
}

/** Milliseconds → "812 ms" / "3.2 s". */
export function fmtMs(v: number | null | undefined): string {
  if (!finite(v)) return DASH
  if (v < 1000) return `${Math.round(v)} ms`
  return fmtSeconds(v / 1000)
}

/** A 0..1 ratio to 2–3 significant decimals, e.g. oracle strength "0.83". */
export function fmtRatio(v: number | null | undefined, digits = 2): string {
  if (!finite(v)) return DASH
  return v.toFixed(digits)
}

/** Wilson interval as "[78.1%, 91.2%]". */
export function fmtCi(low: number | null | undefined, high: number | null | undefined): string {
  if (!finite(low) || !finite(high)) return DASH
  return `[${fmtPct(low)}, ${fmtPct(high)}]`
}

/** ISO timestamp → local, compact ("13 Sep 2026, 14:02"); absent → "—". */
export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return DASH
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return DASH
  return d.toLocaleString('en-GB', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

/** ISO timestamp → "14:02:11.482" for log lines. */
export function fmtTime(iso: string | null | undefined): string {
  if (!iso) return DASH
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  const hh = String(d.getHours()).padStart(2, '0')
  const mm = String(d.getMinutes()).padStart(2, '0')
  const ss = String(d.getSeconds()).padStart(2, '0')
  const ms = String(d.getMilliseconds()).padStart(3, '0')
  return `${hh}:${mm}:${ss}.${ms}`
}

/** A git sha or hash, shortened for display; the full value goes in `title`. */
export function shortId(id: string | null | undefined, n = 10): string {
  if (!id) return DASH
  return id.length > n ? id.slice(0, n) : id
}

/** Wilson score interval (95%) — mirrors `crb.core.stats.wilson_interval`. */
export function wilson(successes: number, n: number, z = 1.959964): { low: number; high: number } {
  if (n <= 0) return { low: 0, high: 0 }
  const p = successes / n
  const z2 = z * z
  const denom = 1 + z2 / n
  const centre = p + z2 / (2 * n)
  const half = z * Math.sqrt((p * (1 - p)) / n + z2 / (4 * n * n))
  return { low: Math.max(0, (centre - half) / denom), high: Math.min(1, (centre + half) / denom) }
}
