/**
 * React Query hooks — one per endpoint in docs/API.md.
 *
 * Doctrine:
 *   - every hook exposes `isError` + `error` and the screens render it
 *     (no swallowed `.catch`, no fabricated data);
 *   - `retry: false` by default so a missing endpoint shows an honest error,
 *     not a 3× delayed spinner;
 *   - polling only while a run is non-terminal, never in a background tab;
 *   - `useRunEvents` is the SSE hook (EventSource, `?after=` resume,
 *     reconnection, bounded buffer) — see `sse.ts`.
 *
 * Navigation
 * ----------
 * What it is:   The UI's data layer: one TanStack Query hook per endpoint in docs/API.md, the
 *               query-key table (`keys`) and the SSE hook `useRunEvents`.
 * What it does: Every read exposes `isError` + `error` and never retries by default (a missing
 *               endpoint shows an honest error, not a delayed spinner); runs poll only while
 *               non-terminal and never in a background tab; mutations invalidate the keys they
 *               change so screens refresh without ad-hoc refetches. `useMe` maps a 401 to
 *               `null` (not logged in); `normaliseEvidence` folds two server shapes into one.
 * How:          `keys` is the single source of every query key → each hook wraps
 *               `api<T>(path)` in `useQuery` / `useMutation` with the key, `enabled` guards on
 *               empty ids and the polling rule → `useRunEvents` owns a `RunEventStream` per
 *               run id and hands React its snapshot through `useSyncExternalStore`.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/api/client.ts (the fetch wrapper every hook calls), ui/src/api/types.ts
 *               (the response types), ui/src/api/sse.ts (the stream `useRunEvents` drives),
 *               ui/src/api/repoConfig.ts (the repo-config hooks nest under `keys.repo`),
 *               ui/src/screens/Capability/contract.ts and ui/src/screens/Runs/contract.ts (the
 *               newer readings not yet folded in here), ui/src/test/utils.tsx (`mockApi` — how
 *               tests answer these hooks)
 * Tested by:    ui/src/screens/Runs/RunDetailPage.test.tsx,
 *               ui/src/screens/Home/HomePage.test.tsx (`useActiveRun`),
 *               ui/src/screens/Connect/ConnectPage.test.tsx (`useQueuedRuns`),
 *               ui/src/screens/Capability/CapabilityPage.test.tsx,
 *               ui/src/screens/Routing/RoutingPage.test.tsx,
 *               ui/src/screens/Signoff/SignoffPage.test.tsx,
 *               ui/src/screens/Connect/GitHubConnectDialog.test.tsx (the GitHub App hooks)
 *               (every screen test exercises its hooks through `mockApi`)
 * Touch when:   an endpoint is added or its path / params change (docs/API.md) — add the type
 *               in ui/src/api/types.ts, the key in `keys` and the hook here, then the screen;
 *               never for a new repository.
 */

import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from 'react'
import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from '@tanstack/react-query'
import { api, ApiError, qs } from './client'
import { RunEventStream, type EventSourceFactory, type SseSnapshot } from './sse'
import type {
  Intake,
  GitHubAppInfo,
  GitHubConnectRequest,
  GitHubInstallation,
  GitHubPickerPage,
  CapabilityMap,
  CellField,
  ControlsReport,
  EvidencePack,
  EvidenceResponse,
  FactoryBacklog,
  FactoryCatalogue,
  FactoryTask,
  ForecastBuild,
  ForecastReadiness,
  GradeListParams,
  GradeRow,
  Health,
  LedgerVerify,
  LoginRequest,
  OracleReport,
  Page,
  PageParams,
  Principal,
  RepoCreateRequest,
  RepoDetail,
  RepoProfile,
  RepoSummary,
  Role,
  RoutesResponse,
  Run,
  RunCreateRequest,
  RunKind,
  RunListParams,
  RunTaskRow,
  Settings,
  Signoff,
  SignoffCreateRequest,
  StepEvent,
  TaskDetail,
  TaskSpec,
  User,
  UserCreateRequest,
  Version,
} from './types'
import { isRunTerminal } from './types'

// ---------------------------------------------------------------------------
// Query keys (one place, so invalidation never drifts)
// ---------------------------------------------------------------------------

/**
 * Every query key in one table so an invalidation in a mutation can never drift from the
 * read it is meant to refresh. Keys nest (`['runs', id, 'tasks']` under `['runs', id]`) so
 * invalidating a prefix reaches its children.
 */
