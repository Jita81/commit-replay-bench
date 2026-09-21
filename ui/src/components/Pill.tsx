/**
 * Pill — the base status chip: soft fill, strong ink, a glyph, and a sentence for assistive tech.
 *
 * Navigation
 * ----------
 * What it is:   The `Pill` primitive every status, belt, route and provenance chip is built on.
 * What it does: Renders a tone from ui/src/lib/verdict.ts with its glyph and text, so colour
 *               never travels alone (design law 2 in ui/README.md); when `label` is given the
 *               pill becomes `role="img"` with that full sentence and the visible text is
 *               hidden from the tree, so a screen reader hears "Belt 2 — target green: held"
 *               rather than "B2 target". With `hint` (a registry id) the pill is the hover /
 *               focus / tap trigger for what the state means; the pill carries
 *               `data-component="pill"` so the ratchet can find every one. There is no
 *               native `title`: it was hover-only and duplicated `label`.
 * How:          A `<span>` with `TONE_CLASSES[tone]`; `size` picks the height and type size;
 *               the root is a `<Hint>` when `hint` is given.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/lib/verdict.ts (`Tone`, `TONE_CLASSES` and the display tables that feed
 *               this), ui/src/components/Hint.tsx (the trigger), ui/src/help/hints.ts
 *               (`HintId`), ui/src/components/VerdictPill.tsx, ui/src/components/BeltPills.tsx
 *               and ui/src/components/Provenance.tsx (the specialised pills, each deriving its
 *               own id), ui/src/components/Layout.tsx (the health pill)
 * Tested by:    ui/src/components/Pill.test.tsx (the hint, no `title`),
 *               ui/src/components/VerdictPill.test.tsx, ui/src/components/BeltPills.test.tsx
 *               (tone classes, glyphs and `aria-label` as rendered through this primitive)
 * Touch when:   a tone is added in ui/src/lib/verdict.ts (add the token in ui/src/index.css
 *               too); never for a new repository.
 */
import type { ReactNode } from 'react'
import type { HintId } from '../help/hints'
import { TONE_CLASSES, type Tone } from '../lib/verdict'
import { Hint } from './Hint'

interface PillProps {
  tone: Tone
  glyph?: string
  children: ReactNode
  /** Full sentence for assistive tech; the visible text is aria-hidden when set. */
  label?: string
  /** What this state means — a registry id; the pill becomes the hover / focus / tap trigger. */
  hint?: HintId
  /** `false` keeps a dense, repeated pill out of the tab order (its text still reaches the About block). */
  tabStop?: boolean
  className?: string
  size?: 'xs' | 'sm'
  'data-testid'?: string
}

/**
 * The base status pill: soft fill + strong ink + glyph. 20px radius. Colour is
 * never the only signal — the glyph and text always travel with it.
 */
export function Pill({ tone, glyph, children, label, hint, tabStop, className = '', size = 'sm', ...rest }: PillProps) {
  const sz = size === 'xs' ? 'h-5 px-1.5 text-[10.5px]' : 'h-6 px-2 text-xs'
  const root = {
    role: label ? 'img' : undefined,
    'aria-label': label,
    'data-testid': rest['data-testid'],
    'data-component': 'pill',
    className: `inline-flex items-center gap-1 rounded-[var(--radius-pill)] border font-semibold leading-none whitespace-nowrap ${sz} ${TONE_CLASSES[tone]} ${className}`,
  }
  const inner = (
    <>
      {glyph && (
        <span aria-hidden className="font-mono">
          {glyph}
        </span>
      )}
      <span aria-hidden={label ? true : undefined}>{children}</span>
    </>
  )
  if (hint) {
    return (
      <Hint id={hint} tabStop={tabStop} {...root}>
        {inner}
      </Hint>
    )
  }
  return <span {...root}>{inner}</span>
}
