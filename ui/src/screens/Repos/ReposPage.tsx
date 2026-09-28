/**
 * Repos — every repository under measurement: probe status, mined tasks, last run (/repos).
 *
 * Navigation
 * ----------
 * What it is:   The screen at /repos — the first screen a new deployment shows — and the
 *               host of the Add-repo dialog.
 * What it does: Lists every page of `GET /repos` (never only the first page) with the probe pill (can the instrument run this repo's
 *               tests?), task counts, gold-clean and hard-pool counts and the last run's kind
 *               and status; rows open the repo page. Operators get "Add repo"; a viewer's
 *               empty state says to ask an operator rather than offering a button that would
 *               403. A line above the table says how many of the served total are listed,
 *               so a list that is not whole says so (G-229).
 * How:          `useAllRepos` (every page, as each journey screen reads) → `DataTable`; `can('operator')` gates the action; the dialog
 *               navigates to the new repo on success.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/api/hooks.ts (`useAllRepos`), ui/src/api/types.ts (`RepoSummary`),
 *               ui/src/screens/Repos/RepoNewDialog.tsx, ui/src/screens/Repos/RepoDetail.tsx
 *               (where a row leads), ui/src/lib/verdict.ts (`probeDisplay`,
 *               `runStatusDisplay`), src/crb/server/routes/repos.py
 * Tested by:    ui/src/screens/Repos/ReposPage.test.tsx (rows, probe pills, the empty state per
 *               role, every page read and the count line), ui/e2e/walkthrough/02-repo-onboard.spec.ts (Add repo → the repo page),
 *               ui/e2e/walkthrough/07-settings-and-a11y.spec.ts (axe)
 * Touch when:   never for a new repository — it appears here once added; a column is worth
 *               adding from `GET /repos` (docs/API.md).
 */
import { useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router'
import { useAllRepos } from '../../api/hooks'
import type { RepoSummary } from '../../api/types'
import { Button } from '../../components/Button'
import { Card } from '../../components/Card'
import { DataTable, type Column } from '../../components/DataTable'
import { EmptyState } from '../../components/EmptyState'
import { Hint } from '../../components/Hint'
import { PageHeader } from '../../components/PageHeader'
import { Pill } from '../../components/Pill'
import { QueryBoundary } from '../../components/QueryBoundary'
import { useAuth } from '../../lib/auth'
import { fmtDate, fmtInt } from '../../lib/format'
import { probeDisplay, runStatusDisplay } from '../../lib/verdict'
import { RepoNewDialog } from './RepoNewDialog'

/** The screen; "Add repo" only for operators. */
export function ReposPage() {
  const repos = useAllRepos()
  const { can } = useAuth()
  const navigate = useNavigate()
  const [adding, setAdding] = useState(false)

  const columns = useMemo<Column<RepoSummary>[]>(
    () => [
      {
        key: 'name',
        header: 'Repo',
        hint: 'col.repos.name',
        sortValue: (r) => r.name,
        cell: (r) => (
          <Link to={`/repos/${encodeURIComponent(r.name)}`} className="font-semibold">
            {r.name}
          </Link>
        ),
      },
      { key: 'language', header: 'Language', hint: 'col.repos.language', sortValue: (r) => r.language, cell: (r) => <span className="font-mono text-xs">{r.language}{r.runner ? ` · ${r.runner}` : ''}</span> },
      {
        key: 'probe',
        header: 'Probe',
        hint: 'col.repos.probe',
        sortValue: (r) => r.probe.status,
        cell: (r) => {
          const d = probeDisplay(r.probe.status)
          return (
            <Pill tone={d.tone} glyph={d.glyph} size="xs" label={`${d.describe}${r.probe.detail ? `: ${r.probe.detail}` : ''}`} hint={d.hint}>
              {d.label}
            </Pill>
          )
        },
      },
      { key: 'tasks', header: 'Tasks', hint: 'col.repos.tasks', numeric: true, sortValue: (r) => r.task_counts.total, cell: (r) => fmtInt(r.task_counts.total) },
      { key: 'gold', header: 'Gold-clean', hint: 'col.repos.gold', numeric: true, sortValue: (r) => r.task_counts.gold_clean, cell: (r) => fmtInt(r.task_counts.gold_clean), hideBelowMd: true },
      { key: 'hard', header: 'Hard pool', hint: 'col.repos.hard', numeric: true, sortValue: (r) => r.task_counts.hard, cell: (r) => fmtInt(r.task_counts.hard), hideBelowMd: true },
      {
        key: 'last_run',
        header: 'Last run',
        hint: 'col.repos.last_run',
        sortValue: (r) => r.last_run?.finished ?? '',
        cell: (r) => {
          if (!r.last_run) return <span className="text-on-surface-muted">—</span>
          const d = runStatusDisplay(r.last_run.status)
          return (
            <span className="inline-flex items-center gap-2">
              <Pill tone={d.tone} glyph={d.glyph} size="xs" label={d.describe} hint={d.hint}>
                {r.last_run.kind}
              </Pill>
              <span className="text-xs text-on-surface-muted">{fmtDate(r.last_run.finished)}</span>
            </span>
          )
        },
      },
    ],
    [],
  )

  return (
    <>
      <PageHeader
        title="Repos"
        purpose="Every repository under measurement: its probe status (can the instrument run its tests?), how many replayable commits were mined, and the last run."
        actions={
          can('operator') && (
            <Button variant="filled" onClick={() => setAdding(true)} hint="button.repos.add">
              Add repo
            </Button>
          )
        }
      />
      <Card padded={false}>
        <QueryBoundary query={repos} loading="Loading repositories…">
          {(page) => (
            <>
            {page.total > 0 && (
              <Hint as="p" id="summary.repos.count" className="m-0 px-4 pt-3 text-xs text-on-surface-muted" data-testid="repos-count">
                {page.items.length === page.total
                  ? page.total === 1
                    ? 'The one repository is listed.'
                    : `All ${fmtInt(page.total)} repositories are listed.`
                  : `${fmtInt(page.items.length)} of ${fmtInt(page.total)} repositories are listed: the list changed while it was read. Reload the page for all of them.`}
              </Hint>
            )}
            <DataTable
              rows={page.items}
              columns={columns}
              rowKey={(r) => r.name}
              caption="Repositories under measurement"
              initialSort={{ key: 'name', dir: 'asc' }}
              onRowClick={(r) => navigate(`/repos/${encodeURIComponent(r.name)}`)}
              empty={
                <EmptyState
                  title="No repositories yet"
                  reason="A repo is the unit of measurement. Add one, probe its toolchain, then mine its history for replayable commits."
                  action={can('operator') ? <Button variant="filled" onClick={() => setAdding(true)} hint="button.repos.add">Add the first repo</Button> : <span className="text-xs text-on-surface-muted">Ask an operator to add one.</span>}
                />
              }
            />
            </>
          )}
        </QueryBoundary>
      </Card>
      <RepoNewDialog open={adding} onClose={() => setAdding(false)} onCreated={(name) => navigate(`/repos/${encodeURIComponent(name)}`)} />
    </>
  )
}

export default ReposPage
