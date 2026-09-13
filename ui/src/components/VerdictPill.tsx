import type { CellVerdict } from '../api/types'
import { routeDisplay } from '../lib/verdict'
import { Pill } from './Pill'

interface VerdictPillProps {
  route: CellVerdict | string | null | undefined
  size?: 'xs' | 'sm'
  /** Extra context for the accessible label (e.g. the reason). */
  reason?: string
}

/**
 * deliver = green ✓, calibrate = primary ◐, granularize = blue ⋮, human =
 * amber ☺, do_not_ship = red ✗, NOT_YET_MEASURED = muted dashed outline ·.
 * Glyph + text always accompany the colour.
 */
export function VerdictPill({ route, size = 'sm', reason }: VerdictPillProps) {
  const d = routeDisplay(route)
  const key = route ?? 'NOT_YET_MEASURED'
  return (
    <Pill tone={d.tone} glyph={d.glyph} size={size} label={reason ? `${d.describe}. ${reason}` : d.describe} data-testid={`verdict-${key}`}>
      {d.label}
    </Pill>
  )
}
