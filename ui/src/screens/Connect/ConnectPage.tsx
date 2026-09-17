/**
 * Connect — the guided walk from a Git URL to a results page, and the connected repositories.
 *
 * Navigation
 * ----------
 * What it is:   The first screen of the journey (/connect): the repositories already connected
 *               with the stage each is at, and — for one repository (/connect/:name) — the six
 *               stages as a task list (register → probe → mine → oracle → controls → first
 *               measurement) with the action for the next one.
 * What it does: Lets an enterprise tech lead connect a repository and get to a results page
 *               without knowing the product's vocabulary: every stage says what it proves and
 *               what it costs ("no model involved" / "spends model budget"), the status is
 *               derived from the API (`stagesFor`), so the walk resumes where the repository
 *               is, and the action is gated on the operator role like the API is. Nothing here
 *               fabricates progress: a stage is done only when the API holds its evidence.
 * How:          `useAllRepos` → the table; `useRepo` + `useOracle` + `useOracleControls` +
 *               `useCapabilityMap` → `stagesFor` → `<TaskList>`; actions are the existing
 *               mutations (`useProbeRepo`, `useCreateRun`) and dialogs (`RepoNewDialog`,
 *               `RunNewDialog`); a running stage polls its run (`useRun`, poll) and refetches
 *               the inputs when it finishes.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/screens/Connect/connection.ts (the derivation), ui/src/screens/Repos/*
 *               (registration and config live there; this screen links to them),
 *               ui/src/screens/Results/ResultsPage.tsx (where the walk ends),
 *               docs/ONBOARDING-A-REPO.md (the same steps for the CLI)
 * Tested by:    ui/src/screens/Connect/ConnectPage.test.tsx
 * Touch when:   a stage is added (connection.ts first); the API grows a GitHub App install
 *               flow (replace the URL field with the installation's repository picker).
 */

import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router'
import {
  useAllRepos,
  useCapabilityMap,
  useCreateRun,
  useGitHubApp,
  useOracle,
  useOracleControls,
  useProbeRepo,
  useRepo,
  useRun,
} from '../../api/hooks'
import { isApiError } from '../../api/client'
import type { RepoSummary } from '../../api/types'
import { Button, LinkButton } from '../../components/Button'
import { Card } from '../../components/Card'
import { EmptyState } from '../../components/EmptyState'
import { ErrorState } from '../../components/ErrorState'
import { PageHeader } from '../../components/PageHeader'
import { Pill } from '../../components/Pill'
import { useAuth } from '../../lib/auth'
import type { Tone } from '../../lib/verdict'
import { RepoNewDialog } from '../Repos/RepoNewDialog'
import { RunNewDialog } from '../Runs/RunNewDialog'
import { GitHubConnectDialog } from './GitHubConnectDialog'
import { type Stage, type StageStatus, stageSummary, stagesFor } from './connection'

const STATUS_DISPLAY: Record<StageStatus, { label: string; tone: Tone; glyph: string }> = {
  done: { label: 'Done', tone: 'green', glyph: '✓' },
  running: { label: 'In progress', tone: 'blue', glyph: '◐' },
  todo: { label: 'Not started', tone: 'muted', glyph: '○' },
  failed: { label: 'Failed', tone: 'red', glyph: '✕' },
  blocked: { label: 'Waiting', tone: 'muted', glyph: '·' },
}

/** A 404 from the oracle / controls routes means "never run" — a stage state, not an error. */
function notRun(err: unknown): boolean {
  return isApiError(err) && err.status === 404
}

// ---------------------------------------------------------------------------
// /connect — the connected repositories
// ---------------------------------------------------------------------------

