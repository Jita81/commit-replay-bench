import type { ReactNode } from 'react'
import { TONE_CLASSES, type Tone } from '../lib/verdict'

interface PillProps {
  tone: Tone
  glyph?: string
  children: ReactNode
  /** Full sentence for assistive tech; the visible text is aria-hidden when set. */
  label?: string
  title?: string
  className?: string
  size?: 'xs' | 'sm'
  'data-testid'?: string
}

/**
 * The base status pill: soft fill + strong ink + glyph. 20px radius. Colour is
 * never the only signal — the glyph and text always travel with it.
 */
export function Pill({ tone, glyph, children, label, title, className = '', size = 'sm', ...rest }: PillProps) {
  const sz = size === 'xs' ? 'h-5 px-1.5 text-[10.5px]' : 'h-6 px-2 text-xs'
  return (
    <span
      role={label ? 'img' : undefined}
      aria-label={label}
      title={title ?? label}
      data-testid={rest['data-testid']}
      className={`inline-flex items-center gap-1 rounded-[var(--radius-pill)] border font-semibold leading-none whitespace-nowrap ${sz} ${TONE_CLASSES[tone]} ${className}`}
    >
      {glyph && (
        <span aria-hidden className="font-mono">
          {glyph}
        </span>
      )}
      <span aria-hidden={label ? true : undefined}>{children}</span>
    </span>
  )
}
