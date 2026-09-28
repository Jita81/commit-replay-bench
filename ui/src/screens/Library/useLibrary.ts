/**
 * The context library's queries and acts — one repository's index, one work type's page, and the
 * five acts (propose, sponsor, sign, revoke, retire).
 *
 * Navigation
 * ----------
 * What it is:   `useLibrary`, `useWorkTypePage` and `useLibraryAct` over `/library`
 *               (docs/API.md#library), with the query keys they share, so the page and the
 *               Decisions inbox read one cache.
 * What it does: Fetches the index and a work type's page; posts an act and refreshes both reads
 *               and the Decisions inbox on success, so a signature shows everywhere at once. A
 *               refusal comes back as the API's error (409 `library_refused` with `detail.code`)
 *               for the screen to show in words.
 * How:          TanStack Query `useQuery` / `useMutation` over `api<T>` (CSRF on every write).
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0026-the-context-standard.md (item 10)
 * Works with:   ui/src/api/client.ts (`api`), ui/src/api/types.ts (`LibraryIndex`, `WorkTypePage`,
 *               `LibraryEntry`), ui/src/screens/Library/LibraryPage.tsx (the screen that uses
 *               them),
 *               ui/src/screens/Decisions/useDecisionCount.ts (reads `libraryKey`)
 * Tested by:    ui/src/screens/Library/LibraryPage.test.tsx
 * Touch when:   never for a new repository; a route of `/library` changes (docs/API.md first).
 */
import { useMutation, useQuery, useQueryClient, type UseMutationResult, type UseQueryResult } from '@tanstack/react-query'
import { api, type ApiError } from '../../api/client'
import type { LibraryEntry, LibraryIndex, LibraryMineRun, LibraryProposeRequest, WorkTypePage } from '../../api/types'

const enc = encodeURIComponent

export const libraryKey = (repo: string) => ['library', repo] as const
export const workTypeKey = (repo: string, slug: string) => ['library', repo, 'work-type', slug] as const

/** `GET /library/{repo}` — the nomenclature index and the work types. */
export function useLibrary(repo: string): UseQueryResult<LibraryIndex, ApiError> {
  return useQuery({ queryKey: libraryKey(repo), queryFn: () => api<LibraryIndex>(`/library/${enc(repo)}`), enabled: Boolean(repo), retry: false })
}

/** `GET /library/{repo}/work-types/{slug}` — the page for one work type. */
export function useWorkTypePage(repo: string, slug: string): UseQueryResult<WorkTypePage, ApiError> {
  return useQuery({
    queryKey: workTypeKey(repo, slug),
    queryFn: () => api<WorkTypePage>(`/library/${enc(repo)}/work-types/${enc(slug)}`),
    enabled: Boolean(repo && slug),
    retry: false,
  })
}

export type LibraryAct =
  | { act: 'propose'; body: LibraryProposeRequest }
  | { act: 'sponsor' | 'sign'; entryId: string; version: string }
  | { act: 'revoke' | 'retire'; entryId: string; reason: string }

/** Post one act; the index, the open page and the inbox refresh on success. */
export function useLibraryAct(repo: string): UseMutationResult<LibraryEntry, ApiError, LibraryAct> {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (a) => {
      if (a.act === 'propose') return api<LibraryEntry>(`/library/${enc(repo)}/entries`, { method: 'POST', body: a.body })
      const [kind, slug] = a.entryId.split('/')
      const path = `/library/${enc(repo)}/entries/${enc(kind ?? '')}/${enc(slug ?? '')}/${a.act}`
      const body = 'version' in a ? { version: a.version } : { reason: a.reason }
      return api<LibraryEntry>(path, { method: 'POST', body })
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['library', repo] })
    },
  })
}

/** `POST /library/{repo}/mine` — run the miners over the repository's clone at one commit (empty
 * = its HEAD). Every proposal is appended unsigned, waiting for a person to sponsor it. */
export function useLibraryMine(repo: string): UseMutationResult<LibraryMineRun, ApiError, { commit: string }> {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ commit }) => api<LibraryMineRun>(`/library/${enc(repo)}/mine`, { method: 'POST', body: { commit: commit.trim() } }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['library', repo] })
    },
  })
}
