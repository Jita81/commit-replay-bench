/**
 * ShortId — the eye sees the first characters; the accessible name is the whole value.
 *
 * Navigation
 * ----------
 * What it is:   The contract test for ui/src/components/ShortId.tsx.
 * What it does: Pins that nothing is lost when a native `title=` is retired: the element's
 *               text is the full id, the visible part is exactly `shortId`'s prefix, the
 *               remainder is `sr-only`, a short value renders whole with no hidden span, a
 *               missing value renders the em dash, and inside a link the accessible name is
 *               the full value (so a keyboard or screen-reader user reads what only a mouse
 *               hover used to give them).
 * How:          `render` from Testing Library; `toHaveAccessibleName` for the link case.
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/components/ShortId.tsx (the component), ui/src/lib/format.ts
 *               (`shortId`, `DASH`), ui/src/help/hints-ratchet.test.tsx (the
 *               `TITLE_ALLOWLIST` this component let shrink)
 * Tested by:    ui/src/components/ShortId.test.tsx
 * Touch when:   the shortening rule or the hidden-remainder mechanism changes.
 */
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Link } from 'react-router'
import { describe, expect, it } from 'vitest'
import { ShortId } from './ShortId'

const HASH = 'a1b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f90'

describe('ShortId', () => {
  it('shows the first n characters and keeps the rest in the accessible text', () => {
    const { container } = render(<ShortId value={HASH} n={10} />)
    const root = container.firstElementChild!
    expect(root.textContent).toBe(HASH)
    expect(root.querySelector('.sr-only')?.textContent).toBe(HASH.slice(10))
    expect(root.firstChild?.textContent).toBe(HASH.slice(0, 10))
    // and no browser tooltip: the full value is text, not a hover-only attribute
    expect(container.querySelectorAll('[title]').length).toBe(0)
  })

  it('a value no longer than n renders whole, with nothing hidden', () => {
    const { container } = render(<ShortId value="abc" n={10} />)
    expect(container.firstElementChild!.textContent).toBe('abc')
    expect(container.querySelector('.sr-only')).toBeNull()
  })

  it('a missing value renders the em dash', () => {
    const { container } = render(<ShortId value={null} />)
    expect(container.firstElementChild!.textContent).toBe('—')
  })

  it('inside a link a screen reader reads the whole value, not the shortened one', () => {
    render(
      <MemoryRouter>
        <Link to="/x">
          <ShortId value={HASH} />
        </Link>
      </MemoryRouter>,
    )
    // the accessible name is built from the two spans, so the name-from-content algorithm
    // puts one space at the element boundary; every character of the value is in it
    const name = screen.getByRole('link').textContent
    expect(name).toBe(HASH)
    expect(screen.getByRole('link')).toHaveAccessibleName(`${HASH.slice(0, 10)} ${HASH.slice(10)}`)
  })
})
