/**
 * ui/src/screens/Runs/contract.ts, EvidenceDrawer.tsx and ReviewPanel.tsx — the patch is hashed in
 * the browser and a review attests to those bytes.
 *
 * Navigation
 * ----------
 * What it is:   Tests for the C13 evidence contract helpers, the drawer's Patch / Transcript
 *               tabs and the Review panel, against a mocked API.
 * What it does: Pins the SHA-256 test vectors, the diff parser's counting rule (files the
 *               pack does not list are shown but not counted) and `deriveVerdict`; that the
 *               Patch tab fetches the retained patch, verifies its hash against the pack and
 *               lists the files, warns when the served bytes were redacted, says why nothing
 *               was retained, and resolves the row from the task when only the pack is known;
 *               that the Review panel stays disabled until the patch was loaded in the
 *               session and then submits that hash, refuses a regression marked mergeable
 *               client-side and renders a server refusal honestly, records `not_reviewed`
 *               without a patch, and is read-only for a viewer.
 * How:          `mockApi` with a pack fixture and a raw `fetch` stub for the byte endpoint;
 *               `userEvent` drives the tabs and the form; assertions on the request bodies
 *               and the `patch-*` / `review-*` test ids.
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0006-zero-raw-retention-and-evidence-packs.md
 * Works with:   ui/src/screens/Runs/contract.ts, ui/src/screens/Runs/EvidenceDrawer.tsx,
 *               ui/src/screens/Runs/ReviewPanel.tsx (the code under test), ui/src/test/utils.tsx
 * Tested by:    ui/src/screens/Runs/ReviewPanel.test.tsx
 * Touch when:   a header, a refusal code or a finding kind is added (docs/API.md "Reviews",
 *               "/grades/{row_hash}/patch") — extend the fixture and the matching case.
 */
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { EvidencePack } from '../../api/types'
import { PRINCIPAL, envelope, json, mockApi, renderApp } from '../../test/utils'
import { deriveVerdict, parseUnifiedDiff, sha256Hex, type RetainedStatus, type Review } from './contract'
import { EvidenceDrawer } from './EvidenceDrawer'

const PACK_HASH = 'e'.repeat(64)
const ROW = 'c'.repeat(64)
const TASK = 'a'.repeat(40)

const PATCH =
  'diff --git a/src/calc/__init__.py b/src/calc/__init__.py\n' +
  'index 74837c2..aba7ab9 100644\n' +
  '--- a/src/calc/__init__.py\n' +
  '+++ b/src/calc/__init__.py\n' +
  '@@ -5,3 +5,7 @@ def add(a, b):\n' +
  '     return a + b\n' +
  '+\n' +
  '+\n' +
  '+def subtract(a, b):\n' +
  '+    return a - b\n' +
  'diff --git a/tests/test_subtract.py b/tests/test_subtract.py\n' +
  'new file mode 100644\n' +
  'index 0000000..1111111\n' +
  '--- /dev/null\n' +
  '+++ b/tests/test_subtract.py\n' +
  '@@ -0,0 +1,2 @@\n' +
  '+def test_subtract():\n' +
  '+    assert subtract(4, 2) == 2\n'
const PATCH_SHA = sha256Hex(new TextEncoder().encode(PATCH))

