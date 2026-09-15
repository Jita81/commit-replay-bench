/**
 * The Configuration tab — edit the repo config, save only what changed, prove it with a probe, read the audit trail.
 *
 * Navigation
 * ----------
 * What it is:   The Configuration tab of the repo page: the form with Save / Discard / Run
 *               probe, the inline probe result, the stored config as returned, and the audit
 *               trail of `repo.created` / `repo.updated` events.
 * What it does: Sends ONLY the changed fields to `PUT /repos/{name}` (diffed against the last
 *               state the SERVER confirmed, never a stale prop), shows a toast naming what was
 *               sent, and offers "Run probe now" so the new configuration is proven rather
 *               than assumed — the probe runs the STORED config, so it is disabled while the
 *               form is dirty. A viewer sees the same form read-only. External changes
 *               (another operator, the worker persisting a clone path) reset an untouched
 *               form and are diffed against by a dirty one.
 * How:          `formFromRepo` → local form state; `changedFields(form, saved)` → the PUT
 *               body; on success the response replaces `saved` and the form; `ProbeResult`
 *               follows the queued run to a terminal state and re-reads the repo (the worker
 *               writes probe status on the repo row).
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/api/repoConfig.ts (`useUpdateRepo`, `useRepoEvents`),
 *               ui/src/screens/Repos/repoConfigModel.ts (diff and validation),
 *               ui/src/screens/Repos/RepoConfigForm.tsx (the fields), ui/src/api/hooks.ts
 *               (`useProbeRepo`, `useRun`), ui/src/screens/Repos/RepoDetail.tsx (the host tab),
 *               src/crb/server/routes/repos.py (the PUT, the events, the probe)
 * Tested by:    ui/src/screens/Repos/RepoConfigTab.test.tsx, ui/e2e/walkthrough/repo-config.spec.ts
 * Touch when:   the audit event payload changes (`system/repo.updated` in docs/API.md) —
 *               update `fieldsOf`; never for a new repository (this IS the surface that
 *               onboards one).
 */
import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useState, type FormEvent } from 'react'
import { Link } from 'react-router'
import { keys, useProbeRepo, useRun } from '../../api/hooks'
import { useRepoEvents, useUpdateRepo } from '../../api/repoConfig'
import { isRunTerminal, type RepoDetail, type Run, type StepEvent } from '../../api/types'
import { Button } from '../../components/Button'
import { Card } from '../../components/Card'
import { EmptyState } from '../../components/EmptyState'
import { ErrorState } from '../../components/ErrorState'
import { JsonView } from '../../components/JsonView'
import { Pill } from '../../components/Pill'
import { QueryBoundary } from '../../components/QueryBoundary'
import { useAuth } from '../../lib/auth'
import { fmtDate, shortId } from '../../lib/format'
import { RepoConfigForm } from './RepoConfigForm'
import { changedFields, formFromRepo, hasErrors, validateForm } from './repoConfigModel'
import { validateRunnerOpts } from './runnerOpts'

/** How long the "Saved …" toast stays. */
const TOAST_MS = 8000

/** The last non-empty line of a runner tail — the runner's own summary ("5 passed in 0.02s"). */
function summaryLine(detail: string): string {
  const lines = detail.split('\n').map((l) => l.trim()).filter(Boolean)
  return lines[lines.length - 1] ?? ''
}

/** The probe run a save offered, followed until it is terminal. */
function ProbeResult({ runId, repo }: { runId: string; repo: RepoDetail }) {
  const run = useRun(runId, { poll: true })
  const qc = useQueryClient()
  const r: Run | undefined = run.data
  const terminal = r !== undefined && isRunTerminal(r.status)
  // The worker writes probe_status/detail on the repo row as the run ends; re-read it.
  useEffect(() => {
    if (terminal) void qc.invalidateQueries({ queryKey: keys.repo(repo.name) })
  }, [terminal, qc, repo.name])
  if (run.isError) return <ErrorState compact error={run.error} />
  if (!r || !terminal) {
    return (
      <div className="flex flex-wrap items-center gap-2 text-sm" role="status" data-testid="repo-config-probe-result" data-outcome="pending">
        <Pill tone="primary" glyph="●" label={`Probe: ${r?.status ?? 'queued'}`}>
          {r?.status ?? 'queued'}
        </Pill>
        <span className="text-on-surface-muted">The probe runs the configured scope through the runner; this follows the run until it ends.</span>
        <Link to={`/runs/${runId}`} className="font-mono text-xs">
          run {shortId(runId, 8)}
        </Link>
      </div>
    )
  }
  const green = r.status === 'succeeded'
  const reason = green ? summaryLine(repo.probe.detail) || 'green' : r.error || `run ${r.status}`
  return (
    <div className="flex flex-wrap items-start gap-2 text-sm" role="status" data-testid="repo-config-probe-result" data-outcome={green ? 'green' : 'red'}>
      <Pill tone={green ? 'green' : 'red'} glyph={green ? '✓' : '✗'} label={green ? 'Probe: green' : 'Probe: failed'}>
        {green ? 'Probe green' : 'Probe failed'}
      </Pill>
      <span className={`min-w-0 whitespace-pre-wrap break-words ${green ? 'text-on-surface' : 'text-status-red'}`} data-testid="repo-config-probe-reason">
        {reason}
      </span>
      <Link to={`/runs/${runId}`} className="font-mono text-xs">
        run {shortId(runId, 8)}
      </Link>
    </div>
  )
}

