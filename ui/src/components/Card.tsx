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
