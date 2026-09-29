/**
 * ExportButton.tsx — a refusal is reported beside the button, a download is counted and named.
 *
 * Navigation
 * ----------
 * What it is:   Unit tests for the shared export control.
 * What it does: Pins that the control is a real link to the API's export URL (the no-script
 *               fallback and the walkthrough's `download` event depend on it); that a non-200
 *               renders the error envelope beside the button with Retry, and Retry fetches
 *               again; that a 200 hands the browser a blob named from Content-Disposition,
 *               revokes the URL afterwards and says "Downloaded <file> — <n> rows" with a
 *               CSV's header left out; and the two pure helpers on their edge cases.
 * How:          `mockApi` answers `GET /ledger/export`; `URL.createObjectURL` / `revokeObjectURL`
 *               (absent in jsdom) and the anchor's `click` are stubbed; `renderApp`.
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0007-abstract-cell-export-only.md
 * Works with:   ui/src/components/ExportButton.tsx (the code under test), ui/src/test/utils.tsx
 * Tested by:    ui/src/components/ExportButton.test.tsx
 * Touch when:   never for a new repository; the status wording or the row count rule changes.
 */
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { PRINCIPAL, envelope, mockApi, renderApp } from '../test/utils'
import { ExportButton, REVOKE_AFTER_MS, countRows, filenameFrom } from './ExportButton'

const CSV = 'row_id,clean\nr1,true\nr2,false\n'

function csvResponse(): Response {
  return new Response(CSV, { status: 200, headers: { 'Content-Type': 'text/csv; charset=utf-8', 'Content-Disposition': 'attachment; filename="crb-ledger-alpha.csv"' } })
}

/** jsdom has no object URLs and no navigation: stub both and record the temporary anchor's click. */
function stubDownloads() {
  const createObjectURL = vi.fn((_blob: Blob) => 'blob:crb/export')
  const revokeObjectURL = vi.fn()
  Object.assign(URL, { createObjectURL, revokeObjectURL })
  const clicked: Array<{ href: string; download: string }> = []
  const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
    clicked.push({ href: this.getAttribute('href') ?? '', download: this.getAttribute('download') ?? '' })
  })
  return { createObjectURL, revokeObjectURL, clicked, click }
}