/** The changed field names of a `repo.updated` event (`payload.fields`, else the diff's keys). */
function fieldsOf(ev: StepEvent): string[] {
  const p = ev.payload
  if (Array.isArray(p.fields)) return p.fields.map(String)
  if (p.diff && typeof p.diff === 'object') return Object.keys(p.diff as object)
  return []
}

/** The repo's system events, newest first, each with its changed fields and the redacted diff behind a disclosure. */
function AuditTrail({ name }: { name: string }) {
  const events = useRepoEvents(name, { limit: 50 })
  return (
    <Card title="Audit trail" eyebrow="who changed what · append-only system events">
      <div data-testid="repo-config-audit">
        <QueryBoundary query={events} loading="Loading the audit trail…">
          {(page) =>
            page.items.length === 0 ? (
              <EmptyState compact title="No configuration events" reason="A repo registered through the API carries a repo.created event and one repo.updated event per save, each with the redacted field diff. This repo has none on record." />
            ) : (
              <ol className="m-0 list-none space-y-2 p-0" data-testid="repo-config-audit-list">
                {page.items.map((ev) => {
                  const fields = fieldsOf(ev)
                  const diff = ev.payload.diff
                  return (
                    <li key={ev.event_id} className="rounded-[var(--radius-control)] border border-border px-3 py-2 text-sm" data-testid="repo-config-audit-event" data-action={ev.action}>
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-mono text-xs font-semibold">{ev.action}</span>
                        <span className="text-xs text-on-surface-muted">{fmtDate(ev.timestamp)}</span>
                        {ev.actor && (
                          <span className="text-xs text-on-surface-muted">
                            by <span className="font-mono">{ev.actor}</span>
                          </span>
                        )}
                        <span className="num font-mono text-[11px] text-on-surface-muted">seq {ev.seq}</span>
                      </div>
                      {fields.length > 0 && (
                        <div className="mt-1 flex flex-wrap gap-1" data-testid="repo-config-audit-fields">
                          {fields.map((f) => (
                            <Pill key={f} tone="primary" size="xs" label={`Changed: ${f}`}>
                              {f}
                            </Pill>
                          ))}
                        </div>
                      )}
                      {diff !== undefined && diff !== null && typeof diff === 'object' && Object.keys(diff as object).length > 0 && (
                        <details className="mt-1 text-xs">
                          <summary className="cursor-pointer text-on-surface-muted">Diff (redacted at write)</summary>
                          <div className="mt-1">
                            <JsonView value={diff} initiallyOpen collapseBelow={4} label={`Diff for event ${ev.seq}`} />
                          </div>
                        </details>
                      )}
                    </li>
                  )
                })}
              </ol>
            )
          }
        </QueryBoundary>
      </div>
    </Card>
  )
}

/**
 * The Configuration tab: every `RepoConfig` field as a form (operators edit, viewers
 * read), a save that sends ONLY the changed fields to `PUT /repos/{name}`, an
 * immediate "Run probe" so the new config is proven rather than assumed, the stored
 * config as the API returns it, and the audit trail of every change.
 */
