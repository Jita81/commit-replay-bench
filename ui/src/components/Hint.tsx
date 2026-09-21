/**
 * Hint — the one hover / focus / tap explanation for an element: what THIS thing on THIS
 * screen shows and what its value means, from the hint registry.
 *
 * Navigation
 * ----------
 * What it is:   `<Hint id="stat.results.false_q1">…</Hint>`, the trigger wrapper every hinted
 *               element renders through, and its `role="tooltip"` bubble.
 * What it does: Makes its element a trigger (`data-hint="<id>"`) whose bubble opens on
 *               mouse-over after 150 ms (closes 100 ms after leave, so the pointer can cross
 *               into it), on keyboard focus of the element or any focusable descendant at
 *               once, and on a touch tap (toggles; stays until a tap outside, Escape or a
 *               scroll). Escape closes from anywhere on the page (a hovered bubble has no
 *               focus inside it) and stops propagating so a dialog behind it does not also
 *               close. The bubble is ALWAYS in the DOM (hidden by `visibility`, never
 *               `display: none`) and portalled to `<body>` so `aria-describedby` on the
 *               trigger resolves whether or not it is visible and no scrolling table or
 *               sticky header can clip it. It never contains a link and never swallows a
 *               click: a hint on a button opens AND lets the click through. A hint adds a
 *               description; it never replaces the element's own name or `aria-label`. When
 *               the element has no focusable descendant the wrapper is the tab stop
 *               (`tabIndex=0`, decided at mount) so a sighted keyboard reader reaches every
 *               hint; `tabStop={false}` opts a dense repeated pill out; an element inside a
 *               link or button is never a tab stop of its own (nested-interactive) — the
 *               control's focus opens it. A hint nested in a hint (the Decisions badge
 *               inside its nav link) opens only the innermost.
 * How:          `useId` for the bubble id (or the caller's `bubbleId`, so a field can add it
 *               to its input's `aria-describedby`); position from `getBoundingClientRect` on
 *               open — below the trigger, flipped above when fewer than 120 px remain, clamped
 *               to a 16 px gutter; `createPortal` for the bubble; `matchMedia` for reduced
 *               motion (no fade, inline as well as in the stylesheet); a `crb:help`
 *               CustomEvent on `document` (`{event: 'help.hint_open', id, trigger}`) for
 *               telemetry.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/help/hints.ts (`HINTS`, `HintId`, `hintText` — the copy),
 *               ui/src/index.css (`.hint-bubble` — tokens for both themes, reduced motion),
 *               ui/src/components/StatTile.tsx, ui/src/components/Pill.tsx,
 *               ui/src/components/DataTable.tsx, ui/src/components/Button.tsx,
 *               ui/src/components/Field.tsx (the shared components that render through this),
 *               ui/src/components/Help.tsx (the About block lists every `data-hint` on the
 *               screen from the same registry), ui/src/components/Layout.tsx (the shell's
 *               nav and chrome hints)
 * Tested by:    ui/src/components/Hint.test.tsx (hover / focus / tap / Escape, the
 *               description resolves, no duplicate ids, reduced motion),
 *               ui/src/help/hints-ratchet.test.tsx (every element carries one),
 *               ui/e2e/walkthrough/11-screens.spec.ts (opens on the live stack; axe clean
 *               with a bubble open)
 * Touch when:   the trigger contract changes (add the case to Hint.test.tsx first); never for
 *               a new repository.
 */
import {
  useCallback,
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type ElementType,
  type FocusEvent,
  type MouseEvent,
  type PointerEvent,
  type ReactNode,
} from 'react'
import { createPortal } from 'react-dom'
import { hintText, type HintId } from '../help/hints'

/** Where a hint opened from — the telemetry dimension. */
export type HintTrigger = 'hover' | 'focus' | 'tap'

/** How long the pointer rests before the bubble opens, and how long it may leave before it closes. */
export const HINT_OPEN_MS = 150
export const HINT_CLOSE_MS = 100

const FOCUSABLE = 'a[href],button,input,select,textarea,[tabindex]'

