/**
 * UnknownRepo — a repository name the API does not know says so and offers the way back.
 *
 * Navigation
 * ----------
 * What it is:   The state a per-repository screen (`/connect/:name`, `/repos/:name`) shows when
 *               its `GET /repos/{name}` read failed.
 * What it does: A 404 is not an error to retry — the name is wrong, renamed or removed — so it
 *               renders the designed empty state "No repository called <name>" with ONE door,
 *               Open Connection (`/connect`, where every repository this deployment knows is
 *               listed and a new one is connected). Any other failure (a 5xx, a timeout, no
 *               response) is a read that may succeed next time and renders `ErrorState` with
 *               Retry, the envelope's own words first (G-979).
 * How:          `isApiError` + `status === 404` → `EmptyState`; else `ErrorState`.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/components/EmptyState.tsx, ui/src/components/ErrorState.tsx (the two
 *               states; never confused), ui/src/api/client.ts (`isApiError`),
 *               ui/src/screens/Connect/ConnectPage.tsx (`ConnectRepoPage`) and
 *               ui/src/screens/Repos/RepoDetail.tsx (the two screens that render it),
 *               ui/src/help/hints.ts (`button.shared.unknown_repo`)
 * Tested by:    ui/src/screens/Connect/ConnectPage.test.tsx and
 *               ui/src/screens/Repos/RepoDetail.test.tsx (a 404 and a 500 on each screen)
 * Touch when:   never for a new repository; a third per-repository screen needs the same state
 *               (render this, do not write another).
 */
import { isApiError } from '../api/client'
import { LinkButton } from './Button'
import { EmptyState } from './EmptyState'
import { ErrorState } from './ErrorState'

interface UnknownRepoProps {
  /** The name the route carried. */
  name: string
  /** The failed read's error (an `ApiError` from `useRepo`, or anything thrown). */
  error: unknown
  onRetry: () => void
}

/** `true` when the failure is the API saying no such repository. */
export function isUnknownRepo(error: unknown): boolean {
  return isApiError(error) && error.status === 404
}

export function UnknownRepo({ name, error, onRetry }: UnknownRepoProps) {
  if (isUnknownRepo(error)) {
    return (
      <EmptyState
        glyph="?"
        title={`No repository called ${name}`}
        reason="It may have been renamed or removed, or the address is mistyped. Connection lists every repository this deployment knows."
        action={
          <LinkButton variant="filled" to="/connect" hint="button.shared.unknown_repo">
            Open Connection
          </LinkButton>
        }
        data-testid="unknown-repo"
      />
    )
  }
  return <ErrorState error={error} onRetry={onRetry} />
}
