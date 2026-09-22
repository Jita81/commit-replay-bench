/**
 * GateBanner — gates look like gates: criteria check-rows and an action disabled until every row
 * holds.
 *
 * Navigation
 * ----------
 * What it is:   The `GateBanner` used by the ledger, oracle and sign-off screens.
 * What it does: Derives its state from the criteria, never from an assertion: OPEN (green)
 *               only when every criterion is `true`, CLOSED (amber) while one is `false`,
 *               PENDING while one is `null`, and REFUSED (red) only when the server refused
 *               (a 409). Each row carries a glyph and a screen-reader word as well as its
 *               colour; `data-state` exposes the verdict to tests. A criterion's `hint` (a
 *               registry id) makes its label the hover / focus / tap trigger for what the
 *               row checks; the section carries `data-component="gate"` so the ratchet can
 *               require one on every row.
 * How:          Count failing / pending criteria → pick tone, glyph and state → a `<section>`
 *               labelled by its heading with the action slot and the rows.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0001-four-belts-and-false-q1-at-write.md
 * Works with:   ui/src/components/Hint.tsx (the row trigger), ui/src/help/hints.ts (`gate.*`
 *               ids), ui/src/screens/Signoff/SignoffPage.tsx (the policy clauses as criteria; a 409
 *               as `refused`), ui/src/screens/Ledger/LedgerPage.tsx (chain intact, false-Q1 =
 *               0), ui/src/screens/Oracle/OraclePage.tsx (the controls verdict),
 *               ui/src/components/ErrorState.tsx (what a refusal outside a gate looks like)
 * Tested by:    ui/src/help/hints-ratchet.test.tsx (the hint contract),
 *               ui/src/screens/Signoff/SignoffPage.test.tsx (CLOSED / REFUSED / OPEN states),
 *               ui/e2e/walkthrough/08-signoff.spec.ts, ui/e2e/walkthrough/05-replay-fake.spec.ts
 *               (the ledger gate OPEN)
 * Touch when:   a gate gains a criterion — add the row at the call site, not here; never for a
 *               new repository.
 * Claims:       A green gate means every listed criterion held at read time, nothing more
 *               (docs/EVIDENCE-AND-CLAIMS.md#6a-what-a-signed-cell-may-be-claimed-to-mean-signoff-policyv2).
 */
import type { ReactNode } from 'react'
import type { HintId } from '../help/hints'
import { Hint } from './Hint'

/** One check-row; `null` = not yet evaluated (pending), so a gate is never green before its data arrived. */
export interface GateCriterion {
  label: string
  /** true = satisfied, false = failed, null = not yet evaluated. */
  ok: boolean | null
  detail?: ReactNode
  /** What this row checks and what failing it means — a registry id; the ratchet requires one on every row. */
  hint?: HintId
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
  // The state is DERIVED, never asserted: a refusal from the server wins outright; a
  // gate with no criteria, a pending row or a failing row is not open. Green requires
  // every row true.
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
      data-component="gate"
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
                {c.hint ? (
                  <Hint id={c.hint} className="font-semibold text-on-surface">
                    {c.label}
                  </Hint>
                ) : (
                  <span className="font-semibold text-on-surface">{c.label}</span>
                )}
                {c.detail && <span className="num block text-xs text-on-surface-muted">{c.detail}</span>}
              </span>
            </li>
          )
        })}
      </ul>
    </section>
  )
}
