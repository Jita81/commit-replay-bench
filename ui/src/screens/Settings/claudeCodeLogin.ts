/**
 * The Claude Code login token — `/settings/secrets` (docs/API.md, "Admin").
 *
 * Lives beside the screen (not in `api/hooks.ts`) because the Settings screen is
 * the only consumer today; fold into `api/hooks.ts` / `api/types.ts` when a second
 * screen needs it. The contract: the API never returns a token value — every
 * response is a status (presence, at most the last four characters, who/when) or
 * the outcome of the verify probe.
 *
 * Navigation
 * ----------
 * What it is:   The hooks and types for the operator-supplied Claude Code token:
 *               `useSecrets` (statuses), `useSaveClaudeCodeToken` (PUT), `useRemoveClaudeCodeToken`
 *               (DELETE), `useVerifyClaudeCodeToken` (one no-tool Haiku turn through the
 *               builder's own environment).
 * What it does: Mirrors a contract in which the API never returns a token value — every
 *               response is a `SecretStatus` (presence, at most the last four characters, who
 *               and when) or a `LoginCheck`. The verify call gets a 75 s timeout because the
 *               server-side probe may take up to 60 s.
 * How:          One query keyed `['settings', 'secrets']`; the write hooks invalidate it.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   src/crb/server/routes/admin.py (the three routes), src/crb/server/secrets.py
 *               (`SecretStatus`, the owner-only file and its shape checks),
 *               ui/src/screens/Settings/ClaudeCodeLoginCard.tsx (the only consumer),
 *               ui/src/api/client.ts (`api`, per-call `timeoutMs`)
 * Tested by:    ui/src/screens/Settings/ClaudeCodeLoginCard.test.tsx,
 *               ui/e2e/walkthrough/07-settings-and-a11y.spec.ts
 *               (round-trips a shape-valid fake token without the value ever appearing in
 *               the page), tests/test_server_routes_admin_secrets.py (no response carries
 *               a value)
 * Touch when:   a second operator secret is added to `/settings/secrets` (docs/API.md
 *               "Admin") — generalise the path constant and the status lookup; never for a
 *               new repository.
 */

import { useMutation, useQuery, useQueryClient, type UseMutationResult, type UseQueryResult } from '@tanstack/react-query'
import { api, ApiError } from '../../api/client'

/** The secret's name in `/settings/secrets` items. */
export const CLAUDE_CODE_TOKEN_NAME = 'claude_code_oauth_token'
/** The PUT / DELETE / verify path. */
export const CLAUDE_CODE_TOKEN_PATH = '/settings/secrets/claude-code-token'
/** The verify probe may take up to 60 s on the server; give the request room. */
export const VERIFY_TIMEOUT_MS = 75_000

/** `SecretStatus` (docs/API.md "Admin") — presence and provenance, never the value. */
export interface SecretStatus {
  name: string
  present: boolean
  /** At most the last four characters of the value; `''` when absent. */
  fingerprint: string
  set_at: string
  set_by: string
}

/** `GET /settings/secrets`. */
export interface SecretsStatusList {
  items: SecretStatus[]
  /** Where the files live on the API host — admins only, `''` otherwise. */
  secrets_dir: string
}

/** The verify probe's outcomes. */
export type LoginCheckStatus = 'ok' | 'invalid' | 'cli_missing' | 'timeout' | 'error'

/** `LoginCheck` (docs/API.md "Admin") — the probe's result; `detail` is redacted and capped server-side. */
export interface LoginCheck {
  status: LoginCheckStatus
  detail: string
  source: string
  fingerprint: string
  model: string
  cli_version: string
  duration_s: number
  cost_usd: number | null
}

/** The one query key the write hooks invalidate. */
export const secretsKey = ['settings', 'secrets'] as const

/** `GET /settings/secrets` — every role may read statuses; `secrets_dir` is `''` unless admin. */
export function useSecrets(enabled = true): UseQueryResult<SecretsStatusList, ApiError> {
  return useQuery({ queryKey: secretsKey, queryFn: () => api<SecretsStatusList>('/settings/secrets'), enabled, retry: false })
}

/** The Claude Code entry of the list, if any. */
export function claudeCodeStatus(list: SecretsStatusList | undefined): SecretStatus | undefined {
  return list?.items.find((s) => s.name === CLAUDE_CODE_TOKEN_NAME)
}

/** `PUT /settings/secrets/claude-code-token` with `{token}`; the value leaves this hook and is never cached. */
export function useSaveClaudeCodeToken(): UseMutationResult<SecretStatus, ApiError, string> {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (token) => api<SecretStatus>(CLAUDE_CODE_TOKEN_PATH, { method: 'PUT', body: { token } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: secretsKey }),
  })
}

/** `DELETE …/claude-code-token`; idempotent on the server. */
export function useRemoveClaudeCodeToken(): UseMutationResult<SecretStatus, ApiError, void> {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => api<SecretStatus>(CLAUDE_CODE_TOKEN_PATH, { method: 'DELETE' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: secretsKey }),
  })
}

/** `POST …/claude-code-token/verify` — one no-tool Haiku turn; rate-limited to once per 10 s (429 + Retry-After). */
export function useVerifyClaudeCodeToken(): UseMutationResult<LoginCheck, ApiError, void> {
  return useMutation({
    mutationFn: () => api<LoginCheck>(`${CLAUDE_CODE_TOKEN_PATH}/verify`, { method: 'POST', timeoutMs: VERIFY_TIMEOUT_MS }),
  })
}
