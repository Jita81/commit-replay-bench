/**
 * The repo-config form model: how a stored `RepoConfig` becomes editable state,
 * which of that state is INVALID (with the server's own words — `RepoConfig.__post_init__`
 * and the pydantic field limits in `crb.server.schemas._RepoConfigFields`), and which
 * fields actually CHANGED (the only ones a save sends: `PUT /repos/{name}` is partial,
 * and the audit event lists exactly what was sent).
 *
 * Pure functions, no React — the create dialog and the Configuration tab share them.
 *
 * Navigation
 * ----------
 * What it is:   Pure functions behind the Configuration tab and the Add-repo dialog:
 *               `formFromRepo`, `requestOf`, `changedFields`, `validateForm`, and the belt /
 *               mining vocabularies with their help text.
 * What it does: Turns `GET /repos/{name}` into form state, validates it with the server's own
 *               messages (`RepoConfig.__post_init__`, the pydantic field limits) so the form
 *               refuses what the API would 422, and computes the CHANGED fields only — compared
 *               in wire vocabulary, so a re-ordered `runner_opts` or a trimmed string is not a
 *               change. `PUT /repos/{name}` is partial and the audit event lists exactly what
 *               was sent, so this diff is what the trail records.
 * How:          Stored → form (belt scope split into policy + list, mining ints to text) →
 *               form → wire (`requestOf`) → `changedFields` diffs `requestOf(form)` against
 *               `requestOf(formFromRepo(repo))` with order-insensitive JSON equality.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   src/crb/core/spec.py (`RepoConfig` and its validation messages),
 *               src/crb/server/schemas.py (`_RepoConfigFields` limits mirrored in
 *               `FIELD_LIMITS`), ui/src/api/repoConfig.ts (`RepoUpdateRequest`),
 *               ui/src/screens/Repos/runnerOpts.ts (`runnersFor` — which runners a language
 *               allows), ui/src/screens/Repos/RepoConfigTab.tsx and
 *               ui/src/screens/Repos/RepoNewDialog.tsx (the two consumers)
 * Tested by:    ui/src/screens/Repos/repoConfigModel.test.ts, ui/src/screens/Repos/RepoConfigTab.test.tsx
 * Touch when:   `RepoConfig` gains a field (src/crb/core/spec.py) — add it to `RepoConfigForm`,
 *               `formFromRepo`, `requestOf` and (if bounded) `FIELD_LIMITS`, with the server's
 *               message in `validateForm`; a new belt policy or mining cap gets its help text
 *               here. Never for a new repository (its config is edited, not coded).
 */

import type { RepoUpdateRequest } from '../../api/repoConfig'
import type { BeltScope, Language, MiningConfig, RepoDetail, Runner } from '../../api/types'
import { LANGUAGES, RUNNERS } from '../../api/types'
import { runnersFor } from './runnerOpts'

/** The three named scopes plus `LIST` (an explicit runner-scope list) — the form's view of `BeltScope`. */
export type BeltPolicy = 'TARGET_ONLY' | 'AFFECTED_DIRS' | 'BARE' | 'LIST'

/** What each belt policy makes belt 3 (no new failures) run; wider = a green means more. */
export const BELT_HELP: Record<BeltPolicy, string> = {
  TARGET_ONLY: 'Regression belt runs only the target tests (weakest; while calibrating a large suite).',
  AFFECTED_DIRS: 'Regression belt runs every test in the target tests’ directories.',
  BARE: 'Regression belt runs the runner’s default discovery (the whole suite).',
  LIST: 'Regression belt runs exactly these runner scopes (paths or patterns the runner accepts).',
}

/** The `MiningConfig` fields, in form order. */
export const MINING_KEYS = ['log_n', 'max_candidates', 'target_valid', 'hard_target'] as const
export type MiningKey = (typeof MINING_KEYS)[number]

/** Label, hint and the miner's default per cap. */
export const MINING_HELP: Record<MiningKey, { label: string; hint: string; placeholder: string }> = {
  log_n: { label: 'History depth (commits)', hint: 'How many commits back a mine run walks. Empty = 3000.', placeholder: '3000' },
  max_candidates: { label: 'Max candidates examined', hint: 'Stop after this many candidate commits, even if the target is not met. Empty = 1000.', placeholder: '1000' },
  target_valid: { label: 'Standard-pool target', hint: 'Replayable tasks to keep in the standard pool. Empty = 25.', placeholder: '25' },
  hard_target: { label: 'Hard-pool target', hint: 'Replayable tasks to keep in the hard pool. Empty = 25.', placeholder: '25' },
}

