/**
 * Dialog.tsx — keyboard focus goes back to the control that opened the dialog.
 *
 * Navigation
 * ----------
 * What it is:   Tests for the `Dialog` primitive's focus return.
 * What it does: Pins that when a dialog closes — by being unmounted (Learn's Decide and Queue
 *               dialogs are mounted only while open) or by `open` turning false (the two
 *               "new …" forms stay mounted) — keyboard focus returns to the button that
 *               opened it rather than falling to the page body (P-055). A removed `<dialog>`
 *               is never closed by the platform, so nothing restores focus unless `Dialog`
 *               does it itself.
 * How:          A small host component with an opener button and each mounting pattern;
 *               `userEvent` clicks, so focus moves as it would for a reader.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/components/Dialog.tsx (under test), ui/src/screens/Learn/LearnPage.tsx
 *               (the unmounting consumers), ui/src/screens/Runs/RunNewDialog.tsx (a mounted
 *               consumer), ui/e2e/walkthrough/13-learn.spec.ts (the same return in Chromium)
 * Tested by:    ui/src/components/Dialog.test.tsx
 * Touch when:   the dialog gains a non-modal mode or a new way to close.
 */
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, it } from 'vitest'
import { Dialog } from './Dialog'

/** Learn's pattern: the dialog exists only while it is open. */
function Unmounting() {
  const [open, setOpen] = useState(false)
  return (
    <>
      <button onClick={() => setOpen(true)}>Decide</button>
      {open && (
        <Dialog open title="Decide this refusal class" onClose={() => setOpen(false)} footer={<button onClick={() => setOpen(false)}>Cancel</button>}>
          <p>body</p>
        </Dialog>
      )}
    </>
  )
}

/** The "new …" forms' pattern: always mounted, `open` toggled. */
function Mounted() {
  const [open, setOpen] = useState(false)
  return (
    <>
      <button onClick={() => setOpen(true)}>Start a run</button>
      <Dialog open={open} title="Start a run" onClose={() => setOpen(false)} footer={<button onClick={() => setOpen(false)}>Cancel</button>}>
        <p>body</p>
      </Dialog>
    </>
  )
}

describe('Dialog focus return (P-055)', () => {
  it('an unmounted dialog returns focus to the button that opened it, after Cancel or ✕', async () => {
    render(<Unmounting />)
    const opener = screen.getByRole('button', { name: 'Decide' })
    for (const close of ['Cancel', 'Close dialog']) {
      await userEvent.click(opener)
      await userEvent.click(screen.getByRole('button', { name: close }))
      expect(screen.queryByText('body')).toBeNull()
      expect(document.activeElement).toBe(opener)
    }
  })

  it('a dialog closed by its open prop returns focus to the button that opened it', async () => {
    render(<Mounted />)
    const opener = screen.getByRole('button', { name: 'Start a run' })
    await userEvent.click(opener)
    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(screen.queryByText('body')).toBeNull()
    expect(document.activeElement).toBe(opener)
  })
})