describe('ExportButton', () => {
  beforeEach(() => vi.useRealTimers())
  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
    delete (URL as unknown as Record<string, unknown>).createObjectURL
    delete (URL as unknown as Record<string, unknown>).revokeObjectURL
  })

  it('is a real link to the export URL, so the no-script fallback and the download event survive', async () => {
    mockApi({ 'GET /auth/me': PRINCIPAL })
    renderApp(<ExportButton path="/ledger/export?format=jsonl&repo=alpha" hint="button.ledger.export_jsonl">Export JSONL</ExportButton>)
    const link = await screen.findByRole('link', { name: 'Export JSONL' })
    expect(link).toHaveAttribute('href', '/api/v1/ledger/export?format=jsonl&repo=alpha')
    expect(link).toHaveAttribute('download')
    expect(link).toHaveAttribute('data-hint', 'button.ledger.export_jsonl')
    // the status line exists before it has anything to say, so the change is announced
    expect(screen.getByRole('status')).toHaveTextContent('')
  })

  it('a non-200 renders the envelope beside the button and Retry re-fetches', async () => {
    const { clicked } = stubDownloads()
    let calls = 0
    const api = mockApi({
      'GET /auth/me': PRINCIPAL,
      'GET /ledger/export': () => (++calls === 1 ? envelope(503, 'service_unavailable', 'The store is not reachable.') : csvResponse()),
    })
    renderApp(<ExportButton path="/ledger/export?format=csv&repo=alpha" hint="button.ledger.export_csv">Export CSV</ExportButton>)
    await userEvent.click(await screen.findByRole('link', { name: 'Export CSV' }))
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('The server reported an error')
    expect(alert).toHaveTextContent('The store is not reachable.')
    expect(alert).toHaveTextContent('HTTP 503 · service_unavailable')
    // nothing was handed to the browser: the refusal is the whole outcome
    expect(clicked).toEqual([])
    // the fetch carried the session and the export's own path
    const first = api.calls.find((c) => c.path === '/ledger/export')!
    expect(first.url).toBe('/api/v1/ledger/export?format=csv&repo=alpha')
    expect(first.init?.credentials).toBe('include')

    await userEvent.click(screen.getByRole('button', { name: 'Retry' }))
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Downloaded crb-ledger-alpha.csv — 2 rows'))
    expect(screen.queryByRole('alert')).toBeNull()
    expect(api.calls.filter((c) => c.path === '/ledger/export')).toHaveLength(2)
  })

  it('a 200 downloads the file named by Content-Disposition, counts the rows without the CSV header, and revokes the URL', async () => {
    const { createObjectURL, revokeObjectURL, clicked } = stubDownloads()
    mockApi({ 'GET /auth/me': PRINCIPAL, 'GET /ledger/export': () => csvResponse() })
    renderApp(<ExportButton path="/ledger/export?format=csv&repo=alpha" hint="button.ledger.export_csv">Export CSV</ExportButton>)
    const link = await screen.findByRole('link', { name: 'Export CSV' })
    await userEvent.click(link)
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Downloaded crb-ledger-alpha.csv — 2 rows'))
    expect(createObjectURL).toHaveBeenCalledTimes(1)
    const blob = createObjectURL.mock.calls[0]![0]
    expect(blob.type).toBe('text/csv; charset=utf-8')
    // jsdom's Blob has no text(): the size is the body's byte length
    expect(blob.size).toBe(new TextEncoder().encode(CSV).byteLength)
    expect(clicked).toEqual([{ href: 'blob:crb/export', download: 'crb-ledger-alpha.csv' }])
    await waitFor(() => expect(revokeObjectURL).toHaveBeenCalledWith('blob:crb/export'), { timeout: REVOKE_AFTER_MS + 2_000 })
    expect(link).not.toHaveAttribute('aria-busy')
  })

  it('says Exporting… while the request is in flight', async () => {
    stubDownloads()
    let release: (r: Response) => void = () => undefined
    mockApi({ 'GET /auth/me': PRINCIPAL, 'GET /ledger/export': () => new Promise<Response>((r) => (release = r)) })
    renderApp(<ExportButton path="/ledger/export?format=jsonl" hint="button.ledger.export_jsonl">Export JSONL</ExportButton>)
    const link = await screen.findByRole('link', { name: 'Export JSONL' })
    await userEvent.click(link)
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Exporting…'))
    expect(link).toHaveAttribute('aria-busy', 'true')
    release(new Response('{"a":1}\n', { status: 200, headers: { 'Content-Disposition': 'attachment; filename="crb-ledger.jsonl"' } }))
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Downloaded crb-ledger.jsonl — 1 row'))
  })

  it('filenameFrom reads a quoted, a bare and an RFC 5987 name, else the path’s last segment', () => {
    expect(filenameFrom('attachment; filename="crb-ledger.jsonl"', '/ledger/export?format=jsonl')).toBe('crb-ledger.jsonl')
    expect(filenameFrom('attachment; filename=crb-abstract-cells.jsonl', '/ledger/export/abstract')).toBe('crb-abstract-cells.jsonl')
    expect(filenameFrom("attachment; filename*=UTF-8''crb%20ledger.csv", '/x')).toBe('crb ledger.csv')
    expect(filenameFrom(null, '/ledger/export/abstract?x=1')).toBe('abstract')
  })

  it('countRows leaves a CSV header out and counts JSONL lines as they are', () => {
    expect(countRows('a,b\n1,2\n3,4\n', 'x.csv')).toBe(2)
    expect(countRows('a,b\n', 'x.csv')).toBe(0)
    expect(countRows('', 'x.csv')).toBe(0)
    expect(countRows('{"a":1}\n{"a":2}\n\n', 'x.jsonl')).toBe(2)
    expect(countRows('{"a":1}\r\n{"a":2}\r\n', 'x.jsonl')).toBe(2)
  })
})
