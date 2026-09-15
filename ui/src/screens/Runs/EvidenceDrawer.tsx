/**
 * Evidence drawer — one evidence pack and what stands behind it: the pack, the retained patch, the transcript, the review.
 *
 * Navigation
 * ----------
 * What it is:   The side drawer opened from a run's task table, the task page and the sweep
 *               views; four tabs: Pack, Patch, Transcript, Review.
 * What it does: Renders `GET /evidence/{hash}` — spec, belts (with the target / belt / lint run
 *               tails, redacted at capture), diff stats, builder ref, apparatus stamp and the
 *               full JSON — with the `verified` badge (the pack's canonical hash recomputed on
 *               read equals its key; a mismatch is red, never hidden). The Patch tab fetches
 *               the retained worktree's diff on demand, hashes the served bytes and shows
 *               whether they match the pack's anchor; the Transcript tab reports why a
 *               transcript is unavailable rather than showing nothing; the Review tab hosts
 *               the review form. When the opener only knows the pack, the ledger row is
 *               resolved from the task's grades.
 * How:          `useEvidence` → `PackBody`; row hash from the prop or `useTask`; `useRetainedStatus`
 *               says what is reachable; the patch query is enabled only once the tab was
 *               opened (so the hash is of bytes the reviewer actually loaded); Esc closes.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0006-zero-raw-retention-and-evidence-packs.md, docs/adr/0011-repo-lint-belt.md
 * Works with:   ui/src/screens/Runs/contract.ts (retained-patch fetch, diff parser, review
 *               hooks), ui/src/screens/Runs/ReviewPanel.tsx (the Review tab), ui/src/api/types.ts
 *               (`EvidencePack`, `TestRun`, `LintRun`), ui/src/components/BeltPills.tsx and
 *               ui/src/components/Provenance.tsx, ui/src/screens/Runs/RunDetailPage.tsx and
 *               ui/src/screens/Runs/TaskDetailPage.tsx (the openers), src/crb/core/evidence.py
 *               (the pack's shape and `verify_pack`)
 * Tested by:    ui/src/screens/Runs/ReviewPanel.test.tsx (Patch tab: verified / redacted /
 *               unavailable; row resolution from the task), ui/src/screens/Runs/RunDetailPage.test.tsx
 *               (the drawer opens with belts and the verified badge), ui/e2e/walkthrough/05-replay-fake.spec.ts,
 *               ui/e2e/walkthrough/09-review.spec.ts
 * Touch when:   the pack schema gains a section (src/crb/core/evidence.py, then ui/src/api/types.ts)
 *               — add it to `PackBody`; never for a new repository.
 * Claims:       `verified` means the pack's bytes hash to their key; it says nothing about
 *               whether the change is mergeable (docs/EVIDENCE-AND-CLAIMS.md#7-what-must-never-be-said).
 */
import { useEffect, useMemo, useState } from 'react'
import { useEvidence, useTask } from '../../api/hooks'
import type { EvidencePack, LintRun, TestRun } from '../../api/types'
import { BeltPills } from '../../components/BeltPills'
import { Button } from '../../components/Button'
import { ErrorState } from '../../components/ErrorState'
import { JsonView } from '../../components/JsonView'
import { Pill } from '../../components/Pill'
import { Provenance } from '../../components/Provenance'
import { fmtDate, fmtInt, fmtSeconds, fmtUsd, shortId } from '../../lib/format'
import { parseUnifiedDiff, useRetainedPatch, useRetainedStatus, useRetainedTranscript, useReviews, type RetainedPatch } from './contract'
import { ReviewPanel, VerdictPill } from './ReviewPanel'

interface Props {
  packHash: string | null
  onClose: () => void
  /**
   * The graded row's chain hash — what the Patch / Transcript / Review tabs are
   * keyed by. Optional: when the opener only knows the pack, the drawer resolves it
   * from the task's grade rows (the row whose `evidence_pack_hash` is this pack).
   */
  rowHash?: string | null
}

/** The four tabs. */
export type DrawerTab = 'pack' | 'patch' | 'transcript' | 'review'

/** A titled block of the pack view. */
function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-2">
      <h3 className="label">{title}</h3>
      {children}
    </section>
  )
}

/** A two-column definition list for the pack's fields. */
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

/** One test run (belt 2 target or belt 3 belt) as a collapsible: verdict pill, failing ids, the redacted output tail. */
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

/** The Pack tab: grade pills, verified badge, spec, belts with run tails, diff stats, builder ref, apparatus, full JSON. */
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

