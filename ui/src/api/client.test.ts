/**
 * ui/src/api/client.ts — the fetch wrapper's contract, against a stubbed `fetch`.
 *
 * Navigation
 * ----------
 * What it is:   Unit tests for the API client (`api`, `fetchBounded`, `ApiError`, `qs`,
 *               `readCookie`, `readCsrfToken`).
 * What it does: Pins that every call is prefixed `/api/v1` with credentials, that unsafe
 *               methods carry the CSRF cookie as `X-CSRF-Token` (and nothing when the cookie
 *               is absent), that the error envelope becomes `ApiError` with 401 / 403 / 409
 *               `false_q1_refused` distinguishable, that a non-envelope body, a timeout and a
 *               network failure map to `invalid_response` / `timeout` / `network`, that an
 *               upstream abort is re-thrown untouched, and that 204 resolves to undefined;
 *               and that `fetchBounded` shares `api`'s one timeout / abort / network guard —
 *               the same error for the same failure, and one AbortController in the source.
 * How:          `vi.stubGlobal('fetch', …)` with `Response` objects per case; fake timers for
 *               the timeout; the cookie set on `document.cookie` in `beforeEach`.
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/api/client.ts (the code under test), docs/API.md (the conventions these
 *               cases pin), ui/src/test/setup.ts (jest-dom matchers, jsdom environment)
 * Tested by:    ui/src/api/client.test.ts
 * Touch when:   a convention in docs/API.md changes (envelope, cookie, header, timeout) —
 *               update ui/src/api/client.ts and the matching case together.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { API_TIMEOUT_MS, ApiError, api, fetchBounded, qs, readCookie, readCsrfToken } from './client'
import clientSource from './client.ts?raw'

function ok(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

describe('client.api', () => {
  beforeEach(() => {
    document.cookie = 'crb_csrf=tok-123; path=/'
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.useRealTimers()
    document.cookie = 'crb_csrf=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/'
  })

  it('sends credentials and prefixes /api/v1', async () => {
    const fetchMock = vi.fn(async () => ok({ hello: 'world' }))
    vi.stubGlobal('fetch', fetchMock)
    const out = await api<{ hello: string }>('/health')
    expect(out).toEqual({ hello: 'world' })
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toBe('/api/v1/health')
    expect(init.credentials).toBe('include')
    expect(init.method).toBe('GET')
    expect((init.headers as Record<string, string>)['X-CSRF-Token']).toBeUndefined()
  })

  it('adds X-CSRF-Token from the crb_csrf cookie on unsafe methods and JSON-encodes the body', async () => {
    const fetchMock = vi.fn(async () => ok({ id: 'r1' }))
    vi.stubGlobal('fetch', fetchMock)
    await api('/runs', { method: 'POST', body: { repo: 'x', kind: 'replay' } })
    const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit]
    const headers = init.headers as Record<string, string>
    expect(headers['X-CSRF-Token']).toBe('tok-123')
    expect(headers['Content-Type']).toBe('application/json')
    expect(init.body).toBe(JSON.stringify({ repo: 'x', kind: 'replay' }))
  })

  it('does not add the CSRF header on PUT when the cookie is absent (server will 403)', async () => {
    document.cookie = 'crb_csrf=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/'
    const fetchMock = vi.fn(async () => ok({}))
    vi.stubGlobal('fetch', fetchMock)
    await api('/users/1/role', { method: 'PUT', body: { role: 'admin' } })
    const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit]
    expect((init.headers as Record<string, string>)['X-CSRF-Token']).toBeUndefined()
  })

  it('parses the error envelope into ApiError {status, code, message, detail}', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ok({ error: { code: 'false_q1_refused', message: 'cell has false-Q1', detail: { cell: 'bug.fix|S', false_q1: 1 } } }, 409)),
    )
    const err = await api('/signoffs', { method: 'POST', body: {} }).catch((e: unknown) => e)
    expect(err).toBeInstanceOf(ApiError)
    const e = err as ApiError
    expect(e.status).toBe(409)
    expect(e.code).toBe('false_q1_refused')
    expect(e.message).toBe('cell has false-Q1')
    expect(e.detail).toEqual({ cell: 'bug.fix|S', false_q1: 1 })
    expect(e.isFalseQ1Refused).toBe(true)
  })

  it('maps a non-envelope error body to code invalid_response with the HTTP status', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('<html>bad gateway</html>', { status: 502, statusText: 'Bad Gateway' })))
    const err = (await api('/health').catch((e: unknown) => e)) as ApiError
    expect(err.status).toBe(502)
    expect(err.code).toBe('invalid_response')
    expect(err.isUnauthenticated).toBe(false)
  })

  it('treats 401 and 403 distinctly', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ok({ error: { code: 'unauthenticated', message: 'login' } }, 401)))
    const e401 = (await api('/auth/me').catch((e: unknown) => e)) as ApiError
    expect(e401.isUnauthenticated).toBe(true)
    vi.stubGlobal('fetch', vi.fn(async () => ok({ error: { code: 'forbidden', message: 'role' } }, 403)))
    const e403 = (await api('/users').catch((e: unknown) => e)) as ApiError
    expect(e403.isForbidden).toBe(true)
  })

  it('aborts after the timeout and throws ApiError{code: timeout}', async () => {
    vi.useFakeTimers()
    const fetchMock = vi.fn(
      (_url: string, init?: RequestInit) =>
        new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')))
        }),
    )
    vi.stubGlobal('fetch', fetchMock)
    const p = api('/slow', { timeoutMs: 500 })
    const caught = p.catch((e: unknown) => e)
    await vi.advanceTimersByTimeAsync(600)
    const err = (await caught) as ApiError
    expect(err).toBeInstanceOf(ApiError)
    expect(err.code).toBe('timeout')
    expect(err.status).toBe(0)
    expect(err.detail.timeout_ms).toBe(500)
  })

  it('has a 25 s default timeout', () => {
    expect(API_TIMEOUT_MS).toBe(25_000)
  })

  it('re-throws an upstream abort untouched (React Query cancellation is not a failure)', async () => {
    const ctrl = new AbortController()
    vi.stubGlobal(
      'fetch',
      vi.fn(
        (_url: string, init?: RequestInit) =>
          new Promise<Response>((_resolve, reject) => {
            init?.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')))
          }),
      ),
    )
    const p = api('/x', { signal: ctrl.signal }).catch((e: unknown) => e)
    ctrl.abort()
    const err = await p
    expect(err).not.toBeInstanceOf(ApiError)
    expect((err as DOMException).name).toBe('AbortError')
  })

  it('resolves undefined for 204 / empty bodies', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(null, { status: 204 })))
    expect(await api('/auth/logout', { method: 'POST' })).toBeUndefined()
  })

  it('wraps a network failure as ApiError{code: network}', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => Promise.reject(new TypeError('Failed to fetch'))))
    const err = (await api('/x').catch((e: unknown) => e)) as ApiError
    expect(err.code).toBe('network')
    expect(err.status).toBe(0)
  })
})

// assessment 2026-09-25, E3: `api` and `fetchBounded` each carried their own copy of the
// timeout / upstream-abort / network-failure logic; a fix to one would silently miss the other
describe('one timeout and abort guard behind api and fetchBounded', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.useRealTimers()
  })

  const hang = () =>
    vi.fn(
      (_url: string, init?: RequestInit) =>
        new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')))
        }),
    )

  it('client.ts arms exactly one AbortController, so the guard exists once', () => {
    expect(clientSource.match(/new AbortController\(\)/g) ?? []).toHaveLength(1)
  })

  it('fetchBounded times out exactly as api does', async () => {
    vi.useFakeTimers()
    vi.stubGlobal('fetch', hang())
    const a = api('/slow', { timeoutMs: 500 }).catch((e: unknown) => e)
    const b = fetchBounded('/slow', {}, { timeoutMs: 500 }).catch((e: unknown) => e)
    await vi.advanceTimersByTimeAsync(600)
    const [ea, eb] = (await Promise.all([a, b])) as [ApiError, ApiError]
    expect(eb).toBeInstanceOf(ApiError)
    expect([eb.status, eb.code, eb.message, eb.detail]).toEqual([ea.status, ea.code, ea.message, ea.detail])
    expect(eb.code).toBe('timeout')
  })

  it('fetchBounded re-throws an upstream abort untouched, as api does', async () => {
    vi.stubGlobal('fetch', hang())
    const ctrl = new AbortController()
    const p = fetchBounded('/x', {}, { signal: ctrl.signal }).catch((e: unknown) => e)
    ctrl.abort()
    const err = await p
    expect(err).not.toBeInstanceOf(ApiError)
    expect((err as DOMException).name).toBe('AbortError')
  })

  it('fetchBounded wraps a network failure as api does, and sends the cookie session', async () => {
    const fetchMock = vi.fn(async (_url: string, _init?: RequestInit) => Promise.reject(new TypeError('Failed to fetch')))
    vi.stubGlobal('fetch', fetchMock)
    const ea = (await api('/x').catch((e: unknown) => e)) as ApiError
    const eb = (await fetchBounded('/x', { method: 'GET' }).catch((e: unknown) => e)) as ApiError
    expect([eb.status, eb.code, eb.message, eb.detail]).toEqual([ea.status, ea.code, ea.message, ea.detail])
    expect(fetchMock.mock.calls[1]?.[0]).toBe('/api/v1/x')
    expect(fetchMock.mock.calls[1]?.[1]?.credentials).toBe('include')
  })
})

describe('helpers', () => {
  it('readCookie finds a named cookie', () => {
    expect(readCookie('b', 'a=1; b=two%20words; c=3')).toBe('two words')
    expect(readCookie('zz', 'a=1')).toBeNull()
  })
  it('qs omits empty values', () => {
    expect(qs({ repo: 'x', kind: undefined, clean: false, limit: 0, offset: '' })).toBe('?repo=x&clean=false&limit=0')
    expect(qs({})).toBe('')
  })

  it('reads the CSRF token under the __Host- name a TLS deployment sets, else the plain name', () => {
    expect(readCsrfToken('__Host-crb_csrf=tls-tok; other=1')).toBe('tls-tok')
    expect(readCsrfToken('crb_csrf=plain-tok')).toBe('plain-tok')
    // both present (a plain one planted beside the real one): the __Host- cookie wins
    expect(readCsrfToken('crb_csrf=planted; __Host-crb_csrf=real')).toBe('real')
    expect(readCsrfToken('other=1')).toBeNull()
  })
})