function pack(over: Partial<EvidencePack['grade']> = {}): EvidencePack {
  return {
    schema: 'crb.evidence.v1',
    task: {
      task_id: TASK,
      repo: 'alpha',
      subject: 'feat: add subtract',
      authored: '2026-08-01T12:00:00+00:00',
      test_files: ['tests/test_subtract.py'],
      src_files: ['src/calc/__init__.py'],
      target_tests: ['tests/test_subtract.py'],
      belt_scope: ['tests/'],
      pool: 'standard',
      src_churn: 4,
      size: 'XS',
      capability_class: 'bug.fix',
      language: 'python',
      baseline_failing: ['tests/test_subtract.py'],
      red_checked: true,
      gold_clean: true,
      gold_note: '',
      labels: {},
    },
    grade: {
      task_id: TASK,
      repo: 'alpha',
      mode: 'sighted',
      clean: true,
      tests_unmodified: true,
      target_green: true,
      no_new_failures: true,
      source_changed: true,
      disqualified: false,
      dq_reason: '',
      error: '',
      note: '',
      new_failures: [],
      tamper_files: [],
      changed_files: ['src/calc/__init__.py'],
      diff: { files: ['src/calc/__init__.py'], additions: 4, deletions: 0, diff_sha256: PATCH_SHA },
      target_run: null,
      belt_run: null,
      duration_s: 1.5,
      extra: {},
      ...over,
    },
    apparatus: { apparatus_version: '2.2', crb_version: '2.0.0a0', grader: 'crb.core.grade', runner: 'pytest', executor: { kind: 'local' }, corpus_sha: '', policy_version: '', extra: {} },
    builder: { name: 'editblock', model: 'm', provider: 'p', mode: 'sighted', attempts: 1, turns: 1, tokens_in: 10, tokens_out: 5, cost_usd: 0, latency_s: 1, transcript_ref: '', budget: {}, note: '' },
    run_id: '9'.repeat(32),
    trial: 'r1',
    actor: 'worker-1',
    created: '2026-09-14T12:00:00+00:00',
    notes: {},
    pack_hash: PACK_HASH,
  }
}

const RETAINED: RetainedStatus = {
  row_hash: ROW,
  run_id: '9'.repeat(32),
  retain_worktrees: true,
  retain_transcripts: false,
  patch_available: true,
  patch_reason: '',
  transcript_available: false,
  transcript_reason: 'the builder transcript was not retained (retain.transcripts was off)',
  diff_sha256: PATCH_SHA,
  extra: {},
}

function patchResponse(body = PATCH, over: Record<string, string> = {}): Response {
  const served = sha256Hex(new TextEncoder().encode(body))
  return new Response(body, {
    status: 200,
    headers: {
      'Content-Type': 'text/x-diff; charset=utf-8',
      'X-CRB-Diff-SHA256': PATCH_SHA,
      'X-CRB-Patch-SHA256': PATCH_SHA,
      'X-CRB-Served-SHA256': served,
      'X-CRB-Patch-Verified': 'true',
      'X-CRB-Redacted': 'false',
      'X-CRB-Truncated': 'false',
      ...over,
    },
  })
}

function review(over: Partial<Review> = {}): Review {
  return {
    review_id: 'v'.repeat(32),
    schema: 'crb.review.v1',
    grade_row_hash: ROW,
    repo: 'alpha',
    task_id: TASK,
    subject: 'feat: add subtract',
    grade_clean: true,
    reviewer: 'u1',
    verdict: 'defect',
    findings: [{ kind: 'defect', note: 'extra() is unreachable', file: 'src/calc/extra.py', line: 1 }],
    mergeable: false,
    statement: 'read every hunk',
    patch_sha256_reviewed: PATCH_SHA,
    evidence_pack_hash: PACK_HASH,
    apparatus_version: '2.2',
    created: '2026-09-14T12:30:00+00:00',
    prev_hash: '0'.repeat(64),
    row_hash: 'b'.repeat(64),
    ...over,
  }
}