export const keys = {
  health: ['health'] as const,
  version: ['version'] as const,
  me: ['auth', 'me'] as const,
  repos: ['repos'] as const,
  repo: (name: string) => ['repos', name] as const,
  repoProfile: (name: string) => ['repos', name, 'profile'] as const,
  repoTasks: (name: string, p?: PageParams) => ['repos', name, 'tasks', p ?? {}] as const,
  runs: (p?: RunListParams) => ['runs', p ?? {}] as const,
  run: (id: string) => ['runs', id] as const,
  runTasks: (id: string) => ['runs', id, 'tasks'] as const,
  runEventLog: (id: string, p?: PageParams) => ['runs', id, 'events', p ?? {}] as const,
  task: (repo: string, taskId: string) => ['tasks', repo, taskId] as const,
  grades: (p?: GradeListParams) => ['grades', p ?? {}] as const,
  grade: (rowId: string) => ['grades', rowId] as const,
  evidence: (hash: string) => ['evidence', hash] as const,
  capability: (repo: string, by: string) => ['capability', repo, by] as const,
  routes: (repo: string) => ['routes', repo] as const,
  forecastBuild: (repo: string, mix: string) => ['forecast', 'build', repo, mix] as const,
  forecastReadiness: (repo: string) => ['forecast', 'readiness', repo] as const,
  signoffs: (repo: string, includeRevoked = false) => ['signoffs', repo, includeRevoked ? 'all' : 'active'] as const,
  ledgerVerify: ['ledger', 'verify'] as const,
  oracle: (repo: string) => ['oracle', repo] as const,
  oracleControls: (repo: string) => ['oracle', repo, 'controls'] as const,
  factoryCatalogue: ['factory', 'catalogue'] as const,
  factoryBacklog: (repo: string) => ['factory', repo, 'backlog'] as const,
  factoryTasks: (repo: string) => ['factory', repo, 'tasks'] as const,
  factoryEvidence: (repo: string) => ['factory', repo, 'evidence'] as const,
  intake: (repo: string) => ['factory', repo, 'intake'] as const,
  users: ['users'] as const,
  settings: ['settings'] as const,
  githubApp: ['github', 'app'] as const,
  githubRepos: (installation: number, q: string, page: number) => ['github', 'repos', installation, q, page] as const,
}

const enc = encodeURIComponent

// ---------------------------------------------------------------------------
// Health / version
// ---------------------------------------------------------------------------

/** `GET /health` — the probes (db, sandbox, toolchains, builders, worker); 15 s stale. */
export function useHealth(): UseQueryResult<Health, ApiError> {
  return useQuery({ queryKey: keys.health, queryFn: () => api<Health>('/health'), retry: false, staleTime: 15_000 })
}

/** `GET /version` — crb, apparatus and policy versions; never refetched (they change only on deploy). */
export function useVersion(): UseQueryResult<Version, ApiError> {
  return useQuery({ queryKey: keys.version, queryFn: () => api<Version>('/version'), retry: false, staleTime: Infinity })
}

// ---------------------------------------------------------------------------
// Auth
// ---------------------------------------------------------------------------

/** `GET /auth/me`. A 401 resolves to `null` (not an error) — it means "not logged in". */
export function useMe(): UseQueryResult<Principal | null, ApiError> {
  return useQuery({
    queryKey: keys.me,
    queryFn: async () => {
      try {
        return await api<Principal>('/auth/me')
      } catch (err) {
        if (err instanceof ApiError && err.isUnauthenticated) return null
        throw err
      }
    },
    retry: false,
    staleTime: 60_000,
  })
}

/** `POST /auth/login` (local account); on success the principal is written straight into `keys.me`. */
export function useLogin(): UseMutationResult<Principal, ApiError, LoginRequest> {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body) => api<Principal>('/auth/login', { method: 'POST', body }),
    onSuccess: (me) => qc.setQueryData(keys.me, me),
  })
}

/** `POST /auth/logout`; clears the whole query cache so nothing from the old session can be shown. */
export function useLogout(): UseMutationResult<void, ApiError, void> {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => api<void>('/auth/logout', { method: 'POST' }),
    onSettled: () => {
      qc.setQueryData(keys.me, null)
      qc.clear()
    },
  })
}

// ---------------------------------------------------------------------------
// Repos
// ---------------------------------------------------------------------------

/** `GET /repos` — the list with probe status, task counts and last run. */
export function useRepos(): UseQueryResult<Page<RepoSummary>, ApiError> {
  return useQuery({ queryKey: keys.repos, queryFn: () => api<Page<RepoSummary>>('/repos'), retry: false })
}

/** The API's page-size ceiling (`PAGE_MAX` in `crb.server.schemas`). */
export const PAGE_MAX = 500

/**
 * EVERY repository, walking `/repos` page by page under the documented `limit`/`offset`
 * contract — for the picker, which must not omit a repo that fell outside the first page
 * (CodeRabbit on PR #6). The result keeps the `Page` shape with `total` = the count seen.
 */
