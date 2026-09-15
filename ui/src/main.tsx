/**
 * Entry point — mounts the app under StrictMode, the query client and the browser router.
 *
 * Navigation
 * ----------
 * What it is:   The Vite entry module (`index.html` → `#root`).
 * What it does: Creates the one `QueryClient` with the UI's defaults — no refetch on window
 *               focus (a governance surface never changes under the reader's eye), no retry,
 *               10 s stale — and renders `App` inside `BrowserRouter`; fails loudly if `#root`
 *               is missing.
 * How:          `createRoot(...).render(...)`; the global stylesheet is imported here.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/App.tsx (the route table), ui/src/api/hooks.ts (hooks opt in to polling
 *               per query on top of these defaults), ui/src/index.css (the design tokens),
 *               ui/index.html (the host page and the anti-FOUC theme script)
 * Tested by:    ui/e2e/smoke.spec.ts (the built bundle boots against a mocked API);
 *               screen tests build their own client in ui/src/test/utils.tsx
 * Touch when:   a query default changes for every screen (keep ui/src/test/utils.tsx in
 *               step); never for a new repository.
 */
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { App } from './App'
import './index.css'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // Hooks opt in to polling explicitly; nothing refetches on focus by default
      // so a governance surface never silently changes under the reader's eye.
      refetchOnWindowFocus: false,
      retry: false,
      staleTime: 10_000,
    },
  },
})

const root = document.getElementById('root')
if (!root) throw new Error('#root missing from index.html')

createRoot(root).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
)