const OPERATOR = { ...PRINCIPAL, role: 'operator' as const }

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('contract helpers', () => {
  it('sha256Hex matches the published test vectors', () => {
    const enc = new TextEncoder()
    expect(sha256Hex(enc.encode(''))).toBe('e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855')
    expect(sha256Hex(enc.encode('abc'))).toBe('ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad')
    expect(sha256Hex(enc.encode('The quick brown fox jumps over the lazy dog'))).toBe('d7a8fbb307d7809469ca9abcb0082e4f8d5651e46d3cdb762d02d0bf37c9e592')
    // a multi-block message (> 64 bytes) exercises the padding path
    expect(sha256Hex(enc.encode('a'.repeat(1000)))).toBe('41edece42d63e8d9bf515a9ba6932e1c20cbc9f5a5d134645adb5db1b9737ea3')
  })

  it('parseUnifiedDiff counts with the grader rule and excludes files the pack does not list', () => {
    const d = parseUnifiedDiff(PATCH, ['src/calc/__init__.py'])
    expect(d.files.map((f) => f.path)).toEqual(['src/calc/__init__.py', 'tests/test_subtract.py'])
    expect(d.files[0]).toMatchObject({ additions: 4, deletions: 0, excluded: false })
    expect(d.files[1]).toMatchObject({ additions: 2, deletions: 0, excluded: true })
    expect([d.additions, d.deletions]).toEqual([4, 0])
    const all = parseUnifiedDiff(PATCH)
    expect([all.additions, all.deletions]).toEqual([6, 0])
    expect(all.files[0]!.lines.filter((l) => l.kind === 'add')).toHaveLength(4)
    expect(all.files[0]!.lines.some((l) => l.kind === 'hunk')).toBe(true)
    expect(parseUnifiedDiff('')).toEqual({ files: [], additions: 0, deletions: 0 })
  })

  it('deriveVerdict picks the most severe finding', () => {
    expect(deriveVerdict([])).toBe('ok')
    expect(deriveVerdict(['style'])).toBe('style')
    expect(deriveVerdict(['style', 'api_change'])).toBe('api_change')
    expect(deriveVerdict(['defect', 'style'])).toBe('defect')
    expect(deriveVerdict(['defect', 'regression'])).toBe('regression')
  })
})