export async function fetchAllRepos(): Promise<Page<RepoSummary>> {
  const items: RepoSummary[] = []
  let offset = 0
  let total = 0
  for (;;) {
    const page = await api<Page<RepoSummary>>(`/repos${qs({ limit: PAGE_MAX, offset })}`)
    items.push(...page.items)
    total = page.total
    offset += page.items.length
    if (page.items.length === 0 || offset >= page.total) break
  }
  return { items, total, limit: items.length, offset: 0 }
}

/** `useRepos` over every page — the picker's source. Shares the repos cache key family so a created repo invalidates it. */
export function useAllRepos(): UseQueryResult<Page<RepoSummary>, ApiError> {
  return useQuery({ queryKey: [...keys.repos, 'all'] as const, queryFn: fetchAllRepos, retry: false })
}

/** `GET /repos/{name}` — the list item plus its `config`. */
export function useRepo(name: string): UseQueryResult<RepoDetail, ApiError> {
  return useQuery({
    queryKey: keys.repo(name),
    queryFn: () => api<RepoDetail>(`/repos/${enc(name)}`),
    enabled: name.length > 0,
    retry: false,
  })
}

/** `POST /repos`; invalidates the list. */
export function useCreateRepo(): UseMutationResult<RepoDetail, ApiError, RepoCreateRequest> {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body) => api<RepoDetail>('/repos', { method: 'POST', body }),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.repos }),
  })
}

/** `POST /repos/{name}/probe` → a queued `probe` run; invalidates the repo, the list and every runs page. */
export function useProbeRepo(): UseMutationResult<Run, ApiError, string> {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (name) => api<Run>(`/repos/${enc(name)}/probe`, { method: 'POST' }),
    onSuccess: (_run, name) => {
      qc.invalidateQueries({ queryKey: keys.repo(name) })
      qc.invalidateQueries({ queryKey: keys.repos })
      qc.invalidateQueries({ queryKey: ['runs'] })
    },
  })
}

/** `GET /repos/{name}/profile` — the (class × size) change profile the coverage figures need. */
export function useRepoProfile(name: string): UseQueryResult<RepoProfile, ApiError> {
  return useQuery({
    queryKey: keys.repoProfile(name),
    queryFn: () => api<RepoProfile>(`/repos/${enc(name)}/profile`),
    enabled: name.length > 0,
    retry: false,
  })
}

/** `GET /repos/{name}/tasks` — one page of mined `TaskSpec`s. */
export function useRepoTasks(name: string, p: PageParams = {}): UseQueryResult<Page<TaskSpec>, ApiError> {
  return useQuery({
    queryKey: keys.repoTasks(name, p),
    queryFn: () => api<Page<TaskSpec>>(`/repos/${enc(name)}/tasks${qs({ limit: p.limit, offset: p.offset })}`),
    enabled: name.length > 0,
    retry: false,
  })
}

// ---------------------------------------------------------------------------
// Runs
// ---------------------------------------------------------------------------

/** Poll period for a non-terminal run; the list polls at twice this. */
export const RUN_POLL_MS = 2_500

/** `GET /runs` (filters + page); polls only while some listed run is non-terminal, never in a hidden tab. */
export function useRuns(p: RunListParams = {}): UseQueryResult<Page<Run>, ApiError> {
  return useQuery({
    queryKey: keys.runs(p),
    queryFn: () => api<Page<Run>>(`/runs${qs({ repo: p.repo, kind: p.kind, status: p.status, limit: p.limit, offset: p.offset })}`),
    retry: false,
    refetchInterval: (q) => (q.state.data?.items.some((r) => !isRunTerminal(r.status)) ? RUN_POLL_MS * 2 : false),
    refetchIntervalInBackground: false,
  })
}

/**
 * The run in flight for one repository and kind (`GET /runs?repo=&kind=` — the newest 20,
 * newest first; the first `queued`/`running` one), or `null` when none is. Polls at the
 * list's pace while one is active; disabled with no repository. Home's task 8 reads the
 * active factory run through this so "In progress" is never shown without a run behind it.
 */
export function useActiveRun(repo: string, kind: RunKind): UseQueryResult<Run | null, ApiError> {
  const p: RunListParams = { repo, kind, limit: 20 }
  return useQuery({
    queryKey: [...keys.runs(p), 'active'] as const,
    queryFn: async () => {
      const page = await api<Page<Run>>(`/runs${qs({ repo, kind, limit: 20 })}`)
      return page.items.find((r) => !isRunTerminal(r.status)) ?? null
    },
    enabled: repo.length > 0,
    retry: false,
    refetchInterval: (q) => (q.state.data ? RUN_POLL_MS * 2 : false),
    refetchIntervalInBackground: false,
  })
}

