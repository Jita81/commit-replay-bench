/**
 * The C13 additions to the evidence contract (docs/API.md, review §5 plays 05/07 /
 * action #3): the retained patch and transcript behind a graded row, and the human
 * REVIEW of that row — a ledger record anchored to the sha256 of the patch bytes the
 * reviewer loaded.
 *
 * Lives beside the screen (not in `api/types.ts` / `api/hooks.ts`, which another
 * workstream owns in this wave) — fold it in when the wave merges. Every field here is
 * `@contract` with `crb.server.schemas_review` / `crb.server.routes.grades`.
 *
 * Navigation
 * ----------
 * What it is:   The UI's reading of the retained-artefact and review endpoints: types
 *               (`Review`, `RetainedStatus`, `RetainedPatch`), the hooks, a dependency-free
 *               SHA-256, the patch fetcher and the unified-diff parser.
 * What it does: Fetches `GET /grades/{row_hash}/patch` as BYTES, hashes them in the browser
 *               and compares with the pack's `diff_sha256` header — `matches` is what unlocks a
 *               review, because a reviewer attests to the exact bytes the instrument graded,
 *               never to a description of them. `parseUnifiedDiff` counts +/− with the
 *               grader's own rule so the view can agree with the pack. `deriveVerdict` mirrors
 *               the core's one rule (most severe finding wins) for the preview.
 * How:          Pure JS SHA-256 (Web Crypto is not in every test runtime) → `fetchRetainedPatch`
 *               reads the `X-CRB-*` headers → TanStack hooks keyed under `['grades', rowHash, …]`
 *               and `['reviews', …]`; `useCreateReview` invalidates every reviews query.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0006-zero-raw-retention-and-evidence-packs.md
 * Works with:   src/crb/server/routes/grades.py (the patch / transcript / retained routes and
 *               their headers), src/crb/server/routes/reviews.py and
 *               src/crb/server/schemas_review.py (the review records), src/crb/core/review.py
 *               (`derive_verdict`, `SEVERITY` — mirrored here),
 *               ui/src/screens/Runs/EvidenceDrawer.tsx
 *               (the Patch and Transcript tabs), ui/src/screens/Runs/ReviewPanel.tsx (the
 *               review form), ui/src/api/client.ts (`ApiError`, `fetchBounded`, `errorFromResponse`)
 * Tested by:    ui/src/screens/Runs/ReviewPanel.test.tsx (SHA-256 test vectors, the diff
 *               parser's counting rule, `deriveVerdict`, the anchor flow),
 *               ui/e2e/walkthrough/09-review.spec.ts (a real retained worktree end to end)
 * Touch when:   a finding kind or the anchor rule changes (src/crb/core/review.py,
 *               docs/API.md "Reviews") — change the vocabulary here and in
 *               ui/src/screens/Runs/ReviewPanel.tsx; never for a new repository.
 * Claims:       A review is a human's verdict on one row, anchored to the patch hash — it is
 *               not part of the grade and never changes `clean`
 *               (docs/EVIDENCE-AND-CLAIMS.md#7-what-must-never-be-said).
 */

import { useMutation, useQuery, useQueryClient, type UseMutationResult, type UseQueryResult } from '@tanstack/react-query'
import { type ApiError, api, errorFromResponse, fetchBounded, qs } from '../../api/client'
import type { Page } from '../../api/types'

// ---------------------------------------------------------------------------
// Vocabulary (crb.core.review)
// ---------------------------------------------------------------------------

/** The closed set of finding kinds (`crb.core.review`); a verdict is the most severe present. */
export type FindingKind = 'regression' | 'defect' | 'api_change' | 'style'
/** A review's headline: `ok`, a finding kind, or `not_reviewed` (looked, could not review). */
export type Verdict = 'ok' | FindingKind | 'not_reviewed'

/** `crb.core.review.SEVERITY` — most severe first; the headline is the first kind present. */
export const FINDING_KINDS: readonly FindingKind[] = ['regression', 'defect', 'api_change', 'style']

