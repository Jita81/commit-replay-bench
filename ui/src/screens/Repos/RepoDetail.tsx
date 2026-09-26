/**
 * Repository detail — the repository as an instrument: probe, change profile, mined tasks,
 * configuration (/repos/:name).
 *
 * Navigation
 * ----------
 * What it is:   The screen at /repos/:name with four tabs: Overview (task counts, probe,
 *               the posture panel — qualified N of M, ADR-0019 — and next steps), Change profile
 *               (class × size histogram), Tasks (the mined
 *               `TaskSpec`s) and Configuration.
 * What it does: Shows what the instrument knows about one repository: whether it can run the
 *               repo's tests (the probe pill with the runner's own summary), how many
 *               replayable commits were mined and how many are gold-clean, and how the repo's
 *               real commits distribute over (class × size) — the denominator behind coverage.
 *               Operators can probe now or start a run from here.
 * How:          `useRepo` / `useRepoProfile` / `useRepoTasks`; the tab lives in `?tab=` so a
 *               link can land on Configuration (an unknown value is Overview);
 *               `RunNewDialog` is mounted for "Start a run"; the Configuration tab is keyed by
 *               repo name so it remounts per repo. Next steps lead to the journey (the
 *               Connection walk, the Factory) as well as the instrument screens.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/api/hooks.ts (`useRepo`, `useRepoProfile`, `useRepoTasks`,
 *               `useProbeRepo`), ui/src/api/types.ts (`RepoDetail`, `TaskSpec`,
 *               `ProfileCell`), ui/src/screens/Repos/RepoConfigTab.tsx (the fourth tab),
 *               ui/src/screens/Runs/RunNewDialog.tsx (start a run),
 *               ui/src/screens/Connect/ConnectPage.tsx (`ConnectRepoPage`) and ui/src/screens/Factory/FactoryPage.tsx
 *               (where Next steps lead), src/crb/server/routes/repos.py (detail, profile,
 *               tasks, probe)
 * Tested by:    ui/src/screens/Repos/RepoDetail.test.tsx (Next steps, `?tab=`, the operator-only
 *               run button), ui/e2e/walkthrough/02-repo-onboard.spec.ts (probe pill reads OK
 *               with the runner's summary), ui/e2e/walkthrough/03-mine.spec.ts (the Tasks tab
 *               lists a mined task), ui/e2e/walkthrough/repo-config.spec.ts
 * Touch when:   a field is added to `GET /repos/{name}` or the profile (docs/API.md "Repos")
 *               — type it in ui/src/api/types.ts first; never for a new repository.
 */