/** pydantic `max_length` per field (`crb.server.schemas._RepoConfigFields`). */
export const FIELD_LIMITS = {
  clone_path: 4096,
  url: 2048,
  src_prefix: 512,
  test_prefix: 512,
  ext: 32,
  test_suffix: 128,
  probe: 1024,
  layer: 64,
  sandbox_image: 512,
} as const

/** Editable state: strings for every field (an empty mining cap = unset), belt scope as policy + list. */
export interface RepoConfigForm {
  language: Language
  runner: Runner
  clone_path: string
  url: string
  src_prefix: string
  test_prefix: string
  ext: string
  test_mode: 'prefix' | 'suffix'
  test_suffix: string
  beltPolicy: BeltPolicy
  beltList: string[]
  probe: string
  layer: string
  sandbox_image: string
  /** Text per key; '' = unset (the key is omitted from `mining`). */
  mining: Record<MiningKey, string>
  runner_opts: Record<string, unknown>
}

/** One message per field (or `mining.<key>` / the runner-opts JSON), in the server's words. */
export type FormErrors = Partial<Record<keyof RepoConfigForm | `mining.${MiningKey}` | 'runner_opts_json', string>>

// ---------------------------------------------------------------------------
// Stored → form
// ---------------------------------------------------------------------------

/** Comma- or newline-separated scopes → trimmed, non-empty list. */
export function parseScopeList(text: string): string[] {
  return text
    .split(/[,\n]/)
    .map((s) => s.trim())
    .filter(Boolean)
}

/** A stored `belt_scope` → policy + list (an array is `LIST`). */
function beltPolicyOf(scope: BeltScope): { policy: BeltPolicy; list: string[] } {
  if (Array.isArray(scope)) return { policy: 'LIST', list: scope.map(String) }
  return { policy: scope, list: [] }
}

/** Stored mining ints → the text the form edits (`''` = unset). */
function miningText(mining: Partial<MiningConfig> | undefined): Record<MiningKey, string> {
  const out = {} as Record<MiningKey, string>
  for (const k of MINING_KEYS) {
    const v = mining?.[k]
    out[k] = v === undefined || v === null ? '' : String(v)
  }
  return out
}

/** Editable state from `GET /repos/{name}` (the stored config plus the row's clone path). */
export function formFromRepo(repo: RepoDetail): RepoConfigForm {
  const c = repo.config
  const belt = beltPolicyOf(c.belt_scope)
  const language = (LANGUAGES as readonly string[]).includes(c.language) ? c.language : 'python'
  const runner = (RUNNERS as readonly string[]).includes(c.runner) ? (c.runner as Runner) : runnersFor(language)[0]!
  return {
    language,
    runner,
    clone_path: repo.clone_path ?? '',
    url: c.url ?? '',
    src_prefix: c.src_prefix ?? '',
    test_prefix: c.test_prefix ?? '',
    ext: c.ext ?? '',
    test_mode: c.test_mode === 'suffix' ? 'suffix' : 'prefix',
    test_suffix: c.test_suffix ?? '',
    beltPolicy: belt.policy,
    beltList: belt.list,
    probe: c.probe ?? '',
    layer: c.layer ?? '',
    sandbox_image: c.sandbox_image ?? '',
    mining: miningText(c.mining as Partial<MiningConfig> | undefined),
    runner_opts: { ...(c.runner_opts ?? {}) },
  }
}

// ---------------------------------------------------------------------------
// Form → wire
// ---------------------------------------------------------------------------

export function beltScopeOf(form: Pick<RepoConfigForm, 'beltPolicy' | 'beltList'>): BeltScope {
  return form.beltPolicy === 'LIST' ? form.beltList.map((s) => s.trim()).filter(Boolean) : form.beltPolicy
}

/** `mining` as the server stores it: only the keys that are set, as integers. */
export function miningOf(form: Pick<RepoConfigForm, 'mining'>): Partial<MiningConfig> {
  const out: Partial<MiningConfig> = {}
  for (const k of MINING_KEYS) {
    const t = form.mining[k].trim()
    if (t !== '' && /^\d+$/.test(t)) out[k] = Number(t)
  }
  return out
}