export function ConnectPage() {
  const repos = useAllRepos()
  const { can } = useAuth()
  const navigate = useNavigate()
  const gh = useGitHubApp()
  const [params] = useSearchParams()
  // the app's setup callback lands here with ?installation=<id> — open the picker on it
  const landedInstallation = Number(params.get('installation') ?? 0) || 0
  const [newOpen, setNewOpen] = useState(false)
  const [ghOpen, setGhOpen] = useState(landedInstallation > 0)
  const ghConfigured = gh.data?.configured === true

  return (
    <>
      <PageHeader
        eyebrow="Journey · 1 of 4"
        title="Connect a repository"
        purpose="Point the instrument at a repository, let it learn how the code tests itself, and get to a results page. Nothing is written to the repository; the first five stages involve no model."
        actions={
          can('operator') ? (
            <div className="flex flex-wrap gap-2">
              <Button variant={ghConfigured ? 'filled' : 'outlined'} onClick={() => setGhOpen(true)}>
                Connect from GitHub
              </Button>
              <Button variant={ghConfigured ? 'outlined' : 'filled'} onClick={() => setNewOpen(true)}>
                Connect by URL
              </Button>
            </div>
          ) : undefined
        }
      />
      {gh.data && !gh.data.configured && can('admin') && (
        <p className="m-0 -mt-3 text-xs text-on-surface-muted" data-testid="github-app-hint">
          The GitHub App is not configured: an admin registers it once (app id + private key, <code>docs/GITHUB-APP.md</code>) and organisations then install it on the repositories it may see — the enterprise way to connect, no tokens to hand over.
        </p>
      )}
      <Card title="Connected repositories" eyebrow="where each one is on the walk">
        {repos.isPending && <p className="text-sm text-on-surface-muted">Loading…</p>}
        {repos.isError && <ErrorState error={repos.error} onRetry={() => void repos.refetch()} />}
        {repos.data && repos.data.items.length === 0 && (
          <EmptyState
            glyph="⎇"
            title="No repository connected yet"
            reason="Connect one to start the walk: register, probe, mine, oracle, controls, then a first measurement."
            action={can('operator') ? <Button variant="filled" onClick={() => (ghConfigured ? setGhOpen(true) : setNewOpen(true))}>Connect a repository</Button> : undefined}
          />
        )}
        {repos.data && repos.data.items.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-sm" aria-label="Connected repositories">
              <thead>
                <tr className="text-left text-xs text-on-surface-muted">
                  <th className="py-2 pr-4 font-medium">Repository</th>
                  <th className="py-2 pr-4 font-medium">Language</th>
                  <th className="py-2 pr-4 font-medium">Tasks</th>
                  <th className="py-2 pr-4 font-medium">Next stage</th>
                  <th className="py-2 pr-4 font-medium">Last run</th>
                  <th className="py-2 font-medium"></th>
                </tr>
              </thead>
              <tbody>
                {repos.data.items.map((r) => (
                  <RepoRow key={r.name} repo={r} />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      <RepoNewDialog
        open={newOpen}
        onClose={() => setNewOpen(false)}
        onCreated={(name) => {
          setNewOpen(false)
          navigate(`/connect/${encodeURIComponent(name)}`)
        }}
      />
      <GitHubConnectDialog
        open={ghOpen}
        initialInstallation={landedInstallation || undefined}
        onClose={() => setGhOpen(false)}
        onUseUrl={() => {
          setGhOpen(false)
          setNewOpen(true)
        }}
        onConnected={(name) => {
          setGhOpen(false)
          navigate(`/connect/${encodeURIComponent(name)}`)
        }}
      />
    </>
  )
}

function RepoRow({ repo }: { repo: RepoSummary }) {
  // the same inputs the per-repository page uses, so the table never says "oracle next" for
  // a repository that is fully measured (three cached reads per row)
  const oracle = useOracle(repo.name)
  const controls = useOracleControls(repo.name)
  const map = useCapabilityMap(repo.name, ['capability_class', 'size'])
  const stages = stagesFor({
    repo,
    oracle: oracle.data ?? (oracle.isError && notRun(oracle.error) ? null : undefined),
    controls: controls.data ?? (controls.isError && notRun(controls.error) ? null : undefined),
    measuredRows: map.data?.summary.n_total,
  })
  const s = stageSummary(stages)
  const d = STATUS_DISPLAY[s.status]
  return (
    <tr className="border-t border-border">
      <td className="py-2 pr-4 font-mono text-xs">
        <Link to={`/connect/${encodeURIComponent(repo.name)}`}>{repo.name}</Link>
      </td>
      <td className="py-2 pr-4">
        {repo.language}
        {repo.runner ? ` / ${repo.runner}` : ''}
      </td>
      <td className="num py-2 pr-4 font-mono text-xs">
        {repo.task_counts.total} · {repo.task_counts.gold_clean} gold-clean
      </td>
      <td className="py-2 pr-4">
        <Pill tone={d.tone} glyph={d.glyph} size="xs">
          {s.label}
        </Pill>
      </td>
      <td className="py-2 pr-4 font-mono text-xs text-on-surface-muted">
        {repo.last_run ? `${repo.last_run.kind} · ${repo.last_run.status}` : '—'}
      </td>
      <td className="py-2 text-right">
        <LinkButton size="sm" to={`/connect/${encodeURIComponent(repo.name)}`}>
          {s.status === 'done' ? 'Results' : 'Continue'}
        </LinkButton>
      </td>
    </tr>
  )
}

// ---------------------------------------------------------------------------
// /connect/:name — the task list for one repository
// ---------------------------------------------------------------------------

export function ConnectRepoPage() {
  const { name = '' } = useParams()
  const { can } = useAuth()
  const repo = useRepo(name)
  const oracle = useOracle(name)
  const controls = useOracleControls(name)
  const map = useCapabilityMap(name, ['capability_class', 'size'])
  const probe = useProbeRepo()
  const createRun = useCreateRun()
  const [measureOpen, setMeasureOpen] = useState(false)

  const oracleInput = oracle.data ?? (oracle.isError && notRun(oracle.error) ? null : undefined)
  const controlsInput = controls.data ?? (controls.isError && notRun(controls.error) ? null : undefined)
  const stages = repo.data
    ? stagesFor({ repo: repo.data, oracle: oracleInput, controls: controlsInput, measuredRows: map.data?.summary.n_total })
    : []
  const running = stages.find((s) => s.status === 'running')
  const watched = useRun(running?.runId ?? '', { poll: Boolean(running?.runId) })

  // when the watched run ends, every input may have changed — refetch them all
  const watchedStatus = watched.data?.status
  useEffect(() => {
    if (watchedStatus && watchedStatus !== 'queued' && watchedStatus !== 'running') {
      void repo.refetch()
      void oracle.refetch()
      void controls.refetch()
      void map.refetch()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [watchedStatus])

  const act = (stage: Stage) => {
    if (stage.runKind === 'probe') probe.mutate(name)
    else if (stage.runKind === 'replay') setMeasureOpen(true)
    else if (stage.runKind) createRun.mutate({ repo: name, kind: stage.runKind })
  }
  const busy = probe.isPending || createRun.isPending
  const actionError = probe.error ?? createRun.error
  const allDone = stages.length > 0 && stages.every((s) => s.status === 'done')
  const next = stages.find((s) => s.status !== 'done')

  return (
    <>
      <PageHeader
        eyebrow="Journey · 1 of 4 · connect"
        title={name}
        purpose={
          allDone
            ? 'Every stage is done — the results page holds what the evidence says about this repository.'
            : next
              ? `Next: ${next.title.toLowerCase()}. ${next.why}`
              : 'Loading the repository…'
        }
        actions={
          <div className="flex gap-2">
            <LinkButton size="sm" to={`/repos/${encodeURIComponent(name)}`}>
              Configuration
            </LinkButton>
            <LinkButton size="sm" variant={allDone ? 'filled' : 'outlined'} to={`/results?repo=${encodeURIComponent(name)}`}>
              Results
            </LinkButton>
          </div>
        }
      />
      {repo.isError && <ErrorState error={repo.error} onRetry={() => void repo.refetch()} />}
      {repo.data && (
        <Card title="The walk" eyebrow="six stages · each says what it proves and what it costs">
          <ol className="m-0 list-none space-y-3 p-0" aria-label="Connection stages">
            {stages.map((s, i) => {
              const d = STATUS_DISPLAY[s.status]
              const canAct = s.status === 'todo' || s.status === 'failed'
              return (
                <li key={s.id} className="grid grid-cols-[2rem_1fr_auto] items-start gap-3 border-t border-border pt-3 first:border-t-0 first:pt-0" data-testid={`stage-${s.id}`}>
                  <span className="num font-mono text-sm text-on-surface-muted">{i + 1}.</span>
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-semibold">{s.title}</span>
                      <Pill tone={d.tone} glyph={d.glyph} size="xs" label={`${s.title}: ${d.label}`}>
                        {d.label}
                      </Pill>
                      {s.spends && s.status !== 'done' && (
                        <Pill tone="amber" size="xs" glyph="$">
                          spends model budget
                        </Pill>
                      )}
                    </div>
                    <p className="mt-1 mb-1 max-w-[70ch] text-sm text-on-surface-body">{s.why}</p>
                    <p className="m-0 text-xs text-on-surface-muted">
                      {s.detail}
                      {s.runId && (
                        <>
                          {' · '}
                          <Link to={`/runs/${s.runId}`}>open run</Link>
                        </>
                      )}
                    </p>
                  </div>
                  <div className="text-right">
                    {canAct && s.runKind && can('operator') && (
                      <Button size="sm" variant={s.spends ? 'outlined' : 'filled'} disabled={busy} onClick={() => act(s)}>
                        {s.status === 'failed' ? 'Retry' : s.runKind === 'replay' ? 'Measure…' : 'Run'}
                      </Button>
                    )}
                    {canAct && s.runKind && !can('operator') && <span className="text-xs text-on-surface-muted">operator</span>}
                  </div>
                </li>
              )
            })}
          </ol>
          {actionError && <ErrorState compact error={actionError} />}
        </Card>
      )}
      <RunNewDialog
        open={measureOpen}
        onClose={() => setMeasureOpen(false)}
        repo={name}
        initialKind="replay"
        onCreated={() => {
          setMeasureOpen(false)
          void repo.refetch()
        }}
      />
    </>
  )
}
