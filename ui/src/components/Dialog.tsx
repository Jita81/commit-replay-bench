/**
 * Dialog — a native <dialog> with the platform's focus trap, Esc to close and a labelled heading.
 *
 * Navigation
 * ----------
 * What it is:   The `Dialog` primitive the two "new …" forms open in.
 * What it does: Opens and closes a native `<dialog>` from an `open` prop, keeps the heading as
 *               its accessible name, routes Esc through `onClose` (an Esc that closes an open
 *               hint bubble is default-prevented by `Hint` and never reaches here), and
 *               unmounts its content while closed so form state resets per opening. A modal
 *               dialog paints in the browser's top layer, so `Hint` portals its bubble into
 *               the dialog rather than `<body>`. No portal library.
 * How:          A `useEffect` calls `showModal()` / `close()` to track `open`; jsdom has no
 *               `showModal`, so the effect falls back to the `open` attribute there.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/screens/Repos/RepoNewDialog.tsx and ui/src/screens/Runs/RunNewDialog.tsx
 *               (the two consumers), ui/src/components/Button.tsx (the close button),
 *               ui/src/components/Hint.tsx (portals its bubble into the open dialog)
 * Tested by:    ui/src/screens/Repos/RepoNewDialog.test.tsx,
 *               ui/src/screens/Runs/RunNewDialog.test.tsx,
 *               ui/e2e/walkthrough/02-repo-onboard.spec.ts (the real modal in Chromium)
 * Touch when:   a third dialog needs a size or a non-modal mode; never for a new repository.
 */
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
      // jsdom lacks close() too: mirror the fallback so a closing dialog never throws there
      if (typeof el.close === 'function') el.close()
      else el.removeAttribute('open')
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