/** Display names per kind. */
export const FINDING_LABELS: Record<FindingKind, string> = {
  regression: 'Regression',
  defect: 'Defect',
  api_change: 'API change',
  style: 'Style',
}

/** Display names per verdict. */
export const VERDICT_LABELS: Record<Verdict, string> = {
  ok: 'OK',
  regression: 'Regression',
  defect: 'Defect',
  api_change: 'API change',
  style: 'Style',
  not_reviewed: 'Not reviewed',
}

/** `crb.core.review.derive_verdict` — the one rule, mirrored for the preview. */
export function deriveVerdict(kinds: Iterable<FindingKind>): Verdict {
  const set = new Set(kinds)
  for (const k of FINDING_KINDS) if (set.has(k)) return k
  return 'ok'
}

/** One finding as stored: kind, note, optional file and line. */
export interface Finding {
  kind: FindingKind
  note: string
  file: string
  line: number | null
}

/** `GET /reviews` items / `POST /reviews` → `ReviewOut`. */
export interface Review {
  review_id: string
  schema: string
  grade_row_hash: string
  repo: string
  task_id: string
  subject: string
  grade_clean: boolean | null
  reviewer: string
  verdict: Verdict
  findings: Finding[]
  mergeable: boolean | null
  statement: string
  patch_sha256_reviewed: string
  evidence_pack_hash: string
  apparatus_version: string
  created: string
  prev_hash: string
  row_hash: string
}

/** `POST /reviews` body; `patch_sha256` must equal the pack's `diff_sha256` or the server answers 422. */
export interface ReviewCreateRequest {
  grade_row_hash: string
  statement: string
  findings: Array<{ kind: FindingKind; note: string; file?: string; line?: number | null }>
  mergeable: boolean | null
  /** sha256 of the patch bytes the reviewer LOADED (must equal the pack's diff_sha256). */
  patch_sha256: string
  not_reviewed?: boolean
}

/** `GET /reviews/verify` — chain intact and every verdict anchored. */
export interface ReviewVerify {
  rows: number
  ok: boolean
  chain_ok: boolean
  broken_at: number | null
  detail: string
  anchored: number
  unanchored: number
  verified_at: string
}

/** `GET /reviews/stats` — the standing verdict per row joined onto one cell. */
export interface ReviewCellStats {
  process_step: string
  capability_class: string
  size: string
  language: string
  builder: string
  model: string
  provider: string
  n_rows: number
  n_reviewed: number
  n_review_defects: number
  reviewed_share: number
  n_ok: number
  n_defect: number
  n_regression: number
  n_api_change: number
  n_style: number
  n_not_reviewed: number
  n_mergeable: number
  n_not_mergeable: number
}

/** `GET /reviews/stats?repo=` — one entry per cell under the same projection as the map. */
export interface ReviewStats {
  repo: string
  by: string[]
  n_reviews: number
  cells: ReviewCellStats[]
}

/** `GET /grades/{row_hash}/retained`. */
export interface RetainedStatus {
  row_hash: string
  run_id: string
  retain_worktrees: boolean
  retain_transcripts: boolean
  patch_available: boolean
  patch_reason: string
  transcript_available: boolean
  transcript_reason: string
  diff_sha256: string
  extra: Record<string, unknown>
}

// ---------------------------------------------------------------------------
// SHA-256 (dependency-free; Web Crypto is not available in every test runtime)
// ---------------------------------------------------------------------------

/** SHA-256 round constants (FIPS 180-4). */
const K = new Uint32Array([
  0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5, 0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3,
  0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
  0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13,
  0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
  0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3, 0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208,
  0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
])

