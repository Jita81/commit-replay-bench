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

const CODE_TITLES: Record<string, string> = {
  timeout: 'The server did not answer in time',
  network: 'Could not reach the server',
  sandbox_unavailable: 'Sandbox unavailable — stopped fail-closed',
  false_q1_refused: 'Refused: false-Q1 invariant',
  invalid_response: 'Unexpected response from the server',
}

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
