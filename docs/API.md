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
| GET | `/health/live` | – | process up + database reachable; never probes the sandbox (container HEALTHCHECK / Helm liveness); 503 when the store is gone |
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
| GET | `/repos/{name}/events` | viewer | page of `StepEventOut` for the repo's system trace (`repo.created`, `repo.updated {diff, fields}`), newest first — the Configuration tab's audit trail |
| POST | `/repos/{name}/probe` | operator | enqueues a `probe` run → 201 run; 503 `queue_unavailable` when no job queue is installed |
| GET | `/repos/{name}/profile` | viewer | change profile `{repo, ref, n_commits, examined, skipped, classes, sizes, cells: [{capability_class, size, count, share}], class_totals, size_totals, computed_at}`; cached on the repo, `?refresh=true` recomputes, `?log_n=` bounds the walk; 409 `no_clone_path` / `clone_unavailable` / `profile_failed` |

## Runs

| Method | Path | Role | Notes |
|---|---|---|---|
| GET | `/runs` | viewer | page, newest first; filters `repo`, `kind`, `status` |
| POST | `/runs` | operator | `{repo, kind: setup|probe|mine|replay|blind|oracle|controls, mode?, builder?, model?, provider?, ladder?, budget?, task_ids?, limit?, pool?, executor?, timeout?, builder_config?, retain?}` → 201 run (status `queued`). `ladder` is a list of at most 16 entries, one attempt per rung until an attempt grades clean, default `["r1"]`; each entry is a rung LABEL (`r1`, `r2` … = one attempt with the run's own `builder:model[@provider]`; `builder:model[:provider]` = a rung as written) or an OBJECT rung `{builder, model, provider?, budget?}` whose `budget` overrides the run's for that rung only — so `[{builder, model, budget: {max_tool_calls: 25}}, {…50}, {…100}]` is a **budget ladder**: the same model, escalating caps, climbed until clean. A rung accepts nothing else (`name`/`config`/a builder kwarg/a credential-shaped key → 422 with the rung's own reason); exact-duplicate rungs and repeated labels are 422; a ladder made only of object rungs needs no run-level `builder` (the first rung fills the run's builder/model/provider). `ladder_json` stores the ladder exactly as declared and `GET /runs/{id}.ladder` echoes it. `budget` is the run-level per-attempt cap set `{max_turns?, max_tool_calls?, max_tokens?, max_cost_usd?, wall_clock_s?}` — every field optional, bounded (`1 ≤ max_turns ≤ 1000`, `1 ≤ max_tool_calls ≤ 5000`, `0 ≤ max_tokens ≤ 50 000 000`, `0 ≤ max_cost_usd ≤ 1000`, `1 ≤ wall_clock_s ≤ 86400`; `0` tokens / `$0` = no cap), stored as `params.budget` with ONLY the fields set (`{}` → not stored) and applied by the worker as **rung > run > builder default, per field** (defaults `25 turns / 25 tool calls / 0 / 0 / 900 s`); the effective budget of every rung is validated before any task runs (a bad cap fails the run closed). `kind: blind` implies `mode: blind`; `replay`/`blind` need a `builder`. A build kind without `model` gets the builder's default when it has one (`claude_code` → `CRB_CLAUDE_CODE_MODEL` on the API host, else `claude-sonnet-5`; the stored run names it). `builder_config` is an object of builder constructor keyword arguments applied to every rung (e.g. `{"auth": "cli", "effort": "high"}` for `claude_code`) — stored as `params.builder_config`, passed to the worker as builder overrides and stamped into the run's apparatus (`extra.builder_config`); keys must be lowercase identifiers, at most 32 keys / 8 KiB; `model`, `provider`, `name` (the recorded identity) and credential-shaped keys (`*api_key*`, `*token*`, `*secret*`, `*password*` …) are 422. 404 unknown repo, 422 on any invalid field, 503 `queue_unavailable` |
| GET | `/runs/{id}` | viewer | `{id, repo, kind, status, mode, builder, model, provider, ladder, budget, executor, timeout, pool, limit, task_ids, builder_config, retain, actor, created, started, finished, cancel_requested, error, cost_usd, apparatus_version, apparatus, worker_id, heartbeat, counts: {tasks, clean, disqualified, errors, first_pass_clean, rows, duration_s, stopped_reason}, progress: {done, total, current_task_id}}`; `ladder` is `ladder_json` as declared (labels and/or object rungs — an object rung echoes only the budget fields it set); `budget` is `params.budget` (`{}` when the defaults apply); a replay's `apparatus.extra` carries `budget` (the run-level caps in full), `builder_config` and `ladder` (one `{builder, model, provider, budget_tier}` per rung, in order); `counts` are the worker's `RunSummary`, re-derived from the run's ledger rows when the worker has written none; `cost_usd` is the sum of the run's rows |
| POST | `/runs/{id}/cancel` | operator | sets `cancel_requested`; worker stops between tasks; 409 `run_terminal` once finished |
| GET | `/runs/{id}/tasks` | viewer | page of `{task_id, capability_class, size, pool, language, trials, clean, first_pass_clean, disqualified, error, belts: {tests_unmodified, target_green, no_new_failures, source_changed}, cost_usd, latency_s, pack_hashes[], row_ids[], budget_tier, budget_tiers[]}` — one row per task, attempts collapsed (`belts` = the clean attempt's, else the last); `budget_tiers` is one `labels.budget_tier` per attempt aligned with `row_ids` and `budget_tier` the decisive attempt's (`""` on rows written before the label) |
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
| GET | `/grades/{row_hash}/retained` | viewer | What stands behind the row right now, with a one-line reason each: `{row_hash, run_id, retain_worktrees, retain_transcripts, patch_available, patch_reason, transcript_available, transcript_reason, diff_sha256, extra}`. Keyed by the row's chain hash (not `row_id`) — the same key a review names |
| GET | `/grades/{row_hash}/patch` | viewer | `text/x-diff` — the unified diff of the row's **retained worktree** (a run queued with `retain.worktrees`), COMPUTED ON DEMAND by the grader's own procedure (`Workspace.diff_stats`: `git diff HEAD` + every untracked file against `/dev/null`, path order — so the text hashes to the pack's `diff_sha256`), passed through `crb.core.redact`, capped at 1 MiB. **Never stored twice: the pack's hash is the anchor** (ADR-0006 amendment). Headers: `X-CRB-Diff-SHA256` (the pack's anchor), `X-CRB-Patch-SHA256` (what the worktree hashes to now), `X-CRB-Served-SHA256` (what the bytes served hash to), `X-CRB-Patch-Verified` (`true` iff worktree == anchor), `X-CRB-Redacted` / `X-CRB-Truncated` (`true` when redaction / the cap changed the served bytes — then the served hash is not the anchor and the UI says so). **404 `patch_unavailable`** with `detail.reason`: no stored pack; the pack records no diff; the run did not retain worktrees; the retained worktree no longer exists (retention); the directory is not a git worktree; git could not read it. `Cache-Control: no-store` |
| GET | `/grades/{row_hash}/transcript` | viewer | the retained (redacted at write, redacted again on read) builder transcript the pack's `builder.transcript_ref` names — served ONLY when the file lies inside `<home>/transcripts/` (a reference anywhere else is refused, never opened); `application/json` when it parses, `text/plain` otherwise. **404 `transcript_unavailable`** with `detail.reason`: not retained (`retain.transcripts` was off / the builder wrote none); swept by retention; reference outside the transcripts directory |

## Capability, routing, forecast, sign-off

| Method | Path | Role | Notes |
|---|---|---|---|
| GET | `/capability-map?repo=&by=class,size[,language][,model][,builder][,provider][,step]&mode=sighted\|blind\|all&apparatus=current\|<version>\|all` | viewer | `{repo, by, classes, sizes, languages, models, cells[], summary, policy, controls}`. `apparatus` defaults to `current` (the running `APPARATUS_VERSION`) — no claim blends apparatus versions (EVIDENCE-AND-CLAIMS §5); `all` pools them on request. `mode` defaults to `sighted`: the map never pools sighted and blind rows (different measurements of the same task) unless `mode=all` is asked for explicitly; `failure_split.outage` counts provider outages (usage limit / 429 / dead credential), which sit outside `n` like `disqualified`. Only MEASURED cells are listed — an unmeasured cell is absent (the UI renders absence as `NOT_YET_MEASURED`), never zero-filled. Each cell: the 7 key fields (`*` where not projected), `label, n, clean, disqualified, errors, rows, repos, point, ci_low, ci_high, sigma, false_q1, cost_usd_mean, latency_s_mean, cost_known, latency_known, oracle_strength_mean, route, reason, reason_code, verification_tier, apparatus_versions, belt_set, belt_sets` **plus the failure split** `n_builder_red, n_budget, n_protocol, n_harness, n_disqualified` (= `failure_split: {builder_red, budget, protocol, harness, disqualified}`; `n == clean + builder_red + budget + protocol + harness`, DQ sits outside `n`) and `model_n, model_point, model_ci_low, model_ci_high` — `model_point` = clean / (clean + builder_red), the model's rate on fair, finished attempts, reported NEXT TO `point` (the all-rows, fail-closed rate that routes) and `null` when `model_n == 0`. `controls` is the repo's latest negative-controls verdict every cell was routed under: `{measured, passed, complete, constructible, total, share, escapes, run_id, created, state: passed|failed|thin|escaped|unmeasured}` (from the latest `controls.report`, else the latest finished `controls` run's counts, else `unmeasured` — always present, never a pass; see ADR-0003 amendment: failed → every cell `human`, escapes > 0 → `human`, unmeasured / < 50 % constructible → `deliver` withheld). `reason_code` ∈ `false_q1|granularize|controls_failed|n_below_min|oracle_weak|controls_escapes|point_below_bar|ci_low_below_bar|controls_unmeasured|controls_thin|deliver`. Active sign-offs are overlaid at read time (a cell whose CURRENT false-Q1 > 0 is never lifted; a sign-off lifts the tier, never the route). `summary`: `{trusted_autonomy_coverage, earned_coverage, profile_commits, total_cells, measured_cells, deliver_cells, cells_by_route, n_total, rows, false_q1_total, apparatus_versions, signoffs_applied}` — coverage is `null` until the repo has a change profile. `policy` adds `min_controls_share, max_controls_escapes, controls_version`. A false-Q1 row anywhere in the repo's ledger → **409 false_q1_refused** (the map is never computed over untrusted rows) |
| GET | `/routes?repo=[&by=]` | viewer | `{repo, by, policy, controls, decisions: [RouteDecision.to_dict() + label, verification_tier, apparatus_versions, model_n, model_point, failure_split]}` per full cell (default) or per projection; each decision carries `reason_code`, `controls_policy` (`controls-gate.v1` — the server always evaluates the verdict) and the `controls` verdict it was taken under |
| GET | `/failure-split?repo=[&run_id=]` | viewer | `FailureSplit.to_dict()` over the repo's rows (or one run's): `{repo, run_id, n, clean, builder_red, budget, protocol, harness, disqualified, rows, point, ci_low, ci_high, model_n, model_point, model_ci_low, model_ci_high, cost_known, cost_unknown, kinds}` — the split every rate is shown with; an unknown `run_id` is an empty split (n = 0), never an invented one; 409 `false_q1_refused` like the map |
| GET | `/forecast/build?repo=&mix=class:size:count,...` | viewer | `{repo, mix, cost_usd_mean, cost_usd_std, minutes, deliver, human, calibrate, buildable_p, buildable_p_stddev, unmeasured, components, measured_components, coverage, costed_components, timed_components, units_by_route, expected_clean_units, single_rep_band, per_component, policy_version}`; `size` may be empty (`class::count`) for a class-level key; `buildable_p` = expected per-unit clean probability over measured units (`p_clean_mean`); unmeasured components are listed and priced at nothing |
| GET | `/forecast/readiness?repo=[&mix=]` | viewer | `{repo, ok, gaps, mix, mix_source: mix\|profile, total, measured, coverage, min_reps_seen, earned_units, buildable_units, buildable_frac, false_q1_total, thresholds, policy_version}`; without `mix` the repo's change profile is the mix (409 `no_profile` when there is none) |
| GET | `/signoffs?repo=[&include_revoked=true]` | viewer | page of `{id, repo, cell, tier, note, approver, created, revoked, revoked_by, revoked_at, active, current_false_q1, evidence: {n, point, ci_low, ci_high, false_q1, oracle_strength, apparatus_versions}, prev_hash, row_hash, schema, policy_version, policy_thresholds, route: {route, reason, reason_code}, controls: {verdict, run_id, k, total, escapes, created}, attestation: {reviewed_task_id, reviewed_row_hash, statement, at, subject} \| null}`; active attestations by default; `active` re-checks the cell's CURRENT false-Q1 (a later violation auto-invalidates). A row signed before the policy is served as `schema: crb.signoff.v1` with `policy_version: ""`, empty route / controls and `attestation: null` — never a fabricated snapshot |
| GET | `/signoffs/policy` | viewer | `SignoffPolicy.to_dict()`: `{policy_version: signoff-policy.v2, relaxed, non_overridable: [false_q1, oracle_unmeasured, attestation_missing], bounds, n_min, require_route_deliver, require_controls_passed, max_controls_escapes, min_constructible_share, min_oracle_strength, require_oracle_measured, require_attestation}` — the bar in force. **Deployment knobs** (`CRB_SIGNOFF__*`, read per request; unset = the published default): `N_MIN` (int, 1–10000; default 10), `MAX_CONTROLS_ESCAPES` (int, 0–100; default 0), `MIN_CONSTRUCTIBLE_SHARE` (0–1; default 0.5), `MIN_ORACLE_STRENGTH` (0–1; default 0.8), `REQUIRE_ROUTE_DELIVER` / `REQUIRE_CONTROLS_PASSED` (bool; default true). `REQUIRE_ATTESTATION` and `REQUIRE_ORACLE_MEASURED` may only be `true` (v2: an unmeasured oracle is exactly the "a green suite proves correctness" claim EVIDENCE-AND-CLAIMS §7 forbids, so no deployment may sign one — there is no knob) and the false-Q1 floor has no knob. A value outside its bounds, a non-number, `REQUIRE_ATTESTATION=false` or `REQUIRE_ORACLE_MEASURED=false` makes every sign-off route answer **503 signoff_policy_invalid** (fail closed: a misconfigured bar is not a lower bar). The thresholds in force are stamped into every record (`policy_thresholds`) so an audit reads the bar the approver actually cleared; a record signed under `signoff-policy.v1` keeps `policy_version: signoff-policy.v1` (no `require_oracle_measured` threshold) and its chain still verifies |
| GET | `/signoffs/preview?repo=&capability_class=[&size=&language=&builder=&model=&provider=&process_step=][&reviewed_row_hash=&statement=]` | viewer | What a `POST /signoffs` for this cell WOULD do right now, without writing: `{repo, cell, policy, evidence: {measured, n, clean, point, ci_low, ci_high, false_q1, oracle_strength, oracle: {strength, scored, tasks}, apparatus_versions, belt_sets, model_n, model_point, failure_split}, route: {route, reason, reason_code}, controls (the repo's latest verdict + state, as `/capability-map`), refusals: [{code, message, threshold, observed, overridable}], signable, would_record (the snapshot the record would carry), accepted_rows: [{row_hash, row_id, task_id, subject, created, run_id, trial, builder, model, evidence_pack_hash}] (clean, not disqualified, newest first, ≤ 50), attestation \| null}`. `evidence.oracle` is the cell's oracle as the repo's task-level mutation scores measure it — the latest `oracle.score` per task (the same reduction `/oracle/{repo}` serves) averaged over the cell's `scored` of `tasks` distinct tasks; `strength: null` = no task of the cell was ever scored (never 0) and the `oracle_unmeasured` refusal is listed with `observed: null`, `threshold: "measured"`, `overridable: false`. `evidence.oracle_strength` is the strength the policy judged (that measurement, else the rows' own `oracle_strength` mean for census-imported rows). With `reviewed_row_hash` the named row is validated exactly as the POST would (422 when it is not an accepted row of this cell); without it `attestation_missing` is listed, as it would be. 404 unknown repo; 422 malformed cell; **409 false_q1_refused** when the cell has a false-Q1 row (a preview is not an attempt: no `signoff.refused` event) |
| GET | `/signoffs/{id}` | viewer | one attestation with its snapshot (the same shape as a list item); 404 for a revocation row or an unknown id |
| POST | `/signoffs` | approver | `{repo, cell: {capability_class, size?, language?, builder?, model?, provider?, process_step?}, note?, tier?: human-verified\|ab-confirmed, attestation: {reviewed_row_hash, statement}}` → 201 with the snapshot. **A sign-off is a policy decision, refused at write**; the cell is measured on sighted rows of the current apparatus only (`signoff-policy.v2`, `crb.core.signoff.SignoffPolicy`), evaluated in this order — the first failing clause is the envelope's `detail.code`, every failing clause is in `detail.refusals[]` as `{code, message, threshold, observed, overridable}`, and `detail.thresholds` / `detail.observed` (incl. `observed.oracle: {strength, scored, tasks}`) carry the bar and the cell's numbers: (1) **409 false_q1_refused** · `false_q1` — any false-Q1 row in the cell (counted over the STORED belts, so a row that bypassed the ledger is caught); first, never overridable; (2) **409 signoff_refused** · `thin_cell` (`n < n_min`), `controls_unmeasured` / `controls_failed` / `controls_escapes` (escapes > `max_controls_escapes`) / `controls_thin` (constructible share < `min_constructible_share`) — the repo's latest negative-controls verdict, the SAME one `/capability-map` routes under, `oracle_unmeasured` (**v2, never overridable**: no task of the cell carries a task-level mutation score — the cell's oracle strength is measured from the repo's `oracle.score` events, the latest per task, averaged over the cell's scored tasks; `observed: null`; run an `oracle` run on the repo first), `oracle_weak` (measured strength < `min_oracle_strength`), `route_not_deliver:<reason_code>` (the ONE routing rule does not say `deliver` — the route is the capability map's; the oracle measurement feeds the two oracle clauses and the stamped snapshot, never the route, so the two can never disagree), `attestation_missing` (never overridable). Every refusal is recorded as a `system/signoff.refused` event and nothing is written. The attestation's `reviewed_row_hash` must be a ledger row of this repo, inside the attested scope and ACCEPTED (clean, not disqualified) — else **422 validation_error** (`detail.errors[0].loc = [body, attestation, reviewed_row_hash]`); the server resolves `reviewed_task_id` and stamps `at`. Rows are append-only and hash-chained (`prev_hash` = previous sign-off's `row_hash`; `row_hash` over the canonical row); the WHOLE decision the approver saw — n, point, Wilson interval, false-Q1, oracle strength, apparatus, route + reason code, controls verdict / run / k of N / escapes, the policy and its thresholds, the attestation — is stamped into the row under the hash |
| POST | `/signoffs/{id}/revoke` | approver | `{note?}` → the attestation with `revoked: true`; appends a revocation row (409 `already_revoked`) |

## Reviews (human verdicts on graded rows)

A review is a person's post-hoc verdict on ONE graded row (`crb.core.review.ReviewRecord`), kept forever as governance evidence (`docs/DATA-RETENTION.md`). The `reviews` table is append-only and hash-chained on its own (`prev_hash` = the previous review's `row_hash`; `row_hash` over the canonical record). **The patch-hash anchor:** a review with a verdict carries `patch_sha256_reviewed`, the SHA-256 of the unified diff the reviewer loaded through `GET /grades/{row_hash}/patch`, and the write boundary refuses it unless that hash equals the row's evidence pack `grade.diff.diff_sha256` — a reviewer attests to the exact bytes the instrument graded, never to a description of them. The verdict is DERIVED from the findings by one rule (`derive_verdict`: the most severe finding kind in `regression > defect > api_change > style`, `ok` with none); `not_reviewed` is the reviewer's explicit "I looked and could not review" (no findings, no `mergeable`, no hash).

| Method | Path | Role | Notes |
|---|---|---|---|
| GET | `/reviews?repo&task_id&grade_row_hash&reviewer&verdict` | viewer | page of `{review_id, schema: crb.review.v1, grade_row_hash, repo, task_id, subject, grade_clean, reviewer, verdict, findings: [{kind, note, file, line}], mergeable, statement, patch_sha256_reviewed, evidence_pack_hash, apparatus_version, created, prev_hash, row_hash}` in chain order, served column-by-column (a tampered row stays visible; `/reviews/verify` says so) |
| GET | `/reviews/verify` | viewer | `{rows, ok, chain_ok, broken_at, detail, anchored, unanchored, verified_at}` — never raises: recomputes every `row_hash` from the stored columns and re-checks every verdict's anchor against its row's stored pack (`anchored` / `unanchored`; `not_reviewed` records count neither way). `ok` ⇔ chain intact ∧ `unanchored = 0`. Additive to `/ledger/verify`, which is unchanged |
| GET | `/reviews/stats?repo=[&by=class,size]` | viewer | the STANDING verdict per row (latest review, chain order) joined onto the repo's cells under the same `by` projection as `/capability-map` (`crb.core.review.review_cell_stats`, a pure function over rows + reviews — `CellStats` itself is unchanged): `{repo, by, n_reviews, cells: [{<cell key>, n_rows, n_reviewed, n_review_defects, reviewed_share, n_ok, n_defect, n_regression, n_api_change, n_style, n_not_reviewed, n_mergeable, n_not_mergeable}]}`. `n_reviewed` counts rows whose standing verdict is a real review; `n_review_defects` those whose standing verdict is `defect` or `regression`. 404 unknown repo; 422 bad `by`; 409 `false_q1_refused` when the repo holds a false-Q1 row |
| GET | `/reviews/{review_id}` | viewer | one review as stored; 404 |
| POST | `/reviews` | operator | `{grade_row_hash, statement, findings?: [{kind: regression\|defect\|api_change\|style, note, file?, line?}], mergeable?: bool\|null, patch_sha256, not_reviewed?: bool, verdict?}` → 201 with the record. CSRF as every write. The server resolves the row (404) and its pack, derives the verdict (a client-sent `verdict` must agree — 422 `validation_error`), builds the record (a `regression` finding with `mergeable: true`, a `not_reviewed` with findings / `mergeable` / a hash, a blank statement → 422 `validation_error`), then applies the anchor: **422 `review_refused`** with `detail.code` ∈ `patch_hash_mismatch` (`detail.expected` = the pack's `diff_sha256`, `detail.observed` = what was sent), `patch_hash_missing` (a verdict without a hash), `no_diff_in_pack` (the pack records no diff / no pack stored — only `not_reviewed` is possible). Nothing is written on a refusal; refusals and writes are `system/review.refused` / `system/review.created` events. Statement, notes and file names are redacted. A later review of the same row is a new record — the latest is the standing verdict; nothing is edited or revoked |

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
| GET | `/oracle/{repo}/controls` | viewer | latest `controls.report` event payload (`ControlsReport.to_dict()` + `run_id`, `reported_at`, `verdict`) or **404 `not_measured`**; `verdict` is the routing-reduced view of the same report (`ControlsVerdict.to_dict()` + `state`) that `/capability-map` and `/routes` route under — one source, so the controls screen and the map can never disagree |

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
| GET | `/settings/secrets` | viewer | `{items: [SecretStatus], secrets_dir}` — statuses of the operator-supplied secrets, never values; `secrets_dir` (the on-host path) is `""` unless the caller is an admin |
| PUT | `/settings/secrets/claude-code-token` | admin | body `{token}` (a `claude setup-token` value: `sk-ant-oat01-…`, 40–512 chars, `[A-Za-z0-9_-]`); stores it owner-only under `CRB_SECRETS_DIR` / `$CRB_HOME/secrets`; returns the `SecretStatus`; `422 invalid_token` on shape, `409 secrets_insecure` when the directory is group/world accessible |
| DELETE | `/settings/secrets/claude-code-token` | admin | removes it; returns the (absent) `SecretStatus`; idempotent |
| POST | `/settings/secrets/claude-code-token/verify` | admin | runs one no-tool Haiku turn through the `claude_code` builder's `cli` environment with the stored token; returns a `LoginCheck`; `404` when nothing is stored, `409 secrets_insecure`, `429 rate_limited` (+ `Retry-After`) more than once per 10 s |

`SecretStatus = {name, present, fingerprint, set_at, set_by}` — `fingerprint` is at most the
**last four characters** of the value (empty when absent or shorter than 12 characters);
`set_by` is the admin's display name, empty for an operator-mounted file.
`LoginCheck = {status: ok | invalid | cli_missing | timeout | error, detail, source: explicit |
env | secrets_file | keychain, fingerprint, model, cli_version, duration_s, cost_usd}`;
`detail` is redacted and capped. No response on these routes ever carries a token value
(`tests/test_server_routes_admin_secrets.py`).

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
- `POST /runs` accepts `retain: {worktrees, transcripts}` (both default `false`) — per-run raw retention chosen by the operator at queue time, stored under `params.retain`, served on the run, honoured by the worker (worktrees under its scratch, transcripts under `<home>/transcripts/<run>`). ADR-0006's zero-retention default is unchanged.
- The retained artefacts are REACHABLE from the evidence drill-down (C13): `GET /grades/{row_hash}/patch` / `/transcript` / `/retained` and the `/reviews` family. The UI's readings live in `ui/src/screens/Runs/contract.ts` (types, hooks, a dependency-free SHA-256 and the diff parser) until they are folded into `api/types.ts` / `api/hooks.ts`. The evidence drawer's Patch tab fetches the patch as bytes, hashes them in the browser and compares with the pack's `diff_sha256`; the Review panel sends that hash as `patch_sha256` and stays disabled until the Patch tab was loaded in the session and the hashes agree. The API host must see the worker's `CRB_HOME` (the walkthrough and the compose stack share it); on a split deployment the patch route answers 404 `patch_unavailable` with the reason.
- **The budget is a measured variable, not a fixed cap (C8).** `POST /runs` accepts a run-level
  `budget` and object rungs `{builder, model, provider?, budget?}` in `ladder` (above). The
  worker stamps every ledger row it writes with two hashed labels: `labels.budget_tier` =
  `<max_tool_calls>/<max_turns>/<wall_clock_s>` of the budget the attempt actually ran under
  (`25/25/900` is the builder default; when a token or dollar cap is also engaged the tier
  appends `/tok=<n>` and/or `/usd=<x>`, because attempts that differ only there were not the
  same experiment), and `labels.rung_index` = the 0-based index of the rung in the run's
  ladder (`trial` stays positional, `r1`, `r2` …). The tier is computed by the same
  `budget_for_rung` call the build adapter makes, so the label and the cap cannot disagree;
  the evidence pack's `builder.budget` carries the full budget. The budget is NOT part of the
  cell key — a sweep lands in one cell and is split by `labels.budget_tier` after the fact
  (`/grades` rows carry `labels`; `/runs/{id}/tasks` carries `budget_tier` / `budget_tiers`).
  **Contract: a blind rate quoted without its budget tier is not a claim** — the NHS
  measurement (docs/reviews/2026-09-14-nhs-public-repos.md §3) found 6 of 8 blind misses
  were `budget` at the fixed `25/25/900`; the rate at that tier is a fact about the cap, and
  only a rate stated *at a tier* (or a sweep across tiers) says anything about the model.
- `/repos` items carry `clone_path` (empty for a URL-only registration until the worker's
  first run clones it — W3-B).
- `GET /settings` (admin, W2-A) still returns `Settings.redacted_dict()`; the UI's
  `{builders, sandbox_mode, retention, oidc_enabled, ledger_backend, apparatus_version,
  policy_version}` reading is NOT yet served — see the W2-B report.
- `GET /capability-map`, `GET /routes` and the new `GET /failure-split` (A2, review action #4)
  carry the `failure_kind` split, `model_point` and the repo's `controls` verdict; the UI's
  readings live in `ui/src/screens/Capability/contract.ts` (extended types + hooks) until they
  are folded into `api/types.ts` / `api/hooks.ts`. `GradeRow.to_dict()` now also carries
  `failure_kind` and `cost_known` (derived — not part of the hashed body; new rows pin them
  into the hashed `labels`); `/grades` still serves the stored columns only, so read the split
  from `/failure-split`. Run detail reads `/failure-split?repo=&run_id=` for its split tiles.
