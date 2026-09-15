/**
 * VerdictPill — a cell's route as a pill: deliver ✓, calibrate ◐, granularize ⋮, human ☺, do_not_ship ✗, not yet measured ·.
 *
 * Navigation
 * ----------
 * What it is:   The `VerdictPill` for a route (or the absence of one).
 * What it does: Shows the route's label, tone and glyph with a full sentence for assistive
 *               tech (plus the routing reason when given); `null` / `undefined` renders as
 *               NOT_YET_MEASURED in a muted dashed outline — the UI never fabricates a
 *               verdict for a cell without rows, and never gives absence a status colour.
 * How:          `routeDisplay(route)` → `Pill`, with `data-testid="verdict-<route>"`.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0003-one-routing-rule.md
 * Works with:   ui/src/lib/verdict.ts (`routeDisplay` — the one table), ui/src/components/Pill.tsx
 *               (the primitive), ui/src/api/types.ts (`CellVerdict`, `NOT_YET_MEASURED`),
 *               ui/src/screens/Capability/CapabilityPage.tsx and ui/src/screens/Routing/RoutingPage.tsx
 *               (a pill per cell)
 * Tested by:    ui/src/components/VerdictPill.test.tsx, ui/src/screens/Capability/CapabilityPage.test.tsx
 *               (`cell-measured` / `cell-not-measured`)
 * Touch when:   a route is added to `crb.core.routing` (an ADR) — extend `Route` in
 *               ui/src/api/types.ts and the table in ui/src/lib/verdict.ts; never for a new
 *               repository.
 */
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
