/**
 * Hint.tsx — hover opens after 150 ms, focus at once, a tap toggles, Escape closes and stays
 * put, the description always resolves, ids never collide, motion is respected.
 *
 * Navigation
 * ----------
 * What it is:   Component tests for the `Hint` primitive.
 * What it does: Pins the trigger contract every hinted element inherits: mouse-over opens at
 *               150 ms and not at 149; focus of the wrapper or a focusable descendant opens
 *               at once and blur closes; a touch `pointerdown` toggles and a mouse one does
 *               not; Escape closes and does not propagate (a dialog behind it stays open);
 *               the trigger's `aria-describedby` resolves to a `role="tooltip"` whose text is
 *               the registry sentence while closed; two hints of the same id render two
 *               distinct bubble ids; a hint on a button lets its click through; a hint on a
 *               `Term` lets the term toggle; a nested hint opens only the innermost; under
 *               prefers-reduced-motion the bubble has no fade; opening emits the `crb:help`
 *               telemetry event once per open.
 * How:          Testing Library render + `fireEvent` with fake timers for the delays;
 *               `matchMedia` stubbed for the motion case.
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/components/Hint.tsx (the code under test), ui/src/help/hints.ts (the
 *               copy asserted), ui/src/components/Help.tsx (`Term`, wrapped in one case),
 *               ui/src/index.css (the `.hint-bubble` rule the inline style mirrors)
 * Tested by:    ui/src/components/Hint.test.tsx
 * Touch when:   the trigger contract changes (a delay, a new trigger) — pin it here first.
 */
