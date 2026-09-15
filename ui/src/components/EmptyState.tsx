/**
 * EmptyState — what this surface will show, why it is empty, and the one action that fills it.
 *
 * Navigation
 * ----------
 * What it is:   The designed empty state (design law 3 in ui/README.md).
 * What it does: Replaces a blank table or card with a title (what will appear), a reason (why
 *               nothing has yet), and at most one call to action. Neutral tone: the absence of
 *               data is not a failure, so it is never red or amber — an unmeasured cell and an
 *               empty ledger look calm, not broken.
 * How:          A centred column; `compact` for inside a table body.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/components/DataTable.tsx (its `empty` slot), ui/src/components/LiveLog.tsx
 *               (waiting for the first event), ui/src/components/ErrorState.tsx (the
 *               counterpart for a failure — the two are never confused),
 *               ui/src/screens/Repos/ReposPage.tsx (the first screen a new deployment shows)
 * Tested by:    ui/src/screens/Runs/RunDetailPage.test.tsx and
 *               ui/src/screens/Capability/CapabilityPage.test.tsx (the empty copy as rendered)
 * Touch when:   never for a new repository; the copy lives at each call site.
 */
import type { ReactNode } from 'react'

interface EmptyStateProps {
  /** What this surface will show once there is data. */
  title: string
  /** Why it is empty, in one sentence. */
  reason?: ReactNode
  /** The ONE call to action that fills it. */
  action?: ReactNode
  glyph?: string
  compact?: boolean
  'data-testid'?: string
}

/**
 * A designed empty state (STANDARD law 3): what this will show, why it's
 * empty, the one CTA that fills it. Neutral tone — absence of data is not a
 * failure, so no red, no amber.
 */
export function EmptyState({ title, reason, action, glyph = '◌', compact = false, ...rest }: EmptyStateProps) {
  return (
    <div
      data-testid={rest['data-testid'] ?? 'empty-state'}
      className={`flex flex-col items-center justify-center text-center ${compact ? 'gap-2 px-4 py-6' : 'gap-3 px-6 py-12'}`}
    >
      <div aria-hidden className="font-serif text-3xl text-on-surface-muted">
        {glyph}
      </div>
      <div className="font-serif text-[16px] font-semibold text-on-surface">{title}</div>
      {reason && <p className="max-w-md text-sm text-on-surface-muted">{reason}</p>}
      {action && <div className="mt-1">{action}</div>}
    </div>
  )
}
