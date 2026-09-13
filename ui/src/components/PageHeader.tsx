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
