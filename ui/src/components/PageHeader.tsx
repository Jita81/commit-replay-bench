/**
 * PageHeader — eyebrow, the page's one h1, its purpose sentence and the actions slot.
 *
 * Navigation
 * ----------
 * What it is:   The `PageHeader` every screen opens with.
 * What it does: Fixes the page anatomy: a small-caps eyebrow (where you are), the single `h1`
 *               (one per page — axe checks it), a one-line purpose, and the top-right slot for
 *               selectors and export / audit affordances (design law 10 in ui/README.md).
 * How:          A flex `<header>`; nothing stateful.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/components/Card.tsx (the section-level counterpart with `h2`),
 *               ui/src/components/RepoPicker.tsx (the usual occupant of the actions slot),
 *               ui/src/screens/Runs/RunDetailPage.tsx (status pills in the purpose slot)
 * Tested by:    ui/e2e/walkthrough/07-settings-and-a11y.spec.ts (one `h1` per page, axe);
 *               rendered by every screen test
 * Touch when:   never for a new repository.
 */
import type { ReactNode } from 'react'

interface PageHeaderProps {
  /** Small-caps breadcrumb, e.g. "Runs · replay". */
  eyebrow?: string
  title: string
  /** The one-line "why this screen exists" sentence. */
  purpose?: ReactNode
  /** Top-right: selectors + export/audit affordances (STANDARD law 10). */
  actions?: ReactNode
}

/** Governance-page anatomy: eyebrow → serif h1 (one per page) → purpose → actions. */
export function PageHeader({ eyebrow, title, purpose, actions }: PageHeaderProps) {
  return (
    <header className="flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0 space-y-1">
        {eyebrow && <div className="label">{eyebrow}</div>}
        <h1>{title}</h1>
        {purpose && <p className="max-w-3xl text-sm text-on-surface-muted">{purpose}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </header>
  )
}
