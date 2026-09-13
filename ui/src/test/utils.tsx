import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, type RenderOptions } from '@testing-library/react'
import type { ReactElement, ReactNode } from 'react'
import { MemoryRouter, Route, Routes } from 'react-router'
import { vi } from 'vitest'
import { AuthProvider } from '../lib/auth'
import type { Principal } from '../api/types'

export const PRINCIPAL: Principal = { id: 'u1', display_name: 'Ada', email: 'ada@example.org', role: 'approver', issuer: 'local' }

type Handler = (url: string, init: RequestInit | undefined) => Response | Promise<Response>

export function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

export function envelope(status: number, code: string, message: string, detail: Record<string, unknown> = {}): Response {
  return json({ error: { code, message, detail } }, status)
}

/**
 * Install a `fetch` mock that dispatches on `${METHOD} ${path}` (path without
 * the /api/v1 prefix and without the query string). Unmatched calls 404 with
 * an envelope so a missing route is visible, not silent.
 */
export function mockApi(routes: Record<string, Handler | unknown>) {
  const calls: Array<{ method: string; path: string; url: string; init: RequestInit | undefined }> = []
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url
    const method = (init?.method ?? 'GET').toUpperCase()
    const path = url.replace(/^\/api\/v1/, '').split('?')[0] ?? ''
    calls.push({ method, path, url, init })
    const key = `${method} ${path}`
    const h = routes[key] ?? routes[`* ${path}`]
    if (h === undefined) return envelope(404, 'not_found', `no mock for ${key}`)
    if (typeof h === 'function') return (h as Handler)(url, init)
    return json(h)
  })
  vi.stubGlobal('fetch', fetchMock)
  return { fetchMock, calls }
}

interface Opts extends Omit<RenderOptions, 'wrapper'> {
  route?: string
  path?: string
  me?: Principal | null
}

/** Render inside QueryClient + MemoryRouter + AuthProvider; `/auth/me` is mocked unless `me` is null. */
export function renderApp(ui: ReactElement, opts: Opts = {}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } } })
  const route = opts.route ?? '/'
  const path = opts.path ?? '*'
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[route]}>
        <AuthProvider>
          <Routes>
            <Route path={path} element={children} />
          </Routes>
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>
  )
  return { ...render(ui, { ...opts, wrapper }), qc }
}
