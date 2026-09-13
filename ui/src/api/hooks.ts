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
  CapabilityMap,
  CellField,
  ControlsReport,
  EvidencePack,
  EvidenceResponse,
  FactoryBacklog,
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
  signoffs: (repo: string) => ['signoffs', repo] as const,
  ledgerVerify: ['ledger', 'verify'] as const,
  oracle: (repo: string) => ['oracle', repo] as const,
  oracleControls: (repo: string) => ['oracle', repo, 'controls'] as const,
  factoryBacklog: (repo: string) => ['factory', repo, 'backlog'] as const,
  factoryTasks: (repo: string) => ['factory', repo, 'tasks'] as const,
  factoryEvidence: (repo: string) => ['factory', repo, 'evidence'] as const,
  users: ['users'] as const,
  settings: ['settings'] as const,
}

const enc = encodeURIComponent

// ---------------------------------------------------------------------------
// Health / version
// ---------------------------------------------------------------------------

export function useHealth(): UseQueryResult<Health, ApiError> {
  return useQuery({ queryKey: keys.health, queryFn: () => api<Health>('/health'), retry: false, staleTime: 15_000 })
}

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

export function useLogin(): UseMutationResult<Principal, ApiError, LoginRequest> {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body) => api<Principal>('/auth/login', { method: 'POST', body }),
    onSuccess: (me) => qc.setQueryData(keys.me, me),
  })
}

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

export function useRepos(): UseQueryResult<Page<RepoSummary>, ApiError> {
  return useQuery({ queryKey: keys.repos, queryFn: () => api<Page<RepoSummary>>('/repos'), retry: false })
}

export function useRepo(name: string): UseQueryResult<RepoDetail, ApiError> {
  return useQuery({
    queryKey: keys.repo(name),
    queryFn: () => api<RepoDetail>(`/repos/${enc(name)}`),
    enabled: name.length > 0,
    retry: false,
  })
}

export function useCreateRepo(): UseMutationResult<RepoDetail, ApiError, RepoCreateRequest> {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body) => api<RepoDetail>('/repos', { method: 'POST', body }),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.repos }),
  })
}

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

export function useRepoProfile(name: string): UseQueryResult<RepoProfile, ApiError> {
  return useQuery({
    queryKey: keys.repoProfile(name),
    queryFn: () => api<RepoProfile>(`/repos/${enc(name)}/profile`),
    enabled: name.length > 0,
    retry: false,
  })
}

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

export const RUN_POLL_MS = 2_500

export function useRuns(p: RunListParams = {}): UseQueryResult<Page<Run>, ApiError> {
  return useQuery({
    queryKey: keys.runs(p),
    queryFn: () => api<Page<Run>>(`/runs${qs({ repo: p.repo, kind: p.kind, status: p.status, limit: p.limit, offset: p.offset })}`),
    retry: false,
    refetchInterval: (q) => (q.state.data?.items.some((r) => !isRunTerminal(r.status)) ? RUN_POLL_MS * 2 : false),
    refetchIntervalInBackground: false,
  })
}

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

export function useCancelRun(): UseMutationResult<Run, ApiError, string> {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id) => api<Run>(`/runs/${enc(id)}/cancel`, { method: 'POST' }),
    onSuccess: (_r, id) => qc.invalidateQueries({ queryKey: keys.run(id) }),
  })
}

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

export function useRunEventLog(id: string, p: PageParams = {}): UseQueryResult<Page<StepEvent>, ApiError> {
  return useQuery({
    queryKey: keys.runEventLog(id, p),
    queryFn: () => api<Page<StepEvent>>(`/runs/${enc(id)}/events/log${qs({ limit: p.limit, offset: p.offset })}`),
    enabled: id.length > 0,
    retry: false,
  })
}

export interface UseRunEventsOptions {
  enabled?: boolean
  maxEvents?: number
  factory?: EventSourceFactory
}

/**
 * The live SSE log for one run. Opens `GET /runs/{id}/events`, resumes with
 * `?after=` on reconnect, appends StepEvents into a bounded buffer, and closes
 * on unmount or when the server sends `event: done`.
 */
const IDLE_SNAPSHOT: SseSnapshot = { status: 'idle', events: [], lastSeq: 0, reconnects: 0, dropped: 0, error: null }

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

