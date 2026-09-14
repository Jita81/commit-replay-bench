import { useEffect } from 'react'
import { useEvidence } from '../../api/hooks'
import type { EvidencePack, LintRun, TestRun } from '../../api/types'
import { BeltPills } from '../../components/BeltPills'
import { Button } from '../../components/Button'
import { ErrorState } from '../../components/ErrorState'
import { JsonView } from '../../components/JsonView'
import { Pill } from '../../components/Pill'
import { Provenance } from '../../components/Provenance'
import { fmtDate, fmtInt, fmtSeconds, fmtUsd, shortId } from '../../lib/format'

interface Props {
  packHash: string | null
  onClose: () => void
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-2">
      <h3 className="label">{title}</h3>
      {children}
    </section>
  )
}

function KV({ rows }: { rows: Array<[string, React.ReactNode]> }) {
  return (
    <dl className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1 text-[13px]">
      {rows.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-on-surface-muted">{k}</dt>
          <dd className="num min-w-0 break-words">{v}</dd>
        </div>
      ))}
    </dl>
  )
}

/**
 * Belt 5's record (ADR-0011): which linter the repository's own configuration
 * selected, and what it said about the changed files. `null` = not evaluated
 * (no linter configured) — shown as such, never as a pass.
 */
function LintRunTail({ run }: { run: LintRun | null }) {
  if (!run) {
    return (
      <div className="text-xs text-on-surface-muted" data-testid="lint-run-none">
        Lint run (belt 5): not evaluated — the repository configures no formatter/linter
      </div>
    )
  }
  const tone = run.error ? 'amber' : run.ok === true ? 'green' : run.ok === false ? 'red' : 'muted'
  const glyph = run.error ? '⚠' : run.ok === true ? '✓' : run.ok === false ? '✗' : '—'
  const word = run.error ? 'could not run' : run.ok === true ? 'accepted' : run.ok === false ? 'rejected' : 'not evaluated'
  return (
    <details className="rounded-[var(--radius-control)] border border-border bg-surface-high" data-testid="lint-run">
      <summary className="flex cursor-pointer flex-wrap items-center gap-2 px-3 py-2 text-xs">
        <span className="font-semibold">Lint run (belt 5)</span>
        <Pill tone={tone} glyph={glyph} size="xs" label={`Lint run (belt 5, ${run.detected}): ${word}`}>
          {word}
        </Pill>
        <span className="num text-on-surface-muted">
          {run.detected} · {run.steps.length} step{run.steps.length === 1 ? '' : 's'} · {fmtSeconds(run.duration_s)}
        </span>
      </summary>
      <div className="space-y-2 border-t border-border px-3 py-2">
        {run.error && <p className="text-xs text-status-amber">{run.error}</p>}
        {run.note && !run.error && <p className="text-xs text-on-surface-muted">{run.note}</p>}
        {run.steps.map((s, i) => (
          <div key={`${s.tool}-${i}`} className="space-y-1">
            <div className="font-mono text-[11px]" title={s.argv.join(' ')}>
              {s.tool}: rc {s.rc}{s.timed_out ? ' (timed out)' : ''} · {s.files.length ? `${s.files.length} file(s)` : 'repo-wide'}
            </div>
            <pre className="max-h-48 overflow-auto whitespace-pre-wrap rounded bg-surface-container p-2 font-mono text-[11px] leading-4 text-on-surface-body">{s.tail || '(no output tail)'}</pre>
          </div>
        ))}
        <p className="text-[10px] text-on-surface-muted">Tail is redacted at capture; secrets never enter a pack.</p>
      </div>
    </details>
  )
}

