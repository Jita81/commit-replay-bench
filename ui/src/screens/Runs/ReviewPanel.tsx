/**
 * Review panel — a person's verdict on one graded row, anchored to the sha256 of the patch they
 * loaded.
 *
 * Navigation
 * ----------
 * What it is:   The `ReviewPanel` (the drawer's Review tab) and the review `VerdictPill`.
 * What it does: Lets an operator record findings (regression / defect / API change / style,
 *               each with a note), a mergeable answer and a statement; the headline verdict
 *               is derived by the core's one rule, shown live. The action stays disabled —
 *               with the reasons listed — until the Patch tab was loaded in THIS session and
 *               its hash matches the pack's anchor, a regression is never marked mergeable,
 *               and every finding has a note; `not_reviewed` is the honest "I looked and could
 *               not review" (no findings, no hash). A server 422 refusal is rendered with its
 *               code. The list below shows every review of the row, newest first.
 * How:          Local draft state → `blockers` (memoised) gates `canSubmit` → `useCreateReview`
 *               posts `patch_sha256 = sha256(loaded bytes)` → on success the form clears and
 *               the record is shown.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0006-zero-raw-retention-and-evidence-packs.md
 * Works with:   ui/src/screens/Runs/contract.ts (`deriveVerdict`, `useCreateReview`,
 *               `useReviews`, `RetainedPatch`), ui/src/screens/Runs/EvidenceDrawer.tsx (the
 *               host; passes the loaded patch), src/crb/core/review.py (the rules this panel
 *               mirrors: verdict derivation, regression ⇒ not mergeable),
 *               src/crb/server/routes/reviews.py (the write boundary and its 422 codes),
 *               ui/src/lib/auth.tsx (`can('operator')`)
 * Tested by:    ui/src/screens/Runs/ReviewPanel.test.tsx, ui/e2e/walkthrough/09-review.spec.ts
 * Touch when:   a finding kind or a write-boundary rule is added (src/crb/core/review.py,
 *               docs/API.md "Reviews") — add the chip, the tone and the client-side blocker
 *               together; never for a new repository.
 * Claims:       A review is governance evidence about mergeability; it never alters the
 *               mechanical grade (docs/EVIDENCE-AND-CLAIMS.md#7-what-must-never-be-said).
 */
import { useMemo, useState } from 'react'
import { isApiError } from '../../api/client'
import { Button } from '../../components/Button'
import { ErrorState } from '../../components/ErrorState'
import { TextArea, TextField } from '../../components/Field'
import { Pill } from '../../components/Pill'
import { Hint } from '../../components/Hint'
import type { HintId } from '../../help/hints'
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

/** Tone per review verdict: regression and defect red, API change amber, style blue, ok green, not reviewed muted. */
export const VERDICT_TONE: Record<Verdict, Tone> = {
  ok: 'green',
  regression: 'red',
  defect: 'red',
  api_change: 'amber',
  style: 'blue',
  not_reviewed: 'muted',
}

/** Glyph per verdict — always alongside the colour. */
const VERDICT_GLYPH: Record<Verdict, string> = {
  ok: '✓',
  regression: '✗',
  defect: '✗',
  api_change: '△',
  style: '≈',
  not_reviewed: '—',
}

/** A review verdict as a pill; `hint` is the shared `review.verdict` unless the caller has a more specific one (the draft preview). */
export function VerdictPill({ verdict, size = 'xs', hint = 'review.verdict' }: { verdict: Verdict; size?: 'xs' | 'sm'; hint?: HintId }) {
  return (
    <Pill tone={VERDICT_TONE[verdict]} glyph={VERDICT_GLYPH[verdict]} size={size} label={`Review verdict: ${VERDICT_LABELS[verdict]}`} data-testid={`review-verdict-${verdict}`} hint={hint}>
      {VERDICT_LABELS[verdict]}
    </Pill>
  )
}

/** The editable note / file / line for one selected finding kind. */
interface FindingDraft {
  note: string
  file: string
  line: string
}