export function useTask(repo: string, taskId: string): UseQueryResult<TaskDetail, ApiError> {
  return useQuery({
    queryKey: keys.task(repo, taskId),
    queryFn: () => api<TaskDetail>(`/tasks/${enc(repo)}/${enc(taskId)}`),
    enabled: repo.length > 0 && taskId.length > 0,
    retry: false,
  })
}

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

export function useRoutes(repo: string): UseQueryResult<RoutesResponse, ApiError> {
  return useQuery({
    queryKey: keys.routes(repo),
    queryFn: () => api<RoutesResponse>(`/routes${qs({ repo })}`),
    enabled: repo.length > 0,
    retry: false,
  })
}

export function useForecastBuild(repo: string, mix: string): UseQueryResult<ForecastBuild, ApiError> {
  return useQuery({
    queryKey: keys.forecastBuild(repo, mix),
    queryFn: () => api<ForecastBuild>(`/forecast/build${qs({ repo, mix })}`),
    enabled: repo.length > 0 && mix.length > 0,
    retry: false,
  })
}

export function useForecastReadiness(repo: string): UseQueryResult<ForecastReadiness, ApiError> {
  return useQuery({
    queryKey: keys.forecastReadiness(repo),
    queryFn: () => api<ForecastReadiness>(`/forecast/readiness${qs({ repo })}`),
    enabled: repo.length > 0,
    retry: false,
  })
}

export function useSignoffs(repo: string): UseQueryResult<Page<Signoff>, ApiError> {
  return useQuery({
    queryKey: keys.signoffs(repo),
    queryFn: () => api<Page<Signoff>>(`/signoffs${qs({ repo })}`),
    enabled: repo.length > 0,
    retry: false,
  })
}

export function useCreateSignoff(): UseMutationResult<Signoff, ApiError, SignoffCreateRequest> {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body) => api<Signoff>('/signoffs', { method: 'POST', body }),
    onSuccess: (s) => {
      qc.invalidateQueries({ queryKey: keys.signoffs(s.repo) })
      qc.invalidateQueries({ queryKey: ['capability', s.repo] })
    },
  })
}

export function useRevokeSignoff(): UseMutationResult<Signoff, ApiError, { id: string; repo: string }> {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id }) => api<Signoff>(`/signoffs/${enc(id)}/revoke`, { method: 'POST' }),
    onSuccess: (_s, v) => qc.invalidateQueries({ queryKey: keys.signoffs(v.repo) }),
  })
}

// ---------------------------------------------------------------------------
// Ledger
// ---------------------------------------------------------------------------

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

export function useOracle(repo: string): UseQueryResult<OracleReport, ApiError> {
  return useQuery({
    queryKey: keys.oracle(repo),
    queryFn: () => api<OracleReport>(`/oracle/${enc(repo)}`),
    enabled: repo.length > 0,
    retry: false,
  })
}

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

export function useFactoryBacklog(repo: string): UseQueryResult<FactoryBacklog, ApiError> {
  return useQuery({
    queryKey: keys.factoryBacklog(repo),
    queryFn: () => api<FactoryBacklog>(`/factory/${enc(repo)}/backlog`),
    enabled: repo.length > 0,
    retry: false,
  })
}

export function useFactoryTasks(repo: string): UseQueryResult<Page<FactoryTask>, ApiError> {
  return useQuery({
    queryKey: keys.factoryTasks(repo),
    queryFn: () => api<Page<FactoryTask>>(`/factory/${enc(repo)}/tasks`),
    enabled: repo.length > 0,
    retry: false,
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

export function useUsers(enabled: boolean): UseQueryResult<Page<User>, ApiError> {
  return useQuery({ queryKey: keys.users, queryFn: () => api<Page<User>>('/users'), enabled, retry: false })
}

export function useCreateUser(): UseMutationResult<User, ApiError, UserCreateRequest> {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body) => api<User>('/users', { method: 'POST', body }),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.users }),
  })
}

export function useSetUserRole(): UseMutationResult<User, ApiError, { id: string; role: Role }> {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, role }) => api<User>(`/users/${enc(id)}/role`, { method: 'PUT', body: { role } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.users }),
  })
}

export function useSettings(enabled: boolean): UseQueryResult<Settings, ApiError> {
  return useQuery({ queryKey: keys.settings, queryFn: () => api<Settings>('/settings'), enabled, retry: false })
}
