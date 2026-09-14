import { useMemo, useState } from 'react'
import { isApiError } from '../../api/client'
import { Button } from '../../components/Button'
import { ErrorState } from '../../components/ErrorState'
import { TextArea, TextField } from '../../components/Field'
import { Pill } from '../../components/Pill'
import { useAuth } from '../../lib/auth'
import { fmtDate, shortId } from '../../lib/format'
import type { Tone } from '../../lib/verdict'
import {
  FINDING_KINDS,
  FINDING_LABELS,
  VERDICT_LABELS,
  deriveVerdict,
  useCreateReview,
  useReviews,
  type FindingKind,
  type RetainedPatch,
  type Review,
  type Verdict,
} from './contract'

export const VERDICT_TONE: Record<Verdict, Tone> = {
  ok: 'green',
  regression: 'red',
  defect: 'red',
  api_change: 'amber',
  style: 'blue',
  not_reviewed: 'muted',
}

const VERDICT_GLYPH: Record<Verdict, string> = {
  ok: '✓',
  regression: '✗',
  defect: '✗',
  api_change: '△',
  style: '≈',
  not_reviewed: '—',
}

export function VerdictPill({ verdict, size = 'xs' }: { verdict: Verdict; size?: 'xs' | 'sm' }) {
  return (
    <Pill tone={VERDICT_TONE[verdict]} glyph={VERDICT_GLYPH[verdict]} size={size} label={`Review verdict: ${VERDICT_LABELS[verdict]}`} data-testid={`review-verdict-${verdict}`}>
      {VERDICT_LABELS[verdict]}
    </Pill>
  )
}

interface FindingDraft {
  note: string
  file: string
  line: string
}

const emptyDraft = (): FindingDraft => ({ note: '', file: '', line: '' })

interface Props {
  /** The graded row the review is about. */
  rowHash: string
  repo: string
  taskId: string
  /** The patch as loaded in THIS session (null until the Patch tab fetched it). */
  patch: RetainedPatch | null
  /** Whether the row's pack records a diff at all (a `not_reviewed` is still possible). */
  hasDiff: boolean
  onOpenPatch: () => void
}

/**
 * The reviewer's verdict on one graded row. Multi-select finding kinds (the headline
 * verdict is derived by the core's one rule), a note per finding, mergeable yes/no,
 * a statement — submitted with the sha256 of the patch bytes loaded in this session.
 * The action stays disabled until the Patch tab has loaded and its hash matches the
 * pack's anchor; the server refuses (422) anything else.
 */
