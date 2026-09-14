/**
 * The B7 additions to the sign-off contract (docs/API.md, review §5 play 06 / §7 item 6):
 * a sign-off is a policy decision refused at write (`signoff-policy.v1`), previewed
 * before the approver tries, and recorded with the approver's attestation that they
 * read one specific accepted row of the cell.
 *
 * Lives beside the screen (not in `api/types.ts` / `api/hooks.ts`, which another
 * workstream owns in this wave) — fold it in when the wave merges. Every field here is
 * `@contract` with `crb.server.schemas_signoff`.
 */

import { useMutation, useQuery, useQueryClient, type UseMutationResult, type UseQueryResult } from '@tanstack/react-query'
import { api, qs, type ApiError } from '../../api/client'
import type { Signoff } from '../../api/types'
import type { ControlsVerdict, FailureSplit, ReasonCode } from '../Capability/contract'

// ---------------------------------------------------------------------------
// Vocabulary (crb.core.signoff)
// ---------------------------------------------------------------------------

/** `crb.core.signoff.REFUSAL_CODES` — the route clause carries its reason code as a suffix. */
export type RefusalCode =
  | 'false_q1'
  | 'scope_mismatch'
  | 'thin_cell'
  | 'controls_unmeasured'
  | 'controls_failed'
  | 'controls_escapes'
  | 'controls_thin'
  | 'oracle_weak'
  | `route_not_deliver:${ReasonCode | 'unrouted' | 'unknown'}`
  | 'attestation_missing'

export const SIGNOFF_POLICY_VERSION = 'signoff-policy.v1'

/** `SignoffPolicy.to_dict()` — the bar in force (defaults or the deployment's relaxed values). */
export interface SignoffPolicy {
  policy_version: string
  relaxed: boolean
  non_overridable: string[]
  bounds: Record<string, [number, number]>
  n_min: number
  require_route_deliver: boolean
  require_controls_passed: boolean
  max_controls_escapes: number
  min_constructible_share: number
  min_oracle_strength: number
  require_attestation: boolean
}

/** `SignoffRefusal.to_dict()` — one failing clause, observed vs threshold. */
export interface SignoffRefusal {
  code: RefusalCode | string
  message: string
  threshold: unknown
  observed: unknown
  overridable: boolean
}

export interface SignoffRoute {
  route: string
  reason: string
  reason_code: ReasonCode | ''
}

/** The controls verdict as stamped into a record (`k` = constructible). */
export interface SignoffControlsSnapshot {
  verdict: ControlsVerdict['state'] | ''
  run_id: string
  k: number
  total: number
  escapes: number
  created: string
}

export interface Attestation {
  reviewed_task_id: string
  reviewed_row_hash: string
  statement: string
  at: string
  subject: string
}

export interface AttestationIn {
  reviewed_row_hash: string
  statement: string
}

/** One accepted row the approver may name (clean, not disqualified; newest first). */
export interface AcceptedRow {
  row_hash: string
  row_id: string
  task_id: string
  subject: string
  created: string
  run_id: string
  trial: string
  builder: string
  model: string
  evidence_pack_hash: string
}

/** `GET /signoffs` items / `POST /signoffs` → `SignoffWithPolicyOut`. */
export interface SignoffWithPolicy extends Signoff {
  active: boolean
  current_false_q1: number
  prev_hash: string
  row_hash: string
  schema: string
  evidence: Signoff['evidence'] & { ci_high: number; oracle_strength: number | null }
  policy_version: string
  policy_thresholds: Record<string, unknown>
  route: SignoffRoute
  controls: SignoffControlsSnapshot
  attestation: Attestation | null
}

export interface SignoffCreateWithAttestation {
  repo: string
  cell: Record<string, string>
  note: string
  attestation: AttestationIn
}

export interface SignoffPreviewEvidence {
  measured: boolean
  n: number
  clean: number
  point: number | null
  ci_low: number | null
  ci_high: number | null
  false_q1: number
  oracle_strength: number | null
  apparatus_versions: string[]
  belt_sets: string[]
  model_n: number
  model_point: number | null
  failure_split: FailureSplit
}