import { useMemo, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router'
import { useProbeRepo, useRepo, useRepoProfile, useRepoTasks } from '../../api/hooks'
import type { ProfileCell, RepoDetail as RepoDetailT, TaskSpec } from '../../api/types'
import { Button, LinkButton } from '../../components/Button'
import { Card } from '../../components/Card'
import { DataTable, type Column } from '../../components/DataTable'
import { EmptyState } from '../../components/EmptyState'
import { ErrorState } from '../../components/ErrorState'
import { Hint } from '../../components/Hint'
import { PageHeader } from '../../components/PageHeader'
import { Pill } from '../../components/Pill'
import { QueryBoundary } from '../../components/QueryBoundary'
import { ShortId } from '../../components/ShortId'
import { StatTile } from '../../components/StatTile'
import { useAuth } from '../../lib/auth'
import { fmtDate, fmtInt, fmtPct, shortId, wilson } from '../../lib/format'
import { probeDisplay } from '../../lib/verdict'
import { RunNewDialog } from '../Runs/RunNewDialog'
import { PosturePanel } from './PosturePanel'
import { RepoConfigTab } from './RepoConfigTab'

/** The four tabs. */
type Tab = 'overview' | 'profile' | 'tasks' | 'config'
const TABS: readonly Tab[] = ['overview', 'profile', 'tasks', 'config']

const SIZE_ORDER = ['XS', 'S', 'M', 'L', 'XL']

/** The change profile as a heat-mapped class × size table with row / column totals and shares. */
function ProfileTable({ cells, classes, sizes, total }: { cells: ProfileCell[]; classes: string[]; sizes: string[]; total: number }) {
  const idx = new Map(cells.map((c) => [`${c.capability_class}|${c.size}`, c]))
  const sizeList = sizes.length ? [...sizes].sort((a, b) => SIZE_ORDER.indexOf(a) - SIZE_ORDER.indexOf(b)) : SIZE_ORDER
  const rowTotals = new Map<string, number>()
  for (const c of cells) rowTotals.set(c.capability_class, (rowTotals.get(c.capability_class) ?? 0) + c.count)
  const colTotals = new Map<string, number>()
  for (const c of cells) colTotals.set(c.size, (colTotals.get(c.size) ?? 0) + c.count)
  const max = Math.max(1, ...cells.map((c) => c.count))
  // focusable: the profile table scrolls sideways at phone width (WCAG 2.1.1, axe scrollable-region-focusable at 375 px)
  return (
    <div className="overflow-auto rounded-[var(--radius-control)] border border-border" tabIndex={0} role="region" aria-label="Change profile, scrollable">
      <table className="num w-full border-collapse text-[13px]">
        <caption className="sr-only">
          Change profile: commits per capability class and size tier over {fmtInt(total)} classified commits. This is a census of the examined history, not a sample: a cell with no commits reads 0 (measured), and shares are exact fractions of the census, so they carry no confidence interval.
        </caption>
        <thead className="bg-surface-high">
          <tr>
            <th scope="col" className="label border-b border-border px-3 py-2 text-left">
              <Hint id="col.profile.class">Class</Hint>
            </th>
            {sizeList.map((s) => (
              <th key={s} scope="col" className="label border-b border-border px-3 py-2 text-right">
                <Hint id="col.profile.size">{s}</Hint>
              </th>
            ))}
            <th scope="col" className="label border-b border-border px-3 py-2 text-right">
              <Hint id="col.profile.total">Total</Hint>
            </th>
            <th scope="col" className="label border-b border-border px-3 py-2 text-right">
              <Hint id="col.profile.share">Share</Hint>
            </th>
          </tr>
        </thead>
        <tbody>
          {classes.map((cls) => {
            const rt = rowTotals.get(cls) ?? 0
            return (
              <tr key={cls} className="border-b border-border last:border-b-0">
                <th scope="row" className="px-3 py-1.5 text-left font-mono text-xs font-normal text-on-surface">
                  {cls}
                </th>
                {sizeList.map((s) => {
                  const c = idx.get(`${cls}|${s}`)
                  // The API lists only cells with commits; the profile walked EVERY commit
                  // in the window, so an absent cell is a measured zero of the census, not
                  // an unmeasured cell (unlike the capability map, where absence is
                  // NOT_YET_MEASURED). Rendered as an explicit 0 with that reading.
                  const n = c?.count ?? 0
                  const alpha = n === 0 ? 0 : 0.15 + 0.6 * (n / max)
                  return (
                    <td key={s} className="px-3 py-1.5 text-right" style={n ? { background: `color-mix(in srgb, var(--trust) ${Math.round(alpha * 100)}%, transparent)` } : undefined}>
                      {/* one hint for every cell of the census (dense: hover and tap, not a tab stop each) */}
                      <Hint id="chart.profile.cell" tabStop={false}>
                        {n === 0 ? <span className="text-on-surface-muted" aria-label="0 commits">0</span> : fmtInt(n)}
                      </Hint>
                    </td>
                  )
                })}
                <td className="px-3 py-1.5 text-right font-semibold">{fmtInt(rt)}</td>
                <td className="px-3 py-1.5 text-right text-on-surface-muted">{total ? fmtPct(rt / total, 0) : '—'}</td>
              </tr>
            )
          })}
          <tr className="bg-surface-high font-semibold">
            <th scope="row" className="px-3 py-1.5 text-left text-xs">
              Total
            </th>
            {sizeList.map((s) => (
              <td key={s} className="px-3 py-1.5 text-right">
                {fmtInt(colTotals.get(s) ?? 0)}
              </td>
            ))}
            <td className="px-3 py-1.5 text-right">{fmtInt(total)}</td>
            <td className="px-3 py-1.5 text-right">100%</td>
          </tr>
        </tbody>
      </table>
    </div>
  )
}

/** Task-count tiles, the probe card (with "Probe now" for operators) and the next-step links. */
function Overview({ repo, onStartRun }: { repo: RepoDetailT; onStartRun: () => void }) {
  const { can } = useAuth()
  const probe = useProbeRepo()
  const navigate = useNavigate()
  const d = probeDisplay(repo.probe.status)
  const tc = repo.task_counts
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap gap-3">
        <StatTile label="Replayable tasks" hint="stat.repo.tasks" value={fmtInt(tc.total)} n={tc.total} apparatus="mined at the commit's parent, RED-checked" />
        <StatTile label="Gold-clean" hint="stat.repo.gold" value={tc.total ? fmtPct(tc.gold_clean / tc.total, 0) : '—'} n={tc.total} ci={tc.total ? wilson(tc.gold_clean, tc.total) : null} apparatus={`${fmtInt(tc.gold_clean)} clean · ${fmtInt(tc.gold_failed)} failed · ${fmtInt(tc.unchecked)} unchecked · Wilson 95% over the mined tasks`} />
        <StatTile label="Hard pool" hint="stat.repo.hard" value={fmtInt(tc.hard)} n={tc.total} apparatus={`${fmtInt(tc.standard)} standard · ${fmtInt(tc.hard)} hard`} />
      </div>
      <Card
        title="Toolchain probe"
        actions={
          can('operator') && (
            <Button size="sm" onClick={() => probe.mutate(repo.name, { onSuccess: (run) => navigate(`/runs/${run.id}`) })} disabled={probe.isPending} hint="button.repo.probe_now">
              {probe.isPending ? 'Enqueuing…' : 'Probe now'}
            </Button>
          )
        }
      >
        <div className="flex flex-wrap items-center gap-3 text-sm">
          <Pill tone={d.tone} glyph={d.glyph} label={d.describe} data-testid="repo-probe" hint="pill.repo.probe">
            {d.label}
          </Pill>
          <span className="text-on-surface-muted" data-testid="repo-probe-detail">
            {repo.probe.detail || 'The probe runs the configured known-green scope through the sandboxed runner.'}
          </span>
          {repo.probe.checked && <span className="text-xs text-on-surface-muted">checked {fmtDate(repo.probe.checked)}</span>}
          {repo.probe.run_id && (
            <Hint as={Link} id="link.repo.probe_run" to={`/runs/${repo.probe.run_id}`} className="font-mono text-xs">
              run {shortId(repo.probe.run_id, 8)}
            </Hint>
          )}
        </div>
        {probe.isError && (
          <div className="mt-3">
            <ErrorState compact error={probe.error} />
          </div>
        )}
      </Card>
      <PosturePanel name={repo.name} />
      <Card title="Next steps">
        <div className="flex flex-wrap gap-2">
          {can('operator') && (
            <Button variant="filled" onClick={onStartRun} hint="button.repo.start_run">
              Start a run
            </Button>
          )}
          <LinkButton to={`/connect/${encodeURIComponent(repo.name)}`} hint="button.repo.next_steps">
            Connection walk
          </LinkButton>
          <LinkButton to={`/factory?repo=${encodeURIComponent(repo.name)}`} hint="button.repo.next_steps">
            Factory
          </LinkButton>
          <LinkButton to={`/capability?repo=${encodeURIComponent(repo.name)}`} hint="button.repo.next_steps">
            Capability map
          </LinkButton>
          <LinkButton to={`/oracle?repo=${encodeURIComponent(repo.name)}`} hint="button.repo.next_steps">
            Oracle adequacy
          </LinkButton>
          <LinkButton to={`/runs?repo=${encodeURIComponent(repo.name)}`} hint="button.repo.next_steps">
            Runs
          </LinkButton>
        </div>
      </Card>
    </div>
  )
}