/**
 * `GET /runs?status=queued` (up to 200, newest first) — the queue, so a screen can say how
 * many runs sit ahead of the one it watches (the worker claims FIFO by `created`). Enabled
 * only while asked; polls at the list's pace while anything is queued.
 */
export function useQueuedRuns(enabled: boolean): UseQueryResult<Page<Run>, ApiError> {
  const p: RunListParams = { status: 'queued', limit: 200 }
  return useQuery({
    queryKey: keys.runs(p),
    queryFn: () => api<Page<Run>>(`/runs${qs({ status: 'queued', limit: 200 })}`),
    enabled,
    retry: false,
    refetchInterval: (q) => (q.state.data?.items.length ? RUN_POLL_MS * 2 : false),
    refetchIntervalInBackground: false,
  })
}

/** `GET /runs/{id}`; polls while the run is non-terminal (`poll: false` to read once). */
export function useRun(id: string, opts: { poll?: boolean } = {}): UseQueryResult<Run, ApiError> {
  const poll = opts.poll ?? true
  return useQuery({
    queryKey: keys.run(id),
    queryFn: () => api<Run>(`/runs/${enc(id)}`),
    enabled: id.length > 0,
    retry: false,
    refetchInterval: (q) => (poll && !isRunTerminal(q.state.data?.status) ? RUN_POLL_MS : false),
    refetchIntervalInBackground: false,
  })
}

/** `POST /runs`; seeds the new run's detail key so the redirect to /runs/{id} renders without a second round trip. */
export function useCreateRun(): UseMutationResult<Run, ApiError, RunCreateRequest> {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body) => api<Run>('/runs', { method: 'POST', body }),
    onSuccess: (run) => {
      qc.invalidateQueries({ queryKey: ['runs'] })
      qc.setQueryData(keys.run(run.id), run)
    },
  })
}

/** `POST /runs/{id}/cancel` — asks the API to set `cancel_requested`; the worker stops between tasks. */
export function useCancelRun(): UseMutationResult<Run, ApiError, string> {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id) => api<Run>(`/runs/${enc(id)}/cancel`, { method: 'POST' }),
    onSuccess: (_r, id) => qc.invalidateQueries({ queryKey: keys.run(id) }),
  })
}

/** `GET /runs/{id}/tasks` — every task of the run (one request, limit 500); polls only while asked. */
export function useRunTasks(id: string, opts: { poll?: boolean } = {}): UseQueryResult<Page<RunTaskRow>, ApiError> {
  return useQuery({
    queryKey: keys.runTasks(id),
    queryFn: () => api<Page<RunTaskRow>>(`/runs/${enc(id)}/tasks?limit=500`),
    enabled: id.length > 0,
    retry: false,
    refetchInterval: opts.poll ? RUN_POLL_MS * 2 : false,
    refetchIntervalInBackground: false,
  })
}

/** `GET /runs/{id}/events/log` — the stored StepEvents as a page (the non-live view). */
export function useRunEventLog(id: string, p: PageParams = {}): UseQueryResult<Page<StepEvent>, ApiError> {
  return useQuery({
    queryKey: keys.runEventLog(id, p),
    queryFn: () => api<Page<StepEvent>>(`/runs/${enc(id)}/events/log${qs({ limit: p.limit, offset: p.offset })}`),
    enabled: id.length > 0,
    retry: false,
  })
}

export interface UseRunEventsOptions {
  /** `false` keeps the stream closed (e.g. before the run id is known). */
  enabled?: boolean
  /** Ring-buffer size; default 5,000 (see `RunEventStream`). */
  maxEvents?: number
  /** Test seam: a fake EventSource. Read once at open; changing it does not reopen. */
  factory?: EventSourceFactory
}

/**
 * The snapshot served before a stream exists (and on the server) — one frozen object so
 * `useSyncExternalStore` sees a stable identity and does not re-render in a loop.
 */
const IDLE_SNAPSHOT: SseSnapshot = { status: 'idle', events: [], lastSeq: 0, reconnects: 0, dropped: 0, error: null }

/**
 * The live SSE log for one run. Opens `GET /runs/{id}/events`, resumes with
 * `?after=` on reconnect, appends StepEvents into a bounded buffer, and closes
 * on unmount or when the server sends `event: done`. Returns the stream's
 * snapshot; the screen renders `status`, `events`, `reconnects` and `dropped`
 * as they are — a dropped frame is counted, never hidden.
 */
