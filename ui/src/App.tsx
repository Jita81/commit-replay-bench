/**
 * Route table — everything but /login sits inside the authenticated shell; unknown routes render the 404 inside it.
 *
 * Navigation
 * ----------
 * What it is:   The `App` component: the auth provider and the route table.
 * What it does: Maps every URL to a screen: `/login` outside the shell; everything else under
 *               `RequireAuth` + `Layout` — repos, runs, tasks, capability, routing, oracle,
 *               learn, ledger, sign-off, factory, settings — with `/` redirecting to `/repos`
 *               and `*` rendering the 404 with the navigation intact.
 * How:          react-router `<Routes>`; the layout route has no path so its children share
 *               the shell.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/main.tsx (mounts this under the router and the query client),
 *               ui/src/lib/auth.tsx (`AuthProvider`, `RequireAuth`), ui/src/components/Layout.tsx
 *               (the shell and its `NAV`, which must list the same screens),
 *               ui/src/screens/NotFoundPage.tsx (the `*` route)
 * Tested by:    ui/e2e/smoke.spec.ts (login and the shell), ui/e2e/walkthrough/01-login.spec.ts;
 *               screen tests mount screens directly through ui/src/test/utils.tsx
 * Touch when:   a screen is added — one `<Route>` here and its `NAV` entry in
 *               ui/src/components/Layout.tsx; never for a new repository.
 */
import { Navigate, Route, Routes } from 'react-router'
import { Layout } from './components/Layout'
import { AuthProvider, RequireAuth } from './lib/auth'
import { CapabilityPage } from './screens/Capability/CapabilityPage'
import { FactoryPage } from './screens/Factory/FactoryPage'
import { LedgerPage } from './screens/Ledger/LedgerPage'
import { LoginPage } from './screens/Login/LoginPage'
import { NotFoundPage } from './screens/NotFoundPage'
import { LearnPage } from './screens/Learn/LearnPage'
import { OraclePage } from './screens/Oracle/OraclePage'
import { RepoDetail } from './screens/Repos/RepoDetail'
import { ReposPage } from './screens/Repos/ReposPage'
import { RoutingPage } from './screens/Routing/RoutingPage'
import { RunDetailPage } from './screens/Runs/RunDetailPage'
import { RunsPage } from './screens/Runs/RunsPage'
import { TaskDetailPage } from './screens/Runs/TaskDetailPage'
import { SettingsPage } from './screens/Settings/SettingsPage'
import { SignoffPage } from './screens/Signoff/SignoffPage'

/**
 * Route table. Everything but /login sits inside the authenticated shell;
 * unknown routes render the 404 INSIDE the shell (nav intact).
 */
export function App() {
  return (
    <AuthProvider>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route
          element={
            <RequireAuth>
              <Layout />
            </RequireAuth>
          }
        >
          <Route index element={<Navigate to="/repos" replace />} />
          <Route path="/repos" element={<ReposPage />} />
          <Route path="/repos/:name" element={<RepoDetail />} />
          <Route path="/runs" element={<RunsPage />} />
          <Route path="/runs/:id" element={<RunDetailPage />} />
          <Route path="/tasks/:repo/:taskId" element={<TaskDetailPage />} />
          <Route path="/capability" element={<CapabilityPage />} />
          <Route path="/routing" element={<RoutingPage />} />
          <Route path="/oracle" element={<OraclePage />} />
          <Route path="/learn" element={<LearnPage />} />
          <Route path="/ledger" element={<LedgerPage />} />
          <Route path="/signoff" element={<SignoffPage />} />
          <Route path="/factory" element={<FactoryPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="*" element={<NotFoundPage />} />
        </Route>
      </Routes>
    </AuthProvider>
  )
}

export default App
