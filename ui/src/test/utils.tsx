/**
 * Test helpers — a fetch mock keyed by "METHOD /path", and renderApp (query client + memory router
 * + auth).
 *
 * Navigation
 * ----------
 * What it is:   `mockApi` (a `fetch` double that dispatches on `${METHOD} ${path}`), `json` /
 *               `envelope` response builders, `PRINCIPAL` (an approver), `renderApp` and
 *               `expectHintOpens` (hover a trigger, the bubble opens with the registry text).
 * What it does: Lets a screen test answer the API contract exactly — a body per route, or a
 *               handler that inspects the request — and records every call so a test can
 *               assert on the body a mutation sent. An unmatched call answers a 404
 *               envelope so a missing mock is visible, never a silent hang. `renderApp`
 *               mounts the same providers the app does (with `gcTime: 0` so nothing is
 *               cached across tests) at a chosen route.
 * How:          `vi.stubGlobal('fetch', …)`; the path is the URL without `/api/v1` and the
 *               query string; `* /path` matches any method.
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/api/client.ts (the fetch calls this intercepts), ui/src/lib/auth.tsx
 *               (`AuthProvider` — `/auth/me` is usually mocked with `PRINCIPAL`),
 *               ui/src/main.tsx (the provider stack this mirrors), ui/src/help/hints.ts
 *               (`hintText` — what `expectHintOpens` asserts), ui/src/components/Hint.tsx
 *               (the bubble it finds through `aria-describedby`),
 *               ui/src/screens/Capability/CapabilityPage.test.tsx (a typical consumer)
 * Tested by:    every `*.test.tsx` under ui/src/screens (they all render through this)
 * Touch when:   the API prefix or the provider stack changes; never for a new repository.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, waitFor, type RenderOptions } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactElement, ReactNode } from 'react'
import { MemoryRouter, Route, Routes } from 'react-router'
import { expect, vi } from 'vitest'
import type { Principal } from '../api/types'
import { hintText, type HintId } from '../help/hints'
import { AuthProvider } from '../lib/auth'

/** A default signed-in approver; override `role` per test to exercise RBAC. */
export const PRINCIPAL: Principal = { id: 'u1', display_name: 'Ada', email: 'ada@example.org', role: 'approver', issuer: 'local' }

/** A route handler: sees the URL and the request init, returns a `Response`. */
type Handler = (url: string, init: RequestInit | undefined) => Response | Promise<Response>

/** A JSON `Response` with the given status. */
export function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

/** An error `Response` in the contract's envelope shape. */
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

/** `route` = the initial URL (query string included); `path` = the route pattern the screen mounts at (`*` by default). `me` is declared but NOT read — the principal comes from the mocked `GET /auth/me`. */
interface Opts extends Omit<RenderOptions, 'wrapper'> {
  route?: string
  path?: string
  me?: Principal | null
}

/** Render inside QueryClient + MemoryRouter + AuthProvider; `/auth/me` is mocked unless `me` is null. */
/**
 * Hover `trigger` (an element carrying `data-hint`) and assert its bubble — found through
 * `aria-describedby`, so a caller's own description is skipped — opens with the registry
 * sentence for `id`. The one hover-opens assertion every on-ramp screen test shares.
 */
export async function expectHintOpens(trigger: Element, id: HintId): Promise<HTMLElement> {
  await userEvent.hover(trigger)
  const ids = (trigger.getAttribute('aria-describedby') ?? '').split(' ')
  const tip = ids.map((i) => document.getElementById(i)).find((el) => el?.getAttribute('role') === 'tooltip')
  if (!tip) throw new Error(`no role=tooltip referenced from aria-describedby on the ${id} trigger`)
  await waitFor(() => expect(tip).toHaveAttribute('data-open', 'true'))
  expect(tip).toHaveTextContent(hintText(id))
  return tip
}

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
