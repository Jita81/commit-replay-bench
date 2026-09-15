/**
 * Card — the bordered surface every screen section sits in.
 *
 * Navigation
 * ----------
 * What it is:   The `Card` section primitive: optional eyebrow, `h2` title and a top-right
 *               actions slot over a padded body.
 * What it does: Gives every screen section the same anatomy so a reader can scan a page; the
 *               actions slot is where selectors and export buttons live (design law 10 in
 *               ui/README.md), never inside the body.
 * How:          A `<section>` with a conditional `<header>`; `padded={false}` for bodies that
 *               are a table.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/components/PageHeader.tsx (the page-level counterpart with the `h1`),
 *               ui/src/components/DataTable.tsx (the usual unpadded body),
 *               ui/src/screens/Runs/RunDetailPage.tsx (a typical multi-card screen)
 * Tested by:    ui/e2e/walkthrough/07-settings-and-a11y.spec.ts (heading order and axe on
 *               every screen); rendered by every screen test
 * Touch when:   never for a new repository; the section anatomy changes only with the design
 *               standard in ui/README.md.
 */
import type { ReactNode } from 'react'

interface CardProps {
  title?: ReactNode
  eyebrow?: string
  /** Top-right slot: selectors + export buttons (STANDARD law 10). */
  actions?: ReactNode
  children: ReactNode
  className?: string
  padded?: boolean
  id?: string
}

/** Borders-first surface, 12px radius, one soft shadow. */
export function Card({ title, eyebrow, actions, children, className = '', padded = true, id }: CardProps) {
  return (
    <section
      id={id}
      className={`rounded-[var(--radius-card)] border border-border bg-surface-container shadow-[var(--shadow-card)] ${className}`}
    >
      {(title || actions || eyebrow) && (
        <header className="flex flex-wrap items-start justify-between gap-3 border-b border-border px-5 py-3.5">
          <div className="min-w-0">
            {eyebrow && <div className="label">{eyebrow}</div>}
            {title && <h2 className="text-[16px] leading-6">{title}</h2>}
          </div>
          {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className={padded ? 'px-5 py-4' : ''}>{children}</div>
    </section>
  )
}