export function useRunEvents(runId: string, options: UseRunEventsOptions = {}): SseSnapshot {
  const enabled = (options.enabled ?? true) && runId.length > 0
  // Options are read through refs so an inline `factory` arrow or a changed
  // buffer size never tears down a live stream; only the run id (or enabled)
  // does.
  const factoryRef = useRef(options.factory)
  factoryRef.current = options.factory
  const maxRef = useRef(options.maxEvents)
  maxRef.current = options.maxEvents
  const [stream, setStream] = useState<RunEventStream | null>(null)

  useEffect(() => {
    if (!enabled) {
      setStream(null)
      return
    }
    const s = new RunEventStream(runId, { factory: factoryRef.current, maxEvents: maxRef.current })
    setStream(s)
    s.open()
    return () => {
      s.close()
      setStream((cur) => (cur === s ? null : cur))
    }
  }, [runId, enabled])

  const subscribe = useCallback((cb: () => void) => (stream ? stream.subscribe(cb) : () => {}), [stream])
  const getSnapshot = useCallback(() => (stream ? stream.getSnapshot() : IDLE_SNAPSHOT), [stream])
  const getServerSnapshot = useCallback(() => IDLE_SNAPSHOT, [])
  return useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot)
}

// ---------------------------------------------------------------------------
// Tasks / grades / evidence
// ---------------------------------------------------------------------------

/** `GET /tasks/{repo}/{task_id}` — the spec plus every grade row for it. */
export function useTask(repo: string, taskId: string): UseQueryResult<TaskDetail, ApiError> {
  return useQuery({
    queryKey: keys.task(repo, taskId),
    queryFn: () => api<TaskDetail>(`/tasks/${enc(repo)}/${enc(taskId)}`),
    enabled: repo.length > 0 && taskId.length > 0,
    retry: false,
  })
}

/** `GET /grades` — ledger rows as stored, with the API's filters. */
export function useGrades(p: GradeListParams = {}): UseQueryResult<Page<GradeRow>, ApiError> {
  return useQuery({
    queryKey: keys.grades(p),
    queryFn: () =>
      api<Page<GradeRow>>(
        `/grades${qs({
          repo: p.repo,
          run_id: p.run_id,
          task_id: p.task_id,
          clean: p.clean,
          mode: p.mode,
          builder: p.builder,
          model: p.model,
          capability_class: p.capability_class,
          size: p.size,
          language: p.language,
          limit: p.limit,
          offset: p.offset,
        })}`,
      ),
    retry: false,
  })
}

/** `GET /grades/{row_id}` — one ledger row. */
export function useGrade(rowId: string): UseQueryResult<GradeRow, ApiError> {
  return useQuery({
    queryKey: keys.grade(rowId),
    queryFn: () => api<GradeRow>(`/grades/${enc(rowId)}`),
    enabled: rowId.length > 0,
    retry: false,
  })
}

/**
 * `GET /evidence/{hash}` → `{pack, verified}`. API.md says "the evidence pack
 * + verified: bool"; a server that inlines the pack body next to `verified`
 * is normalised here so the screens see one shape.
 */
export function normaliseEvidence(raw: unknown): EvidenceResponse {
  const r = raw as Record<string, unknown>
  if (r && typeof r === 'object' && 'pack' in r && r.pack && typeof r.pack === 'object') {
    return { pack: r.pack as EvidencePack, verified: Boolean(r.verified) }
  }
  const { verified, ...pack } = r
  return { pack: pack as unknown as EvidencePack, verified: Boolean(verified) }
}

/** `GET /evidence/{hash}`; a pack is immutable (content-addressed), so it is never refetched. */
export function useEvidence(hash: string): UseQueryResult<EvidenceResponse, ApiError> {
  return useQuery({
    queryKey: keys.evidence(hash),
    queryFn: async () => normaliseEvidence(await api<unknown>(`/evidence/${enc(hash)}`)),
    enabled: hash.length > 0,
    retry: false,
    staleTime: Infinity,
  })
}

// ---------------------------------------------------------------------------
// Capability / routing / forecast / sign-off
// ---------------------------------------------------------------------------

/** `GET /capability-map?repo=&by=` — the cells for one projection; 30 s stale. */
export function useCapabilityMap(repo: string, by: CellField[]): UseQueryResult<CapabilityMap, ApiError> {
  const byStr = by.join(',')
  return useQuery({
    queryKey: keys.capability(repo, byStr),
    queryFn: () => api<CapabilityMap>(`/capability-map${qs({ repo, by: byStr })}`),
    enabled: repo.length > 0,
    retry: false,
    staleTime: 30_000,
  })
}

/** `GET /routes?repo=` — one `RouteDecision` per cell under the published policy. */
export function useRoutes(repo: string): UseQueryResult<RoutesResponse, ApiError> {
  return useQuery({
    queryKey: keys.routes(repo),
    queryFn: () => api<RoutesResponse>(`/routes${qs({ repo })}`),
    enabled: repo.length > 0,
    retry: false,
  })
}

