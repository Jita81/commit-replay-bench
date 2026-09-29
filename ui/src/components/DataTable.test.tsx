/**
 * DataTable — a clickable row, and the controls inside it, each keep their own keys.
 *
 * Navigation
 * ----------
 * What it is:   Tests for the keyboard contract of `DataTable`'s clickable rows.
 * What it does: Pins that Enter or Space on a focused clickable row opens the row, and that a
 *               key pressed on a link or button INSIDE a clickable row is that control's own:
 *               the row neither cancels it (a link that no longer follows) nor answers it with
 *               its own target (the row's pack opened instead of the trial chosen) — P-614,
 *               for every table that has clickable rows, not one screen.
 * How:          A bare `DataTable` with an `onRowClick` spy and one row holding a button and
 *               an anchor; `userEvent.keyboard` on each focused element.
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/components/DataTable.tsx (under test),
 *               ui/src/screens/Runs/RunDetailPage.tsx (the task link and trial buttons that
 *               first showed the fault), ui/src/screens/Runs/RunDetailPage.test.tsx (the same
 *               contract through the run page's own rows)
 * Tested by:    ui/src/components/DataTable.test.tsx
 * Touch when:   never for a new repository; the row's keyboard contract changes.
 */
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { DataTable } from './DataTable'

interface Row {
  id: string
}

function table(onRowClick: (r: Row) => void, onButton: () => void, onLink: (e: { defaultPrevented: boolean }) => void) {
  return render(
    <DataTable<Row>
      rows={[{ id: 'one' }]}
      rowKey={(r) => r.id}
      caption="rows"
      empty={<p>no rows</p>}
      onRowClick={onRowClick}
      columns={[
        { key: 'id', header: '', cell: (r) => r.id },
        {
          key: 'act',
          header: '',
          cell: () => (
            <>
              <button type="button" onClick={(e) => { e.stopPropagation(); onButton() }}>
                trial
              </button>
              <a
                href="#elsewhere"
                onClick={(e) => {
                  e.stopPropagation()
                  onLink({ defaultPrevented: e.defaultPrevented })
                  e.preventDefault() // jsdom does not navigate; what matters is who prevented it first
                }}
              >
                task
              </a>
            </>
          ),
        },
      ]}
    />,
  )
}

describe('DataTable clickable rows', () => {
  it('Enter and Space on the focused row open it', async () => {
    const open = vi.fn()
    table(open, vi.fn(), vi.fn())
    const row = screen.getByText('one').closest('tr')!
    row.focus()
    await userEvent.keyboard('{Enter}')
    await userEvent.keyboard(' ')
    expect(open).toHaveBeenCalledTimes(2)
  })

  it('a key pressed on a button or link inside the row is that control’s own (P-614)', async () => {
    const open = vi.fn()
    const button = vi.fn()
    const link = vi.fn()
    table(open, button, link)
    screen.getByRole('button', { name: 'trial' }).focus()
    await userEvent.keyboard('{Enter}')
    expect(button).toHaveBeenCalledTimes(1)
    screen.getByRole('link', { name: 'task' }).focus()
    await userEvent.keyboard('{Enter}')
    expect(link).toHaveBeenCalledWith({ defaultPrevented: false })
    expect(open).not.toHaveBeenCalled()
  })
})