/** A blank draft per kind. */
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

  // The verdict is DERIVED, never chosen: the server re-derives it and refuses a
  // disagreeing client value (422), so the preview and the record cannot diverge.
  const verdict: Verdict = notReviewed ? 'not_reviewed' : deriveVerdict(kinds)
  const anchored = patch !== null && patch.matches
  const missingNotes = kinds.filter((k) => !drafts[k].note.trim())
  const regressionMergeable = kinds.includes('regression') && mergeable === 'yes'
  // Every reason the record cannot be written yet, in the words the reviewer sees. These
  // mirror the server's write boundary (crb.core.review) so a refusal is rare and explained.
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
  // A 422 is the server's write boundary speaking (patch_hash_mismatch, no_diff_in_pack …):
  // rendered with its code, not as a generic failure.
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
              <Hint
                as="button"
                key={k}
                id="button.review.finding"
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
              </Hint>
            )
          })}
          <span className="ml-auto flex items-center gap-2 text-xs text-on-surface-muted">
            verdict <VerdictPill verdict={verdict} hint="pill.review.draft_verdict" />
          </span>
        </div>

        {!notReviewed &&
          FINDING_KINDS.filter((k) => kinds.includes(k)).map((k) => (
            <div key={k} className="grid gap-2 rounded-[var(--radius-control)] border border-border bg-surface-high p-3 sm:grid-cols-[1fr_180px_80px]" data-testid={`finding-${k}`}>
              <TextField
                label={`${FINDING_LABELS[k]} — note`}
                hint="field.review.finding"
                required
                value={drafts[k].note}
                onChange={(e) => setDrafts((d) => ({ ...d, [k]: { ...d[k], note: e.target.value } }))}
                placeholder="What you saw, in one sentence"
              />
              <TextField label="File" hint="field.review.finding" value={drafts[k].file} onChange={(e) => setDrafts((d) => ({ ...d, [k]: { ...d[k], file: e.target.value } }))} placeholder="path (optional)" />
              <TextField label="Line" hint="field.review.finding" inputMode="numeric" value={drafts[k].line} onChange={(e) => setDrafts((d) => ({ ...d, [k]: { ...d[k], line: e.target.value.replace(/[^0-9]/g, '') } }))} placeholder="n" />
            </div>
          ))}

        <Hint as="fieldset" id="field.review.mergeable" className="flex flex-wrap items-center gap-4 text-xs" disabled={notReviewed}>
          <legend className="label">Would a maintainer merge this as-is?</legend>
          {(['yes', 'no', ''] as const).map((v) => (
            <label key={v || 'unanswered'} className="inline-flex items-center gap-1">
              <input type="radio" name="mergeable" value={v} checked={mergeable === v} onChange={() => setMergeable(v)} />
              {v === 'yes' ? 'Mergeable' : v === 'no' ? 'Not mergeable' : 'Not answered'}
            </label>
          ))}
        </Hint>

        <TextArea label="Statement" hint="field.review.statement" required rows={3} value={statement} onChange={(e) => setStatement(e.target.value)} placeholder="What you concluded and why — this is the governance record." />

        <Hint as="label" id="field.review.not_reviewed" className="inline-flex items-center gap-2 text-xs">
          <input type="checkbox" checked={notReviewed} onChange={(e) => setNotReviewed(e.target.checked)} data-testid="not-reviewed" />
          I looked but could not review this row (records <em>not reviewed</em>: no findings, no hash)
        </Hint>

        <Hint as="div" id="tile.review.anchor" className="rounded-[var(--radius-control)] border border-border bg-surface-high p-3 text-xs" data-testid="review-anchor" data-state={anchored ? 'anchored' : 'unanchored'}>
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
        </Hint>

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
          <Button variant="filled" onClick={submit} disabled={!canSubmit} data-testid="review-submit" hint="button.review.record">
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
                    <Pill tone={r.mergeable ? 'green' : 'amber'} size="xs" label={r.mergeable ? 'Mergeable' : 'Not mergeable'} hint="pill.review.mergeable">
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