/**
 * The retained patch: a syntax-neutral unified-diff view with +/− colouring, the
 * file list with per-file counts, and the anchor check — sha256 of the SERVED bytes
 * against the pack's `diff_sha256`. A mismatch is shown as a warning, never hidden.
 */
export function PatchView({ patch, pack }: { patch: RetainedPatch; pack: EvidencePack }) {
  const packFiles = pack.grade.diff?.files
  const parsed = useMemo(() => parseUnifiedDiff(patch.text, packFiles ?? []), [patch.text, packFiles])
  const packAdds = pack.grade.diff?.additions ?? 0
  const packDels = pack.grade.diff?.deletions ?? 0
  const countsMatch = parsed.additions === packAdds && parsed.deletions === packDels
  return (
    <div className="space-y-4" data-testid="patch-view" data-state={patch.matches ? 'verified' : 'mismatch'}>
      <div className="flex flex-wrap items-center gap-2">
        {patch.matches ? (
          <Pill tone="primary" glyph="✦" label="Served patch hashes to the pack's diff_sha256" data-testid="patch-verified">
            hash matches pack
          </Pill>
        ) : (
          <Pill tone="amber" glyph="⚠" label="Served patch does NOT hash to the pack's diff_sha256" data-testid="patch-mismatch">
            hash mismatch
          </Pill>
        )}
        {patch.redacted && (
          <Pill tone="amber" glyph="⊘" size="xs" label="Secret-shaped content was redacted before serving" data-testid="patch-redacted">
            redacted
          </Pill>
        )}
        {patch.truncated && (
          <Pill tone="amber" glyph="…" size="xs" label="The patch was capped at 1 MiB" data-testid="patch-truncated">
            truncated
          </Pill>
        )}
        <span className="font-mono text-[11px] text-on-surface-muted" title={`served ${patch.sha256} · pack ${patch.diffSha256}`}>
          sha256 {shortId(patch.sha256, 16)}
        </span>
      </div>
      {!patch.matches && (
        <p className="rounded-[var(--radius-control)] border border-status-amber/40 bg-status-amber-soft p-3 text-xs" role="alert" data-testid="patch-warning">
          {patch.redacted
            ? 'The served bytes were redacted (secret-shaped content); they are not the bytes the instrument graded. '
            : patch.truncated
              ? 'The served bytes were capped; they are not the whole patch the instrument graded. '
              : patch.serverVerified
                ? 'The served bytes do not hash to the anchor although the worktree does — the transfer changed them. '
                : 'The retained worktree no longer hashes to the pack’s diff_sha256 — it drifted since grading. '}
          A review cannot attest to these bytes.
        </p>
      )}
      <KV
        rows={[
          ['files', <span className="font-mono text-xs">{parsed.files.length}</span>],
          [
            '+ / −',
            <span data-testid="patch-counts" data-state={countsMatch ? 'match' : 'mismatch'}>
              {fmtInt(parsed.additions)} / {fmtInt(parsed.deletions)}
              {countsMatch ? ' · matches the pack' : ` · pack says ${fmtInt(packAdds)} / ${fmtInt(packDels)}`}
            </span>,
          ],
        ]}
      />
      <ul className="m-0 list-none space-y-1 p-0 text-xs" data-testid="patch-files">
        {parsed.files.map((f, i) => (
          <li key={`${f.path}-${i}`} className="flex items-center gap-2">
            <a href={`#patch-file-${i}`} className="font-mono text-primary underline-offset-2 hover:underline">
              {f.path || '(unnamed)'}
            </a>
            <span className="num text-status-green">+{f.additions}</span>
            <span className="num text-status-red">−{f.deletions}</span>
            {f.excluded && (
              <span className="text-on-surface-muted" title="Not in the pack's diff.files (e.g. the overlaid oracle): shown, not counted">
                (not counted)
              </span>
            )}
          </li>
        ))}
      </ul>
      {parsed.files.map((f, i) => (
        <section key={`${f.path}-${i}`} id={`patch-file-${i}`} className="rounded-[var(--radius-control)] border border-border" data-testid="patch-file">
          <header className="flex items-center gap-2 border-b border-border bg-surface-high px-3 py-1.5 font-mono text-[11px]">
            <span>{f.path || '(unnamed)'}</span>
            <span className="num text-status-green">+{f.additions}</span>
            <span className="num text-status-red">−{f.deletions}</span>
          </header>
          <pre className="m-0 max-h-[480px] overflow-auto bg-surface-container p-0 font-mono text-[11px] leading-4">
            {f.lines.map((ln, j) => (
              <div
                key={j}
                data-kind={ln.kind}
                className={
                  ln.kind === 'add'
                    ? 'bg-status-green-soft text-status-green'
                    : ln.kind === 'del'
                      ? 'bg-status-red-soft text-status-red'
                      : ln.kind === 'hunk'
                        ? 'bg-surface-high text-primary'
                        : ln.kind === 'meta'
                          ? 'text-on-surface-muted'
                          : 'text-on-surface-body'
                }
              >
                <span className="whitespace-pre px-2">{ln.text || ' '}</span>
              </div>
            ))}
          </pre>
        </section>
      ))}
      <p className="text-[10px] text-on-surface-muted">Computed on demand from the retained worktree, redacted, never stored twice. The pack’s hash is the anchor.</p>
    </div>
  )
}