function TestRunTail({ label, run }: { label: string; run: TestRun | null }) {
  if (!run) {
    return (
      <div className="text-xs text-on-surface-muted">
        {label}: not run
      </div>
    )
  }
  const tone = run.timed_out ? 'red' : run.parse_error ? 'amber' : run.returncode === 0 ? 'green' : 'red'
  const glyph = run.timed_out ? '⏱' : run.parse_error ? '⚠' : run.returncode === 0 ? '✓' : '✗'
  const label2 = run.timed_out ? 'timed out' : run.parse_error ? 'parse error' : run.returncode === 0 ? 'green' : `red (rc ${run.returncode})`
  return (
    <details className="rounded-[var(--radius-control)] border border-border bg-surface-high">
      <summary className="flex cursor-pointer flex-wrap items-center gap-2 px-3 py-2 text-xs">
        <span className="font-semibold">{label}</span>
        <Pill tone={tone} glyph={glyph} size="xs" label={`${label}: ${label2}`}>
          {label2}
        </Pill>
        <span className="num text-on-surface-muted">
          {run.failing.length} failing · {fmtSeconds(run.duration_s)}
        </span>
      </summary>
      <div className="space-y-2 border-t border-border px-3 py-2">
        {run.parse_error && <p className="text-xs text-status-amber">{run.parse_error}</p>}
        {run.failing.length > 0 && (
          <ul className="m-0 list-none p-0 font-mono text-[11px]">
            {run.failing.slice(0, 30).map((f) => (
              <li key={f} className="truncate" title={f}>
                {f}
              </li>
            ))}
            {run.failing.length > 30 && <li className="text-on-surface-muted">… {run.failing.length - 30} more</li>}
          </ul>
        )}
        <pre className="max-h-64 overflow-auto whitespace-pre-wrap rounded bg-surface-container p-2 font-mono text-[11px] leading-4 text-on-surface-body">{run.tail || '(no output tail)'}</pre>
        <p className="text-[10px] text-on-surface-muted">Tail is redacted at capture; secrets never enter a pack.</p>
      </div>
    </details>
  )
}

function PackBody({ pack, verified }: { pack: EvidencePack; verified: boolean }) {
  const g = pack.grade
  const b = pack.builder
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-2">
        {g.clean ? (
          <Pill tone="green" glyph="✓" label="Grade: clean — all four belts held">clean</Pill>
        ) : g.disqualified ? (
          <Pill tone="amber" glyph="⊘" label={`Grade: disqualified — ${g.dq_reason}`}>disqualified</Pill>
        ) : (
          <Pill tone="red" glyph="✗" label="Grade: not clean">not clean</Pill>
        )}
        {verified ? (
          <Pill tone="primary" glyph="✦" label="Pack hash verified against its canonical body" data-testid="pack-verified">
            verified
          </Pill>
        ) : (
          <Pill tone="red" glyph="✗" label="Pack hash does NOT verify — evidence untrusted" data-testid="pack-unverified">
            hash mismatch
          </Pill>
        )}
        <span className="font-mono text-[11px] text-on-surface-muted" title={pack.pack_hash}>
          {shortId(pack.pack_hash, 16)}
        </span>
      </div>

      <Section title="Spec">
        <KV
          rows={[
            ['task', <span className="font-mono text-xs" title={pack.task.task_id}>{shortId(pack.task.task_id)}</span>],
            ['subject', pack.task.subject],
            ['class · size · pool', <span className="font-mono text-xs">{pack.task.capability_class} · {pack.task.size} · {pack.task.pool}</span>],
            ['language', pack.task.language || '—'],
            ['target tests', <span className="font-mono text-xs">{pack.task.target_tests.join(', ') || '—'}</span>],
            ['test files', <span className="font-mono text-xs">{pack.task.test_files.join(', ')}</span>],
            ['src files', <span className="font-mono text-xs">{pack.task.src_files.join(', ')}</span>],
            ['belt scope', <span className="font-mono text-xs">{pack.task.belt_scope.length ? pack.task.belt_scope.join(', ') : 'BARE (runner default)'}</span>],
            ['baseline failing', fmtInt(pack.task.baseline_failing.length)],
            ['gold', pack.task.gold_clean === null ? 'unchecked' : pack.task.gold_clean ? 'clean' : `failed — ${pack.task.gold_note}`],
          ]}
        />
      </Section>

      <Section title="Belts">
        <BeltPills belts={g} size="sm" />
        {g.error && <p className="text-xs text-status-red">error: {g.error}</p>}
        {g.dq_reason && <p className="text-xs text-status-amber">disqualified: {g.dq_reason}</p>}
        {g.note && <p className="text-xs text-on-surface-muted">{g.note}</p>}
        {g.tamper_files.length > 0 && (
          <p className="text-xs text-status-red">
            tampered test files: <span className="font-mono">{g.tamper_files.join(', ')}</span>
          </p>
        )}
        {g.new_failures.length > 0 && (
          <p className="text-xs text-status-red">
            new failures ({g.new_failures.length}): <span className="font-mono">{g.new_failures.slice(0, 10).join(', ')}{g.new_failures.length > 10 ? ' …' : ''}</span>
          </p>
        )}
        <div className="space-y-2">
          <TestRunTail label="Target run (belt 2)" run={g.target_run} />
          <TestRunTail label="Belt run (belt 3)" run={g.belt_run} />
          {'repo_lint_clean' in g && <LintRunTail run={g.lint_run ?? null} />}
        </div>
      </Section>

      <Section title="Diff">
        {g.diff ? (
          <KV
            rows={[
              ['files', <span className="font-mono text-xs">{g.diff.files.join(', ') || '—'}</span>],
              ['+ / −', `${fmtInt(g.diff.additions)} / ${fmtInt(g.diff.deletions)}`],
              ['sha256', <span className="font-mono text-xs" title={g.diff.diff_sha256}>{shortId(g.diff.diff_sha256, 16)}</span>],
              ['changed files', <span className="font-mono text-xs">{g.changed_files.join(', ') || '—'}</span>],
            ]}
          />
        ) : (
          <p className="text-xs text-on-surface-muted">No diff recorded (the builder produced no change).</p>
        )}
      </Section>

      <Section title="Builder">
        {b ? (
          <KV
            rows={[
              ['builder', <span className="font-mono text-xs">{b.name}{b.model ? ` · ${b.model}` : ''}{b.provider ? ` · ${b.provider}` : ''}</span>],
              ['mode', b.mode],
              ['attempts · turns', `${fmtInt(b.attempts)} · ${fmtInt(b.turns)}`],
              ['tokens in / out', `${fmtInt(b.tokens_in)} / ${fmtInt(b.tokens_out)}`],
              ['cost', fmtUsd(b.cost_usd)],
              ['latency', fmtSeconds(b.latency_s)],
              ['transcript', b.transcript_ref ? <span className="font-mono text-xs">{b.transcript_ref}</span> : 'not retained'],
              ...(b.note ? ([['note', b.note]] as Array<[string, React.ReactNode]>) : []),
            ]}
          />
        ) : (
          <p className="text-xs text-on-surface-muted">No builder (gold or control trial).</p>
        )}
      </Section>

      <Section title="Apparatus">
        <Provenance apparatus={pack.apparatus.apparatus_version} policy={pack.apparatus.policy_version || null} />
        <KV
          rows={[
            ['crb', pack.apparatus.crb_version],
            ['grader', <span className="font-mono text-xs">{pack.apparatus.grader}</span>],
            ['runner', <span className="font-mono text-xs">{pack.apparatus.runner || '—'}</span>],
            ['executor', <span className="font-mono text-xs">{JSON.stringify(pack.apparatus.executor)}</span>],
            ['corpus', pack.apparatus.corpus_sha ? <span className="font-mono text-xs">{shortId(pack.apparatus.corpus_sha, 12)}</span> : '—'],
            ['run · trial', <span className="font-mono text-xs">{shortId(pack.run_id, 8)} · {pack.trial || '—'}</span>],
            ['actor', pack.actor || '—'],
            ['created', fmtDate(pack.created)],
            ['schema', <span className="font-mono text-xs">{pack.schema}</span>],
          ]}
        />
      </Section>

      <Section title="Full pack">
        <JsonView value={pack} label="Evidence pack" />
      </Section>
    </div>
  )
}