describe('EvidenceDrawer: Patch tab', () => {
  it('fetches the retained patch, verifies its hash against the pack and lists the files', async () => {
    const { calls } = mockApi({
      'GET /auth/me': PRINCIPAL,
      [`GET /evidence/${PACK_HASH}`]: { pack: pack(), verified: true },
      [`GET /grades/${ROW}/retained`]: RETAINED,
      [`GET /grades/${ROW}/patch`]: () => patchResponse(),
      'GET /reviews': { items: [], total: 0, limit: 200, offset: 0 },
    })
    renderApp(<EvidenceDrawer packHash={PACK_HASH} rowHash={ROW} onClose={() => {}} />, { me: PRINCIPAL })
    const user = userEvent.setup()
    await screen.findByTestId('tab-patch')
    expect(calls.some((c) => c.path === `/grades/${ROW}/patch`)).toBe(false) // nothing fetched until the tab opens
    await user.click(screen.getByTestId('tab-patch'))
    await screen.findByTestId('patch-verified')
    expect(screen.queryByTestId('patch-warning')).toBeNull()
    const files = within(screen.getByTestId('patch-files')).getAllByRole('listitem')
    expect(files).toHaveLength(2)
    expect(files[0]).toHaveTextContent('src/calc/__init__.py')
    expect(files[0]).toHaveTextContent('+4')
    expect(files[1]).toHaveTextContent('(not counted)')
    expect(screen.getByTestId('patch-counts')).toHaveAttribute('data-state', 'match')
    expect(screen.getByTestId('patch-counts')).toHaveTextContent('4 / 0 · matches the pack')
    const added = screen.getAllByTestId('patch-file')[0]!.querySelectorAll('[data-kind="add"]')
    expect(added).toHaveLength(4)
  })

  it('warns when the served bytes do not hash to the pack (redacted)', async () => {
    mockApi({
      'GET /auth/me': PRINCIPAL,
      [`GET /evidence/${PACK_HASH}`]: { pack: pack(), verified: true },
      [`GET /grades/${ROW}/retained`]: RETAINED,
      [`GET /grades/${ROW}/patch`]: () => patchResponse(PATCH.replace('subtract(4, 2)', '[REDACTED]'), { 'X-CRB-Redacted': 'true' }),
      'GET /reviews': { items: [], total: 0, limit: 200, offset: 0 },
    })
    renderApp(<EvidenceDrawer packHash={PACK_HASH} rowHash={ROW} onClose={() => {}} />, { me: PRINCIPAL })
    const user = userEvent.setup()
    await user.click(await screen.findByTestId('tab-patch'))
    await screen.findByTestId('patch-mismatch')
    expect(screen.getByTestId('patch-redacted')).toBeInTheDocument()
    expect(screen.getByTestId('patch-warning')).toHaveTextContent(/redacted/)
    expect(screen.getByTestId('patch-view')).toHaveAttribute('data-state', 'mismatch')
  })

  it('says why when nothing was retained, and the transcript tab reports its reason', async () => {
    mockApi({
      'GET /auth/me': PRINCIPAL,
      [`GET /evidence/${PACK_HASH}`]: { pack: pack(), verified: true },
      [`GET /grades/${ROW}/retained`]: { ...RETAINED, patch_available: false, patch_reason: 'the run did not retain worktrees (retain.worktrees was off) and none exists', retain_worktrees: false },
      [`GET /grades/${ROW}/transcript`]: () => envelope(404, 'transcript_unavailable', 'not retained', { reason: 'the builder transcript was not retained (retain.transcripts was off)' }),
      'GET /reviews': { items: [], total: 0, limit: 200, offset: 0 },
    })
    renderApp(<EvidenceDrawer packHash={PACK_HASH} rowHash={ROW} onClose={() => {}} />, { me: PRINCIPAL })
    const user = userEvent.setup()
    await user.click(await screen.findByTestId('tab-patch'))
    expect(await screen.findByTestId('patch-unavailable')).toHaveTextContent('did not retain worktrees')
    await user.click(screen.getByTestId('tab-transcript'))
    expect(await screen.findByTestId('transcript-unavailable')).toHaveTextContent('was not retained')
  })

  it('resolves the row from the task when the opener only knows the pack', async () => {
    mockApi({
      'GET /auth/me': PRINCIPAL,
      [`GET /evidence/${PACK_HASH}`]: { pack: pack(), verified: true },
      [`GET /tasks/alpha/${TASK}`]: { spec: pack().task, grades: [{ row_hash: ROW, evidence_pack_hash: PACK_HASH, row_id: 'r1' }] },
      [`GET /grades/${ROW}/retained`]: RETAINED,
      [`GET /grades/${ROW}/patch`]: () => patchResponse(),
      'GET /reviews': { items: [review()], total: 1, limit: 200, offset: 0 },
    })
    renderApp(<EvidenceDrawer packHash={PACK_HASH} onClose={() => {}} />, { me: PRINCIPAL })
    const user = userEvent.setup()
    await screen.findByText('Review (1)')
    await user.click(screen.getByTestId('tab-patch'))
    await screen.findByTestId('patch-verified')
  })
})