/** The Transcript tab; an unavailable transcript states the server's reason. */
function TranscriptView({ rowHash }: { rowHash: string }) {
  const q = useRetainedTranscript(rowHash, true)
  if (q.isPending) {
    return (
      <p role="status" className="text-sm text-on-surface-muted">
        Fetching the retained transcript…
      </p>
    )
  }
  if (q.isError) {
    const reason = typeof q.error.detail.reason === 'string' ? q.error.detail.reason : q.error.message
    return (
      <p className="text-xs text-on-surface-muted" data-testid="transcript-unavailable">
        Transcript unavailable: {reason}
      </p>
    )
  }
  return (
    <div className="space-y-2" data-testid="transcript-view">
      {q.data.json !== null ? (
        <JsonView value={q.data.json} label="Builder transcript" />
      ) : (
        <pre className="max-h-[560px] overflow-auto whitespace-pre-wrap rounded bg-surface-container p-2 font-mono text-[11px] leading-4">{q.data.text}</pre>
      )}
      <p className="text-[10px] text-on-surface-muted">Redacted at write and again on read; served only from inside the transcripts directory.</p>
    </div>
  )
}

/** One drawer tab button (`role="tab"`). */
function Tab({ id, active, onClick, children, testId }: { id: DrawerTab; active: DrawerTab; onClick: (t: DrawerTab) => void; children: React.ReactNode; testId: string }) {
  const on = id === active
  return (
    <button
      type="button"
      role="tab"
      aria-selected={on}
      aria-controls={`evidence-tab-${id}`}
      data-testid={testId}
      onClick={() => onClick(id)}
      className={`-mb-px border-b-2 px-3 py-2 text-xs font-semibold ${on ? 'border-primary text-primary' : 'border-transparent text-on-surface-muted hover:text-on-surface'}`}
    >
      {children}
    </button>
  )
}

