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
