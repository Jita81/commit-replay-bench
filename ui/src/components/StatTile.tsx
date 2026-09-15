/**
 * StatTile — a headline metric that carries its evidence: value + n + interval + apparatus, always.
 *
 * Navigation
 * ----------
 * What it is:   The `StatTile` every headline number on every screen is shown in.
 * What it does: Enforces design law 1 (ui/README.md) at the type level: there is no variant
 *               without `n` and an apparatus line, and the value arrives already formatted so
 *               a bare number can never reach the page. An unmeasured value (`—`, or `n` of 0 /
 *               null) renders muted as an honest empty tile, never as a zero rate; a
 *               non-finite `n` renders as a dash.
 * How:          A `<dl>` of n / 95 % CI / apparatus under the value; `fmtInt` and `fmtCi` do
 *               the guarding.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/lib/format.ts (`fmtInt`, `fmtCi`, `wilson` for a client-side interval),
 *               ui/src/lib/verdict.ts (`TONE_TEXT` for a toned value),
 *               ui/src/screens/Runs/RunDetailPage.tsx (a run's tiles),
 *               ui/src/screens/Capability/CapabilityPage.tsx
 *               (coverage and false-Q1 tiles), ui/src/screens/Signoff/SignoffPage.tsx
 *               (the evidence tiles an approver reads)
 * Tested by:    ui/src/components/StatTile.test.tsx, ui/src/screens/Runs/RunDetailPage.test.tsx
 *               (`tile-*` test ids), ui/e2e/walkthrough/05-replay-fake.spec.ts
 * Touch when:   never for a new repository; the tile's anatomy changes only with
 *               docs/EVIDENCE-AND-CLAIMS.md#3-every-number-carries-its-method.
 * Claims:       Every number the UI shows carries its n and its method
 *               (docs/EVIDENCE-AND-CLAIMS.md#3-every-number-carries-its-method).
 */
import type { ReactNode } from 'react'
import { fmtCi, fmtInt } from '../lib/format'
import { TONE_TEXT, type Tone } from '../lib/verdict'

interface StatTileProps {
  label: string
  /** The headline value, already formatted (never a bare number — see below). */
  value: string
  /** The sample size behind the value. Required: a rate without its n is a rumour. */
  n: number | null | undefined
  /** Wilson 95% interval when the value is a rate. */
  ci?: { low: number; high: number } | null
  /** Apparatus/method line, e.g. "apparatus 2.0 · belt set v4 · Wilson 95%". */
  apparatus: string
  tone?: Tone
  hint?: ReactNode
  'data-testid'?: string
}

/**
 * A headline metric that carries its evidence (STANDARD law 1, brief
 * non-negotiable 5): value + n + CI + apparatus. There is no variant without
 * the n and the apparatus line; when the value is unmeasured pass "—" and
 * n = 0 and it renders as an honest empty tile, never a zero.
 */
export function StatTile({ label, value, n, ci, apparatus, tone, hint, ...rest }: StatTileProps) {
  const nText = typeof n === 'number' && Number.isFinite(n) ? fmtInt(n) : '—'
  const unmeasured = value === '—' || n === 0 || n === null || n === undefined
  return (
    <div
      data-testid={rest['data-testid']}
      className="min-w-[150px] flex-[1_1_150px] rounded-[var(--radius-card)] border border-border bg-surface-container px-4 py-3 shadow-[var(--shadow-card)]"
    >
      <div className="label">{label}</div>
      <div className={`num mt-1 text-[24px] font-semibold leading-8 ${unmeasured ? 'text-on-surface-muted' : tone ? TONE_TEXT[tone] : 'text-on-surface'}`}>
        {value}
      </div>
      <dl className="num mt-1 space-y-0.5 text-[11px] text-on-surface-muted">
        <div className="flex gap-1">
          <dt>n =</dt>
          <dd>{nText}</dd>
        </div>
        {ci !== undefined && (
          <div className="flex gap-1">
            <dt>95% CI</dt>
            <dd>{ci ? fmtCi(ci.low, ci.high) : '—'}</dd>
          </div>
        )}
        <div className="flex gap-1">
          <dt className="sr-only">apparatus</dt>
          <dd className="truncate" title={apparatus}>
            {apparatus}
          </dd>
        </div>
      </dl>
      {hint && <div className="mt-1 text-[11px] text-on-surface-muted">{hint}</div>}
    </div>
  )
}
