# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/). The **apparatus version**
(`crb.core.version.APPARATUS_VERSION`) is listed separately because a change to it changes
the meaning of a verdict (see [EVIDENCE-AND-CLAIMS §4](docs/EVIDENCE-AND-CLAIMS.md#4-the-apparatus-stamp--evidence-expires)).

## [Unreleased]

Nothing yet — everything on `reboot/v2` up to the rc pin is in 2.0.0a1 below.

## [2.0.0a1] — unreleased — first releasable v2 (dated on the day it is tagged; pinned as `2.0.0a1-rc1`)

### 2026-09-15 — the NHS measurement's instrument findings (DL-020..025)
- **CI green.** Red on every push since 2026-09-13: labeller tests needed a real `claude` on
  PATH; git 2.5x renders a UTC `%aI` as `Z` (`GitRepo.author_date` normalises to `+00:00`);
  `grades.trial` is `VARCHAR(16)`, which PostgreSQL enforces and SQLite does not
  (`GradeRow` now refuses a longer label on every dialect; the store suite verified on
  postgres:16); a non-existent `hadolint@v3` pin; artifact uploads made non-fatal.
- **JavaScript dependency eras** (ADR-0011 amendment c): a task commit whose lockfile differs
  from HEAD's gets its own `node_modules`, installed once per lockfile hash; a failed install
  is a harness row; installs refuse below 2 GiB free, at most 8 eras per repo (LRU).
- **Support files under the test layout** (`tests/helpers.py`, `tests/mock_server.py`) are
  overlaid, never targets; a candidate with only support files is skipped. `kind: mine` +
  `task_ids` re-qualifies known commits under their stored pool.
- **One oracle measurement**: the capability map routes every cell under the repo's
  task-level mutation scores — the same number the sign-off evidences — so the two can never
  disagree (`oracle_strength_mean` is the strength the cell was routed under).
- **The builder gets the grader's services** (DL-024): a sighted build brings the task's era
  services up first and exports their environment in the test command.
- **`outage` failure kind**: a provider refusal (usage limit / 429 / dead credential) is
  outside `n`, never `harness`; label runs with only outage labels fail instead of succeeding.
- Error strings are capped head-first so a long docker refusal keeps its
  `protocol violation:` kind; one candidate's harness error skips it in a mine run (three in a
  row stop the run); a non-build run's own counters are served as `counts.detail`.
- Capability map: `mode` (default sighted) and `apparatus` (default current) filters; the
  sign-off measures sighted rows of the current apparatus only.
- **Licence**: BSL 1.1 adopted (DL-015/DL-025); `LICENSE` is a reservation of rights until
  the text lands; the image label is `NOASSERTION`; `docs/LICENSING.md`.

### Evidence caveat for this release
Every ledger row to date was measured on the **host executor posture** (`executor: local`)
— including the rows graded after the independent review's finding 1 (the builder
controlled the grader's git view) was closed in code. The sealed-container posture
(ADR-0012) is built and tested; no measurement has yet been taken on it. Numbers in this
release license statements about the instrument, not demonstrations (EVIDENCE-AND-CLAIMS §7).



### Independent AI review pass (2026-09-14) — findings 1, 2, 4, 5, 6, 7, 8 closed
Every finding of `docs/reviews/signoffs/2026-09-14-fable-ai-pass.md` was reproduced with its
recorded command before it was fixed, and each reproduction is now a regression test. Finding 3
(`oracle_unmeasured`) is the sign-off policy v2 entry below.
- **The grader's view is independent of the builder's git (finding 1, blocks demo).**
  `Workspace.touched_files` enumerates from the filesystem against the parent tree
  (`ls-tree -r <parent>` object ids vs a fresh blob hash of every file); the index, `HEAD`,
  `info/exclude` and `core.excludesFile` are never consulted, and the only ignore rules
  honoured for an untracked path are patterns present in a `.gitignore` tracked at the
  parent. `Workspace.enforce_integrity` is the grader's pre-flight: `HEAD == parent`, the
  gitdir is the harness clone's, no skip-worktree / assume-unchanged bits, and the shared
  `info/exclude` (the *main clone's*, for a linked worktree) holds only what the harness
  recorded at create time — foreign lines are removed and reported. `grade()` disqualifies
  on any violation (`dq_reason: worktree integrity: …`, event `grade.tamper kind=worktree`)
  on the CLI and `run_task` paths alike; `diff_stats` diffs against the parent by sha. The
  three reproductions (`info/exclude`, a commit inside the worktree, `--skip-worktree`)
  each graded `clean` on `842875b` and DQ now; a forged index entry, a self-hiding
  `.gitignore` and symlink type changes are covered too.
- **Lint configuration is test infrastructure (finding 2; ADR-0011 amendment).**
  `ruff.toml`/`.ruff.toml`/`.flake8`/`.pre-commit-config.yaml`, `.eslintrc*`/
  `eslint.config.*`/`.eslintignore`/`.prettierrc*`/`prettier.config.*`/`.prettierignore`/
  `.editorconfig` (JS only — prettier reads it), `.golangci.*`, `rustfmt.toml`/`clippy.toml`
  (+ dotted forms), `*checkstyle*.xml`; section-aware `pyproject.toml [tool.ruff*]`,
  `setup.cfg`/`tox.ini` `[flake8]`, `package.json` `eslintConfig`/`prettier`/`scripts.lint`,
  `Cargo.toml [lints]`. Touching any disqualifies under belt 1b before a test runs
  (`[tool.ruff.lint] select = []` and a nested `pkg/ruff.toml` had turned a
  `repo_lint_clean=False` row `CLEAN`).
- **`belt_set` must agree with the apparatus (finding 4).** `GradeRow` refuses
  (`LedgerIntegrityError`, at construction — so at write and on read) any belt set its
  `apparatus_version` could not have recorded: `v3-legacy` (and a `1.0-census` `v4`) only for
  `imported:` census rows, `2.0`–`2.1` ⇒ `v4`, `2.2+` ⇒ `v5`; a `v3-legacy` row records no
  `source_changed`. `expected_belt_sets` is the one rule.
- **A review is anchored to the reviewed row's pack (finding 5).** `DbReviewLedger.append`
  resolves the row by `grade_row_hash` (`row_not_found` otherwise) and the pack by the
  row's hash, never the record's field (`pack_hash_mismatch`); a caller's pack is only
  accepted as a self-certifying copy of the row's. `JsonlReviewLedger.append` requires the
  pack for a verdict (`pack_required`). `check_review_anchor` is the one rule both apply.
- **Guard (findings 6/7).** Redirection targets (`>` `>>` `<` …), `dd of=` and
  tee/cp/mv/install/ln targets that resolve into `.git` — through a symlink when the cwd is
  known — are refused; `TestFileGuard` classifies by what a path resolves to (`gitlink ->
  .git`, `t2 -> tests`); a quoted or escaped paren is text, not a stray sub-shell token
  (`grep '('`, `find … \( … \)`). Corpus: 456 honest / 461 refused lines.
- **Guide (finding 8).** `docs/reviews/human-review-guide.md` re-baselined: twelve files to
  read (adds `core/workspace.py`, `core/test_infra.py`, `core/lint.py`,
  `builders/container.py`, `core/review.py`, `core/signoff.py`), ten triggers, exercises 3b
  and 4 now DQ, new exercises 4b/4c/6b/6c, exercise 5's four bypasses refused and the live
  gaps named; the sign-off template's tables grow to match.

### Sign-off policy v2 — an unmeasured oracle is a refusal (`signoff-policy.v2`)
- **`oracle_unmeasured`** (`crb.core.signoff`): a cell none of whose tasks carries a
  task-level mutation score cannot be signed off — "≥ `min_oracle_strength` when
  measured" became "measured AND ≥". Non-overridable like `false_q1` and
  `attestation_missing`: there is no `CRB_SIGNOFF__*` knob (`REQUIRE_ORACLE_MEASURED`
  may only be `true`; anything else is **503 signoff_policy_invalid**), because signing an
  unmeasured oracle is exactly the "a green suite proves correctness" claim
  EVIDENCE-AND-CLAIMS §7 forbids. Decided 2026-09-14 by the independent decider
  (`signoff-policy: adjust`, DL-016) from the NHS reading: oracle 0.36 with 2 of 6 tasks
  scoreable, 4 of 10 clean rows failing their own repo's `tsc`.
- The server measures the cell's oracle from the repo's `oracle.score` events (the latest
  per task, the same reduction `/oracle/{repo}` serves, averaged over the cell's scored
  tasks — `cell_oracle_strength`); the preview and the 409 detail carry
  `evidence.oracle: {strength, scored, tasks}`; the refusal lists `observed: null` (never
  0). The measurement feeds the two oracle clauses and the stamped
  `oracle_strength_at_signoff`, never the route (the route stays the capability map's).
- `policy_version` → `signoff-policy.v2`; `policy_thresholds` gains
  `require_oracle_measured: true`. Records signed under v1 keep their stamp and verify.
- UI: the Sign-off gate row reads "Oracle strength measured and ≥ 0.80"; the tile says
  how many of the cell's tasks are scored; the clause renders as non-overridable.
- Walkthrough 08 seeds the signable cell with an `oracle` run as well.

### Belt 5 runs `tsc` where the repository's CI does (ADR-0011 amendment)
- `crb.core.lint.tsc_evidence` / `js_plan`: a JavaScript / TypeScript repository whose
  `package.json` `scripts["lint:types"]` (or another script, or its CI) runs `tsc` and
  that carries `tsconfig.json` + `node_modules/.bin/tsc` gets a `tsc` step appended to
  its belt-5 plan — the script verbatim + `--pretty false` (nhsuk-frontend and
  nhsuk-react-components: `tsc --build tsconfig.json --pretty`). `[measured 2026-09-14]`
  4 of 10 clean NHS rows failed the repositories' own type check; belt 5 never ran it.
- Whole-project, attributed per file: `LintTool.findings_re` (`TSC_FINDINGS_RE`) makes
  the rejection count only findings in CHANGED files (`LintStep.findings_changed` /
  `findings_other`, in the pack); errors only in unchanged files are the maintainers'
  debt — belt `True` with the counts on the run's note; a rejection naming no file is a
  harness error, never a pass. `RepoConfig.lint.findings_re` declares the same for any
  other whole-project tool. `lint_run.detected` records `…+tsc:lint:types`.
- Guard corpus: the 19 refusal groups of the NHS + public measurement pinned with the
  independent decider's verdicts (9 honest / 10 refused, provenance per line); `npx
  standard` on koa is honest — the pre-fill's "not in node_modules/.bin" came from a
  cwd-less check.


Apparatus version **2.2** (2.0 → 2.1 in Wave A, 2.1 → 2.2 in Wave B; the sections below
say what each bump changed about the meaning of a verdict). Everything on `reboot/v2`
since the reboot commit, grouped by wave and area. `pyproject.toml`,
`crb.core.version.__version__` and the chart's `appVersion` are `2.0.0a1`; the release
workflow refuses a `v*` tag that does not match `pyproject.toml`.

### Follow-ups (Wave C17)
- **The gold must pass belt 5 too** (ADR-0011's named residual): `crb.core.mine.gold_check`
  runs the same lint plan `grade()` would on the overlaid gold's source files; a gold the
  repository's own linter rejects (or that times out) is `gold_clean=False` with
  `gold_note="gold fails belt 5 (<detected>): …"` — the maintainers' lint debt is excluded
  from the denominator, never counted against the builder. A linter that cannot run is a
  harness error (never a pass); no linter leaves belt 5 not evaluated. The `mine.gold`
  event carries `lint` (`true`/`false`/`null`).
- **`crb learn strengthen` derives the route's items from the server's exports.** A ledger
  export is the rows alone; the per-task oracle scores are `oracle.score` events and the
  cell's held-ness is the controls verdict. `--oracle` now takes `GET /oracle/{repo}` JSON,
  a run's `events/log` page/JSONL (score actions only), a `to_report()` JSON or a bare
  list; new `--controls` takes `GET /oracle/{repo}/controls` (or a `controls` run body).
  With both, the CLI's items and ids equal the route's; `/learn/strengthen` stamps the
  repo on every score so they can.
- **`GET /api/v1/health/live`** — liveness: the process is up and its database answers
  (one probe; never the sandbox). `/health` stays the deep probe and is role-aware:
  `CRB_ROLE=api` (`api` | `worker` | `all`, default `all`) reports the sandbox `skipped`
  instead of failing the API for a docker socket it is not meant to have. The image
  `HEALTHCHECK` and the Helm startup/liveness probes hit `/health/live`; readiness stays
  on `/health`; the chart sets `CRB_ROLE` per container.
- **CI**: the `types` and `test` jobs install `.[server,postgres,dev]` (mypy under `.[dev]`
  alone reported 95 `import-not-found`, 277 errors with the cascades).
- **Version** `2.0.0a0 → 2.0.0a1` in `pyproject.toml`, `crb.core.version.__version__`
  (`APPARATUS_VERSION` stays `2.2`) and `deploy/helm/crb/Chart.yaml` `appVersion`.

### Sign-off is a policy decision, refused at write (`signoff-policy.v1`, Wave B7, DL-014)
- `crb.core.signoff.SignoffPolicy` (defaults: `n_min = 10`, route must be `deliver`, controls
  gate passed with `max_controls_escapes = 0` and `min_constructible_share = 0.5`,
  `min_oracle_strength = 0.80` when measured, attestation mandatory) and
  `evaluate_signoff` / `check_signable`: refusal codes `false_q1` (first, non-overridable),
  `thin_cell`, `controls_unmeasured|failed|escapes|thin`, `oracle_weak`,
  `route_not_deliver:<reason_code>`, `attestation_missing` (non-overridable), each naming the
  number that failed and the threshold it missed. Operator-adjustable within published bounds
  via `CRB_SIGNOFF__*`; a value outside them makes the sign-off routes answer
  `503 signoff_policy_invalid`.
- `SignoffRecord` schema `crb.signoff.v2`: `ci_low_at_signoff`, `oracle_strength_at_signoff`,
  `policy_version` + `policy_thresholds`, `route_at_signoff` + `route_reason_code`,
  `controls_verdict|run_id|k|total|escapes`, `attestation {reviewed_task_id,
  reviewed_row_hash, statement, at}` — all hashed into the chain; `v1` records still verify
  (schema-aware body) and load with defaults.
- API: `POST /signoffs` takes `attestation {reviewed_row_hash, statement}` (the row must be an
  accepted row of the cell — else 422), routes the cell under the repo's latest controls
  verdict (the same helper as `/capability-map`) and answers `409 signoff_refused` with
  `detail.{code, thresholds, observed, refusals[]}`; `GET /signoffs/preview` (the bar before
  the approver tries, plus the cell's accepted rows), `GET /signoffs/policy`,
  `GET /signoffs/{id}`.
- UI: the Sign-off screen shows n / point / Wilson-low / false-Q1 / oracle strength / the
  controls verdict (k of N, escapes, run, date) / route + reason, every refusal with observed
  vs threshold, an accepted-row picker with the "I have read this accepted diff" affirmation
  and statement; the button stays disabled while the preview refuses. Walkthrough `08-signoff`
  proves the refusal on the live fixture (whose `hardcode_cheat` control really escapes) and a
  real sign-off on an API-seeded repo whose tests are parametrised.

### Apparatus 2.1 → 2.2 — belt 5 `repo_lint_clean` (ADR-0011, Wave B5)
- **Grader**: after belt 4, the repository's OWN formatter/linter runs on the changed
  non-test files (`crb.core.lint`): declared by `RepoConfig.lint` or detected from the
  repo's configuration — `gofmt -l` (Go), `ruff check` (+ `ruff format --check`) (Python),
  `eslint` / `prettier --check` / `standard` (JS), `spotless:check` / `checkstyle:check`
  (Maven), `cargo fmt --check` / `clippy` (Rust). No linter ⇒ belt `None` (not evaluated:
  neither a pass nor a fail). Rejected or timed out ⇒ `False`, never clean. A linter that
  cannot run ⇒ harness error. `GradeResult.lint_run` records the tool, files and redacted
  tail; `grade.belt` events carry `belt="repo_lint_clean"` + `detected`.
- **Ledger**: `GradeRow.repo_lint_clean`; `belt_set="v5"` for new rows; `v4` / `v3-legacy`
  rows never carry belt 5 and hash byte-for-byte as before (ADR-0002 rule 2 amended: the
  body excludes an unrecorded optional belt). New failure kind `lint` (belts 1–4 held,
  belt 5 rejected); `FailureSplit.lint` / `lint_evaluated`; `CellStats.n_lint` /
  `n_lint_evaluated`; `model_n` includes `lint`.
- **Store**: revision `0002` adds `grades.repo_lint_clean` (nullable, in place);
  revision-aware adoption of unversioned `init_db` databases (`REVISION_MARKERS`).
- **API/UI**: `repo_lint_clean` on grade rows and belts, `belt_set` on run task rows,
  `lint` / `lint_evaluated` on every split; five belt pills under `v5`, four otherwise;
  "Lint run (belt 5)" in the evidence drawer.

### Wave A and the reboot → first-releasable work (2026-09-13)

Apparatus version **2.0** at the time these entries were written (Wave A bumped it to
2.1 — belt 1 covers test infrastructure, routing gated on the controls verdict,
intent-resolved change class, polyglot controls.v2; see `crb.core.version`). 76 commits,
grouped by area.

### Release engineering
- `release.yml` now publishes the container image on a `v*` tag: build `deploy/Dockerfile`
  (UI + package), smoke it (uid 10001, read-only root, `migrate upgrade`, UI present), syft
  SPDX SBOM, then push `ghcr.io/jita81/commit-replay-bench:<version>` and `:sha-<short>`
  with SLSA provenance — only for a tag of the canonical repository. A separate `sign` job
  signs the digest with cosign **keyless** (GitHub OIDC) and attaches the SBOM as an in-toto
  attestation; it is skipped on forks and dry runs. `workflow_dispatch` is a no-push dry run.
- `deploy/verify-image.sh`: operator verification (signature + SBOM attestation + optional
  digest pin) with a `--print` mode; `tests/test_release_verify_image.py` holds the script,
  the workflow and the Helm values to one repository / issuer / signing identity.
- CI `container` job: hadolint; explicit tmpfs ownership in the image smoke (newer daemons
  make `--tmpfs` inherit `root:0750`, which uid 10001 cannot write); asserts the UI is in the
  image. `docs/DEPLOYMENT.md §2.2` and `deploy/README.md §1.1`: image name, tags, how to
  verify, and the compose path with the released image instead of a local build.
- `docs/REPRODUCING-THE-CENSUS.md`: a reviewer's step-by-step to re-derive the census
  ledger invariants (manifest, import, chain, false-Q1 = 0, routing) with real output.

### Core (`crb.core`, stdlib-only)
- Census / legacy import (`crb.core.legacy`): 1,071 verdicts as `GradeRow`s with imported
  evidence packs, `belt_set = v3-legacy` for the 706 three-belt rows; Athena aggregates as
  reference-only `AggregateRow`s (never in the grade ledger).
- Capability map, forecast / readiness, sign-off ledger (409 on false-Q1), federated
  abstract export (cells only, no ids, no code).
- Oracle-adequacy programme (`crb.core.oracle`): mutation strength, adequacy gate, negative
  controls, sealed corpus; text-level mutators for Go / JavaScript / JVM / Rust with
  uncompilable mutants excluded (ADR-0009).
- Runners: environment-setup phase (the one network-permitted step) for venv/pip, npm, go,
  mvn, cargo; jest/vitest `--` path handling and suite-load attribution; snapshot files map
  to their owning test; `|`-separated extension / test-suffix alternatives; `runner_opts.env`
  and `extra_args`. `LocalExecutor` closes stdin (tests waiting on input fail at EOF); cancel
  tokens kill the running process / container.
- Run orchestrator: prep → build (escalation ladder) → grade → evidence pack → ledger, per
  attempt; one `GradeResult → GradeRow` mapping shared by CLI and worker.
- Forward-mode factory core: frozen backlog, DoR gate, RED proof, build under belts,
  never-to-default delivery, verdict-before-edit review, evidence ledger.

### Builders
- Adapter contract, budgets and guards; `editblock`, OpenAI-compatible tool loop (Azure
  OpenAI / Cerebras / local), Claude Code CLI with `api_key` and `cli` auth modes (Sonnet 5
  default; `CLAUDE_CODE_OAUTH_TOKEN` forwarded in `cli` mode); `fixture_gold` test builder.
- Archaeology guard: command substitutions are checked recursively, quoted parentheses are
  not sub-shells (both false positives found on live koa / click runs); the sighted test
  command carries the runner env and the rules state the environment is provisioned.
- Token accounting: `tokens_in` is the whole prompt (cache creation + reads included).

### Server, store, worker
- FastAPI core: settings, auth (local + OIDC), RBAC, CSRF, health / metrics / version, error
  envelope; domain routes (repos, runs + SSE, grades / evidence, capability, routes,
  forecast, sign-offs, ledger verify / export / import, oracle, factory stubs); the built UI
  served at `/` with deep-link fallback.
- SQLAlchemy models with append-only triggers (SQLite and PostgreSQL), `DbLedger` with the
  hash chain, Alembic migrations, store suite on both dialects.
- DB job queue, run executors (probe / setup / mine / replay / blind / oracle / controls),
  DB event sink; a run whose every attempt errored on infrastructure is `failed`, never
  `succeeded`.
- **Per-run raw retention** (`POST /runs` `retain: {worktrees, transcripts}`): the operator
  may keep attempt worktrees and builder transcripts for human re-examination of a clean
  grade; the ADR-0006 default (keep nothing) is unchanged.

### UI and walkthrough
- Vite / React observability front end (Ledger v2 tokens, 16 screens, SSE live log,
  evidence drawer, repo / run dialogs with presets and editors); unit tests + axe smoke.
- Full-browser walkthrough against a live temp stack (`scripts/walkthrough.sh`, 25
  Playwright specs; hermetic tier 1 in CI).

### Deployment
- `deploy/Dockerfile` (multi-stage, non-root, read-only-root compatible, docker client
  only), `docker-compose.yml` (hardened single host), Helm chart `deploy/helm/crb` (default
  deny NetworkPolicy, dind / hostSocket sandbox modes, external or embedded PostgreSQL),
  `docs/DEPLOYMENT.md`, `docs/SECURITY.md`, `docs/DATA-RETENTION.md`, Postgres + container
  + walkthrough CI jobs.

### Evidence and reviews
- Vendored census evidence `data/census-2026-07-08/` (1,071 grades, 25 task sets, 24
  configs, sha256 manifest) with the CI gate `tests/test_census_gate.py` (false-Q1 = 0
  re-derived on every PR).
- `docs/reviews/2026-09-13-critical-friend.md`: the critical-friend review of AI output
  quality and process governance — the floor held (false-Q1 = 0 on every live row), 13 of 15
  non-clean live rows were harness-caused, none of three "clean" cobra patches was
  mergeable as-is, the class axis is degenerate on library repos, and `env_poison` escapes
  belt 1 on click. Its §8 actions are the Wave A / B backlog.

### Documentation
- README, `docs/ARCHITECTURE.md` (arc42-lite, C4 mermaid, sequence diagrams, data model),
  `docs/EVIDENCE-AND-CLAIMS.md`, `docs/CONTRIBUTING.md`, `docs/OPERATOR.md`, `docs/API.md`
  (HTTP contract v1), `docs/DECISION-LOG.md`, ADR index and ADR-0001…0009.
- CI: lint, types, layers, test matrix (3.12 / 3.13, coverage ≥ 70%), security (gitleaks +
  pip-audit), SBOM (CycloneDX); Dependabot for pip and GitHub Actions; `.gitleaks.toml`
  with the `tests/` fixture allowlist.
- `crb.observability`: `StepEvent` envelope, sinks, Prometheus metrics with no-op fallback,
  JSON logging with redaction, health probes.

### Changed
- `pyproject.toml` import-linter contract: `include_external_packages = true`; not-yet-existing
  layers are optional (parenthesised) until their packages land; `cli` sits above `server`.

## [2.0.0a0] — 2026-09-13 — reboot

Apparatus version **2.0**.

### Added
- Package `crb` with a **standard-library-only** core (`crb.core`): `spec` (languages, one
  size table, deterministic change classes, `RepoConfig`, `TaskSpec`), `git`, `execution`
  (`LocalExecutor`, fail-closed `DockerExecutor`), `runners` (pytest, go, node, vitest,
  jest, mocha, maven, cargo), `workspace`, `mine` (RED / baseline / gold), `grade` (**four
  belts**, `FalseQ1Violation` at construction), `evidence` (`EvidencePack`,
  `ApparatusStamp`, `BuilderRef`), `ledger` (`GradeRow` with write-time invariants,
  hash-chained `JsonlLedger`, `verify_chain`, `CellKey`, `cell_stats`), `stats` (Wilson),
  `routing` (the one published rule, `routing.v1`), `redact`, `version`.
- `pyproject.toml` (Python ≥ 3.12; ruff, mypy strict, import-linter, pytest-cov configuration;
  optional extras `openai`, `claude`, `server`, `postgres`, `dev`, `all`).

### Changed
- **Breaking (apparatus):** verdicts are four belts + `clean`, not the v1 three-bucket
  `ai_can / needs_human / fails`; `source_changed` is a new belt. Rows graded under the
  three-belt census apparatus are imported as `belt_set = v3-legacy` and reported separately.
- **Breaking:** false-Q1 is enforced at **write** time (previously read time upstream);
  a clean row requires an evidence-pack hash.
- Package renamed `commit_replay_bench` → `crb`; CLI `commit-replay` → `crb`.

### Removed
- The v1 (June 2026) implementation (`src/commit_replay_bench/*`, SEARCH/REPLACE-only
  generator, host-only pytest harness). Its last commit is tagged `v1.0.0-legacy`.

[Unreleased]: https://github.com/Jita81/commit-replay-bench/compare/2.0.0a1-rc1...reboot/v2
[2.0.0a1]: https://github.com/Jita81/commit-replay-bench/compare/v1.0.0-legacy...2.0.0a1-rc1
[2.0.0a0]: https://github.com/Jita81/commit-replay-bench/compare/v1.0.0-legacy...v2.0.0a0
