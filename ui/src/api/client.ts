/**
 * The one fetch wrapper every hook uses.
 *
 * Contract (docs/API.md, "Conventions"):
 *   - cookie session → `credentials: 'include'` on every call;
 *   - unsafe methods carry `X-CSRF-Token` equal to the CSRF cookie — `__Host-crb_csrf` on a
 *     TLS deployment, `crb_csrf` otherwise (the server binds the token to the session);
 *   - errors are `{"error": {"code", "message", "detail"}}` → {@link ApiError};
 *   - a stalled endpoint is bounded by {@link API_TIMEOUT_MS} → {@link ApiError}
 *     with `code: 'timeout'`, never an infinite spinner.
 *
 * Nothing here knows about React. Pure I/O with typed failures.
 *
 * Navigation
 * ----------
 * What it is:   The single fetch wrapper (`api<T>`) behind every hook, with `ApiError`, `qs`
 *               and `readCookie` / `readCsrfToken`.
 * What it does: Prefixes `/api/v1`, sends the cookie session, adds `X-CSRF-Token` on unsafe
 *               methods, JSON-encodes bodies, aborts after 25 s and turns every failure into
 *               one typed `ApiError {status, code, message, detail}` — a timeout, a network
 *               failure and a non-envelope body are `timeout` / `network` /
 *               `invalid_response`, never a hang or a fabricated body. An upstream abort
 *               (React Query cancelling) is re-thrown untouched so it never reads as a failure.
 * How:          `api` builds the headers and body, then calls `fetchBounded` — the one place a
 *               timeout is armed on an AbortController and the caller's signal chained to it,
 *               with `credentials: 'include'` → on non-2xx `errorFromResponse` parses the
 *               envelope → on 2xx parse JSON (204 / empty body → undefined).
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/api/hooks.ts (every query and mutation calls `api`), ui/src/api/types.ts
 *               (`ApiErrorEnvelope`), ui/src/api/sse.ts (shares `API_BASE` for the stream URL),
 *               ui/src/components/ErrorState.tsx (renders an `ApiError` by status and code),
 *               src/crb/server/auth.py (the cookie and CSRF names this file mirrors),
 *               src/crb/server/app.py (emits the error envelope)
 * Tested by:    ui/src/api/client.test.ts
 * Touch when:   the error envelope, the cookie names or the CSRF header change (docs/API.md
 *               "Conventions") — change src/crb/server/auth.py and this file together; never
 *               for a new repository.
 */

import type { ApiErrorEnvelope } from './types'

export const API_BASE = '/api/v1'
export const API_TIMEOUT_MS = 25_000
export const CSRF_COOKIE = 'crb_csrf'
/** A deployment with secure cookies sets `__Host-crb_csrf`; read first, so a plain-named
 * cookie planted beside it is never the one echoed. */
export const CSRF_COOKIE_NAMES = [`__Host-${CSRF_COOKIE}`, CSRF_COOKIE] as const
export const CSRF_HEADER = 'X-CSRF-Token'

const UNSAFE_METHODS = new Set(['POST', 'PUT', 'PATCH', 'DELETE'])

/**
 * The CSRF token the server set for this session, under whichever name the deployment
 * uses ({@link CSRF_COOKIE_NAMES}); `null` when there is none.
 */
export function readCsrfToken(source?: string): string | null {
  for (const name of CSRF_COOKIE_NAMES) {
    const token = readCookie(name, source)
    if (token) return token
  }
  return null
}

/**
 * A non-2xx response, a timeout, or a network failure. `status` is the HTTP
 * status (0 for network/timeout), `code` the envelope's snake_case code
 * (`'timeout'` / `'network'` / `'invalid_response'` when the server did not
 * answer with an envelope), `detail` the envelope's structured detail.
 */
export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly detail: Record<string, unknown>

  constructor(status: number, code: string, message: string, detail: Record<string, unknown> = {}) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.detail = detail
  }

  get isFalseQ1Refused(): boolean {
    return this.status === 409 && this.code === 'false_q1_refused'
  }

  get isUnauthenticated(): boolean {
    return this.status === 401
  }

  get isForbidden(): boolean {
    return this.status === 403
  }
}

/** Type guard for `catch (err: unknown)` blocks — the only sanctioned way to branch on a failure. */
export function isApiError(err: unknown): err is ApiError {
  return err instanceof ApiError
}

/** Read a cookie by name from `document.cookie` (no external dep). */
export function readCookie(name: string, source?: string): string | null {
  const jar = source ?? (typeof document === 'undefined' ? '' : document.cookie)
  if (!jar) return null
  for (const part of jar.split(';')) {
    const [k, ...rest] = part.trim().split('=')
    if (k === name) return decodeURIComponent(rest.join('='))
  }
  return null
}

/**
 * The contract's error envelope, or `null` when the body is not one (a proxy's HTML page,
 * an empty body). Strict on `code` and `message` being strings so a half-shaped body is
 * reported as `invalid_response` rather than as a fabricated code.
 */