/** `GET /forecast/build?repo=&mix=` — enabled only once a mix is given. */
export function useForecastBuild(repo: string, mix: string): UseQueryResult<ForecastBuild, ApiError> {
  return useQuery({
    queryKey: keys.forecastBuild(repo, mix),
    queryFn: () => api<ForecastBuild>(`/forecast/build${qs({ repo, mix })}`),
    enabled: repo.length > 0 && mix.length > 0,
    retry: false,
  })
}

/** `GET /forecast/readiness?repo=` — ok + gaps punch-list. */
export function useForecastReadiness(repo: string): UseQueryResult<ForecastReadiness, ApiError> {
  return useQuery({
    queryKey: keys.forecastReadiness(repo),
    queryFn: () => api<ForecastReadiness>(`/forecast/readiness${qs({ repo })}`),
    enabled: repo.length > 0,
    retry: false,
  })
}

/** `GET /signoffs?repo=` — the attestations (active by default). */
export function useSignoffs(repo: string, opts: { includeRevoked?: boolean } = {}): UseQueryResult<Page<Signoff>, ApiError> {
  const includeRevoked = opts.includeRevoked === true
  return useQuery({
    queryKey: keys.signoffs(repo, includeRevoked),
    queryFn: () => api<Page<Signoff>>(`/signoffs${qs({ repo, include_revoked: includeRevoked ? 'true' : undefined })}`),
    enabled: repo.length > 0,
    retry: false,
  })
}

/** `POST /signoffs`; a 409 arrives as `ApiError` (false-Q1 or a policy refusal) and is rendered, never retried. Invalidates the repo's sign-offs and every capability projection (a sign-off lifts a tier). */
export function useCreateSignoff(): UseMutationResult<Signoff, ApiError, SignoffCreateRequest> {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body) => api<Signoff>('/signoffs', { method: 'POST', body }),
    onSuccess: (s) => {
      qc.invalidateQueries({ queryKey: ['signoffs', s.repo] })
      qc.invalidateQueries({ queryKey: ['capability', s.repo] })
    },
  })
}

/** `POST /signoffs/{id}/revoke` with the reason (recorded verbatim on the revocation row); invalidates the repo's sign-offs (both listings) and its capability projections (a revocation drops a tier). */
export function useRevokeSignoff(): UseMutationResult<Signoff, ApiError, { id: string; repo: string; note: string }> {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, note }) => api<Signoff>(`/signoffs/${enc(id)}/revoke`, { method: 'POST', body: { note } }),
    onSuccess: (_s, v) => {
      qc.invalidateQueries({ queryKey: ['signoffs', v.repo] })
      qc.invalidateQueries({ queryKey: ['capability', v.repo] })
    },
  })
}

// ---------------------------------------------------------------------------
// Ledger
// ---------------------------------------------------------------------------

/** `GET /ledger/verify` — walks the chain server-side; 30 s stale. */
export function useLedgerVerify(): UseQueryResult<LedgerVerify, ApiError> {
  return useQuery({
    queryKey: keys.ledgerVerify,
    queryFn: () => api<LedgerVerify>('/ledger/verify'),
    retry: false,
    staleTime: 30_000,
  })
}

// ---------------------------------------------------------------------------
// Oracle
// ---------------------------------------------------------------------------

/** `GET /oracle/{repo}` — per-task and per-cell mutation strength. */
export function useOracle(repo: string): UseQueryResult<OracleReport, ApiError> {
  return useQuery({
    queryKey: keys.oracle(repo),
    queryFn: () => api<OracleReport>(`/oracle/${enc(repo)}`),
    enabled: repo.length > 0,
    retry: false,
  })
}

/** `GET /oracle/{repo}/controls` — the latest negative-controls report (404 `not_measured` before one). */
export function useOracleControls(repo: string): UseQueryResult<ControlsReport, ApiError> {
  return useQuery({
    queryKey: keys.oracleControls(repo),
    queryFn: () => api<ControlsReport>(`/oracle/${enc(repo)}/controls`),
    enabled: repo.length > 0,
    retry: false,
  })
}

// ---------------------------------------------------------------------------
// Factory (P6)
// ---------------------------------------------------------------------------

/** `GET /factory/{repo}/backlog` (P6; 501 until it lands — the screen renders that honestly). */
/** `GET /factory/catalogue` — the classes, their slots, sizes, kinds and levels; static per release. */
export function useFactoryCatalogue(enabled = true): UseQueryResult<FactoryCatalogue, ApiError> {
  return useQuery({
    queryKey: keys.factoryCatalogue,
    queryFn: () => api<FactoryCatalogue>('/factory/catalogue'),
    enabled,
    staleTime: 60 * 60_000,
    retry: false,
  })
}

