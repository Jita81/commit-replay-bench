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
