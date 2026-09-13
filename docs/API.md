# crb HTTP API contract (v1)

Base path `/api/v1`. JSON everywhere. This document is the contract the server
(`crb.server`) implements and the UI (`ui/`) consumes; both are built against it
in parallel, so changes here are changes to both.

## Conventions

- **Auth**: cookie session (`crb_session`, HttpOnly, SameSite=Lax, Secure in prod).
  Login via `POST /auth/login` (local account) or `GET /auth/oidc/start` → provider →
  `GET /auth/oidc/callback` (Entra ID / any OIDC). `GET /auth/me` returns the principal.
  Mutating requests must carry `X-CSRF-Token` equal to the `crb_csrf` cookie.
- **Roles** (ascending): `viewer` (read everything), `operator` (+ create/cancel runs,
  add/probe repos, mine), `approver` (+ sign-offs), `admin` (+ users, settings).
  A route lists its minimum role. 401 = not logged in, 403 = insufficient role.
- **Errors**: `{"error": {"code": "<snake_case>", "message": "...", "detail": {...}}}`.
  `409 false_q1_refused` is reserved for sign-off refusals and ledger invariant
  violations; `503 sandbox_unavailable` for fail-closed sandbox stops.
- **Pagination**: `?limit=` (default 50, max 500) `&offset=`; responses carry
  `{"items": [...], "total": n, "limit": l, "offset": o}`.
- **Numbers carry their method**: every rate is accompanied by `n`, `ci_low`, `ci_high`
  (Wilson 95%), `apparatus_versions`, and `belt_set` where mixed.
- **Never fabricated**: an unmeasured cell is `NOT_YET_MEASURED`, never an empty row.

## Health / metrics (no auth; bind to an internal interface)

| Method | Path | Returns |
|---|---|---|
| GET | `/health` | `{"status": "ok|degraded|down", "probes": [...]}` — db (incl. append-only trigger check), sandbox, toolchains, builders, worker heartbeat |
| GET | `/metrics` | Prometheus text (`crb_false_q1_total` must be 0) |
| GET | `/version` | `{"crb": "...", "apparatus": "2.0", "policy": "routing.v1"}` |

## Auth

| Method | Path | Role | Body / Returns |
|---|---|---|---|
| POST | `/auth/login` | – | `{username, password}` → principal; sets cookies |
| POST | `/auth/logout` | any | – |
| GET | `/auth/me` | any | `{id, display_name, email, role, issuer}` |
| GET | `/auth/oidc/start` | – | 302 to provider (state in cookie) |
| GET | `/auth/oidc/callback` | – | 302 to `/` after establishing session |
| GET | `/auth/csrf` | any | `{token}` |

## Repos

| Method | Path | Role | Notes |
|---|---|---|---|
| GET | `/repos` | viewer | list with probe status, task counts, last run |
| POST | `/repos` | operator | `{name, language, clone_path|url, runner?, src_prefix?, test_prefix?, ext?, belt_scope?, probe?, runner_opts?, sandbox_image?, mining?}` → repo |
| GET | `/repos/{name}` | viewer | repo + config |
| PUT | `/repos/{name}` | operator | update config (history kept in events) |
| POST | `/repos/{name}/probe` | operator | enqueues a `probe` run; returns run |
| GET | `/repos/{name}/profile` | viewer | change profile (class × size histogram) |

## Runs

| Method | Path | Role | Notes |
|---|---|---|---|
| GET | `/runs` | viewer | filters `repo`, `kind`, `status` |
| POST | `/runs` | operator | `{repo, kind: mine|replay|blind|oracle|controls, mode?, builder?, model?, provider?, ladder?, task_ids?, limit?, pool?, executor?, timeout?}` → run (status `queued`) |
| GET | `/runs/{id}` | viewer | run + counts + progress |
| POST | `/runs/{id}/cancel` | operator | sets `cancel_requested`; worker stops between tasks |
| GET | `/runs/{id}/tasks` | viewer | per-task outcome table (task, trials, clean, belts, cost, latency, pack hashes) |
| GET | `/runs/{id}/events` | viewer | **SSE** stream of StepEvents (`event: step`, `data: {...}`); `?after=<seq>` resumes; ends with `event: done` when the run is terminal |
| GET | `/runs/{id}/events/log` | viewer | paginated events (non-streaming) |

