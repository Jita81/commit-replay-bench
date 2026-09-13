import { useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router'
import { useProbeRepo, useRepo, useRepoProfile, useRepoTasks } from '../../api/hooks'
import type { ProfileCell, RepoDetail as RepoDetailT, TaskSpec } from '../../api/types'
import { Button, LinkButton } from '../../components/Button'
import { Card } from '../../components/Card'
import { DataTable, type Column } from '../../components/DataTable'
import { EmptyState } from '../../components/EmptyState'
import { ErrorState } from '../../components/ErrorState'
import { JsonView } from '../../components/JsonView'
import { PageHeader } from '../../components/PageHeader'
import { Pill } from '../../components/Pill'
import { QueryBoundary } from '../../components/QueryBoundary'
import { StatTile } from '../../components/StatTile'
import { useAuth } from '../../lib/auth'
import { fmtDate, fmtInt, fmtPct, shortId } from '../../lib/format'
import { probeDisplay } from '../../lib/verdict'
import { RunNewDialog } from '../Runs/RunNewDialog'

type Tab = 'overview' | 'profile' | 'tasks' | 'config'

const SIZE_ORDER = ['XS', 'S', 'M', 'L', 'XL']

function ProfileTable({ cells, classes, sizes, total }: { cells: ProfileCell[]; classes: string[]; sizes: string[]; total: number }) {
  const idx = new Map(cells.map((c) => [`${c.capability_class}|${c.size}`, c]))
  const sizeList = sizes.length ? [...sizes].sort((a, b) => SIZE_ORDER.indexOf(a) - SIZE_ORDER.indexOf(b)) : SIZE_ORDER
  const rowTotals = new Map<string, number>()
  for (const c of cells) rowTotals.set(c.capability_class, (rowTotals.get(c.capability_class) ?? 0) + c.count)
  const colTotals = new Map<string, number>()
  for (const c of cells) colTotals.set(c.size, (colTotals.get(c.size) ?? 0) + c.count)
  const max = Math.max(1, ...cells.map((c) => c.count))
  return (
    <div className="overflow-auto rounded-[var(--radius-control)] border border-border">
      <table className="num w-full border-collapse text-[13px]">
        <caption className="sr-only">Change profile: commits per capability class and size tier</caption>
        <thead className="bg-surface-high">
          <tr>
            <th scope="col" className="label border-b border-border px-3 py-2 text-left">
              Class
            </th>
            {sizeList.map((s) => (
              <th key={s} scope="col" className="label border-b border-border px-3 py-2 text-right">
                {s}
              </th>
            ))}
            <th scope="col" className="label border-b border-border px-3 py-2 text-right">
              Total
            </th>
            <th scope="col" className="label border-b border-border px-3 py-2 text-right">
              Share
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
                  const n = c?.count ?? 0
                  const alpha = n === 0 ? 0 : 0.15 + 0.6 * (n / max)
                  return (
                    <td key={s} className="px-3 py-1.5 text-right" style={n ? { background: `color-mix(in srgb, var(--trust) ${Math.round(alpha * 100)}%, transparent)` } : undefined}>
                      {n === 0 ? <span className="text-on-surface-muted">·</span> : fmtInt(n)}
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

function Overview({ repo, onStartRun }: { repo: RepoDetailT; onStartRun: () => void }) {
  const { can } = useAuth()
  const probe = useProbeRepo()
  const navigate = useNavigate()
  const d = probeDisplay(repo.probe.status)
  const tc = repo.task_counts
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap gap-3">
        <StatTile label="Replayable tasks" value={fmtInt(tc.total)} n={tc.total} apparatus="mined at the commit's parent, RED-checked" />
        <StatTile label="Gold-clean" value={tc.total ? fmtPct(tc.gold_clean / tc.total, 0) : '—'} n={tc.total} apparatus={`${fmtInt(tc.gold_clean)} clean · ${fmtInt(tc.gold_failed)} failed · ${fmtInt(tc.unchecked)} unchecked`} />
        <StatTile label="Hard pool" value={fmtInt(tc.hard)} n={tc.total} apparatus={`${fmtInt(tc.standard)} standard · ${fmtInt(tc.hard)} hard`} />
      </div>
      <Card
        title="Toolchain probe"
        actions={
          can('operator') && (
            <Button size="sm" onClick={() => probe.mutate(repo.name, { onSuccess: (run) => navigate(`/runs/${run.id}`) })} disabled={probe.isPending}>
              {probe.isPending ? 'Enqueuing…' : 'Probe now'}
            </Button>
          )
        }
      >
        <div className="flex flex-wrap items-center gap-3 text-sm">
          <Pill tone={d.tone} glyph={d.glyph} label={d.describe} data-testid="repo-probe">
            {d.label}
          </Pill>
          <span className="text-on-surface-muted" data-testid="repo-probe-detail">
            {repo.probe.detail || 'The probe runs the configured known-green scope through the sandboxed runner.'}
          </span>
          {repo.probe.checked && <span className="text-xs text-on-surface-muted">checked {fmtDate(repo.probe.checked)}</span>}
          {repo.probe.run_id && (
            <Link to={`/runs/${repo.probe.run_id}`} className="font-mono text-xs">
              run {shortId(repo.probe.run_id, 8)}
            </Link>
          )}
        </div>
        {probe.isError && (
          <div className="mt-3">
            <ErrorState compact error={probe.error} />
          </div>
        )}
      </Card>
      <Card title="Next steps">
        <div className="flex flex-wrap gap-2">
          {can('operator') && (
            <Button variant="filled" onClick={onStartRun}>
              Start a run
            </Button>
          )}
          <LinkButton to={`/capability?repo=${encodeURIComponent(repo.name)}`}>Capability map</LinkButton>
          <LinkButton to={`/oracle?repo=${encodeURIComponent(repo.name)}`}>Oracle adequacy</LinkButton>
          <LinkButton to={`/runs?repo=${encodeURIComponent(repo.name)}`}>Runs</LinkButton>
        </div>
      </Card>
    </div>
  )
}

function TasksTab({ name }: { name: string }) {
  const tasks = useRepoTasks(name, { limit: 500 })
  const columns = useMemo<Column<TaskSpec>[]>(
    () => [
      { key: 'task_id', header: 'Task', mono: true, sortValue: (t) => t.task_id, cell: (t) => <Link to={`/tasks/${encodeURIComponent(t.repo)}/${t.task_id}`} title={t.task_id}>{shortId(t.task_id)}</Link> },
      { key: 'subject', header: 'Subject', sortValue: (t) => t.subject, cell: (t) => <span className="line-clamp-1" title={t.subject}>{t.subject}</span> },
      { key: 'class', header: 'Class', mono: true, sortValue: (t) => t.capability_class, cell: (t) => t.capability_class },
      { key: 'size', header: 'Size', sortValue: (t) => SIZE_ORDER.indexOf(t.size), cell: (t) => <span className="font-mono text-xs">{t.size}</span> },
      { key: 'pool', header: 'Pool', sortValue: (t) => t.pool, cell: (t) => t.pool, hideBelowMd: true },
      { key: 'churn', header: 'Churn', numeric: true, sortValue: (t) => t.src_churn, cell: (t) => fmtInt(t.src_churn), hideBelowMd: true },
      {
        key: 'gold',
        header: 'Gold',
        sortValue: (t) => (t.gold_clean === null ? -1 : Number(t.gold_clean)),
        cell: (t) =>
          t.gold_clean === null ? (
            <Pill tone="muted" glyph="·" size="xs" label="Gold status: unchecked">unchecked</Pill>
          ) : t.gold_clean ? (
            <Pill tone="green" glyph="✓" size="xs" label="Gold status: clean">clean</Pill>
          ) : (
            <Pill tone="red" glyph="✗" size="xs" label={`Gold status: failed${t.gold_note ? ` — ${t.gold_note}` : ''}`}>failed</Pill>
          ),
      },
      { key: 'red', header: 'RED-checked', sortValue: (t) => Number(t.red_checked), cell: (t) => (t.red_checked ? '✓' : '—'), hideBelowMd: true },
      { key: 'authored', header: 'Authored', sortValue: (t) => t.authored, cell: (t) => <span className="text-xs text-on-surface-muted">{fmtDate(t.authored)}</span>, hideBelowMd: true },
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

export function RepoDetail() {
  const { name = '' } = useParams()
  const repo = useRepo(name)
  const profile = useRepoProfile(name)
  const [tab, setTab] = useState<Tab>('overview')
  const [starting, setStarting] = useState(false)
  const navigate = useNavigate()

  const tabs: Array<{ id: Tab; label: string }> = [
    { id: 'overview', label: 'Overview' },
    { id: 'profile', label: 'Change profile' },
    { id: 'tasks', label: 'Tasks' },
    { id: 'config', label: 'Config' },
  ]

  return (
    <>
      <PageHeader eyebrow="Repositories" title={name} purpose="The repository as an instrument: probe, mined tasks, change profile, and the config that governs how its commits are replayed." />
      <div role="tablist" aria-label="Repository sections" className="flex gap-1 border-b border-border">
        {tabs.map((t) => (
          <button
            key={t.id}
            role="tab"
            type="button"
            aria-selected={tab === t.id}
            onClick={() => setTab(t.id)}
            className={`-mb-px h-10 border-b-2 px-3 text-sm ${tab === t.id ? 'border-primary font-semibold text-primary' : 'border-transparent text-on-surface-muted hover:text-on-surface'}`}
          >
            {t.label}
          </button>
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
            {tab === 'config' && (
              <Card title="Repo config" eyebrow="layout · runner · belt scope · mining">
                <JsonView value={r.config} initiallyOpen label="Repository configuration" />
              </Card>
            )}
          </div>
        )}
      </QueryBoundary>
      <RunNewDialog open={starting} onClose={() => setStarting(false)} repo={name} onCreated={(run) => navigate(`/runs/${run.id}`)} />
    </>
  )
}

export default RepoDetail