/** The mined tasks with class, size, pool, churn, gold status and RED-checked. */
function TasksTab({ name }: { name: string }) {
  const tasks = useRepoTasks(name, { limit: 500 })
  const columns = useMemo<Column<TaskSpec>[]>(
    () => [
      { key: 'task_id', header: 'Task', hint: 'col.tasks.task', mono: true, sortValue: (t) => t.task_id, cell: (t) => <Link to={`/tasks/${encodeURIComponent(t.repo)}/${t.task_id}`}><ShortId value={t.task_id} /></Link> },
      { key: 'subject', header: 'Subject', hint: 'col.tasks.subject', sortValue: (t) => t.subject, cell: (t) => <span className="line-clamp-1">{t.subject}</span> },
      { key: 'class', header: 'Class', hint: 'col.tasks.class', mono: true, sortValue: (t) => t.capability_class, cell: (t) => t.capability_class },
      { key: 'size', header: 'Size', hint: 'col.tasks.size', sortValue: (t) => SIZE_ORDER.indexOf(t.size), cell: (t) => <span className="font-mono text-xs">{t.size}</span> },
      { key: 'pool', header: 'Pool', hint: 'col.tasks.pool', sortValue: (t) => t.pool, cell: (t) => t.pool, hideBelowMd: true },
      { key: 'churn', header: 'Churn', hint: 'col.tasks.churn', numeric: true, sortValue: (t) => t.src_churn, cell: (t) => fmtInt(t.src_churn), hideBelowMd: true },
      {
        key: 'gold',
        header: 'Gold',
        hint: 'col.tasks.gold',
        sortValue: (t) => (t.gold_clean === null ? -1 : Number(t.gold_clean)),
        cell: (t) =>
          t.gold_clean === null ? (
            <Pill tone="muted" glyph="·" size="xs" label="Gold status: unchecked" hint="pill.tasks.gold" tabStop={false}>
              unchecked
            </Pill>
          ) : t.gold_clean ? (
            <Pill tone="green" glyph="✓" size="xs" label="Gold status: clean" hint="pill.tasks.gold" tabStop={false}>
              clean
            </Pill>
          ) : (
            <Pill tone="red" glyph="✗" size="xs" label={`Gold status: failed${t.gold_note ? ` — ${t.gold_note}` : ''}`} hint="pill.tasks.gold" tabStop={false}>
              failed
            </Pill>
          ),
      },
      { key: 'red', header: 'RED-checked', hint: 'col.tasks.red', sortValue: (t) => Number(t.red_checked), cell: (t) => (t.red_checked ? '✓' : '—'), hideBelowMd: true },
      { key: 'authored', header: 'Authored', hint: 'col.tasks.authored', sortValue: (t) => t.authored, cell: (t) => <span className="text-xs text-on-surface-muted">{fmtDate(t.authored)}</span>, hideBelowMd: true },
    ],
    [],
  )
  return (
    <Card padded={false} title="Mined tasks">
      <QueryBoundary query={tasks} loading="Loading tasks…">
        {(page) => (
          <DataTable
            rows={page.items}
            columns={columns}
            rowKey={(t) => t.task_id}
            caption={`Mined tasks for ${name}`}
            initialSort={{ key: 'authored', dir: 'desc' }}
            empty={<EmptyState title="No tasks mined yet" reason="Mining walks the history for commits whose tests turn RED at the parent and GREEN with the commit's own source." action={<LinkButton to={`/runs?repo=${encodeURIComponent(name)}&new=mine`}>Start a mine run</LinkButton>} />}
          />
        )}
      </QueryBoundary>
    </Card>
  )
}

