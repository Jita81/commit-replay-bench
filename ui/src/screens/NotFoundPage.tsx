/**
 * 404 inside the shell — nav intact, the missing path shown, a way back.
 *
 * Navigation
 * ----------
 * What it is:   The catch-all route's screen.
 * What it does: Renders an unknown path as a designed empty state inside the shell (design
 *               law 5 in ui/README.md) so the navigation stays usable, shows the whole
 *               address that was requested (path, query string and hash — the link the person
 *               followed, not a trimmed copy of it: G-197), says why an address fails here and
 *               what to do for each cause (typed or copied wrongly: check it; a link from an
 *               older version, or to a run or task since deleted: start from Home or Runs, and
 *               tell whoever sent it), states what the page will not do (search, guess a near
 *               match, report the link: G-196), and offers one way back: Home, the start of
 *               the journey (never the legacy repository list, which is not in the journey nav).
 * How:          `useLocation` for the address; `PageHeader` + `EmptyState`; no API call, so it
 *               can add no failure of its own.
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

/** 404 inside the shell (STANDARD law 5): nav intact, the address asked for, why, what to do, a way back. */
export function NotFoundPage() {
  const loc = useLocation()
  // the address as it was asked for: the query string and hash are part of the link a person followed
  const address = `${loc.pathname}${loc.search}${loc.hash}`
  return (
    <>
      <PageHeader eyebrow="Not found" title="This page does not exist" />
      <EmptyState
        glyph="∅"
        title="Nothing lives at this address"
        reason={
          <>
            <span className="block break-all font-mono text-xs" data-testid="notfound-address">
              {address}
            </span>
            <span className="mt-3 block" data-testid="notfound-cause">
              If you typed or copied the address, check it for a mistake and try again. If you followed a link, it may come from an older version of this product, or point to a run or task that has since been deleted: start from Home, or look for the run on Runs, and tell whoever sent you the link.
            </span>
            <span className="mt-3 block" data-testid="notfound-nongoal">
              This page does not search for what you meant, guess a near match or report the broken link to anyone.
            </span>
          </>
        }
        action={
          <LinkButton variant="filled" to="/home" hint="button.notfound.home">
            Back to Home
          </LinkButton>
        }
      />
    </>
  )
}

export default NotFoundPage