/** `GET /signoffs/preview` — what a sign-off WOULD record, and every refusal that would apply. */
export interface SignoffPreview {
  repo: string
  cell: Record<string, string>
  policy: SignoffPolicy
  evidence: SignoffPreviewEvidence
  route: SignoffRoute
  controls: ControlsVerdict
  refusals: SignoffRefusal[]
  signable: boolean
  would_record: Record<string, unknown>
  accepted_rows: AcceptedRow[]
  attestation: Attestation | null
}

// ---------------------------------------------------------------------------
// Hooks
// ---------------------------------------------------------------------------

export const signoffKeys = {
  preview: (repo: string, cell: Record<string, string>, rowHash: string) => ['signoff-preview', repo, cell, rowHash] as const,
  policy: () => ['signoff-policy'] as const,
}

/**
 * The preview re-fetches as the approver's choices change (the cell, the named row):
 * it reflects exactly what the POST would do with the form as it stands.
 */
export function useSignoffPreview(repo: string, cell: Record<string, string> | null, reviewedRowHash = ''): UseQueryResult<SignoffPreview, ApiError> {
  const key = cell ?? {}
  return useQuery({
    queryKey: signoffKeys.preview(repo, key, reviewedRowHash),
    queryFn: () => api<SignoffPreview>(`/signoffs/preview${qs({ repo, ...key, reviewed_row_hash: reviewedRowHash || undefined })}`),
    enabled: repo.length > 0 && cell !== null && Boolean(cell.capability_class),
    retry: false,
    staleTime: 5_000,
  })
}

export function useSignoffPolicy(enabled = true): UseQueryResult<SignoffPolicy, ApiError> {
  return useQuery({
    queryKey: signoffKeys.policy(),
    queryFn: () => api<SignoffPolicy>('/signoffs/policy'),
    enabled,
    retry: false,
    staleTime: 60_000,
  })
}

export function useCreateSignoffWithAttestation(): UseMutationResult<SignoffWithPolicy, ApiError, SignoffCreateWithAttestation> {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body) => api<SignoffWithPolicy>('/signoffs', { method: 'POST', body }),
    onSuccess: (s) => {
      qc.invalidateQueries({ queryKey: ['signoffs', s.repo] })
      qc.invalidateQueries({ queryKey: ['signoff-preview', s.repo] })
      qc.invalidateQueries({ queryKey: ['capability-map', s.repo] })
    },
  })
}

// ---------------------------------------------------------------------------
// Display vocabulary
// ---------------------------------------------------------------------------

/** The refusal code family (`route_not_deliver:n_below_min` → `route_not_deliver`). */
export function refusalFamily(code: string): string {
  return code.split(':', 1)[0] ?? code
}

/** One line per clause — what the approver is waiting on. */
export const REFUSAL_DISPLAY: Record<string, string> = {
  false_q1: 'false-Q1 in cell — the evidence is untrusted; no policy can override this',
  scope_mismatch: 'the attestation scope does not cover this cell',
  thin_cell: 'thin cell — not enough evidence (n below the policy minimum)',
  controls_unmeasured: 'negative controls never run for this repo',
  controls_failed: 'negative-controls gate FAILED on this repo — an instrument defect',
  controls_escapes: 'a measurement control escaped the oracle (graded clean)',
  controls_thin: 'fewer than half the controls were constructible',
  oracle_weak: 'oracle too weak to license auto-delivery',
  route_not_deliver: 'the routing rule does not say deliver',
  attestation_missing: 'name the accepted row you read and affirm it — no policy can waive this',
}

/** A refusal's threshold / observed values, rendered as the approver reads them. */
export function fmtBound(v: unknown): string {
  if (v === null || v === undefined || v === '') return '—'
  if (typeof v === 'number') return Number.isInteger(v) ? String(v) : v.toFixed(2)
  if (typeof v === 'boolean') return v ? 'yes' : 'no'
  return String(v)
}

/** `POST /signoffs` 409 detail (`crb.server.routes.signoffs`). */
export interface SignoffRefusedDetail {
  code?: string
  threshold?: unknown
  observed_value?: unknown
  refusals?: SignoffRefusal[]
  thresholds?: Record<string, unknown>
  observed?: Record<string, unknown>
  false_q1?: number
  rows?: string[]
}

export function isSignoffRefused(e: unknown): e is ApiError & { detail: SignoffRefusedDetail } {
  return Boolean(e) && typeof e === 'object' && (e as ApiError).status === 409 && ((e as ApiError).code === 'signoff_refused' || (e as ApiError).code === 'false_q1_refused')
}
