/**
 * An organisation's class sets — the index, one version, one class's page, the labelling queue
 * and the acts (propose, label, sign, revoke).
 *
 * Navigation
 * ----------
 * What it is:   `useClassSets`, `useClassSetVersion`, `useClassPage`, `useLabelQueue` and
 *               `useClassSetAct` over `/classes` (docs/API.md#classes), with the query keys they
 *               share.
 * What it does: Fetches each read; posts an act and refreshes every `/classes` read on success, so
 *               a signature or a label shows everywhere at once. A refusal comes back as the API's
 *               error (409 `class_set_refused` with `detail.code`) for the screen to say in words.
 * How:          TanStack Query `useQuery` / `useMutation` over `api<T>` (CSRF on every write).
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0026-the-context-standard.md (item 9)
 * Works with:   ui/src/api/client.ts (`api`), ui/src/api/types.ts (`ClassSetIndex`,
 *               `ClassSetVersionDetail`, `ClassPage`, `ClassLabelQueue`),
 *               ui/src/screens/Classes/ClassesPage.tsx (the screen that uses them)
 * Tested by:    ui/src/screens/Classes/ClassesPage.test.tsx
 * Touch when:   never for a new repository; a route of `/classes` changes (docs/API.md first).
 */
import { useMutation, useQuery, useQueryClient, type UseMutationResult, type UseQueryResult } from '@tanstack/react-query'
import { api, type ApiError } from '../../api/client'
import type { ClassLabelQueue, ClassPage, ClassSetIndex, ClassSetProposal, ClassSetVersionDetail, ClassSetVersionSummary } from '../../api/types'

const enc = encodeURIComponent

export const classesKey = ['classes'] as const

/** `GET /classes` — every organisation's versions. */
export function useClassSets(): UseQueryResult<ClassSetIndex, ApiError> {
  return useQuery({ queryKey: classesKey, queryFn: () => api<ClassSetIndex>('/classes'), retry: false })
}

/** `GET /classes/{org}/v/{n}` — one version with its report and split. */
export function useClassSetVersion(org: string, n: number): UseQueryResult<ClassSetVersionDetail, ApiError> {
  return useQuery({
    queryKey: ['classes', org, n],
    queryFn: () => api<ClassSetVersionDetail>(`/classes/${enc(org)}/v/${n}`),
    enabled: Boolean(org && n),
    retry: false,
  })
}

/** `GET /classes/{org}/v/{n}/classes/{slug}` — the page for one class. */
export function useClassPage(org: string, n: number, slug: string): UseQueryResult<ClassPage, ApiError> {
  return useQuery({
    queryKey: ['classes', org, n, 'class', slug],
    queryFn: () => api<ClassPage>(`/classes/${enc(org)}/v/${n}/classes/${enc(slug)}`),
    enabled: Boolean(org && n && slug),
    retry: false,
  })
}

/** `GET /classes/{org}/v/{n}/label-queue` — derivation commits for a person to label. */
export function useLabelQueue(org: string, n: number, enabled: boolean): UseQueryResult<ClassLabelQueue, ApiError> {
  return useQuery({
    queryKey: ['classes', org, n, 'queue'],
    queryFn: () => api<ClassLabelQueue>(`/classes/${enc(org)}/v/${n}/label-queue`),
    enabled: Boolean(org && n && enabled),
    retry: false,
  })
}

export type ClassSetAct =
  | { act: 'propose'; org: string; body: ClassSetProposal }
  | { act: 'sign'; org: string; n: number; digest: string }
  | { act: 'revoke'; org: string; n: number; reason: string }
  | { act: 'label'; org: string; n: number; repo: string; taskId: string; klass: string }

/** Post one act; every `/classes` read refreshes on success. */
export function useClassSetAct(): UseMutationResult<ClassSetVersionSummary | Record<string, unknown>, ApiError, ClassSetAct> {
  const qc = useQueryClient()
  return useMutation<ClassSetVersionSummary | Record<string, unknown>, ApiError, ClassSetAct>({
    mutationFn: (a): Promise<ClassSetVersionSummary | Record<string, unknown>> => {
      if (a.act === 'propose') return api<ClassSetVersionSummary>(`/classes/${enc(a.org)}/versions`, { method: 'POST', body: a.body })
      if (a.act === 'sign') return api<ClassSetVersionSummary>(`/classes/${enc(a.org)}/v/${a.n}/sign`, { method: 'POST', body: { digest: a.digest } })
      if (a.act === 'revoke') return api<ClassSetVersionSummary>(`/classes/${enc(a.org)}/v/${a.n}/revoke`, { method: 'POST', body: { reason: a.reason } })
      return api<Record<string, unknown>>(`/classes/${enc(a.org)}/v/${a.n}/labels`, { method: 'POST', body: { repo: a.repo, task_id: a.taskId, class: a.klass } })
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: classesKey })
    },
  })
}