export function RepoConfigTab({ repo }: { repo: RepoDetail }) {
  const { can, me, loading: authLoading } = useAuth()
  const editable = can('operator')
  const update = useUpdateRepo(repo.name)
  const probe = useProbeRepo()
  // `saved` is the last state the SERVER confirmed (the prop, then every PUT response);
  // the diff a save sends is always computed against it, never against a stale prop.
  const [saved, setSaved] = useState(repo)
  const [form, setForm] = useState(() => formFromRepo(repo))
  const [jsonError, setJsonError] = useState<string | undefined>(undefined)
  const [toast, setToast] = useState<{ fields: string[] } | null>(null)
  const [probeRunId, setProbeRunId] = useState<string | null>(null)
  // Bumped whenever the form is replaced wholesale (reset, save, external change) so the
  // runner-options editor's own draft text is discarded with it.
  const [version, setVersion] = useState(0)

  const changes = useMemo(() => changedFields(form, saved), [form, saved])
  const dirty = Object.keys(changes).length > 0
  // A change that arrived from elsewhere (another operator, the worker persisting a
  // clone path) resets an UNTOUCHED form; a form with edits keeps them, diffed against
  // the newer server state.
  useEffect(() => {
    if (repo.updated !== saved.updated || repo.probe.checked !== saved.probe.checked || repo.probe.detail !== saved.probe.detail) {
      setSaved(repo)
      if (!dirty) {
        setForm(formFromRepo(repo))
        setVersion((v) => v + 1)
      }
    }
  }, [repo, saved, dirty])

  useEffect(() => {
    if (!toast) return
    const t = setTimeout(() => setToast(null), TOAST_MS)
    return () => clearTimeout(t)
  }, [toast])

  const errors = validateForm(form)
  const optErrors = validateRunnerOpts(form.runner, form.runner_opts)
  const invalid = hasErrors(errors) || Object.keys(optErrors).length > 0 || Boolean(jsonError)
  const canSave = editable && dirty && !invalid && !update.isPending

  const submit = (e: FormEvent) => {
    e.preventDefault()
    if (!canSave) return
    const body = changes
    update.mutate(body, {
      onSuccess: (fresh) => {
        setSaved(fresh)
        setForm(formFromRepo(fresh))
        setJsonError(undefined)
        setVersion((v) => v + 1)
        setToast({ fields: Object.keys(body).sort() })
        setProbeRunId(null)
      },
    })
  }

  const runProbe = () => {
    probe.mutate(repo.name, { onSuccess: (run) => setProbeRunId(run.id) })
  }

  const reset = () => {
    setForm(formFromRepo(saved))
    setJsonError(undefined)
    setVersion((v) => v + 1)
    update.reset()
  }

  return (
    <div className="space-y-6">
      <Card
        title="Configuration"
        eyebrow="layout · belt scope · probe · runner options"
        actions={
          authLoading ? null : editable ? (
            <>
              <Button size="sm" onClick={reset} disabled={!dirty || update.isPending} data-testid="repo-config-reset">
                Discard changes
              </Button>
              <Button size="sm" onClick={runProbe} disabled={probe.isPending || dirty} title={dirty ? 'Save first: the probe runs the STORED configuration' : undefined} data-testid="repo-config-probe-run">
                {probe.isPending ? 'Enqueuing…' : 'Run probe'}
              </Button>
              <Button size="sm" type="submit" form="repo-config-form" variant="filled" disabled={!canSave} data-testid="repo-config-save">
                {update.isPending ? 'Saving…' : 'Save changes'}
              </Button>
            </>
          ) : (
            <span className="text-xs text-on-surface-muted" data-testid="repo-config-readonly">
              Read-only: your role ({me?.role ?? 'viewer'}) can read this configuration; an operator can edit it.
            </span>
          )
        }
      >
        <form id="repo-config-form" onSubmit={submit} className="space-y-6" aria-describedby="repo-config-status">
          <div id="repo-config-status" className="space-y-3">
            {toast && (
              <div role="status" className="flex flex-wrap items-center gap-3 rounded-[var(--radius-control)] border border-status-green/40 bg-status-green-soft px-3 py-2 text-sm" data-testid="repo-config-toast">
                <span className="font-mono text-status-green" aria-hidden>
                  ✓
                </span>
                <span>
                  Saved <span className="font-mono text-xs">{toast.fields.join(', ')}</span> — recorded as a redacted diff in the audit trail.
                </span>
                {editable && (
                  <Button size="sm" variant="filled" onClick={runProbe} disabled={probe.isPending} data-testid="repo-config-toast-probe">
                    {probe.isPending ? 'Enqueuing…' : 'Run probe now'}
                  </Button>
                )}
                <Button size="sm" variant="ghost" onClick={() => setToast(null)} aria-label="Dismiss">
                  ✕
                </Button>
              </div>
            )}
            {probe.isError && <ErrorState compact error={probe.error} />}
            {probeRunId && <ProbeResult runId={probeRunId} repo={saved} />}
            {update.isError && <ErrorState compact error={update.error} />}
          </div>
          <RepoConfigForm key={version} form={form} onChange={setForm} errors={errors} disabled={!editable} onJsonError={setJsonError} />
          {editable && dirty && (
            <div className="text-xs text-on-surface-muted" data-testid="repo-config-pending">
              Will send: <span className="font-mono">{Object.keys(changes).sort().join(', ')}</span>
              {invalid && <span className="text-status-red"> — fix the highlighted fields first</span>}
            </div>
          )}
        </form>
      </Card>
      <Card title="Stored configuration" eyebrow="as the API returns it (RepoConfig.to_dict)">
        <JsonView value={saved.config} initiallyOpen label="Repository configuration" />
      </Card>
      <AuditTrail name={repo.name} />
    </div>
  )
}
