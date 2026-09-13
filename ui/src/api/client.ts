/**
 * The one fetch wrapper every hook uses.
 *
 * Contract (docs/API.md, "Conventions"):
 *   - cookie session → `credentials: 'include'` on every call;
 *   - unsafe methods carry `X-CSRF-Token` equal to the `crb_csrf` cookie;
 *   - errors are `{"error": {"code", "message", "detail"}}` → {@link ApiError};
 *   - a stalled endpoint is bounded by {@link API_TIMEOUT_MS} → {@link ApiError}
 *     with `code: 'timeout'`, never an infinite spinner.
 *
 * Nothing here knows about React. Pure I/O with typed failures.
 */

import type { ApiErrorEnvelope } from './types'

export const API_BASE = '/api/v1'
export const API_TIMEOUT_MS = 25_000
export const CSRF_COOKIE = 'crb_csrf'
export const CSRF_HEADER = 'X-CSRF-Token'

const UNSAFE_METHODS = new Set(['POST', 'PUT', 'PATCH', 'DELETE'])

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

function parseEnvelope(body: unknown): ApiErrorEnvelope['error'] | null {
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
 * Fetch `${API_BASE}${path}` and return the parsed JSON body as `T`.
 * 204 / empty bodies resolve to `undefined as T`.
 */
export async function api<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const method = options.method ?? 'GET'
  const timeoutMs = options.timeoutMs ?? API_TIMEOUT_MS

  const controller = new AbortController()
  let timedOut = false
  const timer = setTimeout(() => {
    timedOut = true
    controller.abort()
  }, timeoutMs)

  const upstream = options.signal
  let onUpstreamAbort: (() => void) | undefined
  if (upstream) {
    if (upstream.aborted) controller.abort()
    else {
      onUpstreamAbort = () => controller.abort()
      upstream.addEventListener('abort', onUpstreamAbort)
    }
  }

  const headers: Record<string, string> = { Accept: 'application/json', ...options.headers }
  let body: BodyInit | undefined
  if (options.body instanceof FormData) {
    body = options.body
  } else if (options.body !== undefined) {
    headers['Content-Type'] = 'application/json'
    body = JSON.stringify(options.body)
  }
  if (UNSAFE_METHODS.has(method)) {
    const token = readCookie(CSRF_COOKIE)
    if (token) headers[CSRF_HEADER] = token
  }

  let res: Response
  try {
    res = await fetch(`${API_BASE}${path}`, {
      method,
      headers,
      body,
      credentials: 'include',
      signal: controller.signal,
    })
  } catch (err) {
    if (timedOut) {
      throw new ApiError(0, 'timeout', `The server did not answer within ${Math.round(timeoutMs / 1000)} s.`, {
        path,
        timeout_ms: timeoutMs,
      })
    }
    if (upstream?.aborted) throw err
    throw new ApiError(0, 'network', 'Could not reach the server.', {
      path,
      cause: err instanceof Error ? err.message : String(err),
    })
  } finally {
    clearTimeout(timer)
    if (upstream && onUpstreamAbort) upstream.removeEventListener('abort', onUpstreamAbort)
  }

  if (!res.ok) {
    let parsed: unknown = null
    try {
      parsed = await res.json()
    } catch {
      parsed = null
    }
    const env = parseEnvelope(parsed)
    if (env) throw new ApiError(res.status, env.code, env.message, env.detail ?? {})
    throw new ApiError(res.status, 'invalid_response', res.statusText || `HTTP ${res.status}`, { path })
  }

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