interface HintProps {
  /** The registry id; a typo is a compile error. */
  id: HintId
  children?: ReactNode
  /** The element the wrapper renders as (`span` by default; `div` for a tile, a component such as `NavLink`). */
  as?: ElementType
  /** A class string, or the render-prop form a `NavLink` takes. */
  className?: string | ((arg: never) => string)
  /** The wrapper's own DOM `id` (the `id` prop is the hint's). */
  elementId?: string
  /** The bubble's DOM id, when the caller must reference it (a field adds it to its input's `aria-describedby`). */
  bubbleId?: string
  /** `false` opts a dense, repeated element out of being a tab stop; its text still reaches the About block and assistive technology. */
  tabStop?: boolean
  /** Anything else lands on the wrapper (`data-testid`, `role`, `aria-label`, handlers, `to`…). */
  [prop: string]: unknown
}

/** The innermost hinted element under an event's target — a nested hint opens only itself. */
function ownsEvent(wrapper: HTMLElement | null, target: EventTarget | null): boolean {
  if (!wrapper) return false
  const el = target instanceof Element ? target : null
  const inner = el?.closest('[data-hint]')
  return inner === wrapper || (inner === null && el === wrapper)
}

/**
 * The trigger wrapper and its bubble. Every wrapped element gets `data-hint="<id>"` and
 * `aria-describedby` pointing at a bubble that is always rendered.
 */