/** The whole form in `PUT /repos/{name}` vocabulary (before the changed-only filter). */
export function requestOf(form: RepoConfigForm): Required<RepoUpdateRequest> {
  return {
    clone_path: form.clone_path.trim(),
    url: form.url.trim(),
    language: form.language,
    runner: form.runner,
    src_prefix: form.src_prefix,
    test_prefix: form.test_prefix,
    ext: form.ext.trim(),
    test_mode: form.test_mode,
    test_suffix: form.test_suffix.trim(),
    belt_scope: beltScopeOf(form),
    probe: form.probe.trim(),
    layer: form.layer.trim(),
    sandbox_image: form.sandbox_image.trim(),
    runner_opts: form.runner_opts,
    mining: miningOf(form),
  }
}

/** Order-insensitive deep equality for the JSON values a config carries. */
export function sameJson(a: unknown, b: unknown): boolean {
  return canonical(a) === canonical(b)
}

/** Stable JSON with sorted object keys — the equality `sameJson` compares. */
function canonical(v: unknown): string {
  if (v === null || typeof v !== 'object') return JSON.stringify(v)
  if (Array.isArray(v)) return `[${v.map(canonical).join(',')}]`
  const o = v as Record<string, unknown>
  return `{${Object.keys(o)
    .sort()
    .map((k) => `${JSON.stringify(k)}:${canonical(o[k])}`)
    .join(',')}}`
}

/**
 * Only the fields whose value differs from what the server holds — compared in wire
 * vocabulary, so a re-ordered runner_opts object or a trimmed string is not a change.
 * `test_suffix` is compared as stored; switching `test_mode` alone is a change on its own.
 */
export function changedFields(form: RepoConfigForm, repo: RepoDetail): RepoUpdateRequest {
  const now = requestOf(form)
  const was = requestOf(formFromRepo(repo))
  const out: RepoUpdateRequest = {}
  for (const key of Object.keys(now) as Array<keyof RepoUpdateRequest>) {
    if (!sameJson(now[key], was[key])) (out as Record<string, unknown>)[key] = now[key]
  }
  return out
}

// ---------------------------------------------------------------------------
// Validation (the server's messages, so the form refuses what the API would 422)
// ---------------------------------------------------------------------------

/** The pydantic `max_length` message, verbatim, for a bounded field. */
function tooLong(field: keyof typeof FIELD_LIMITS, value: string): string | undefined {
  const max = FIELD_LIMITS[field]
  return value.length > max ? `String should have at most ${max} characters` : undefined
}

/** Every check the server would make, with its message — so the Save button refuses what the API would 422. */
export function validateForm(form: RepoConfigForm): FormErrors {
  const errors: FormErrors = {}
  if (!(LANGUAGES as readonly string[]).includes(form.language)) errors.language = `unknown language '${form.language}'`
  const allowed = runnersFor(form.language)
  if (!(RUNNERS as readonly string[]).includes(form.runner)) {
    errors.runner = `unknown runner '${form.runner}'; expected one of (${RUNNERS.join(', ')})`
  } else if (!allowed.includes(form.runner)) {
    errors.runner = `runner '${form.runner}' does not run ${form.language}; expected one of (${allowed.join(', ')})`
  }
  if (form.test_mode !== 'prefix' && form.test_mode !== 'suffix') errors.test_mode = "test_mode must be 'prefix' or 'suffix'"
  if (form.test_mode === 'suffix' && !form.test_suffix.trim()) errors.test_suffix = "test_mode='suffix' requires test_suffix"
  if (form.beltPolicy === 'LIST' && beltScopeOf(form).length === 0) {
    errors.beltList = 'belt_scope must be TARGET_ONLY | AFFECTED_DIRS | BARE | [scopes] — list at least one scope'
  }
  for (const field of Object.keys(FIELD_LIMITS) as Array<keyof typeof FIELD_LIMITS>) {
    const msg = tooLong(field, form[field])
    if (msg) errors[field] = msg
  }
  for (const k of MINING_KEYS) {
    const t = form.mining[k].trim()
    if (t !== '' && !/^\d+$/.test(t)) errors[`mining.${k}`] = 'Input should be a valid integer'
  }
  return errors
}

/** Any error at all. */
export function hasErrors(errors: FormErrors): boolean {
  return Object.keys(errors).length > 0
}