/** The screen: the tab is `?tab=` (Overview when absent or unknown); the config tab is keyed by repo name. */
export function RepoDetail() {
  const { name = '' } = useParams()
  const repo = useRepo(name)
  const profile = useRepoProfile(name)
  const [params, setParams] = useSearchParams()
  const wanted = params.get('tab')
  const tab: Tab = TABS.includes(wanted as Tab) ? (wanted as Tab) : 'overview'
  const setTab = (t: Tab) => {
    const next = new URLSearchParams(params)
    if (t === 'overview') next.delete('tab')
    else next.set('tab', t)
    setParams(next, { replace: true })
  }
  const [starting, setStarting] = useState(false)
  const navigate = useNavigate()

  const tabs: Array<{ id: Tab; label: string }> = [
    { id: 'overview', label: 'Overview' },
    { id: 'profile', label: 'Change profile' },
    { id: 'tasks', label: 'Tasks' },
    { id: 'config', label: 'Configuration' },
  ]

  return (
    <>
      <PageHeader eyebrow="Instrument · Repositories" title={name} purpose="The repository as an instrument: probe, mined tasks, change profile, and the config that governs how its commits are replayed." />
      <div role="tablist" aria-label="Repository sections" className="flex gap-1 border-b border-border">
        {tabs.map((t) => (
          <Hint
            as="button"
            key={t.id}
            id={`tab.repo.${t.id}`}
            role="tab"
            type="button"
            aria-selected={tab === t.id}
            onClick={() => setTab(t.id)}
            className={`-mb-px h-10 border-b-2 px-3 text-sm ${tab === t.id ? 'border-primary font-semibold text-primary' : 'border-transparent text-on-surface-muted hover:text-on-surface'}`}
          >
            {t.label}
          </Hint>
        ))}
      </div>
      <QueryBoundary query={repo} loading="Loading repository…">
        {(r) => (
          <div role="tabpanel">
            {tab === 'overview' && <Overview repo={r} onStartRun={() => setStarting(true)} />}
            {tab === 'profile' && (
              <Card title="Change profile" eyebrow="class × size histogram">
                <QueryBoundary query={profile} loading="Computing the change profile…">
                  {(p) =>
                    p.cells.length === 0 ? (
                      <EmptyState title="No change profile yet" reason="The profile is the class × size histogram of mined commits. Mine the repo to populate it." />
                    ) : (
                      <ProfileTable cells={p.cells} classes={p.classes} sizes={p.sizes} total={p.n_commits} />
                    )
                  }
                </QueryBoundary>
              </Card>
            )}
            {tab === 'tasks' && <TasksTab name={name} />}
            {tab === 'config' && <RepoConfigTab key={r.name} repo={r} />}
          </div>
        )}
      </QueryBoundary>
      <RunNewDialog open={starting} onClose={() => setStarting(false)} repo={name} onCreated={(run) => navigate(`/runs/${run.id}`)} />
    </>
  )
}

export default RepoDetail
