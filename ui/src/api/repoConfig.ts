/**
 * Repository configuration editing — the client side of `PUT /repos/{name}` (a
 * PARTIAL update: only the fields sent change) and the config audit trail
 * `GET /repos/{name}/events` (the repo's system trace — `repo.created`, then one
 * `repo.updated` per save carrying the REDACTED field diff — newest first).
 *
 * Kept apart from the shared `hooks.ts` on purpose: this is the repo-config
 * workstream's own wire surface. Query keys nest under `keys.repo(name)` so the
 * existing invalidations (create, probe) reach the trail as well.
 */

import { useMutation, useQuery, useQueryClient, type UseMutationResult, type UseQueryResult } from '@tanstack/react-query'
import { api, ApiError, qs } from './client'
import { keys } from './hooks'
import type { BeltScope, Language, MiningConfig, Page, PageParams, RepoDetail, Runner, StepEvent } from './types'

/**
 * `PUT /repos/{name}` body (API.md): the `POST /repos` fields minus `name`, every one
 * optional. The server merges what is sent over the stored config and re-validates the
 * whole `RepoConfig`, so a field that is not sent is a field that does not change.
 */
export interface RepoUpdateRequest {
  clone_path?: string
  url?: string
  language?: Language
  runner?: Runner
  src_prefix?: string
  test_prefix?: string
  ext?: string
  test_mode?: 'prefix' | 'suffix'
  test_suffix?: string
  belt_scope?: BeltScope
  probe?: string
  layer?: string
  runner_opts?: Record<string, unknown>
  sandbox_image?: string
  mining?: Partial<MiningConfig>
}

export const repoConfigKeys = {
  events: (name: string, p?: PageParams) => ['repos', name, 'events', p ?? {}] as const,
}

const enc = encodeURIComponent

/** `PUT /repos/{name}`; the response is the fresh detail and replaces the cached one. */
export function useUpdateRepo(name: string): UseMutationResult<RepoDetail, ApiError, RepoUpdateRequest> {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body) => api<RepoDetail>(`/repos/${enc(name)}`, { method: 'PUT', body }),
    onSuccess: (repo) => {
      qc.setQueryData(keys.repo(name), repo)
      void qc.invalidateQueries({ queryKey: keys.repos })
      void qc.invalidateQueries({ queryKey: repoConfigKeys.events(name) })
    },
  })
}

/** `GET /repos/{name}/events` — the config audit trail, newest first. */
export function useRepoEvents(name: string, p: PageParams = {}): UseQueryResult<Page<StepEvent>, ApiError> {
  return useQuery({
    queryKey: repoConfigKeys.events(name, p),
    queryFn: () => api<Page<StepEvent>>(`/repos/${enc(name)}/events${qs({ limit: p.limit, offset: p.offset })}`),
    enabled: name.length > 0,
    retry: false,
  })
}