export function useFactoryBacklog(repo: string): UseQueryResult<FactoryBacklog, ApiError> {
  return useQuery({
    queryKey: keys.factoryBacklog(repo),
    queryFn: () => api<FactoryBacklog>(`/factory/${enc(repo)}/backlog`),
    enabled: repo.length > 0,
    retry: false,
  })
}

/** Poll period for the factory item chain while a factory run is working it (J-FAC-5). */
export const FACTORY_POLL_MS = 5_000

/** `GET /factory/{repo}/tasks` (P6); polls every 5 s while `poll` (a factory run is active), never in a hidden tab. */
export function useFactoryTasks(repo: string, opts: { poll?: boolean } = {}): UseQueryResult<FactoryTask[], ApiError> {
  return useQuery({
    queryKey: keys.factoryTasks(repo),
    // the server answers a bare list here (docs/API.md), not a Page
    queryFn: () => api<FactoryTask[]>(`/factory/${enc(repo)}/tasks`),
    enabled: repo.length > 0,
    retry: false,
    refetchInterval: opts.poll ? FACTORY_POLL_MS : false,
    refetchIntervalInBackground: false,
  })
}

/** `GET /factory/{repo}/evidence` (P6). */
/** `POST /factory/{repo}/tasks/{id}/signoff-gap` (approver) — a structural gap signed with an answer; invalidates the tasks. */
export function useSignGap(): UseMutationResult<unknown, ApiError, { repo: string; itemId: string; slot: string; answer: string }> {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ repo, itemId, slot, answer }) =>
      api<unknown>(`/factory/${encodeURIComponent(repo)}/tasks/${encodeURIComponent(itemId)}/signoff-gap`, { method: 'POST', body: { slot, answer } }),
    onSuccess: (_d, v) => {
      void qc.invalidateQueries({ queryKey: keys.factoryTasks(v.repo) })
      void qc.invalidateQueries({ queryKey: keys.factoryEvidence(v.repo) })
    },
  })
}

/** `POST /factory/{repo}/backlog` (operator) — freeze a backlog; 409 while a factory run is active. */
export function useRegisterBacklog(): UseMutationResult<FactoryBacklog, ApiError, { repo: string; body: unknown }> {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ repo, body }) => api<FactoryBacklog>(`/factory/${encodeURIComponent(repo)}/backlog`, { method: 'POST', body }),
    onSuccess: (_d, v) => {
      void qc.invalidateQueries({ queryKey: keys.factoryBacklog(v.repo) })
      void qc.invalidateQueries({ queryKey: keys.factoryTasks(v.repo) })
    },
  })
}

export function useFactoryEvidence(repo: string): UseQueryResult<Page<EvidencePack>, ApiError> {
  return useQuery({
    queryKey: keys.factoryEvidence(repo),
    queryFn: () => api<Page<EvidencePack>>(`/factory/${enc(repo)}/evidence`),
    enabled: repo.length > 0,
    retry: false,
  })
}

// ---------------------------------------------------------------------------
// Admin
// ---------------------------------------------------------------------------

/** `GET /users` — admin only, so the caller passes `enabled` from the role check. */
export function useUsers(enabled: boolean): UseQueryResult<Page<User>, ApiError> {
  return useQuery({ queryKey: keys.users, queryFn: () => api<Page<User>>('/users'), enabled, retry: false })
}

/** `POST /users` (local account); invalidates the list. */
export function useCreateUser(): UseMutationResult<User, ApiError, UserCreateRequest> {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body) => api<User>('/users', { method: 'POST', body }),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.users }),
  })
}

/** `PUT /users/{id}/role`; invalidates the list. */
export function useSetUserRole(): UseMutationResult<User, ApiError, { id: string; role: Role }> {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, role }) => api<User>(`/users/${enc(id)}/role`, { method: 'PUT', body: { role } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.users }),
  })
}

/** `GET /settings` — non-secret settings; admin only, `enabled` from the role check. */
export function useSettings(enabled: boolean): UseQueryResult<Settings, ApiError> {
  return useQuery({ queryKey: keys.settings, queryFn: () => api<Settings>('/settings'), enabled, retry: false })
}

// --- GitHub App (the enterprise connection) ----------------------------------------------

/** `GET /github/app` — configured or not, the install link, the installations on record. */
export function useGitHubApp(): UseQueryResult<GitHubAppInfo, ApiError> {
  return useQuery({ queryKey: keys.githubApp, queryFn: () => api<GitHubAppInfo>('/github/app'), retry: false })
}

/** `POST /github/installations/sync` (operator) — refresh the installations from GitHub. */
export function useSyncGitHubInstallations(): UseMutationResult<GitHubInstallation[], ApiError, void> {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => api<GitHubInstallation[]>('/github/installations/sync', { method: 'POST' }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: keys.githubApp }),
  })
}

