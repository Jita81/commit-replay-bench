/**
 * The Claude Code login token — `/settings/secrets` (docs/API.md, "Admin").
 *
 * Lives beside the screen (not in `api/hooks.ts`) because the Settings screen is
 * the only consumer today; fold into `api/hooks.ts` / `api/types.ts` when a second
 * screen needs it. The contract: the API never returns a token value — every
 * response is a status (presence, at most the last four characters, who/when) or
 * the outcome of the verify probe.
 */

import { useMutation, useQuery, useQueryClient, type UseMutationResult, type UseQueryResult } from '@tanstack/react-query'
import { api, ApiError } from '../../api/client'

export const CLAUDE_CODE_TOKEN_NAME = 'claude_code_oauth_token'
export const CLAUDE_CODE_TOKEN_PATH = '/settings/secrets/claude-code-token'
/** The verify probe may take up to 60 s on the server; give the request room. */
export const VERIFY_TIMEOUT_MS = 75_000

export interface SecretStatus {
  name: string
  present: boolean
  /** At most the last four characters of the value; `''` when absent. */
  fingerprint: string
  set_at: string
  set_by: string
}

export interface SecretsStatusList {
  items: SecretStatus[]
  /** Where the files live on the API host — admins only, `''` otherwise. */
  secrets_dir: string
}

export type LoginCheckStatus = 'ok' | 'invalid' | 'cli_missing' | 'timeout' | 'error'

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

export const secretsKey = ['settings', 'secrets'] as const

export function useSecrets(enabled = true): UseQueryResult<SecretsStatusList, ApiError> {
  return useQuery({ queryKey: secretsKey, queryFn: () => api<SecretsStatusList>('/settings/secrets'), enabled, retry: false })
}

export function claudeCodeStatus(list: SecretsStatusList | undefined): SecretStatus | undefined {
  return list?.items.find((s) => s.name === CLAUDE_CODE_TOKEN_NAME)
}

export function useSaveClaudeCodeToken(): UseMutationResult<SecretStatus, ApiError, string> {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (token) => api<SecretStatus>(CLAUDE_CODE_TOKEN_PATH, { method: 'PUT', body: { token } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: secretsKey }),
  })
}

export function useRemoveClaudeCodeToken(): UseMutationResult<SecretStatus, ApiError, void> {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => api<SecretStatus>(CLAUDE_CODE_TOKEN_PATH, { method: 'DELETE' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: secretsKey }),
  })
}

export function useVerifyClaudeCodeToken(): UseMutationResult<LoginCheck, ApiError, void> {
  return useMutation({
    mutationFn: () => api<LoginCheck>(`${CLAUDE_CODE_TOKEN_PATH}/verify`, { method: 'POST', timeoutMs: VERIFY_TIMEOUT_MS }),
  })
}