export function Hint({ id, children, as: Tag = 'span', className = '', elementId, bubbleId, tabStop = true, ...rest }: HintProps) {
  const autoId = useId()
  const tipId = bubbleId ?? `hint-${autoId}`
  const ref = useRef<HTMLElement | null>(null)
  const [open, setOpen] = useState(false)
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null)
  const [tabbable, setTabbable] = useState(false)
  const openTimer = useRef<number | null>(null)
  const closeTimer = useRef<number | null>(null)
  const tapped = useRef(false)
  const text = hintText(id)

  const clearTimers = useCallback(() => {
    if (openTimer.current !== null) window.clearTimeout(openTimer.current)
    if (closeTimer.current !== null) window.clearTimeout(closeTimer.current)
    openTimer.current = null
    closeTimer.current = null
  }, [])

  const bubbleRef = useRef<HTMLSpanElement | null>(null)

  // below the trigger by default, above when fewer than 120 px remain, clamped to a 16 px
  // gutter — measured from the rendered bubble, so it is right at phone width too
  useLayoutEffect(() => {
    const el = ref.current
    const tip = bubbleRef.current
    if (!open || !el || !tip) return
    const r = el.getBoundingClientRect()
    const gutter = 16
    const vw = window.innerWidth || 1024
    const vh = window.innerHeight || 768
    const width = tip.offsetWidth || Math.min(vw - gutter * 2, 36 * 8)
    const height = tip.offsetHeight || 40
    const below = vh - r.bottom >= 120
    const top = below ? r.bottom + 6 : Math.max(gutter, r.top - 6 - height)
    const left = Math.max(gutter, Math.min(r.left, vw - gutter - width))
    setPos({ top, left })
  }, [open])

  const openRef = useRef(false)
  const show = useCallback(
    (trigger: HintTrigger) => {
      clearTimers()
      if (!openRef.current) document.dispatchEvent(new CustomEvent('crb:help', { detail: { event: 'help.hint_open', id, trigger } }))
      openRef.current = true
      setOpen(true)
    },
    [id, clearTimers],
  )
  const hide = useCallback(() => {
    clearTimers()
    tapped.current = false
    openRef.current = false
    setOpen(false)
  }, [clearTimers])

  // decided at mount: the wrapper is a tab stop only when nothing inside it is one and it does
  // not sit inside a control (a status tag inside a task-list link: a focusable descendant of a
  // link is a nested-interactive defect, so the link's own focus opens the hint instead)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const host = el.parentElement?.closest<HTMLElement>('a[href],button,[role="button"],[role="link"]') ?? null
    setTabbable(tabStop && host === null && !el.matches(FOCUSABLE) && el.querySelector(FOCUSABLE) === null)
    if (!host) return
    const onHostFocus = () => show('focus')
    const onHostBlur = () => hide()
    host.addEventListener('focus', onHostFocus)
    host.addEventListener('blur', onHostBlur)
    return () => {
      host.removeEventListener('focus', onHostFocus)
      host.removeEventListener('blur', onHostBlur)
    }
  }, [tabStop, show, hide])

  // a tapped bubble stays until a tap outside, Escape or a scroll; a hovered one closes on scroll too
  useEffect(() => {
    if (!open) return
    const onDown = (e: Event) => {
      if (ref.current && e.target instanceof Node && ref.current.contains(e.target)) return
      hide()
    }
    const onScroll = () => hide()
    // Escape closes from anywhere (a hovered bubble has no focus inside it) and goes no
    // further: a dialog or drawer behind the bubble stays open
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return
      e.stopPropagation()
      hide()
    }
    document.addEventListener('pointerdown', onDown, true)
    document.addEventListener('keydown', onKey, true)
    window.addEventListener('scroll', onScroll, true)
    window.addEventListener('resize', onScroll)
    return () => {
      document.removeEventListener('pointerdown', onDown, true)
      document.removeEventListener('keydown', onKey, true)
      window.removeEventListener('scroll', onScroll, true)
      window.removeEventListener('resize', onScroll)
    }
  }, [open, hide])

  useEffect(() => () => clearTimers(), [clearTimers])

  const onMouseOver = (e: MouseEvent) => {
    if (!ownsEvent(ref.current, e.target)) return
    if (open || openTimer.current !== null) {
      if (closeTimer.current !== null) window.clearTimeout(closeTimer.current)
      closeTimer.current = null
      return
    }
    openTimer.current = window.setTimeout(() => {
      openTimer.current = null
      show('hover')
    }, HINT_OPEN_MS)
  }
  const onMouseOut = (e: MouseEvent) => {
    const to = e.relatedTarget
    if (to instanceof Node && ref.current?.contains(to)) return
    if (openTimer.current !== null) window.clearTimeout(openTimer.current)
    openTimer.current = null
    if (open && !tapped.current) {
      if (closeTimer.current !== null) window.clearTimeout(closeTimer.current)
      closeTimer.current = window.setTimeout(() => {
        closeTimer.current = null
        openRef.current = false
        setOpen(false)
      }, HINT_CLOSE_MS)
    }
  }
  const onFocus = (e: FocusEvent) => {
    if (!ownsEvent(ref.current, e.target)) return
    show('focus')
  }
  const onBlur = (e: FocusEvent) => {
    const to = e.relatedTarget
    if (to instanceof Node && ref.current?.contains(to)) return
    hide()
  }
  const onPointerDown = (e: PointerEvent) => {
    if (e.pointerType !== 'touch' || !ownsEvent(ref.current, e.target)) return
    if (open && tapped.current) {
      hide()
      return
    }
    tapped.current = true
    show('tap')
  }

  // reduced motion is honoured in the stylesheet and, so it can never be lost to a cascade, inline
  const reduced = typeof window !== 'undefined' && typeof window.matchMedia === 'function' && window.matchMedia('(prefers-reduced-motion: reduce)').matches
  const bubble = (
    <span
      ref={bubbleRef}
      id={tipId}
      role="tooltip"
      className="hint-bubble"
      data-open={open ? 'true' : 'false'}
      style={{ ...(pos ? { top: pos.top, left: pos.left } : {}), ...(reduced ? { transition: 'none' } : {}) }}
    >
      {text}
    </span>
  )

  // the caller's own handlers run first; a hint never swallows an action
  const chain =
    <E,>(theirs: unknown, mine: (e: E) => void) =>
    (e: E) => {
      if (typeof theirs === 'function') (theirs as (e: E) => void)(e)
      mine(e)
    }
  const theirDescribedBy = typeof rest['aria-describedby'] === 'string' ? (rest['aria-describedby'] as string) : ''

  return (
    <>
      <Tag
        {...rest}
        ref={ref}
        id={elementId}
        className={className || undefined}
        data-hint={id}
        data-open={open ? 'true' : undefined}
        aria-describedby={theirDescribedBy ? `${theirDescribedBy} ${tipId}` : tipId}
        tabIndex={tabbable ? 0 : (rest.tabIndex as number | undefined)}
        onMouseOver={chain(rest.onMouseOver, onMouseOver)}
        onMouseOut={chain(rest.onMouseOut, onMouseOut)}
        onFocus={chain(rest.onFocus, onFocus)}
        onBlur={chain(rest.onBlur, onBlur)}
        onPointerDown={chain(rest.onPointerDown, onPointerDown)}
      >
        {children}
      </Tag>
      {typeof document !== 'undefined' && createPortal(bubble, document.body)}
    </>
  )
}