/** `GET /github/installations/{id}/repositories?q=&page=` — the picker page. */
export function useGitHubRepos(installation: number, q: string, page = 1): UseQueryResult<GitHubPickerPage, ApiError> {
  return useQuery({
    queryKey: keys.githubRepos(installation, q, page),
    queryFn: () => api<GitHubPickerPage>(`/github/installations/${installation}/repositories${qs({ q: q || undefined, page, per_page: 50 })}`),
    enabled: installation > 0,
    retry: false,
  })
}

/** `POST /github/installations/{id}/connect` (operator) — register a linked repository. */
export function useConnectGitHubRepo(): UseMutationResult<RepoDetail, ApiError, { installation: number; body: GitHubConnectRequest }> {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ installation, body }) => api<RepoDetail>(`/github/installations/${installation}/connect`, { method: 'POST', body }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: keys.repos })
      void qc.invalidateQueries({ queryKey: ['github', 'repos'] })
    },
  })
}

/**
 * `POST /repos/{name}/github-link` (operator) — link an EXISTING repository (its name, and
 * so its ledger rows, stay) to one of an installation's repositories; the row's URL becomes
 * the GitHub clone URL. Invalidates the repo, the list and the picker, as connect does.
 */
export function useLinkRepoToGitHub(): UseMutationResult<RepoDetail, ApiError, { name: string; installation: number; full_name: string }> {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ name, installation, full_name }) =>
      api<RepoDetail>(`/repos/${enc(name)}/github-link`, { method: 'POST', body: { installation_id: installation, full_name } }),
    onSuccess: (_repo, { name }) => {
      void qc.invalidateQueries({ queryKey: keys.repo(name) })
      void qc.invalidateQueries({ queryKey: keys.repos })
      void qc.invalidateQueries({ queryKey: ['github', 'repos'] })
    },
  })
}


// --- intake: the enterprise's own board (ADR-0017) ------------------------------------

/** `GET /factory/{repo}/intake` — the listener, the connection, the last poll and the
 *  watched column's tickets. No tracker is contacted by this read, so it never waits on
 *  somebody else's service. */
export function useIntake(repo: string): UseQueryResult<Intake, ApiError> {
  return useQuery({
    queryKey: keys.intake(repo),
    queryFn: () => api<Intake>(`/factory/${enc(repo)}/intake`),
    enabled: repo.length > 0,
    retry: false,
  })
}

/** `PUT /factory/{repo}/intake` (operator) — switch the listener on or off, and set the
 *  column this repository watches. The switch is the consent gate (ADR-0017). */
export function useSetIntakeListener(): UseMutationResult<Intake, ApiError, { repo: string; enabled: boolean; column?: string }> {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ repo, enabled, column }) =>
      api<Intake>(`/factory/${enc(repo)}/intake`, { method: 'PUT', body: { enabled, column: column ?? '' } }),
    onSuccess: (data, { repo }) => {
      qc.setQueryData(keys.intake(repo), data)
    },
  })
}

/** `POST /factory/{repo}/intake/{key}/register` (operator) — the Register act (ADR-0022):
 *  put the draft waiting for ticket `key` on the frozen backlog, exactly as it was read at
 *  `revision` (409 `revision_moved` when the ticket changed since). Invalidates the backlog
 *  and the tasks, because it registers an item. */
export function useRegisterIntakeTicket(): UseMutationResult<Intake, ApiError, { repo: string; key: string; revision: string }> {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ repo, key, revision }) =>
      api<Intake>(`/factory/${enc(repo)}/intake/${enc(key)}/register`, { method: 'POST', body: { revision } }),
    onSuccess: (data, { repo }) => {
      qc.setQueryData(keys.intake(repo), data)
      void qc.invalidateQueries({ queryKey: keys.factoryBacklog(repo) })
      void qc.invalidateQueries({ queryKey: keys.factoryTasks(repo) })
    },
  })
}

/** `POST /factory/{repo}/intake/poll` (operator) — read the column now. `force` re-reads
 *  every ticket even when its revision was already handled ("Post the feedback again");
 *  the writes are idempotent either way. Invalidates the backlog and the tasks, because a
 *  poll can register an item. */
export function usePollIntake(): UseMutationResult<Intake, ApiError, { repo: string; force?: boolean }> {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ repo, force }) =>
      api<Intake>(`/factory/${enc(repo)}/intake/poll`, { method: 'POST', body: { force: Boolean(force) } }),
    onSuccess: (data, { repo }) => {
      qc.setQueryData(keys.intake(repo), data)
      void qc.invalidateQueries({ queryKey: keys.factoryBacklog(repo) })
      void qc.invalidateQueries({ queryKey: keys.factoryTasks(repo) })
    },
  })
}