/** SHA-256 of `bytes`, lowercase hex. Pure JS, ~1 MiB in well under a second. */
export function sha256Hex(bytes: Uint8Array): string {
  const rotr = (x: number, n: number) => (x >>> n) | (x << (32 - n))
  const len = bytes.length
  const bitLenHi = Math.floor((len * 8) / 0x100000000)
  const bitLenLo = (len * 8) >>> 0
  const padded = new Uint8Array(((len + 9 + 63) >> 6) << 6)
  padded.set(bytes)
  padded[len] = 0x80
  const dv = new DataView(padded.buffer)
  dv.setUint32(padded.length - 8, bitLenHi)
  dv.setUint32(padded.length - 4, bitLenLo)
  const h = new Uint32Array([0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19])
  const w = new Uint32Array(64)
  for (let off = 0; off < padded.length; off += 64) {
    for (let i = 0; i < 16; i++) w[i] = dv.getUint32(off + i * 4)
    for (let i = 16; i < 64; i++) {
      const s0 = rotr(w[i - 15]!, 7) ^ rotr(w[i - 15]!, 18) ^ (w[i - 15]! >>> 3)
      const s1 = rotr(w[i - 2]!, 17) ^ rotr(w[i - 2]!, 19) ^ (w[i - 2]! >>> 10)
      w[i] = (w[i - 16]! + s0 + w[i - 7]! + s1) >>> 0
    }
    let [a, b, c, d, e, f, g, hh] = h as unknown as [number, number, number, number, number, number, number, number]
    for (let i = 0; i < 64; i++) {
      const S1 = rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25)
      const ch = (e & f) ^ (~e & g)
      const t1 = (hh + S1 + ch + K[i]! + w[i]!) >>> 0
      const S0 = rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22)
      const maj = (a & b) ^ (a & c) ^ (b & c)
      const t2 = (S0 + maj) >>> 0
      hh = g
      g = f
      f = e
      e = (d + t1) >>> 0
      d = c
      c = b
      b = a
      a = (t1 + t2) >>> 0
    }
    h[0] = (h[0]! + a) >>> 0
    h[1] = (h[1]! + b) >>> 0
    h[2] = (h[2]! + c) >>> 0
    h[3] = (h[3]! + d) >>> 0
    h[4] = (h[4]! + e) >>> 0
    h[5] = (h[5]! + f) >>> 0
    h[6] = (h[6]! + g) >>> 0
    h[7] = (h[7]! + hh) >>> 0
  }
  let out = ''
  for (let i = 0; i < 8; i++) out += h[i]!.toString(16).padStart(8, '0')
  return out
}

// ---------------------------------------------------------------------------
// The patch: fetched as bytes, hashed here, parsed for the viewer
// ---------------------------------------------------------------------------

/** Response headers of `GET /grades/{row_hash}/patch` (crb.server.routes.grades). */
export const PATCH_HEADERS = {
  diffSha: 'x-crb-diff-sha256',
  patchSha: 'x-crb-patch-sha256',
  servedSha: 'x-crb-served-sha256',
  verified: 'x-crb-patch-verified',
  redacted: 'x-crb-redacted',
  truncated: 'x-crb-truncated',
} as const

/** The served patch plus every hash involved; `matches` (our own hash == the pack's anchor) is the only flag that unlocks a review. */
export interface RetainedPatch {
  /** The served bytes, decoded. */
  text: string
  /** sha256 of the served bytes, computed HERE — what a review attests to. */
  sha256: string
  /** The pack's anchor (`X-CRB-Diff-SHA256`). */
  diffSha256: string
  /** What the worktree hashed to on the server (`X-CRB-Patch-SHA256`). */
  patchSha256: string
  /** The server's own verdict: worktree hash == anchor. */
  serverVerified: boolean
  redacted: boolean
  truncated: boolean
  /** Our verdict: sha256(served bytes) == the anchor. This is what unlocks a review. */
  matches: boolean
}