/** Side drawer for one evidence pack (`GET /evidence/{hash}`). */
export function EvidenceDrawer({ packHash, onClose }: Props) {
  const q = useEvidence(packHash ?? '')
  useEffect(() => {
    if (!packHash) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [packHash, onClose])

  if (!packHash) return null
  return (
    <div className="fixed inset-0 z-40" role="presentation">
      <button type="button" aria-label="Close evidence" className="absolute inset-0 bg-black/40" onClick={onClose} />
      <aside
        role="dialog"
        aria-modal="true"
        aria-labelledby="evidence-title"
        data-testid="evidence-drawer"
        className="absolute right-0 top-0 flex h-full w-[min(720px,100vw)] flex-col border-l border-border bg-surface-container shadow-[var(--shadow-card)]"
      >
        <header className="flex items-center justify-between border-b border-border px-5 py-3">
          <div>
            <div className="label">Evidence pack</div>
            <h2 id="evidence-title" className="text-[18px] leading-7">
              {q.data ? `Task ${shortId(q.data.pack.task.task_id)}` : 'Loading…'}
            </h2>
          </div>
          <Button size="sm" onClick={onClose}>
            Close
          </Button>
        </header>
        <div className="flex-1 overflow-y-auto px-5 py-4">
          {q.isPending && (
            <p role="status" className="text-sm text-on-surface-muted">
              Fetching the pack and verifying its hash…
            </p>
          )}
          {q.isError && <ErrorState error={q.error} onRetry={() => void q.refetch()} />}
          {q.data && <PackBody pack={q.data.pack} verified={q.data.verified} />}
        </div>
      </aside>
    </div>
  )
}
