/**
 * Button.tsx — a pending button keeps focus and ignores presses (P-396).
 *
 * Navigation
 * ----------
 * What it is:   Component tests for the `Button` primitive's `pending` state.
 * What it does: Pins that a button marked `pending` stays the focused element (a `disabled`
 *               one drops focus to <body>, and a keyboard user loses their place after every
 *               submit), reads as unavailable (`aria-disabled`, `aria-busy`), and that a
 *               press — a click, or Enter in the form's field — neither calls its handler nor
 *               submits its form; and that the same button, no longer pending, submits.
 * How:          Testing Library render with a real `<form>`, focus read from
 *               `document.activeElement`, `userEvent` for the keyboard.
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/components/Button.tsx (the code under test),
 *               ui/src/screens/Settings/InviteApproverCard.tsx (a form that uses it),
 *               ui/src/screens/Invite/AcceptInvitePage.tsx (a form that uses it),
 *               docs/PREVENTION.md (P-396, the class it closes)
 * Tested by:    ui/src/components/Button.test.tsx
 * Touch when:   never for a new repository; the pending contract changes.
 */
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { Button } from './Button'

function Form({ pending, onSubmit }: { pending: boolean; onSubmit: () => void }) {
  const [v, setV] = useState('')
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault()
        onSubmit()
      }}
    >
      <label>
        Name <input value={v} onChange={(e) => setV(e.target.value)} />
      </label>
      <Button type="submit" variant="filled" hint="button.invitations.invite" pending={pending}>
        {pending ? 'Inviting…' : 'Invite'}
      </Button>
    </form>
  )
}

describe('Button pending', () => {
  it('keeps focus, reads as busy, and a press neither acts nor submits', async () => {
    const submitted = vi.fn()
    const { rerender } = render(<Form pending={false} onSubmit={submitted} />)
    const button = screen.getByRole('button', { name: 'Invite' })
    button.focus()
    rerender(<Form pending onSubmit={submitted} />)
    const busy = screen.getByRole('button', { name: 'Inviting…' })
    expect(document.activeElement).toBe(busy)
    expect(busy).not.toBeDisabled()
    expect(busy).toHaveAttribute('aria-disabled', 'true')
    expect(busy).toHaveAttribute('aria-busy', 'true')
    await userEvent.click(busy)
    await userEvent.type(screen.getByLabelText('Name'), 'x{Enter}')
    expect(submitted).not.toHaveBeenCalled()
    rerender(<Form pending={false} onSubmit={submitted} />)
    await userEvent.click(screen.getByRole('button', { name: 'Invite' }))
    expect(submitted).toHaveBeenCalledTimes(1)
  })

  it('a plain button that is pending never calls its handler', async () => {
    const onClick = vi.fn()
    render(
      <Button pending onClick={onClick}>
        Withdraw
      </Button>,
    )
    await userEvent.click(screen.getByRole('button', { name: 'Withdraw' }))
    expect(onClick).not.toHaveBeenCalled()
  })
})
