import type { ReactNode } from 'react'

export interface GateCriterion {
  label: string
  /** true = satisfied, false = failed, null = not yet evaluated. */
  ok: boolean | null
  detail?: ReactNode
}

interface GateBannerProps {
  title: string
  /** Derived from the data, never asserted: all criteria ok ⇒ pass. */
  criteria: GateCriterion[]
  /** The primary action, disabled until every criterion holds. */
  action?: ReactNode
  /** Overrides the derived state (e.g. a server 409 refusal). */
  refused?: { title: string; message: ReactNode }
  eyebrow?: string
  'data-testid'?: string
}

/**
 * Gates look like gates (STANDARD law 7): a full-width banner-card with
 * explicit criteria check-rows and an action that is disabled until every
 * row holds. Tone and copy derive from the rows (law 2) — green only when
 * all hold, amber when a counted gap remains, red only on a refusal.
 */
export function GateBanner({ title, criteria, action, refused, eyebrow, ...rest }: GateBannerProps) {
  const failing = criteria.filter((c) => c.ok === false).length
  const pending = criteria.filter((c) => c.ok === null).length
  const passed = !refused && failing === 0 && pending === 0 && criteria.length > 0

  const tone = refused
    ? 'border-status-red/50 bg-status-red-soft'
    : passed
      ? 'border-status-green/50 bg-status-green-soft'
      : 'border-status-amber/50 bg-status-amber-soft'
  const ink = refused ? 'text-status-red' : passed ? 'text-status-green' : 'text-status-amber'
  const glyph = refused ? '⛔' : passed ? '✓' : '⚠'
  const state = refused ? 'REFUSED' : passed ? 'OPEN' : failing > 0 ? 'CLOSED' : 'PENDING'

  return (
    <section
      data-testid={rest['data-testid'] ?? 'gate-banner'}
      data-state={state}
      aria-labelledby="gate-title"
      className={`rounded-[var(--radius-card)] border-2 px-5 py-4 ${tone}`}
    >
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          {eyebrow && <div className="label">{eyebrow}</div>}
          <h2 id="gate-title" className={`flex items-center gap-2 text-[18px] ${ink}`}>
            <span aria-hidden className="font-mono">
              {glyph}
            </span>
            {refused ? refused.title : title}
            <span className={`label ml-1 rounded-[var(--radius-pill)] border px-1.5 py-0.5 ${ink}`}>{state}</span>
          </h2>
          {refused && <p className="mt-1 text-sm text-on-surface">{refused.message}</p>}
        </div>
        {action && <div>{action}</div>}
      </div>
      <ul className="mt-3 grid list-none gap-1.5 p-0 sm:grid-cols-2">
        {criteria.map((c) => {
          const g = c.ok === true ? '✓' : c.ok === false ? '✗' : '○'
          const t = c.ok === true ? 'text-status-green' : c.ok === false ? 'text-status-red' : 'text-on-surface-muted'
          const sr = c.ok === true ? 'satisfied' : c.ok === false ? 'not satisfied' : 'not yet evaluated'
          return (
            <li key={c.label} className="flex items-start gap-2 rounded-[var(--radius-control)] bg-surface-container/70 px-3 py-2 text-sm">
              <span aria-hidden className={`font-mono ${t}`}>
                {g}
              </span>
              <span className="sr-only">{sr}:</span>
              <span className="min-w-0">
                <span className="font-semibold text-on-surface">{c.label}</span>
                {c.detail && <span className="num block text-xs text-on-surface-muted">{c.detail}</span>}
              </span>
            </li>
          )
        })}
      </ul>
    </section>
  )
}