/** `GET /grades/{row_hash}/patch` as bytes (not through `api<T>`, which parses JSON): hash the bytes here, read the `X-CRB-*` headers, and map a non-2xx to `ApiError` like the client does. */
export async function fetchRetainedPatch(rowHash: string, signal?: AbortSignal): Promise<RetainedPatch> {
  const path = `/grades/${encodeURIComponent(rowHash)}/patch`
  // The shared client's two guarantees, kept here too: a stall is bounded (`timeout`,
  // never an infinite spinner) and a half-shaped error body is `invalid_response`, not a
  // fabricated code (CodeRabbit on PR #6).
  const res = await fetchBounded(path, { headers: { Accept: 'text/x-diff' } }, { signal })
  if (!res.ok) throw await errorFromResponse(res, path)
  const bytes = new Uint8Array(await res.arrayBuffer())
  const sha256 = sha256Hex(bytes)
  const diffSha256 = res.headers.get(PATCH_HEADERS.diffSha) ?? ''
  return {
    text: new TextDecoder('utf-8').decode(bytes),
    sha256,
    diffSha256,
    patchSha256: res.headers.get(PATCH_HEADERS.patchSha) ?? '',
    serverVerified: res.headers.get(PATCH_HEADERS.verified) === 'true',
    redacted: res.headers.get(PATCH_HEADERS.redacted) === 'true',
    truncated: res.headers.get(PATCH_HEADERS.truncated) === 'true',
    matches: diffSha256.length === 64 && sha256 === diffSha256,
  }
}

/** Line classes of a unified diff for colouring. */
export type DiffLineKind = 'add' | 'del' | 'ctx' | 'hunk' | 'meta'

/** One line of the parsed diff. */
export interface DiffLine {
  kind: DiffLineKind
  text: string
}

/** One file of the parsed diff with its own +/− counts; `excluded` = not in the pack's `diff.files` (shown, not counted). */
export interface DiffFile {
  path: string
  additions: number
  deletions: number
  lines: DiffLine[]
  /** Not in the pack's `diff.files` (e.g. the overlaid oracle): shown, not counted. */
  excluded: boolean
}

/** The files plus the counts over the files the pack lists — so the view can agree with the pack. */
export interface ParsedDiff {
  files: DiffFile[]
  /** Counts over the files the pack lists — the pack's own counting rule. */
  additions: number
  deletions: number
}

/** Split a unified diff into files with +/− counts (the grader's counting rule: a
 * line is an addition when it starts with `+` but not `+++`). */
export function parseUnifiedDiff(text: string, packFiles: readonly string[] = []): ParsedDiff {
  const counted = new Set(packFiles)
  const files: DiffFile[] = []
  let cur: DiffFile | null = null
  for (const raw of text.split('\n')) {
    if (raw.startsWith('diff --git ')) {
      cur = { path: '', additions: 0, deletions: 0, lines: [], excluded: false }
      files.push(cur)
      cur.lines.push({ kind: 'meta', text: raw })
      continue
    }
    if (!cur) {
      if (raw === '') continue
      cur = { path: '', additions: 0, deletions: 0, lines: [], excluded: false }
      files.push(cur)
    }
    if (raw.startsWith('+++ ')) {
      const p = raw.startsWith('+++ b/') ? raw.slice(6) : raw.slice(4)
      if (p !== '/dev/null') cur.path = p
      cur.lines.push({ kind: 'meta', text: raw })
    } else if (raw.startsWith('--- ')) {
      if (!cur.path && raw.startsWith('--- a/')) cur.path = raw.slice(6)
      cur.lines.push({ kind: 'meta', text: raw })
    } else if (raw.startsWith('@@')) {
      cur.lines.push({ kind: 'hunk', text: raw })
    } else if (raw.startsWith('+')) {
      cur.additions += 1
      cur.lines.push({ kind: 'add', text: raw })
    } else if (raw.startsWith('-')) {
      cur.deletions += 1
      cur.lines.push({ kind: 'del', text: raw })
    } else if (raw.startsWith(' ') || raw === '') {
      cur.lines.push({ kind: 'ctx', text: raw })
    } else {
      cur.lines.push({ kind: 'meta', text: raw })
    }
  }
  for (const f of files) f.excluded = counted.size > 0 && !counted.has(f.path)
  const inScope = files.filter((f) => !f.excluded)
  return {
    files,
    additions: inScope.reduce((n, f) => n + f.additions, 0),
    deletions: inScope.reduce((n, f) => n + f.deletions, 0),
  }
}

