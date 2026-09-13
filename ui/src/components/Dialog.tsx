import { useEffect, useRef, type ReactNode } from 'react'
import { Button } from './Button'

interface DialogProps {
  open: boolean
  title: string
  onClose: () => void
  children: ReactNode
  /** Footer slot (actions). */
  footer?: ReactNode
  width?: 'md' | 'lg'
}

/**
 * Native <dialog> with focus trapping from the platform, Esc to close, and a
 * labelled heading. Kept deliberately small — no portal library.
 */
export function Dialog({ open, title, onClose, children, footer, width = 'md' }: DialogProps) {
  const ref = useRef<HTMLDialogElement>(null)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    if (open && !el.open) {
      // jsdom lacks showModal; fall back to the `open` attribute.
      if (typeof el.showModal === 'function') el.showModal()
      else el.setAttribute('open', '')
    } else if (!open && el.open) {
      el.close()
    }
  }, [open])

  return (
    <dialog
      ref={ref}
      aria-labelledby="crb-dialog-title"
      onClose={onClose}
      onCancel={(e) => {
        e.preventDefault()
        onClose()
      }}
      className={`m-auto w-[min(92vw,${width === 'lg' ? '860px' : '560px'})] rounded-[var(--radius-card)] border border-border bg-surface-container p-0 text-on-surface shadow-[var(--shadow-card)] backdrop:bg-black/40`}
    >
      {open && (
        <div className="flex max-h-[85vh] flex-col">
          <header className="flex items-center justify-between border-b border-border px-5 py-3.5">
            <h2 id="crb-dialog-title" className="text-[18px] leading-7">
              {title}
            </h2>
            <Button variant="ghost" size="sm" onClick={onClose} aria-label="Close dialog">
              ✕
            </Button>
          </header>
          <div className="overflow-y-auto px-5 py-4">{children}</div>
          {footer && <footer className="flex justify-end gap-2 border-t border-border px-5 py-3">{footer}</footer>}
        </div>
      )}
    </dialog>
  )
}
