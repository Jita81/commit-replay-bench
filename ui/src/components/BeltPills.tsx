import { BELT_NAMES, type Belts } from '../api/types'
import { BELT_LABELS, beltDisplay } from '../lib/verdict'
import { Pill } from './Pill'

interface BeltPillsProps {
  belts: Belts
  /** Show the belt name next to the glyph (default true; false = glyph-only, name in aria). */
  showNames?: boolean
  size?: 'xs' | 'sm'
}

/**
 * The four belts, each ✓ / ✗ / — (None = not recorded, e.g. a legacy v3 row
 * has no belt 4). Each pill carries the belt's full name for assistive tech.
 */
export function BeltPills({ belts, showNames = true, size = 'xs' }: BeltPillsProps) {
  return (
    <ul className={`m-0 flex list-none gap-1 p-0 ${showNames ? 'flex-wrap' : 'flex-nowrap'}`} aria-label="Four belts">
      {BELT_NAMES.map((name) => {
        const value = belts[name]
        const d = beltDisplay(value)
        const labels = BELT_LABELS[name] ?? { short: name, long: name }
        return (
          <li key={name}>
            <Pill
              tone={d.tone}
              glyph={d.glyph}
              size={size}
              label={`${labels.long}: ${d.describe}`}
              data-testid={`belt-${name}`}
            >
              {showNames ? labels.short : d.label}
            </Pill>
          </li>
        )
      })}
    </ul>
  )
}