describe('EvidenceDrawer: Review panel', () => {
  function setup(routes: Record<string, unknown> = {}) {
    const posts: unknown[] = []
    const reviewsList = { items: [] as Review[], total: 0, limit: 200, offset: 0 }
    const m = mockApi({
      'GET /auth/me': OPERATOR,
      [`GET /evidence/${PACK_HASH}`]: { pack: pack(), verified: true },
      [`GET /grades/${ROW}/retained`]: RETAINED,
      [`GET /grades/${ROW}/patch`]: () => patchResponse(),
      'GET /reviews': () => json(reviewsList),
      'POST /reviews': (_url: string, init: RequestInit | undefined) => {
        const body = JSON.parse(String(init?.body)) as Record<string, unknown>
        posts.push(body)
        const r = review({ verdict: body.not_reviewed ? 'not_reviewed' : deriveVerdict((body.findings as Array<{ kind: 'defect' }>).map((f) => f.kind)), statement: String(body.statement), mergeable: (body.mergeable as boolean | null) ?? null })
        reviewsList.items.push(r)
        reviewsList.total = reviewsList.items.length
        return json(r, 201)
      },
      ...routes,
    })
    renderApp(<EvidenceDrawer packHash={PACK_HASH} rowHash={ROW} onClose={() => {}} />, { me: OPERATOR })
    return { ...m, posts }
  }

  it('stays disabled until the patch was loaded in this session, then submits the loaded hash', async () => {
    const { posts } = setup()
    const user = userEvent.setup()
    await user.click(await screen.findByTestId('tab-review'))
    const submit = await screen.findByTestId('review-submit')
    expect(submit).toBeDisabled()
    expect(screen.getByTestId('review-anchor')).toHaveAttribute('data-state', 'unanchored')
    expect(screen.getByTestId('review-blockers')).toHaveTextContent('Open the Patch tab first')
    expect(screen.getByTestId('reviews-empty')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Open the Patch tab' }))
    await screen.findByTestId('patch-verified')
    await user.click(screen.getByTestId('tab-review'))
    await waitFor(() => expect(screen.getByTestId('review-anchor')).toHaveAttribute('data-state', 'anchored'))

    // a defect finding needs a note; the verdict chip follows the selection
    await user.click(screen.getByTestId('finding-chip-defect'))
    expect(screen.getByTestId('review-verdict-defect')).toBeInTheDocument()
    expect(screen.getByTestId('review-blockers')).toHaveTextContent('Each selected finding needs a note')
    await user.type(screen.getByLabelText(/Defect — note/), 'extra() is unreachable')
    await user.type(screen.getByLabelText(/^File/), 'src/calc/extra.py')
    await user.type(screen.getByLabelText(/^Line/), '1')
    await user.click(screen.getByLabelText('Not mergeable'))
    await user.type(screen.getByLabelText(/^Statement/), 'read every hunk')
    expect(screen.queryByTestId('review-blockers')).toBeNull()
    expect(screen.getByTestId('review-submit')).toBeEnabled()
    await user.click(screen.getByTestId('review-submit'))

    await screen.findByTestId('review-recorded')
    expect(posts).toHaveLength(1)
    expect(posts[0]).toEqual({
      grade_row_hash: ROW,
      statement: 'read every hunk',
      findings: [{ kind: 'defect', note: 'extra() is unreachable', file: 'src/calc/extra.py', line: 1 }],
      mergeable: false,
      patch_sha256: PATCH_SHA,
    })
    // the list refreshes and shows the recorded review
    const list = await screen.findByTestId('reviews-list')
    expect(within(list).getAllByTestId('review-item')).toHaveLength(1)
    expect(within(list).getByTestId('review-verdict-defect')).toBeInTheDocument()
    expect(list).toHaveTextContent('extra() is unreachable')
  })

  it('refuses a regression marked mergeable client-side and renders a server refusal honestly', async () => {
    setup({
      'POST /reviews': () => envelope(422, 'review_refused', 'patch_sha256_reviewed does not match the evidence pack', { code: 'patch_hash_mismatch', expected: PATCH_SHA, observed: 'f'.repeat(64) }),
    })
    const user = userEvent.setup()
    await user.click(await screen.findByTestId('tab-patch'))
    await screen.findByTestId('patch-verified')
    await user.click(screen.getByTestId('tab-review'))
    await user.click(screen.getByTestId('finding-chip-regression'))
    await user.type(screen.getByLabelText(/Regression — note/), 'breaks add')
    await user.click(screen.getByLabelText('Mergeable'))
    await user.type(screen.getByLabelText(/^Statement/), 's')
    expect(screen.getByTestId('review-blockers')).toHaveTextContent('never mergeable')
    expect(screen.getByTestId('review-submit')).toBeDisabled()
    await user.click(screen.getByLabelText('Not mergeable'))
    expect(screen.getByTestId('review-submit')).toBeEnabled()
    await user.click(screen.getByTestId('review-submit'))
    const alert = await screen.findByTestId('review-refused')
    expect(alert).toHaveTextContent('review_refused · patch_hash_mismatch')
    expect(screen.queryByTestId('review-recorded')).toBeNull()
  })

  it('records not_reviewed without a patch and hides the finding chips', async () => {
    const { posts } = setup({ [`GET /grades/${ROW}/retained`]: { ...RETAINED, patch_available: false, patch_reason: 'gone' } })
    const user = userEvent.setup()
    await user.click(await screen.findByTestId('tab-review'))
    await user.click(screen.getByTestId('not-reviewed'))
    expect(screen.getByTestId('finding-chip-defect')).toBeDisabled()
    expect(screen.getByTestId('review-verdict-not_reviewed')).toBeInTheDocument()
    await user.type(screen.getByLabelText(/^Statement/), 'worktree gone')
    await user.click(screen.getByTestId('review-submit'))
    await screen.findByTestId('review-recorded')
    expect(posts[0]).toEqual({ grade_row_hash: ROW, statement: 'worktree gone', findings: [], mergeable: null, patch_sha256: '', not_reviewed: true })
  })

  it('a viewer sees the panel but cannot record', async () => {
    mockApi({
      'GET /auth/me': { ...PRINCIPAL, role: 'viewer' },
      [`GET /evidence/${PACK_HASH}`]: { pack: pack(), verified: true },
      [`GET /grades/${ROW}/retained`]: RETAINED,
      'GET /reviews': { items: [review()], total: 1, limit: 200, offset: 0 },
    })
    renderApp(<EvidenceDrawer packHash={PACK_HASH} rowHash={ROW} onClose={() => {}} />, { me: { ...PRINCIPAL, role: 'viewer' } })
    const user = userEvent.setup()
    await user.click(await screen.findByTestId('tab-review'))
    expect(await screen.findByTestId('review-blockers')).toHaveTextContent('operator role')
    expect(screen.getByTestId('review-submit')).toBeDisabled()
    expect(within(screen.getByTestId('reviews-list')).getAllByTestId('review-item')).toHaveLength(1)
  })
})

describe('EvidenceDrawer: Pack tab headline (J-FAC-9)', () => {
  const routes = (p: EvidencePack, verified = true) => ({
    'GET /auth/me': PRINCIPAL,
    [`GET /evidence/${PACK_HASH}`]: { pack: p, verified },
    [`GET /grades/${ROW}/retained`]: RETAINED,
    'GET /reviews': { items: [], total: 0, limit: 200, offset: 0 },
  })

  it('opens with one sentence: clean names the belt count and what verified does not mean', async () => {
    mockApi(routes(pack()))
    renderApp(<EvidenceDrawer packHash={PACK_HASH} rowHash={ROW} onClose={() => {}} />, { me: PRINCIPAL })
    const h = await screen.findByTestId('pack-headline')
    expect(h.textContent).toBe('Clean: all four belts held and the pack’s hash verifies. This says nothing about whether the change is mergeable.')
  })

  it('not clean names the first failed belt and its cause', async () => {
    mockApi(routes(pack({ clean: false, no_new_failures: false, new_failures: ['test_divide_zero', 'test_divide_negative'] })))
    renderApp(<EvidenceDrawer packHash={PACK_HASH} rowHash={ROW} onClose={() => {}} />, { me: PRINCIPAL })
    const h = await screen.findByTestId('pack-headline')
    expect(h.textContent).toBe('Not clean: belt 3 (the repository’s own suite) — 2 new failures: test_divide_zero, test_divide_negative.')
  })

  it('a hash mismatch is the headline, never hidden behind a clean grade', async () => {
    mockApi(routes(pack(), false))
    renderApp(<EvidenceDrawer packHash={PACK_HASH} rowHash={ROW} onClose={() => {}} />, { me: PRINCIPAL })
    const h = await screen.findByTestId('pack-headline')
    expect(h.textContent).toContain('does not verify — treat this evidence as untrusted')
  })
})
