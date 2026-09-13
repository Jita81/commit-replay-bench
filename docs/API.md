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
| GET | `/repos` | viewer | page of `{name, language, runner, url, clone_path, probe: {status, run_id, checked, detail}, task_counts: {total, standard, hard, gold_clean, gold_failed, unchecked}, last_run: {id, kind, status, finished} \| null, created, updated}`; `probe.status` is `ok\|degraded\|down` once probed, `not_probed` before, or the probe run's own status while queued/running |
| POST | `/repos` | operator | `{name, language, clone_path|url, runner?, src_prefix?, test_prefix?, ext?, test_mode?, test_suffix?, belt_scope?, probe?, layer?, runner_opts?, sandbox_image?, mining?}` → 201 repo detail; config validated by `RepoConfig.from_dict` (422 `validation_error`), 409 `already_exists`; recorded as a `system/repo.created` event. **URL-only registration** (no `clone_path`): the URL is policy-checked at write — `https://`, `ssh://` or `user@host:path` only; `http://`, `git://`, local paths and `file://` are 422 (`file://` is accepted only on a server started with `CRB_ALLOW_LOCAL_CLONE=1`, a test/dev switch) — and the **worker clones it on the repo's first run** (`git clone --no-tags`, full history, 30-minute wall clock) into `<home>/repos/<name>`, persisting `clone_path` and `config.path`; the run's trace carries `system/repo.clone.start {url, dest}` and `system/repo.clone.done {url, dest, head, duration_ms}` (or `status: error`); credentials in the URL are never echoed. With `clone_path` the URL is informational |
| GET | `/repos/{name}` | viewer | list item + `config` (`RepoConfig.to_dict()`) + `profile_computed_at` |
| PUT | `/repos/{name}` | operator | partial config update (same fields as POST minus `name`); the REDACTED field diff is appended as a `system/repo.updated` event (trace `sha256("repo:<name>")[:32]`) |
| POST | `/repos/{name}/probe` | operator | enqueues a `probe` run → 201 run; 503 `queue_unavailable` when no job queue is installed |
| GET | `/repos/{name}/profile` | viewer | change profile `{repo, ref, n_commits, examined, skipped, classes, sizes, cells: [{capability_class, size, count, share}], class_totals, size_totals, computed_at}`; cached on the repo, `?refresh=true` recomputes, `?log_n=` bounds the walk; 409 `no_clone_path` / `clone_unavailable` / `profile_failed` |

## Runs