/** Side drawer for one evidence pack (`GET /evidence/{hash}`) and what stands behind it. */
export function EvidenceDrawer({ packHash, onClose, rowHash: rowHashProp }: Props) {
  const q = useEvidence(packHash ?? '')
  const [tab, setTab] = useState<DrawerTab>('pack')
  const [patchOpened, setPatchOpened] = useState(false)
  useEffect(() => {
    if (!packHash) return
    setTab('pack')
    setPatchOpened(false)
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [packHash, onClose])

  // Resolve the row when the opener did not pass it: the task's grade row whose pack this is.
  const pack = q.data?.pack
  const task = useTask(rowHashProp ? '' : (pack?.task.repo ?? ''), rowHashProp ? '' : (pack?.task.task_id ?? ''))
  const rowHash = rowHashProp ?? task.data?.grades.find((g) => g.evidence_pack_hash === packHash)?.row_hash ?? ''
  const retained = useRetainedStatus(rowHash)
  const patchAvailable = retained.data?.patch_available ?? false
  // The patch is fetched only after the reviewer OPENS the tab: the review's anchor is the
  // hash of bytes a person actually loaded, so it must not be pre-fetched on their behalf.
  const patch = useRetainedPatch(rowHash, patchOpened && patchAvailable)
  const reviews = useReviews({ grade_row_hash: rowHash }, rowHash.length > 0)
  // Reviews come in chain order; the last one is the standing verdict (nothing is edited).
  const latest = reviews.data?.items.length ? reviews.data.items[reviews.data.items.length - 1] : null
  const hasDiff = Boolean(pack?.grade.diff?.diff_sha256)

  function go(t: DrawerTab) {
    if (t === 'patch') setPatchOpened(true)
    setTab(t)
  }

  if (!packHash) return null
  return (
    <div className="fixed inset-0 z-40" role="presentation">
      <button type="button" aria-label="Close evidence" className="absolute inset-0 bg-black/40" onClick={onClose} />
      <aside
        role="dialog"
        aria-modal="true"
        aria-labelledby="evidence-title"
        data-testid="evidence-drawer"
        className="absolute right-0 top-0 flex h-full w-[min(760px,100vw)] flex-col border-l border-border bg-surface-container shadow-[var(--shadow-card)]"
      >
        <header className="flex items-center justify-between border-b border-border px-5 py-3">
          <div>
            <div className="label">Evidence pack</div>
            <h2 id="evidence-title" className="text-[18px] leading-7">
              {q.data ? `Task ${shortId(q.data.pack.task.task_id)}` : 'Loading…'}
            </h2>
          </div>
          <div className="flex items-center gap-2">
            {latest && <VerdictPill verdict={latest.verdict} />}
            <Button size="sm" onClick={onClose}>
              Close
            </Button>
          </div>
        </header>
        {q.data && (
          <nav className="flex items-center gap-1 border-b border-border px-5" role="tablist" aria-label="Evidence sections">
            <Tab id="pack" active={tab} onClick={go} testId="tab-pack">
              Pack
            </Tab>
            <Tab id="patch" active={tab} onClick={go} testId="tab-patch">
              Patch
            </Tab>
            <Tab id="transcript" active={tab} onClick={go} testId="tab-transcript">
              Transcript
            </Tab>
            <Tab id="review" active={tab} onClick={go} testId="tab-review">
              Review{reviews.data?.total ? ` (${reviews.data.total})` : ''}
            </Tab>
          </nav>
        )}
        <div className="flex-1 overflow-y-auto px-5 py-4">
          {q.isPending && (
            <p role="status" className="text-sm text-on-surface-muted">
              Fetching the pack and verifying its hash…
            </p>
          )}
          {q.isError && <ErrorState error={q.error} onRetry={() => void q.refetch()} />}
          {q.data && tab === 'pack' && (
            <div role="tabpanel" id="evidence-tab-pack">
              <PackBody pack={q.data.pack} verified={q.data.verified} />
            </div>
          )}
          {q.data && tab === 'patch' && (
            <div role="tabpanel" id="evidence-tab-patch">
              {!rowHash && (
                <p className="text-xs text-on-surface-muted" data-testid="patch-unavailable">
                  {task.isPending ? 'Resolving the graded row…' : 'No ledger row found for this pack.'}
                </p>
              )}
              {rowHash && retained.isPending && (
                <p role="status" className="text-xs text-on-surface-muted">
                  Checking what was retained…
                </p>
              )}
              {rowHash && retained.isError && <ErrorState error={retained.error} onRetry={() => void retained.refetch()} />}
              {retained.data && !retained.data.patch_available && (
                <p className="text-xs text-on-surface-muted" data-testid="patch-unavailable">
                  Patch unavailable: {retained.data.patch_reason}
                </p>
              )}
              {retained.data?.patch_available && patch.isPending && (
                <p role="status" className="text-xs text-on-surface-muted">
                  Fetching the retained patch and hashing it…
                </p>
              )}
              {patch.isError && (
                <p className="text-xs text-on-surface-muted" data-testid="patch-unavailable">
                  Patch unavailable: {typeof patch.error.detail.reason === 'string' ? patch.error.detail.reason : patch.error.message}
                </p>
              )}
              {patch.data && <PatchView patch={patch.data} pack={q.data.pack} />}
            </div>
          )}
          {q.data && tab === 'transcript' && (
            <div role="tabpanel" id="evidence-tab-transcript">
              {rowHash ? (
                <TranscriptView rowHash={rowHash} />
              ) : (
                <p className="text-xs text-on-surface-muted" data-testid="transcript-unavailable">
                  No ledger row found for this pack.
                </p>
              )}
            </div>
          )}
          {q.data && tab === 'review' && (
            <div role="tabpanel" id="evidence-tab-review">
              {rowHash ? (
                <ReviewPanel rowHash={rowHash} repo={q.data.pack.task.repo} taskId={q.data.pack.task.task_id} patch={patch.data ?? null} hasDiff={hasDiff} onOpenPatch={() => go('patch')} />
              ) : (
                <p className="text-xs text-on-surface-muted">No ledger row found for this pack — nothing to review.</p>
              )}
            </div>
          )}
        </div>
      </aside>
    </div>
  )
}
