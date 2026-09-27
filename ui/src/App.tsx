/**
 * Route table — everything but /login sits inside the authenticated shell; unknown routes render
 * the 404 inside it.
 *
 * Navigation
 * ----------
 * What it is:   The `App` component: the auth provider and the route table.
 * What it does: Maps every URL to a screen: `/login` outside the shell; everything else under
 *               `RequireAuth` + `Layout` — the journey (home, connect, results, decisions,
 *               factory, posture), the instrument (repos, runs, tasks, capability, routing,
 *               oracle, learn, ledger, sign-off, settings) and help (`/help`, `/help/docs/:name`)
 *               — with `/` redirecting to `/home` and `*` rendering the 404 with the
 *               navigation intact. Every route except `/login`, `/help*` and `*` must have an
 *               entry in ui/src/help/help.ts; its test reads this file.
 * How:          react-router `<Routes>`; the layout route has no path so its children share
 *               the shell.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/main.tsx (mounts this under the router and the query client),
 *               ui/src/lib/auth.tsx (`AuthProvider`, `RequireAuth`), ui/src/components/Layout.tsx
 *               (the shell and its `NAV`, which must list the same screens),
 *               ui/src/help/help.ts (one About entry per route here — the ratchet reads this
 *               file), ui/src/screens/NotFoundPage.tsx (the `*` route)
 * Tested by:    ui/e2e/smoke.spec.ts (login and the shell), ui/e2e/walkthrough/01-login.spec.ts;
 *               screen tests mount screens directly through ui/src/test/utils.tsx
 * Touch when:   a screen is added — one `<Route>` here, its `NAV` entry in
 *               ui/src/components/Layout.tsx and its `HELP` entry in ui/src/help/help.ts;
 *               never for a new repository.
 */
import { Navigate, Route, Routes } from 'react-router'
import { Layout } from './components/Layout'
import { AuthProvider, RequireAuth } from './lib/auth'
import { CapabilityPage } from './screens/Capability/CapabilityPage'
import { ConnectPage, ConnectRepoPage } from './screens/Connect/ConnectPage'
import { MeasurePage } from './screens/Connect/MeasurePage'
import { HomePage } from './screens/Home/HomePage'
import { PosturePage } from './screens/Posture/PosturePage'
import { DecisionsPage } from './screens/Decisions/DecisionsPage'
import { FactoryPage } from './screens/Factory/FactoryPage'
import { IntakePage } from './screens/Factory/IntakePage'
import { DocPage } from './screens/Help/DocPage'
import { HelpPage } from './screens/Help/HelpPage'
import { LedgerPage } from './screens/Ledger/LedgerPage'
import { AcceptInvitePage } from './screens/Invite/AcceptInvitePage'
import { LoginPage } from './screens/Login/LoginPage'
import { NotFoundPage } from './screens/NotFoundPage'
import { LearnPage } from './screens/Learn/LearnPage'
import { OraclePage } from './screens/Oracle/OraclePage'
import { RepoDetail } from './screens/Repos/RepoDetail'
import { ReposPage } from './screens/Repos/ReposPage'
import { ResultsPage } from './screens/Results/ResultsPage'
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
        <Route path="/invite" element={<AcceptInvitePage />} />
        <Route
          element={
            <RequireAuth>
              <Layout />
            </RequireAuth>
          }
        >
          <Route index element={<Navigate to="/home" replace />} />
          <Route path="/home" element={<HomePage />} />
          <Route path="/connect" element={<ConnectPage />} />
          <Route path="/connect/:name" element={<ConnectRepoPage />} />
          <Route path="/connect/:name/measure" element={<MeasurePage />} />
          <Route path="/posture" element={<PosturePage />} />
          <Route path="/results" element={<ResultsPage />} />
          <Route path="/decisions" element={<DecisionsPage />} />
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
          <Route path="/factory/intake" element={<IntakePage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="/help" element={<HelpPage />} />
          <Route path="/help/docs/:name" element={<DocPage />} />
          <Route path="*" element={<NotFoundPage />} />
        </Route>
      </Routes>
    </AuthProvider>
  )
}

export default App
