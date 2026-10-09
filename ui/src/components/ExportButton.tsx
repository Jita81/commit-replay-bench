/**
 * ExportButton — a download the page reports: fetch the file, hand it over, and say so.
 *
 * Navigation
 * ----------
 * What it is:   The one export control the Ledger and Capability pages share: a real
 *               `<a href download>` to the API's export URL whose click the page intercepts.
 * What it does: Renders the export as a link (role `link`; with scripts off the browser follows
 *               the href and downloads the file as before) and on click fetches the same URL
 *               itself with a 120 s bound, so a refusal is reported on the page: a non-2xx —
 *               the abstract export's 409 while a false-Q1 row exists — becomes the error
 *               envelope beside the button with Retry, never a raw API response in a new tab
 *               (G-101, G-182). On 200 it builds a blob, names the file from
 *               Content-Disposition, clicks a temporary `<a download>` and revokes the URL
 *               once the browser has taken it; a `role="status"` line reads "Exporting…" and
 *               then "Downloaded <file> — <n> rows" (a CSV is counted by record, not by
 *               line, and its header is not a row). A click while a fetch is in flight is
 *               ignored, so a double-click is one download. It does not detect a stream cut
 *               short after a 200: that is what `crb ledger verify` on the export is for.
 * How:          `fetchBounded` + `errorFromResponse` from the client; local state
 *               idle → exporting → done | error; `ErrorState compact` for the envelope.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0007-abstract-cell-export-only.md
 * Works with:   ui/src/api/client.ts (`fetchBounded`, `errorFromResponse`, `apiUrl`),
 *               ui/src/components/Button.tsx (`AnchorButton`),
 *               ui/src/components/ErrorState.tsx (`compact` — the envelope beside the button),
 *               ui/src/screens/Ledger/LedgerPage.tsx and
 *               ui/src/screens/Capability/CapabilityPage.tsx (the two callers),
 *               src/crb/server/routes/ledger.py (the export routes and their
 *               Content-Disposition)
 * Tested by:    ui/src/components/ExportButton.test.tsx, ui/src/screens/Ledger/LedgerPage.test.tsx
 *               (the refused abstract export), ui/src/screens/Capability/CapabilityPage.test.tsx,
 *               ui/e2e/walkthrough/05-replay-fake.spec.ts (the JSONL download under the served CSP)
 * Touch when:   never for a new repository; an export format is added — decide how its rows
 *               are counted in `countRows`.
 */
import { useCallback, useRef, useState, type AnchorHTMLAttributes, type ReactNode } from 'react'
import { apiUrl, errorFromResponse, fetchBounded } from '../api/client'
import type { HintId } from '../help/hints'
import { AnchorButton, type ButtonSize } from './Button'
import { ErrorState } from './ErrorState'

/** An export may walk the whole ledger: longer than the client's 25 s default. */
export const EXPORT_TIMEOUT_MS = 120_000
/** The blob URL is revoked after the browser has started the download, not on the same tick. */
export const REVOKE_AFTER_MS = 1_000

type ExportState = { state: 'idle' } | { state: 'exporting' } | { state: 'done'; file: string; rows: number } | { state: 'error'; error: unknown }

interface ExportButtonProps extends Omit<AnchorHTMLAttributes<HTMLAnchorElement>, 'href' | 'onClick' | 'children'> {
  /** The API path of the export with its query (`/ledger/export?format=csv&repo=x`); the href is `apiUrl(path)`. */
  path: string
  hint: HintId
  size?: ButtonSize
  children: ReactNode
}

/** The file name the server sent (`Content-Disposition: attachment; filename="…"`), else the path's last segment. */
export function filenameFrom(disposition: string | null, path: string): string {
  const m = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(disposition ?? '')
  if (m?.[1]) {
    try {
      return decodeURIComponent(m[1].trim())
    } catch {
      return m[1].trim()
    }
  }
  return path.split('?')[0]!.split('/').filter(Boolean).pop() ?? 'export'
}

/**
 * Rows in the export. JSONL is one record per line by construction. A CSV record may span
 * lines — `csv.writer` quotes a free-text `error` or `dq_reason` that holds a newline across
 * them — so a CSV is counted by record: a line break ends a record only outside quotes (a
 * doubled `""` inside a quoted cell toggles twice, so it does not end the cell), and the
 * header is not a row.
 */
export function countRows(text: string, filename: string): number {
  if (!filename.toLowerCase().endsWith('.csv')) return text.split(/\r?\n/).filter((l) => l.length > 0).length
  let records = 0
  let quoted = false
  let cur = ''
  for (const ch of text) {
    if (ch === '"') quoted = !quoted
    if (ch === '\n' && !quoted) {
      if (cur.replace(/\r$/, '').length > 0) records += 1
      cur = ''
    } else cur += ch
  }
  if (cur.replace(/\r$/, '').length > 0) records += 1
  return Math.max(0, records - 1)
}

/** Hand `text` to the browser as a download named `file`. */
function download(text: string, file: string, type: string): void {
  const blob = new Blob([text], { type })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = file
  a.rel = 'noopener'
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), REVOKE_AFTER_MS)
}

/** The export link with its status line and, on a refusal, the envelope beside it. */
export function ExportButton({ path, hint, size = 'md', children, ...rest }: ExportButtonProps) {
  const [state, setState] = useState<ExportState>({ state: 'idle' })
  // a second click while a fetch is in flight would hand the browser a second download: a ref,
  // because a double-click's two clicks land before the state has re-rendered
  const inFlight = useRef(false)

  const run = useCallback(async () => {
    if (inFlight.current) return
    inFlight.current = true
    setState({ state: 'exporting' })
    try {
      const res = await fetchBounded(path, { method: 'GET' }, { timeoutMs: EXPORT_TIMEOUT_MS })
      if (!res.ok) throw await errorFromResponse(res, path)
      const text = await res.text()
      const file = filenameFrom(res.headers.get('content-disposition'), path)
      download(text, file, res.headers.get('content-type') ?? 'application/octet-stream')
      setState({ state: 'done', file, rows: countRows(text, file) })
    } catch (error) {
      setState({ state: 'error', error })
    } finally {
      inFlight.current = false
    }
  }, [path])

  return (
    <div className="inline-flex flex-wrap items-center gap-2" data-testid="export-button">
      <AnchorButton
        size={size}
        href={apiUrl(path)}
        download
        hint={hint}
        aria-busy={state.state === 'exporting' || undefined}
        onClick={(e) => {
          e.preventDefault()
          void run()
        }}
        {...rest}
      >
        {children}
      </AnchorButton>
      {/* mounted before it has anything to say, so assistive technology announces the change */}
      <span role="status" aria-live="polite" className="num text-xs text-on-surface-muted" data-testid="export-status">
        {state.state === 'exporting' ? 'Exporting…' : state.state === 'done' ? `Downloaded ${state.file} — ${state.rows} row${state.rows === 1 ? '' : 's'}` : ''}
      </span>
      {state.state === 'error' && <ErrorState compact error={state.error} onRetry={() => void run()} />}
    </div>
  )
}