// ---------------------------------------------------------------------------
// Hooks
// ---------------------------------------------------------------------------

/** Query keys for the retained artefacts and the reviews (nested under `['grades', rowHash]` / `['reviews']`). */
export const reviewKeys = {
  retained: (rowHash: string) => ['grades', rowHash, 'retained'] as const,
  patch: (rowHash: string) => ['grades', rowHash, 'patch'] as const,
  transcript: (rowHash: string) => ['grades', rowHash, 'transcript'] as const,
  reviews: (p: ReviewListParams) => ['reviews', p] as const,
  verify: ['reviews', 'verify'] as const,
  stats: (repo: string, by: string) => ['reviews', 'stats', repo, by] as const,
}

/** `GET /grades/{row_hash}/retained` — what stands behind the row right now, with a reason each. */
export function useRetainedStatus(rowHash: string): UseQueryResult<RetainedStatus, ApiError> {
  return useQuery({
    queryKey: reviewKeys.retained(rowHash),
    queryFn: () => api<RetainedStatus>(`/grades/${encodeURIComponent(rowHash)}/retained`),
    enabled: rowHash.length > 0,
    retry: false,
  })
}

/** The patch, fetched only once `enabled` (the tab was opened) — content-addressed, never refetched. */
export function useRetainedPatch(rowHash: string, enabled: boolean): UseQueryResult<RetainedPatch, ApiError> {
  return useQuery({
    queryKey: reviewKeys.patch(rowHash),
    queryFn: ({ signal }) => fetchRetainedPatch(rowHash, signal),
    enabled: enabled && rowHash.length > 0,
    retry: false,
    staleTime: Infinity,
  })
}

/** The transcript as text, and parsed when it was JSON. */
export interface RetainedTranscript {
  text: string
  json: unknown | null
}

/** `GET /grades/{row_hash}/transcript` — served only from inside the transcripts directory; a 404 carries the reason. */
export function useRetainedTranscript(rowHash: string, enabled: boolean): UseQueryResult<RetainedTranscript, ApiError> {
  return useQuery({
    queryKey: reviewKeys.transcript(rowHash),
    queryFn: async () => {
      const raw = await api<unknown>(`/grades/${encodeURIComponent(rowHash)}/transcript`)
      if (typeof raw === 'string') return { text: raw, json: null }
      return { text: JSON.stringify(raw, null, 2), json: raw }
    },
    enabled: enabled && rowHash.length > 0,
    retry: false,
    staleTime: Infinity,
  })
}

/** `GET /reviews` filters. */
export interface ReviewListParams {
  repo?: string
  task_id?: string
  grade_row_hash?: string
  limit?: number
}

/** `GET /reviews` in chain order (the latest per row is the standing verdict). */
export function useReviews(p: ReviewListParams, enabled = true): UseQueryResult<Page<Review>, ApiError> {
  return useQuery({
    queryKey: reviewKeys.reviews(p),
    queryFn: () =>
      api<Page<Review>>(`/reviews${qs({ repo: p.repo, task_id: p.task_id, grade_row_hash: p.grade_row_hash, limit: p.limit ?? 200 })}`),
    enabled,
    retry: false,
  })
}

/** `POST /reviews`; invalidates every reviews query (lists, stats, the drawer's count). */
export function useCreateReview(): UseMutationResult<Review, ApiError, ReviewCreateRequest> {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body) => api<Review>('/reviews', { method: 'POST', body }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['reviews'] })
    },
  })
}

/** `GET /reviews/stats?repo=&by=`. */
export function useReviewStats(repo: string, by = 'class,size'): UseQueryResult<ReviewStats, ApiError> {
  return useQuery({
    queryKey: reviewKeys.stats(repo, by),
    queryFn: () => api<ReviewStats>(`/reviews/stats${qs({ repo, by })}`),
    enabled: repo.length > 0,
    retry: false,
  })
}
