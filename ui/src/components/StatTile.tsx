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
