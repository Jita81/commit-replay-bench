/**
 * 404 inside the shell — nav intact, the missing path shown, a way back.
 *
 * Navigation
 * ----------
 * What it is:   The catch-all route's screen.
 * What it does: Renders an unknown path as a designed empty state inside the shell (design
 *               law 5 in ui/README.md) so the navigation stays usable, shows the path that was
 *               requested, and offers one way back: Home, the start of the journey (never
 *               the legacy repository list, which is not in the journey nav).
 * How:          `useLocation` for the path; `PageHeader` + `EmptyState`.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/App.tsx (the `*` route), ui/src/components/EmptyState.tsx,
 *               ui/src/components/Layout.tsx (the shell it renders inside)
 * Tested by:    ui/src/screens/NotFoundPage.test.tsx
 * Touch when:   never for a new repository.
 */
import { useLocation } from 'react-router'
import { LinkButton } from '../components/Button'
import { EmptyState } from '../components/EmptyState'
import { PageHeader } from '../components/PageHeader'

/** 404 inside the shell (STANDARD law 5): nav intact, a way back. */
export function NotFoundPage() {
  const loc = useLocation()
  return (
    <>
      <PageHeader eyebrow="Not found" title="This page does not exist" />
      <EmptyState glyph="∅" title="Nothing lives at this address" reason={<span className="font-mono text-xs">{loc.pathname}</span>} action={<LinkButton variant="filled" to="/home">Back to Home</LinkButton>} />
    </>
  )
}

export default NotFoundPage