## Tasks / grades / evidence

| Method | Path | Role | Notes |
|---|---|---|---|
| GET | `/repos/{name}/tasks` | viewer | mined TaskSpecs (pool, size, class, gold status) |
| GET | `/tasks/{repo}/{task_id}` | viewer | spec + all grade rows for it |
| GET | `/grades` | viewer | ledger rows; filters `repo, run_id, task_id, clean, mode, builder, model, capability_class, size, language` |
| GET | `/grades/{row_id}` | viewer | one row |
| GET | `/evidence/{pack_hash}` | viewer | the evidence pack (redacted body) + `verified: bool` |

## Capability, routing, forecast, sign-off

| Method | Path | Role | Notes |
|---|---|---|---|
| GET | `/capability-map?repo=&by=class,size[,language][,model]` | viewer | cells with `n, clean, point, ci_low, ci_high, false_q1, cost_usd_mean, latency_s_mean, oracle_strength_mean, route, reason, verification_tier, apparatus_versions`; absent cells `NOT_YET_MEASURED`; `summary.trusted_autonomy_coverage` |
| GET | `/routes?repo=` | viewer | route decisions per cell with reasons and the policy in force |
| GET | `/forecast/build?repo=&mix=class:size:count,...` | viewer | cost μ/σ, minutes, deliver/human/calibrate counts, buildable P, unmeasured |
| GET | `/forecast/readiness?repo=` | viewer | ok + gaps punch-list |
| GET | `/signoffs?repo=` | viewer | active attestations |
| POST | `/signoffs` | approver | `{repo, cell, note}` → 201, or **409 false_q1_refused** |
| POST | `/signoffs/{id}/revoke` | approver | appends a revocation |

## Ledger

| Method | Path | Role | Notes |
|---|---|---|---|
| GET | `/ledger/verify` | viewer | `{rows, ok, false_q1_total, broken_at?}` |
| GET | `/ledger/export?format=jsonl|csv&repo=` | viewer | streaming download; JSONL rows verify standalone |
| GET | `/ledger/export/abstract` | operator | abstract cells only (federated export, k-anonymous) |
| POST | `/ledger/import` | admin | multipart JSONL (crb rows or census rows) → count |

## Oracle adequacy

| Method | Path | Role | Notes |
|---|---|---|---|
| GET | `/oracle/{repo}` | viewer | per-task and per-cell oracle strength, gate classification |
| GET | `/oracle/{repo}/controls` | viewer | latest negative-controls report |

## Factory (phase P6)

| Method | Path | Role | Notes |
|---|---|---|---|
| GET/POST | `/factory/{repo}/backlog` | viewer/operator | frozen backlog (hash) |
| GET | `/factory/{repo}/tasks` | viewer | DoR gaps, RED proof, build, PR, review verdict |
| POST | `/factory/{repo}/tasks/{id}/signoff-gap` | approver | sign a structural gap |
| GET | `/factory/{repo}/evidence` | viewer | factory evidence packs |

## Admin

| Method | Path | Role | Notes |
|---|---|---|---|
| GET/POST | `/users` | admin | list / create local user |
| PUT | `/users/{id}/role` | admin | change role |
| GET | `/settings` | admin | non-secret settings (builders configured: yes/no, sandbox mode, retention) |

## SSE event shape

```
event: step
data: {"event_id":"…","seq":12,"timestamp":"…","trace_id":"<run_id>","stage":"grade","action":"grade.belt","status":"ok","task_id":"…","payload":{"belt":"target_green","value":true}}
```