import { act, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { HINTS } from '../help/hints'
import { Button } from './Button'
import { Term } from './Help'
import { HINT_CLOSE_MS, HINT_OPEN_MS, Hint } from './Hint'

const ID = 'nav.baseline'
const TEXT = HINTS[ID]

/** jsdom has no PointerEvent: a `pointerdown` whose `pointerType` React can read. */
function pointerDown(el: Element, pointerType: 'touch' | 'mouse'): void {
  const ev = new MouseEvent('pointerdown', { bubbles: true, cancelable: true })
  Object.defineProperty(ev, 'pointerType', { value: pointerType })
  fireEvent(el, ev)
}

function tooltipFor(trigger: HTMLElement): HTMLElement {
  const ids = (trigger.getAttribute('aria-describedby') ?? '').split(' ')
  const tip = ids.map((i) => document.getElementById(i)).find((el) => el?.getAttribute('role') === 'tooltip')
  if (!tip) throw new Error('no tooltip referenced from aria-describedby')
  return tip
}

describe('Hint', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => vi.useRealTimers())

  it('the trigger carries data-hint and aria-describedby that resolves, while closed, to a role=tooltip with the registry text', () => {
    render(<Hint id={ID}>Baseline</Hint>)
    const trigger = screen.getByText('Baseline')
    expect(trigger).toHaveAttribute('data-hint', ID)
    const tip = tooltipFor(trigger)
    expect(tip).toHaveAttribute('role', 'tooltip')
    expect(tip).toHaveAttribute('data-open', 'false')
    expect(tip.textContent).toBe(TEXT)
    expect(tip.parentElement).toBe(document.body)
    expect(trigger).toHaveAccessibleDescription(TEXT)
    // no link may live in a tooltip
    expect(tip.querySelector('a')).toBeNull()
  })

  it('mouse-over opens after 150 ms and not at 149; leaving closes after the grace period', () => {
    render(<Hint id={ID}>Baseline</Hint>)
    const trigger = screen.getByText('Baseline')
    const tip = tooltipFor(trigger)
    fireEvent.mouseOver(trigger)
    act(() => vi.advanceTimersByTime(HINT_OPEN_MS - 1))
    expect(tip).toHaveAttribute('data-open', 'false')
    act(() => vi.advanceTimersByTime(1))
    expect(tip).toHaveAttribute('data-open', 'true')
    expect(trigger).toHaveAttribute('data-open', 'true')
    fireEvent.mouseOut(trigger, { relatedTarget: document.body })
    expect(tip).toHaveAttribute('data-open', 'true')
    act(() => vi.advanceTimersByTime(HINT_CLOSE_MS))
    expect(tip).toHaveAttribute('data-open', 'false')
  })

  it('a wrapper with no focusable child is the tab stop; focus opens at once and blur closes', () => {
    render(<Hint id={ID}>Baseline</Hint>)
    const trigger = screen.getByText('Baseline')
    expect(trigger).toHaveAttribute('tabindex', '0')
    const tip = tooltipFor(trigger)
    fireEvent.focus(trigger)
    expect(tip).toHaveAttribute('data-open', 'true')
    fireEvent.blur(trigger, { relatedTarget: document.body })
    expect(tip).toHaveAttribute('data-open', 'false')
  })

  it('a wrapper with a focusable child is not a tab stop; focusing the child opens the hint', () => {
    render(
      <Hint id={ID}>
        <button type="button">Go</button>
      </Hint>,
    )
    const btn = screen.getByRole('button', { name: 'Go' })
    const trigger = btn.parentElement!
    expect(trigger).not.toHaveAttribute('tabindex')
    const tip = tooltipFor(trigger)
    fireEvent.focus(btn)
    expect(tip).toHaveAttribute('data-open', 'true')
  })

  it('an element inside a link is not a tab stop of its own (nested-interactive); the link’s focus opens it', () => {
    render(
      <MemoryRouter>
        <a href="/x">
          Task <Hint id="task.home.connect_github">Completed</Hint>
        </a>
      </MemoryRouter>,
    )
    const tag = screen.getByText('Completed')
    expect(tag).not.toHaveAttribute('tabindex')
    const tip = tooltipFor(tag)
    const link = screen.getByRole('link')
    fireEvent.focus(link)
    expect(tip).toHaveAttribute('data-open', 'true')
    fireEvent.blur(link)
    expect(tip).toHaveAttribute('data-open', 'false')
  })

  it('tabStop={false} keeps a dense repeated element out of the tab order but keeps its description', () => {
    render(
      <Hint id={ID} tabStop={false}>
        x
      </Hint>,
    )
    const trigger = screen.getByText('x')
    expect(trigger).not.toHaveAttribute('tabindex')
    expect(trigger).toHaveAccessibleDescription(TEXT)
  })

  it('a touch pointerdown toggles; a mouse pointerdown does not open', () => {
    render(<Hint id={ID}>Baseline</Hint>)
    const trigger = screen.getByText('Baseline')
    const tip = tooltipFor(trigger)
    pointerDown(trigger, 'mouse')
    expect(tip).toHaveAttribute('data-open', 'false')
    pointerDown(trigger, 'touch')
    expect(tip).toHaveAttribute('data-open', 'true')
    // it stays put: no hover grace period applies to a tapped bubble
    fireEvent.mouseOut(trigger, { relatedTarget: document.body })
    act(() => vi.advanceTimersByTime(HINT_CLOSE_MS + 10))
    expect(tip).toHaveAttribute('data-open', 'true')
    pointerDown(trigger, 'touch')
    expect(tip).toHaveAttribute('data-open', 'false')
  })

  it('a tap outside closes a tapped bubble', () => {
    render(
      <div>
        <Hint id={ID}>Baseline</Hint>
        <p>elsewhere</p>
      </div>,
    )
    const trigger = screen.getByText('Baseline')
    const tip = tooltipFor(trigger)
    pointerDown(trigger, 'touch')
    expect(tip).toHaveAttribute('data-open', 'true')
    pointerDown(screen.getByText('elsewhere'), 'touch')
    expect(tip).toHaveAttribute('data-open', 'false')
  })

  it('Escape closes and does not propagate to a dialog behind it; Escape while closed propagates', () => {
    const outer = vi.fn()
    render(
      <div onKeyDown={outer}>
        <Hint id={ID}>Baseline</Hint>
      </div>,
    )
    const trigger = screen.getByText('Baseline')
    const tip = tooltipFor(trigger)
    fireEvent.focus(trigger)
    expect(tip).toHaveAttribute('data-open', 'true')
    fireEvent.keyDown(trigger, { key: 'Escape' })
    expect(tip).toHaveAttribute('data-open', 'false')
    expect(outer).not.toHaveBeenCalled()
    fireEvent.keyDown(trigger, { key: 'Escape' })
    expect(outer).toHaveBeenCalledTimes(1)
    // a hovered bubble has no focus inside it: Escape pressed anywhere still closes it
    fireEvent.mouseOver(trigger)
    act(() => vi.advanceTimersByTime(HINT_OPEN_MS))
    expect(tip).toHaveAttribute('data-open', 'true')
    fireEvent.keyDown(document.body, { key: 'Escape' })
    expect(tip).toHaveAttribute('data-open', 'false')
  })

  it('two hints of the same id render two distinct bubble ids — no duplicate id in the document', () => {
    render(
      <>
        <Hint id={ID}>one</Hint>
        <Hint id={ID}>two</Hint>
      </>,
    )
    const ids = Array.from(document.querySelectorAll('[id]')).map((el) => el.id)
    expect(new Set(ids).size).toBe(ids.length)
    expect(document.querySelectorAll('[role="tooltip"]').length).toBe(2)
  })

  it('a hint on a Button lets the click through and opens on focus', () => {
    const onClick = vi.fn()
    render(
      <Button variant="filled" hint="button.home.continue" onClick={onClick}>
        Continue
      </Button>,
    )
    const btn = screen.getByRole('button', { name: 'Continue' })
    expect(btn).toHaveAttribute('data-hint', 'button.home.continue')
    expect(btn).toHaveAttribute('data-primary')
    pointerDown(btn, 'touch')
    fireEvent.click(btn)
    expect(onClick).toHaveBeenCalledTimes(1)
    expect(tooltipFor(btn)).toHaveAttribute('data-open', 'true')
  })

  it('a hint wrapping a Term lets the term toggle its definition', () => {
    render(
      <MemoryRouter>
        <Hint id={ID}>
          <Term id="deliver" />
        </Hint>
      </MemoryRouter>,
    )
    const term = screen.getByRole('button', { name: /deliver/ })
    fireEvent.click(term)
    expect(screen.getByRole('note')).toBeInTheDocument()
  })

  it('a nested hint opens only the innermost', () => {
    render(
      <Hint id="nav.decisions">
        Decisions <Hint id="nav.decisions_count">3</Hint>
      </Hint>,
    )
    const inner = screen.getByText('3')
    const outer = inner.parentElement!
    fireEvent.mouseOver(inner)
    act(() => vi.advanceTimersByTime(HINT_OPEN_MS))
    expect(tooltipFor(inner)).toHaveAttribute('data-open', 'true')
    expect(tooltipFor(outer)).toHaveAttribute('data-open', 'false')
  })

  it('the caller’s own aria-describedby is kept alongside the bubble', () => {
    render(
      <>
        <p id="desc">a description</p>
        <Hint id={ID} aria-describedby="desc">
          Baseline
        </Hint>
      </>,
    )
    const trigger = screen.getByText('Baseline')
    expect(trigger.getAttribute('aria-describedby')!.split(' ')[0]).toBe('desc')
    expect(trigger).toHaveAccessibleDescription(`a description ${TEXT}`)
  })

  it('emits one crb:help event per open, with the id and the trigger', () => {
    const seen: unknown[] = []
    const listener = (e: Event) => seen.push((e as CustomEvent).detail)
    document.addEventListener('crb:help', listener)
    render(<Hint id={ID}>Baseline</Hint>)
    const trigger = screen.getByText('Baseline')
    fireEvent.focus(trigger)
    fireEvent.focus(trigger)
    fireEvent.blur(trigger, { relatedTarget: document.body })
    pointerDown(trigger, 'touch')
    document.removeEventListener('crb:help', listener)
    expect(seen).toEqual([
      { event: 'help.hint_open', id: ID, trigger: 'focus' },
      { event: 'help.hint_open', id: ID, trigger: 'tap' },
    ])
  })

  it('prefers-reduced-motion: the bubble gets no fade (inline, so no cascade can restore it); otherwise the stylesheet’s transition stands', () => {
    const original = window.matchMedia
    vi.stubGlobal('matchMedia', (q: string) => ({ matches: q.includes('reduce'), media: q, onchange: null, addListener: vi.fn(), removeListener: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn(), dispatchEvent: vi.fn() }))
    const first = render(<Hint id={ID}>Reduced</Hint>)
    expect(tooltipFor(screen.getByText('Reduced')).style.transition).toBe('none')
    first.unmount()
    vi.stubGlobal('matchMedia', (q: string) => ({ matches: false, media: q, onchange: null, addListener: vi.fn(), removeListener: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn(), dispatchEvent: vi.fn() }))
    render(<Hint id={ID}>Animated</Hint>)
    expect(tooltipFor(screen.getByText('Animated')).style.transition).toBe('')
    vi.unstubAllGlobals()
    if (original) window.matchMedia = original
  })
})
