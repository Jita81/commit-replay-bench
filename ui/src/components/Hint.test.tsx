/**
 * Hint.tsx — hover opens after 150 ms, focus at once, a tap toggles, Escape closes and stays
 * put, the description always resolves, ids never collide, motion is respected.
 *
 * Navigation
 * ----------
 * What it is:   Component tests for the `Hint` primitive.
 * What it does: Pins the trigger contract every hinted element inherits: mouse-over opens at
 *               150 ms and not at 149; the pointer may cross into the bubble and rest there
 *               (leaving the bubble closes); focus of the wrapper or a focusable descendant
 *               opens at once and blur closes; typing in a control inside the trigger
 *               closes it and a pointer over the field does not reopen it until the
 *               control is left; a touch `pointerdown` toggles and a mouse one does not;
 *               Escape closes, does not propagate and is default-prevented (a native
 *               dialog behind it does not cancel); inside a `<dialog>` the bubble is
 *               portalled into the dialog (the top layer), elsewhere into `<body>`; a
 *               control that is itself a hint opens only its own bubble on focus, and a
 *               focus-opened bubble carries `data-trigger="focus"` (no pointer events) until
 *               the pointer arrives on its trigger;
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
import { TextField } from './Field'
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

  it('the bubble is part of the hover region: moving the pointer into it keeps it open; leaving the bubble closes it', () => {
    render(<Hint id={ID}>Baseline</Hint>)
    const trigger = screen.getByText('Baseline')
    const tip = tooltipFor(trigger)
    fireEvent.mouseOver(trigger)
    act(() => vi.advanceTimersByTime(HINT_OPEN_MS))
    expect(tip).toHaveAttribute('data-open', 'true')
    // trigger → bubble: no close is scheduled, and the bubble's own mouse-over cancels any
    fireEvent.mouseOut(trigger, { relatedTarget: tip })
    fireEvent.mouseOver(tip)
    act(() => vi.advanceTimersByTime(HINT_CLOSE_MS + 50))
    expect(tip).toHaveAttribute('data-open', 'true')
    // bubble → trigger: still open
    fireEvent.mouseOut(tip, { relatedTarget: trigger })
    fireEvent.mouseOver(trigger)
    act(() => vi.advanceTimersByTime(HINT_CLOSE_MS + 50))
    expect(tip).toHaveAttribute('data-open', 'true')
    // bubble → elsewhere: closes after the grace period
    fireEvent.mouseOut(trigger, { relatedTarget: tip })
    fireEvent.mouseOut(tip, { relatedTarget: document.body })
    act(() => vi.advanceTimersByTime(HINT_CLOSE_MS))
    expect(tip).toHaveAttribute('data-open', 'false')
    // a pointer-down on the open bubble closes it (it never swallows an action)
    fireEvent.mouseOver(trigger)
    act(() => vi.advanceTimersByTime(HINT_OPEN_MS))
    expect(tip).toHaveAttribute('data-open', 'true')
    pointerDown(tip, 'mouse')
    expect(tip).toHaveAttribute('data-open', 'false')
  })

  it('a control that is itself a hint opens only its own bubble on focus — its nested hints stay closed (no bubble storm on a map cell)', () => {
    const onClick = vi.fn()
    render(
      <Hint as="button" id="map.cell.tile" type="button" onClick={onClick}>
        <Hint id="route.deliver">Deliver</Hint> <Hint id="chart.ci_bar">bar</Hint>
      </Hint>,
    )
    const cell = screen.getByRole('button')
    const inner = screen.getByText('Deliver')
    fireEvent.focus(cell)
    expect(tooltipFor(cell)).toHaveAttribute('data-open', 'true')
    expect(tooltipFor(inner)).toHaveAttribute('data-open', 'false')
    expect(tooltipFor(screen.getByText('bar'))).toHaveAttribute('data-open', 'false')
    // and the click that focused it still lands
    fireEvent.click(cell)
    expect(onClick).toHaveBeenCalledTimes(1)
  })

  it('a bubble opened by focus takes no pointer events (data-trigger=focus) until the pointer arrives on its trigger; a hover-opened one is hoverable', () => {
    render(<Hint id={ID}>Baseline</Hint>)
    const trigger = screen.getByText('Baseline')
    const tip = tooltipFor(trigger)
    fireEvent.focus(trigger)
    expect(tip).toHaveAttribute('data-trigger', 'focus')
    // the pointer moves onto the trigger: from here the bubble is hover content
    fireEvent.mouseOver(trigger)
    expect(tip).toHaveAttribute('data-trigger', 'hover')
    fireEvent.blur(trigger, { relatedTarget: document.body })
    expect(tip).not.toHaveAttribute('data-trigger')
    fireEvent.mouseOver(trigger)
    act(() => vi.advanceTimersByTime(HINT_OPEN_MS))
    expect(tip).toHaveAttribute('data-trigger', 'hover')
  })

  it('inside a <dialog> the bubble is portalled into the dialog, so the top layer cannot paint over it', () => {
    render(
      <dialog open data-testid="dlg">
        <Hint id={ID}>In a dialog</Hint>
      </dialog>,
    )
    const tip = tooltipFor(screen.getByText('In a dialog'))
    expect(tip.parentElement).toBe(screen.getByTestId('dlg'))
    expect(tip.parentElement).not.toBe(document.body)
  })

  it('typing in a control inside the trigger closes the bubble and keeps it closed until the control is left', () => {
    render(<TextField label="Name" hint="field.login.username" />)
    const input = screen.getByLabelText('Name')
    const tip = tooltipFor(input.closest('[data-hint]') as HTMLElement)
    fireEvent.focus(input)
    expect(tip).toHaveAttribute('data-open', 'true')
    fireEvent.input(input, { target: { value: 'a' } })
    expect(tip).toHaveAttribute('data-open', 'false')
    // a pointer over the field while typing does not bring it back over the next field
    fireEvent.mouseOver(input)
    act(() => vi.advanceTimersByTime(HINT_OPEN_MS + 10))
    expect(tip).toHaveAttribute('data-open', 'false')
    // leaving and coming back explains again
    fireEvent.blur(input, { relatedTarget: document.body })
    fireEvent.focus(input)
    expect(tip).toHaveAttribute('data-open', 'true')
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
    // a native <dialog> cancels on an Escape keydown unless it is default-prevented: while
    // a bubble is open the press is consumed; while closed it reaches the dialog
    fireEvent.focus(trigger)
    const consumed = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true })
    act(() => {
      trigger.dispatchEvent(consumed)
    })
    expect(consumed.defaultPrevented).toBe(true)
    expect(tip).toHaveAttribute('data-open', 'false')
    const passed = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true })
    act(() => {
      trigger.dispatchEvent(passed)
    })
    expect(passed.defaultPrevented).toBe(false)
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