export function parseEnvelope(body: unknown): ApiErrorEnvelope['error'] | null {
  if (!body || typeof body !== 'object') return null
  const err = (body as { error?: unknown }).error
  if (!err || typeof err !== 'object') return null
  const e = err as Record<string, unknown>
  if (typeof e.code !== 'string' || typeof e.message !== 'string') return null
  const detail = e.detail && typeof e.detail === 'object' ? (e.detail as Record<string, unknown>) : {}
  return { code: e.code, message: e.message, detail }
}

export interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'
  /** JSON-serialised when it is not FormData. */
  body?: unknown
  signal?: AbortSignal
  timeoutMs?: number
  headers?: Record<string, string>
}

/** Build a query string, omitting undefined/null/'' values. */
export function qs(params: Record<string, string | number | boolean | undefined | null>): string {
  const sp = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === '') continue
    sp.set(k, String(v))
  }
  const s = sp.toString()
  return s ? `?${s}` : ''
}

/**
 * `fetch` with the client's two guarantees, for the one caller that needs raw bytes
 * (`fetchRetainedPatch`) as well as `api<T>`: a stall is bounded by `timeoutMs` and
 * surfaces as `ApiError('timeout')`, and a caller-initiated abort is rethrown raw so React
 * Query treats it as a cancellation. A network failure is `ApiError('network')`.
 */
export async function fetchBounded(path: string, init: RequestInit, opts: { timeoutMs?: number; signal?: AbortSignal } = {}): Promise<Response> {
  const timeoutMs = opts.timeoutMs ?? API_TIMEOUT_MS
  const controller = new AbortController()
  let timedOut = false
  const timer = setTimeout(() => {
    timedOut = true
    controller.abort()
  }, timeoutMs)
  const upstream = opts.signal
  let onUpstreamAbort: (() => void) | undefined
  if (upstream) {
    if (upstream.aborted) controller.abort()
    else {
      onUpstreamAbort = () => controller.abort()
      upstream.addEventListener('abort', onUpstreamAbort)
    }
  }
  try {
    return await fetch(`${API_BASE}${path}`, { ...init, credentials: 'include', signal: controller.signal })
  } catch (err) {
    if (timedOut) {
      throw new ApiError(0, 'timeout', `The server did not answer within ${Math.round(timeoutMs / 1000)} s.`, { path, timeout_ms: timeoutMs })
    }
    if (upstream?.aborted) throw err
    throw new ApiError(0, 'network', 'Could not reach the server.', { path, cause: err instanceof Error ? err.message : String(err) })
  } finally {
    clearTimeout(timer)
    if (upstream && onUpstreamAbort) upstream.removeEventListener('abort', onUpstreamAbort)
  }
}

/** A non-2xx response → the `ApiError` the envelope describes, or `invalid_response` for a half-shaped body. */
export async function errorFromResponse(res: Response, path: string): Promise<ApiError> {
  let parsed: unknown = null
  try {
    parsed = await res.json()
  } catch {
    parsed = null
  }
  const env = parseEnvelope(parsed)
  if (env) return new ApiError(res.status, env.code, env.message, env.detail ?? {})
  return new ApiError(res.status, 'invalid_response', res.statusText || `HTTP ${res.status}`, { path })
}

/**
 * Fetch `${API_BASE}${path}` and return the parsed JSON body as `T`.
 * 204 / empty bodies resolve to `undefined as T`.
 */
export async function api<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const method = options.method ?? 'GET'
  const headers: Record<string, string> = { Accept: 'application/json', ...options.headers }
  let body: BodyInit | undefined
  if (options.body instanceof FormData) {
    body = options.body
  } else if (options.body !== undefined) {
    headers['Content-Type'] = 'application/json'
    body = JSON.stringify(options.body)
  }
  // CSRF: echo the (JS-readable) cookie the server set for this session; the server checks
  // it is this session's token. Without the cookie the header is left off and the server
  // answers 403 — the UI never invents a token.
  if (UNSAFE_METHODS.has(method)) {
    const token = readCsrfToken()
    if (token) headers[CSRF_HEADER] = token
  }

  // The timeout, the caller's abort and a network failure are handled once, in fetchBounded.
  const res = await fetchBounded(path, { method, headers, body }, { timeoutMs: options.timeoutMs, signal: options.signal })
  if (!res.ok) throw await errorFromResponse(res, path)

  if (res.status === 204) return undefined as T
  const text = await res.text()
  if (!text) return undefined as T
  try {
    return JSON.parse(text) as T
  } catch {
    throw new ApiError(res.status, 'invalid_response', 'The server returned a non-JSON body.', { path })
  }
}

/** Absolute URL for a download endpoint (export buttons point straight at the API). */
export function apiUrl(path: string): string {
  return `${API_BASE}${path}`
}
