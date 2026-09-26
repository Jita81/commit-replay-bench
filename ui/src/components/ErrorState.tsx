/**
 * ErrorState — the API's error envelope rendered honestly: message first, code and status small,
 * detail behind a disclosure.
 *
 * Navigation
 * ----------
 * What it is:   The `ErrorState` alert every failed query or mutation renders through.
 * What it does: Shows the human message from the envelope under a heading chosen by code
 *               (`timeout`, `network`, `sandbox_unavailable`, `false_q1_refused`,
 *               `invalid_response`, `builder_credential_missing`) or by HTTP status
 *               (401 / 403 / 404 / 409 / 5xx), the `HTTP <status> · <code>` line in small
 *               mono, the structured `detail` behind a
 *               collapsed disclosure, and an optional Retry. No stack traces, no raw JSON in
 *               chrome (design law 4 in ui/README.md); a non-`ApiError` is shown by its
 *               message.
 * How:          `instanceof ApiError` → pick the heading (code table, then status, then a
 *               generic) → `role="alert"` card with `JsonView` for the detail.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/api/client.ts (`ApiError` — the only failure shape),
 *               ui/src/components/QueryBoundary.tsx (renders this for every failed query),
 *               ui/src/components/JsonView.tsx (the detail), ui/src/components/GateBanner.tsx
 *               (a 409 `false_q1_refused` on a gate is rendered as a REFUSED gate, not here),
 *               ui/src/screens/Login/LoginPage.tsx (a wrong password shows the envelope)
 * Tested by:    ui/src/screens/Signoff/SignoffPage.test.tsx and
 *               ui/src/screens/Capability/CapabilityPage.test.tsx (a 409 and a 5xx as rendered),
 *               ui/e2e/walkthrough/01-login.spec.ts (the envelope on a wrong password)
 * Touch when:   a reserved error code is added to docs/API.md "Conventions" — add its heading
 *               to `CODE_TITLES`; never for a new repository.
 */
import type { ReactNode } from 'react'
import { ApiError } from '../api/client'
import { Button } from './Button'
import { JsonView } from './JsonView'

interface ErrorStateProps {
  error: unknown
  onRetry?: () => void
  /** Overrides the generic title. */
  title?: string
  compact?: boolean
  children?: ReactNode
}

/** Headings for the reserved codes (docs/API.md "Conventions") — chosen before the HTTP status. */
const CODE_TITLES: Record<string, string> = {
  timeout: 'The server did not answer in time',
  network: 'Could not reach the server',
  sandbox_unavailable: 'Sandbox unavailable — stopped fail-closed',
  false_q1_refused: 'Refused: false-Q1 invariant',
  invalid_response: 'Unexpected response from the server',
  // POST /runs: the chosen builder auth has no credential (docs/PREVENTION.md P-003)
  builder_credential_missing: 'No credential for this builder — nothing was queued',
}

/** A heading from the HTTP status when the code is not a reserved one. */
function statusTitle(status: number): string | null {
  if (status === 401) return 'You are not signed in'
  if (status === 403) return 'Your role does not allow this'
  if (status === 404) return 'Not found'
  if (status === 409) return 'Refused'
  if (status >= 500) return 'The server reported an error'
  return null
}

/**
 * Renders the error envelope honestly: the human message first, the
 * machine code and HTTP status as small mono text, and the structured
 * `detail` behind a collapsed disclosure. No stack traces, no raw JSON in
 * chrome — the detail is opt-in, labelled, and formatted.
 */
export function ErrorState({ error, onRetry, title, compact = false, children }: ErrorStateProps) {
  const api = error instanceof ApiError ? error : null
  const heading = title ?? (api ? (CODE_TITLES[api.code] ?? statusTitle(api.status) ?? 'Request failed') : 'Something went wrong')
  const message = api ? api.message : error instanceof Error ? error.message : String(error)
  const hasDetail = api ? Object.keys(api.detail).length > 0 : false

  return (
    <div
      role="alert"
      data-testid="error-state"
      className={`rounded-[var(--radius-card)] border border-status-red/40 bg-status-red-soft text-on-surface ${compact ? 'px-4 py-3' : 'px-5 py-4'}`}
    >
      <div className="flex items-start gap-3">
        <span aria-hidden className="mt-0.5 font-mono text-status-red">
          ✗
        </span>
        <div className="min-w-0 flex-1 space-y-1">
          <div className="font-serif text-[16px] font-semibold text-status-red">{heading}</div>
          <p className="text-sm">{message}</p>
          {api && (
            <p className="num font-mono text-[11px] text-on-surface-muted">
              {api.status > 0 ? `HTTP ${api.status}` : 'no response'} · {api.code}
            </p>
          )}
          {hasDetail && api && (
            <details className="text-xs">
              <summary className="cursor-pointer text-on-surface-muted">Details</summary>
              <div className="mt-2">
                <JsonView value={api.detail} initiallyOpen />
              </div>
            </details>
          )}
          {children}
        </div>
        {onRetry && (
          <Button size="sm" onClick={onRetry}>
            Retry
          </Button>
        )}
      </div>
    </div>
  )
}
