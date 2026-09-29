/**
 * Entry point — mounts the app under StrictMode, the query client and the browser router.
 *
 * Navigation
 * ----------
 * What it is:   The Vite entry module (`index.html` → `#root`).
 * What it does: Creates the one `QueryClient` (`makeQueryClient`: the UI's defaults — no
 *               refetch on window focus, no retry, 10 s stale — and every act re-reading the
 *               decisions inbox) and renders `App` inside `BrowserRouter`; fails loudly if
 *               `#root` is missing.
 * How:          `createRoot(...).render(...)`; the global stylesheet is imported here.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/App.tsx (the route table), ui/src/api/queryClient.ts (the client and
 *               its defaults), ui/src/api/hooks.ts (hooks opt in to polling
 *               per query on top of these defaults), ui/src/index.css (the design tokens),
 *               ui/index.html (the host page and the anti-FOUC theme script)
 * Tested by:    ui/e2e/smoke.spec.ts (the built bundle boots against a mocked API);
 *               screen tests build their own client in ui/src/test/utils.tsx
 * Touch when:   never for a new repository; the provider stack changes (a query default for
 *               every screen is ui/src/api/queryClient.ts's).
 */
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router'
import { QueryClientProvider } from '@tanstack/react-query'
import { App } from './App'
import { makeQueryClient } from './api/queryClient'
import './index.css'

// The app's defaults (no refetch on focus, no retry, 10 s stale) and the rule that every act
// re-reads the decisions inbox live in ui/src/api/queryClient.ts.
const queryClient = makeQueryClient()

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