export function ReviewPanel({ rowHash, repo, taskId, patch, hasDiff, onOpenPatch }: Props) {
  const { can } = useAuth()
  const mayReview = can('operator')
  const list = useReviews({ grade_row_hash: rowHash }, rowHash.length > 0)
  const create = useCreateReview()
  const [kinds, setKinds] = useState<FindingKind[]>([])
  const [drafts, setDrafts] = useState<Record<FindingKind, FindingDraft>>({
    regression: emptyDraft(),
    defect: emptyDraft(),
    api_change: emptyDraft(),
    style: emptyDraft(),
  })
  const [mergeable, setMergeable] = useState<'yes' | 'no' | ''>('')
  const [statement, setStatement] = useState('')
  const [notReviewed, setNotReviewed] = useState(false)
  const [submitted, setSubmitted] = useState<Review | null>(null)

  const verdict: Verdict = notReviewed ? 'not_reviewed' : deriveVerdict(kinds)
  const anchored = patch !== null && patch.matches
  const missingNotes = kinds.filter((k) => !drafts[k].note.trim())
  const regressionMergeable = kinds.includes('regression') && mergeable === 'yes'
  const blockers = useMemo(() => {
    const out: string[] = []
    if (!mayReview) out.push('Reviews need the operator role or above.')
    if (!notReviewed) {
      if (!hasDiff) out.push('The evidence pack records no diff — there is no patch to attest to (you may record “not reviewed”).')
      else if (patch === null) out.push('Open the Patch tab first: a review attests to the exact bytes you read.')
      else if (!patch.matches)
        out.push(
          patch.redacted
            ? 'The served patch was redacted (secret-shaped content), so its bytes differ from the attested hash — this row cannot be reviewed through the UI; read the retained worktree directly or record “not reviewed”.'
            : patch.truncated
              ? 'The served patch was capped at 1 MiB — its bytes differ from the attested hash; read the retained worktree directly.'
              : 'The served patch does not hash to the pack’s diff_sha256 (the worktree drifted) — a review cannot attest to it.',
        )
      if (missingNotes.length) out.push(`Each selected finding needs a note (${missingNotes.map((k) => FINDING_LABELS[k]).join(', ')}).`)
      if (regressionMergeable) out.push('A change with a regression finding is never mergeable.')
    }
    if (!statement.trim()) out.push('A statement is required.')
    return out
  }, [mayReview, notReviewed, hasDiff, patch, missingNotes, regressionMergeable, statement])

  const canSubmit = blockers.length === 0 && !create.isPending

  function toggle(kind: FindingKind) {
    setKinds((ks) => (ks.includes(kind) ? ks.filter((k) => k !== kind) : [...ks, kind]))
  }

  function submit() {
    if (!canSubmit) return
    const body = notReviewed
      ? { grade_row_hash: rowHash, statement: statement.trim(), findings: [], mergeable: null, patch_sha256: '', not_reviewed: true }
      : {
          grade_row_hash: rowHash,
          statement: statement.trim(),
          findings: FINDING_KINDS.filter((k) => kinds.includes(k)).map((k) => ({
            kind: k,
            note: drafts[k].note.trim(),
            file: drafts[k].file.trim(),
            line: drafts[k].line.trim() ? Number(drafts[k].line) : null,
          })),
          mergeable: mergeable === '' ? null : mergeable === 'yes',
          patch_sha256: patch?.sha256 ?? '',
        }
    create.mutate(body, {
      onSuccess: (r) => {
        setSubmitted(r)
        setKinds([])
        setStatement('')
        setMergeable('')
        setNotReviewed(false)
      },
    })
  }

  const err = create.error
  const refusal = err && isApiError(err) && err.status === 422 ? err : null

  return (
    <div className="space-y-6" data-testid="review-panel">
      <section className="space-y-3">
        <h3 className="label">Your review</h3>
        <p className="text-xs text-on-surface-muted">
          Row <span className="font-mono">{shortId(rowHash, 12)}</span> · task <span className="font-mono">{shortId(taskId)}</span> · {repo}. A review is a
          ledger row: append-only, hash-chained, anchored to the sha256 of the patch you loaded.
        </p>

        <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Findings">
          {FINDING_KINDS.map((k) => {
            const on = kinds.includes(k)
            return (
              <button
                key={k}
                type="button"
                aria-pressed={on}
                disabled={notReviewed}
                data-testid={`finding-chip-${k}`}
                onClick={() => toggle(k)}
                className={`rounded-[var(--radius-pill)] border px-3 py-1 text-xs font-semibold transition-colors disabled:opacity-50 ${
                  on ? 'border-primary bg-primary-container text-primary' : 'border-border bg-surface-container text-on-surface-body hover:bg-surface-high'
                }`}
              >
                {FINDING_LABELS[k]}
              </button>
            )
          })}
          <span className="ml-auto flex items-center gap-2 text-xs text-on-surface-muted">
            verdict <VerdictPill verdict={verdict} />
          </span>
        </div>

        {!notReviewed &&
          FINDING_KINDS.filter((k) => kinds.includes(k)).map((k) => (
            <div key={k} className="grid gap-2 rounded-[var(--radius-control)] border border-border bg-surface-high p-3 sm:grid-cols-[1fr_180px_80px]" data-testid={`finding-${k}`}>
              <TextField
                label={`${FINDING_LABELS[k]} — note`}
                required
                value={drafts[k].note}
                onChange={(e) => setDrafts((d) => ({ ...d, [k]: { ...d[k], note: e.target.value } }))}
                placeholder="What you saw, in one sentence"
              />
              <TextField label="File" value={drafts[k].file} onChange={(e) => setDrafts((d) => ({ ...d, [k]: { ...d[k], file: e.target.value } }))} placeholder="path (optional)" />
              <TextField label="Line" inputMode="numeric" value={drafts[k].line} onChange={(e) => setDrafts((d) => ({ ...d, [k]: { ...d[k], line: e.target.value.replace(/[^0-9]/g, '') } }))} placeholder="n" />
            </div>
          ))}

        <fieldset className="flex flex-wrap items-center gap-4 text-xs" disabled={notReviewed}>
          <legend className="label">Would a maintainer merge this as-is?</legend>
          {(['yes', 'no', ''] as const).map((v) => (
            <label key={v || 'unanswered'} className="inline-flex items-center gap-1">
              <input type="radio" name="mergeable" value={v} checked={mergeable === v} onChange={() => setMergeable(v)} />
              {v === 'yes' ? 'Mergeable' : v === 'no' ? 'Not mergeable' : 'Not answered'}
            </label>
          ))}
        </fieldset>

        <TextArea label="Statement" required rows={3} value={statement} onChange={(e) => setStatement(e.target.value)} placeholder="What you concluded and why — this is the governance record." />

        <label className="inline-flex items-center gap-2 text-xs">
          <input type="checkbox" checked={notReviewed} onChange={(e) => setNotReviewed(e.target.checked)} data-testid="not-reviewed" />
          I looked but could not review this row (records <em>not reviewed</em>: no findings, no hash)
        </label>

        <div className="rounded-[var(--radius-control)] border border-border bg-surface-high p-3 text-xs" data-testid="review-anchor" data-state={anchored ? 'anchored' : 'unanchored'}>
          <div className="font-semibold">Anchor</div>
          {patch === null ? (
            <p className="text-on-surface-muted">
              No patch loaded in this session.{' '}
              {hasDiff && (
                <button type="button" className="text-primary underline-offset-2 hover:underline" onClick={onOpenPatch}>
                  Open the Patch tab
                </button>
              )}
            </p>
          ) : (
            <p className={anchored ? 'text-status-green' : 'text-status-amber'}>
              sha256(loaded patch) <span className="font-mono">{shortId(patch.sha256, 16)}</span> {anchored ? '=' : '≠'} pack diff_sha256{' '}
              <span className="font-mono">{shortId(patch.diffSha256, 16)}</span>
            </p>
          )}
        </div>

        {blockers.length > 0 && (
          <ul className="m-0 list-disc space-y-1 pl-5 text-xs text-on-surface-muted" data-testid="review-blockers">
            {blockers.map((b) => (
              <li key={b}>{b}</li>
            ))}
          </ul>
        )}

        {refusal && (
          <div role="alert" className="rounded-[var(--radius-control)] border border-status-red/40 bg-status-red-soft p-3 text-xs" data-testid="review-refused">
            <div className="font-semibold text-status-red">
              Refused ({refusal.code}
              {typeof refusal.detail.code === 'string' ? ` · ${refusal.detail.code}` : ''})
            </div>
            <p>{refusal.message}</p>
          </div>
        )}
        {err && !refusal && <ErrorState error={err} onRetry={submit} />}

        <div className="flex items-center gap-3">
          <Button variant="filled" onClick={submit} disabled={!canSubmit} data-testid="review-submit">
            {create.isPending ? 'Recording…' : 'Record review'}
          </Button>
          {submitted && (
            <span className="text-xs text-status-green" data-testid="review-recorded">
              Recorded {VERDICT_LABELS[submitted.verdict]} · <span className="font-mono">{shortId(submitted.row_hash, 12)}</span>
            </span>
          )}
        </div>
      </section>

      <section className="space-y-2">
        <h3 className="label">Reviews of this row</h3>
        {list.isPending && (
          <p role="status" className="text-xs text-on-surface-muted">
            Loading reviews…
          </p>
        )}
        {list.isError && <ErrorState error={list.error} onRetry={() => void list.refetch()} />}
        {list.data && list.data.items.length === 0 && (
          <p className="text-xs text-on-surface-muted" data-testid="reviews-empty">
            No human has reviewed this row yet.
          </p>
        )}
        {list.data && list.data.items.length > 0 && (
          <ol className="m-0 list-none space-y-2 p-0" data-testid="reviews-list">
            {[...list.data.items].reverse().map((r) => (
              <li key={r.review_id} className="rounded-[var(--radius-control)] border border-border bg-surface-high p-3 text-xs" data-testid="review-item">
                <div className="flex flex-wrap items-center gap-2">
                  <VerdictPill verdict={r.verdict} />
                  {r.mergeable !== null && (
                    <Pill tone={r.mergeable ? 'green' : 'amber'} size="xs" label={r.mergeable ? 'Mergeable' : 'Not mergeable'}>
                      {r.mergeable ? 'mergeable' : 'not mergeable'}
                    </Pill>
                  )}
                  <span className="text-on-surface-muted">
                    {r.reviewer} · {fmtDate(r.created)} · <span className="font-mono" title={r.row_hash}>{shortId(r.row_hash, 10)}</span>
                  </span>
                </div>
                <p className="mt-1 text-on-surface-body">{r.statement}</p>
                {r.findings.length > 0 && (
                  <ul className="mt-1 list-disc space-y-0.5 pl-5">
                    {r.findings.map((f, i) => (
                      <li key={`${f.kind}-${i}`}>
                        <span className="font-semibold">{FINDING_LABELS[f.kind]}</span>: {f.note}
                        {f.file && (
                          <span className="font-mono text-on-surface-muted">
                            {' '}
                            — {f.file}
                            {f.line !== null ? `:${f.line}` : ''}
                          </span>
                        )}
                      </li>
                    ))}
                  </ul>
                )}
                {r.patch_sha256_reviewed && (
                  <div className="mt-1 font-mono text-[10px] text-on-surface-muted" title={r.patch_sha256_reviewed}>
                    attested patch {shortId(r.patch_sha256_reviewed, 16)}
                  </div>
                )}
              </li>
            ))}
          </ol>
        )}
      </section>
    </div>
  )
}

export default ReviewPanel