| Method | Path | Role | Notes |
|---|---|---|---|
| GET | `/runs` | viewer | page, newest first; filters `repo`, `kind`, `status` |
| POST | `/runs` | operator | `{repo, kind: setup|probe|mine|replay|blind|oracle|controls, mode?, builder?, model?, provider?, ladder?, task_ids?, limit?, pool?, executor?, timeout?, builder_config?}` → 201 run (status `queued`). `ladder` is a list of rung labels (`r1`, `r2` … or `builder:model[:provider]`), one attempt per rung, default `["r1"]`: a bare label means one attempt with the run's own `builder:model[@provider]`, an explicit label is a rung as written; `kind: blind` implies `mode: blind`; `replay`/`blind` need a `builder`. A build kind without `model` gets the builder's default when it has one (`claude_code` → `CRB_CLAUDE_CODE_MODEL` on the API host, else `claude-sonnet-5`; the stored run names it). `builder_config` is an object of builder constructor keyword arguments applied to every rung (e.g. `{"auth": "cli", "effort": "high"}` for `claude_code`) — stored as `params.builder_config`, passed to the worker as builder overrides and stamped into the run's apparatus (`extra.builder_config`); keys must be lowercase identifiers, at most 32 keys / 8 KiB; `model`, `provider`, `name` (the recorded identity) and credential-shaped keys (`*api_key*`, `*token*`, `*secret*`, `*password*` …) are 422. 404 unknown repo, 422 on any invalid field, 503 `queue_unavailable` |
| GET | `/runs/{id}` | viewer | `{id, repo, kind, status, mode, builder, model, provider, ladder, executor, timeout, pool, limit, task_ids, builder_config, actor, created, started, finished, cancel_requested, error, cost_usd, apparatus_version, apparatus, worker_id, heartbeat, counts: {tasks, clean, disqualified, errors, first_pass_clean, rows, duration_s, stopped_reason}, progress: {done, total, current_task_id}}`; `counts` are the worker's `RunSummary`, re-derived from the run's ledger rows when the worker has written none; `cost_usd` is the sum of the run's rows |
| POST | `/runs/{id}/cancel` | operator | sets `cancel_requested`; worker stops between tasks; 409 `run_terminal` once finished |
| GET | `/runs/{id}/tasks` | viewer | page of `{task_id, capability_class, size, pool, language, trials, clean, first_pass_clean, disqualified, error, belts: {tests_unmodified, target_green, no_new_failures, source_changed}, cost_usd, latency_s, pack_hashes[], row_ids[]}` — one row per task, attempts collapsed (`belts` = the clean attempt's, else the last) |
| GET | `/runs/{id}/events` | viewer | **SSE** (`text/event-stream`): replays stored StepEvents with `seq > after` (`event: step`, `id: <seq>`, `data: {...}`), then polls the events table every 1 s; `: keepalive` comment every 15 s while idle; ends with `event: done` `{run_id, status, last_seq}` once the run is terminal |
| GET | `/runs/{id}/events/log` | viewer | page of StepEvents (`StepEvent.to_dict()`), oldest first |

## Tasks / grades / evidence

| Method | Path | Role | Notes |
|---|---|---|---|
| GET | `/repos/{name}/tasks` | viewer | page of `TaskSpec.to_dict()`, newest first; filters `pool, size, capability_class, gold_clean` |
| GET | `/tasks/{repo}/{task_id}` | viewer | `{spec, grades}` — the spec + every grade row for it in chain order |
| GET | `/grades` | viewer | ledger rows AS STORED (`GradeRow.to_dict()` + `seq`), chain order; filters `repo, run_id, task_id, clean, mode, builder, model, provider, capability_class, size, language, pool, process_step, belt_set, disqualified`. Served column-by-column so a row that bypassed the write path stays visible to an auditor |
| GET | `/grades/{row_id}` | viewer | one row |
| GET | `/evidence/{pack_hash}` | viewer | `{pack, verified, pack_hash, schema, repo, task_id, run_id, created}` — `verified` = the recomputed canonical hash equals the key (native packs via `verify_pack`; imported packs hashed whole) |

## Capability, routing, forecast, sign-off

| Method | Path | Role | Notes |
|---|---|---|---|
| GET | `/capability-map?repo=&by=class,size[,language][,model][,builder][,provider][,step]` | viewer | `{repo, by, classes, sizes, languages, models, cells[], summary, policy}`. Only MEASURED cells are listed — an unmeasured cell is absent (the UI renders absence as `NOT_YET_MEASURED`), never zero-filled. Each cell: the 7 key fields (`*` where not projected), `label, n, clean, disqualified, errors, rows, repos, point, ci_low, ci_high, sigma, false_q1, cost_usd_mean, latency_s_mean, cost_known, latency_known, oracle_strength_mean, route, reason, verification_tier, apparatus_versions, belt_set, belt_sets`. Active sign-offs are overlaid at read time (a cell whose CURRENT false-Q1 > 0 is never lifted). `summary`: `{trusted_autonomy_coverage, earned_coverage, profile_commits, total_cells, measured_cells, deliver_cells, cells_by_route, n_total, rows, false_q1_total, apparatus_versions, signoffs_applied}` — coverage is `null` until the repo has a change profile. A false-Q1 row anywhere in the repo's ledger → **409 false_q1_refused** (the map is never computed over untrusted rows) |
| GET | `/routes?repo=[&by=]` | viewer | `{repo, by, policy, decisions: [RouteDecision.to_dict() + label, verification_tier, apparatus_versions]}` per full cell (default) or per projection |
| GET | `/forecast/build?repo=&mix=class:size:count,...` | viewer | `{repo, mix, cost_usd_mean, cost_usd_std, minutes, deliver, human, calibrate, buildable_p, buildable_p_stddev, unmeasured, components, measured_components, coverage, costed_components, timed_components, units_by_route, expected_clean_units, single_rep_band, per_component, policy_version}`; `size` may be empty (`class::count`) for a class-level key; `buildable_p` = expected per-unit clean probability over measured units (`p_clean_mean`); unmeasured components are listed and priced at nothing |
| GET | `/forecast/readiness?repo=[&mix=]` | viewer | `{repo, ok, gaps, mix, mix_source: mix\|profile, total, measured, coverage, min_reps_seen, earned_units, buildable_units, buildable_frac, false_q1_total, thresholds, policy_version}`; without `mix` the repo's change profile is the mix (409 `no_profile` when there is none) |
| GET | `/signoffs?repo=[&include_revoked=true]` | viewer | page of `{id, repo, cell, tier, note, approver, created, revoked, revoked_by, revoked_at, active, current_false_q1, evidence: {n, point, ci_low, ci_high, false_q1, apparatus_versions}, prev_hash, row_hash}`; active attestations by default; `active` re-checks the cell's CURRENT false-Q1 (a later violation auto-invalidates) |
| POST | `/signoffs` | approver | `{repo, cell: {capability_class, size?, language?, builder?, model?, provider?, process_step?}, note?, tier?: human-verified\|ab-confirmed}` → 201, or **409 false_q1_refused** when the cell has any false-Q1 row (counted over the STORED belts, so a row that bypassed the ledger is caught) or no measured evidence; the refusal is itself recorded as a `system/signoff.refused` event. Rows are append-only and hash-chained (`prev_hash` = previous sign-off's `row_hash`; `row_hash` over the canonical row); the evidence the approver saw is stamped into the row |
| POST | `/signoffs/{id}/revoke` | approver | `{note?}` → the attestation with `revoked: true`; appends a revocation row (409 `already_revoked`) |

## Ledger

| Method | Path | Role | Notes |
|---|---|---|---|
| GET | `/ledger/verify` | viewer | `{rows, ok, false_q1_total, chain_ok, broken_at, detail, clean_without_pack, verified_at}` — never raises: walks the chain recomputing every `row_hash` from the stored columns, counts false-Q1 over the stored belts; `broken_at` is the first bad `seq` (or `null`) |
| GET | `/ledger/export?format=jsonl|csv&repo=` | viewer | streaming download of the stored rows verbatim (chain fields included); an unfiltered JSONL export verifies standalone with `verify_chain`; a `repo`-filtered one is a subsequence (each row's own hash verifies, the links do not); CSV has a header row (`GradeRow` field order, `labels` as JSON) |
| GET | `/ledger/export/abstract` | operator | JSONL of abstract cells only (`ABSTRACT_ALLOWLIST` fields — no repo, no ids, no timestamps); 409 if the ledger holds a false-Q1 row |
| POST | `/ledger/import` | admin | multipart `file` of crb JSONL rows → `{imported, skipped, read, rows, source_chain_ok}`; rows are re-chained here with the source hash kept in `labels.source_row_hash`; duplicates (by `row_id` / pack hash) are skipped; a false-Q1 row → 409; census rows (`bench.py` verdicts) → 422 `census_import_unsupported` pointing at `crb ledger import-census` (they need their task files and configs) |

## Oracle adequacy

| Method | Path | Role | Notes |
|---|---|---|---|
| GET | `/oracle/{repo}` | viewer | `{repo, policy: AdequacyPolicy, tasks: [{task_id, capability_class, size, strength, band, mutants, killed, errors, gate, run_id, scored_at, note}], cells: [{capability_class, size, n, tasks, strength_mean, strength_min, band, gate}], apparatus_versions, runs}` — aggregated from `oracle.score` events (latest per task wins); `band` ∈ strong|adequate|weak|unscoreable, `gate` = what a CLEAN grade on that oracle licenses (auto_ship|human_review); unscoreable oracles are never averaged in |
| GET | `/oracle/{repo}/controls` | viewer | latest `controls.report` event payload (`ControlsReport.to_dict()` + `run_id`, `reported_at`) or **404 `not_measured`** |

## Factory (phase P6)

| Method | Path | Role | Notes |
|---|---|---|---|
| GET/POST | `/factory/{repo}/backlog` | viewer/operator | frozen backlog (hash) |
| GET | `/factory/{repo}/tasks` | viewer | DoR gaps, RED proof, build, PR, review verdict |
| POST | `/factory/{repo}/tasks/{id}/signoff-gap` | approver | sign a structural gap |
| GET | `/factory/{repo}/evidence` | viewer | factory evidence packs |

Until P6 lands every factory path answers **501 `not_implemented`** with
`detail: {"phase": "P6", "path": …}` (role gates already apply: 401/403 come first).

## Admin

| Method | Path | Role | Notes |
|---|---|---|---|
| GET/POST | `/users` | admin | list / create local user |
| PUT | `/users/{id}/role` | admin | change role |
| GET | `/settings` | admin | non-secret settings (builders configured: yes/no, sandbox mode, retention) |

## SSE event shape

```
event: step
id: 12
data: {"event_id":"…","seq":12,"timestamp":"…","trace_id":"<run_id>","stage":"grade","action":"grade.belt","status":"ok","task_id":"…","payload":{"belt":"target_green","value":true}}

: keepalive

event: done
data: {"run_id":"<run_id>","status":"succeeded","last_seq":12}
```

`id:` is the event's `seq`, so a browser `EventSource` resumes on its own after a drop;
`?after=<seq>` does the same for any client.

## Contract notes (server ↔ UI)

`ui/src/api/types.ts` is the UI's reading of this document; where the two differed the
UI's shape was adopted (2026-09-13, W2-B):

- `/repos` items carry `probe`, `task_counts` and `last_run` objects (not flat columns).
- `/runs/{id}` carries `counts` (`RunSummary.to_dict()` fields) and `progress` with
  `current_task_id`; `started`/`finished`/`heartbeat` are `null` when unset.
- `/runs/{id}/tasks` rows carry `belts` as an object and `pack_hashes` / `row_ids` lists.
- `/evidence/{hash}` is `{pack, verified, …}` (the pack is not inlined next to `verified`).
- `/capability-map` `summary.trusted_autonomy_coverage` is a number OR `null` (no profile
  → no coverage claim). The UI's `fmtPct` renders `null` as a dash.
- `/signoffs` items carry `approver` (the verifier's principal id) and `evidence` (the
  snapshot stamped at write time).
- `/oracle/{repo}` uses `strength` / `strength_mean` / `mutants` / `killed` / `gate`.
- `ladder` in `POST /runs` is a list of rung labels (`r1`, `r2` …), as the core's run
  orchestrator defines it; `builder:model[:provider]` triples are accepted as labels too.
  The worker resolves a bare label to the run's own `builder:model[@provider]` (W3-B; before
  that every API-created replay failed at the worker with `rung 'r1' must look like
  builder:model`); the stored `ladder` stays what was declared; `trial` on ledger rows is
  positional (`r1`, `r2` …) either way.
- `GET /runs/{id}` carries `builder_config` (`{}` when none) — W3-B. The UI's run dialog
  offers it as a validated JSON editor plus a one-click "Use my Claude Code login (dev)"
  toggle (`{"auth": "cli"}`).
- `/repos` items carry `clone_path` (empty for a URL-only registration until the worker's
  first run clones it — W3-B).
- `GET /settings` (admin, W2-A) still returns `Settings.redacted_dict()`; the UI's
  `{builders, sandbox_mode, retention, oidc_enabled, ledger_backend, apparatus_version,
  policy_version}` reading is NOT yet served — see the W2-B report.
