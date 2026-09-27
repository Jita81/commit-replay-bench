<!--
Navigation
----------
What it is:   The external assessment of 25 September 2026 — gap-closure instructions for
              agents, groups A to F — vendored verbatim so the criteria that cite it resolve.
What it does: Records what an outside reviewer found on `main` at `8ab88ad` (2.0.0a1, apparatus
              2.2): evidence integrity (A1–A6), leakage and posture (B1–B5), forward mode
              (C1–C8), security (D1–D5), engineering hygiene (E1–E4), and §F, the order of work
              and the five conditions under which the product is trustworthy for its purpose.
How:          The operator supplied the document on 25 September 2026; it is copied below
              byte for byte after this header and the note under it. Nothing in it is edited:
              where the tree has moved on, the definition of done says so, not this file.
Layer:        docs — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0013-external-review-is-advisory-and-recorded.md (an outside review is
              advisory and recorded); ADR-0021, ADR-0022 and ADR-0023 answer C1–C3, C6 and B2
Works with:   docs/dod/product.md (criteria 201 to 205 are its §F, one condition each),
              docs/PREVENTION.md (P-053 to P-058 register its B5 and A5(c) defects),
              docs/dod/streams/measure.md (its A3 criterion), docs/dod/journeys/prove-the-instrument.md
              (its A6 criterion), docs/dod/streams/manufacture-and-deliver.md (its C4 criterion),
              docs/dod/PLAN.md (the waves that close what it found)
Tested by:    not applicable — a review record; scripts/dod_check.py resolves the criteria that
              cite it, and scripts/claims_check.py reads it for an Actions table (it has none)
Touch when:   never to change its words; a finding it records is closed in the artefact that
              names it, with the evidence there.
-->

> **What this is.** An external assessment of Commit Replay Bench, supplied by the operator on
> 25 September 2026 and vendored here verbatim: everything below this note is the document as
> it was supplied. The criteria `product.claims.201` to `product.evidence.205` cite its §F.
> Its findings describe `main` at `8ab88ad`; what has closed since is recorded in
> `docs/dod/` and `docs/PREVENTION.md`, not here.

# Commit Replay Bench — gap-closure instructions for agents

Assessment date 2026-09-25, `main` at `8ab88ad` (2.0.0a1, apparatus 2.2, belt set v5).
Audience: a coding agent (Claude Code or equivalent) working in a clone of
`Jita81/commit-replay-bench`. Each work item below is written to be picked up on its own.

## 0. How to work in this repository

Read these before touching anything, in this order: `docs/CONTRIBUTING.md`,
`docs/EVIDENCE-AND-CLAIMS.md`, `docs/adr/README.md`, `docs/FILE-HEADER-STANDARD.md`,
`docs/dod/STANDARD.md`.

Rules that apply to every item:

1. **Never weaken a gate** (`docs/CONTRIBUTING.md` §"The never weaken a gate rule"). No
   lowered coverage, no `noqa`, no `type: ignore`, no `xfail` without an issue, no relaxed
   invariant in `crb.core`, no less-strict `RoutingPolicy` threshold.
2. **Verdict semantics need an ADR and an apparatus bump.** Anything that changes what a
   belt, a cell, a route or a threshold means: new ADR under `docs/adr/` (next number,
   supersede rather than edit), bump `crb.core.version.APPARATUS_VERSION`, bump the policy
   constant it touches (`routing.POLICY_VERSION`, `routing.CONTROLS_POLICY_VERSION`, the
   sign-off policy version). Rows from different apparatus versions are never pooled.
3. **One PR per file-disjoint workstream.** Conventional Commits, imperative subject
   ≤ 72 chars, body says why. Branch `feat/<area>-<topic>` or `fix/<area>-<topic>` **[hypothesis — recorded at the time; not re-checked since]**.
4. **Every source file carries the Navigation header**; `python scripts/code_map.py --check`
   must pass. Update `docs/CODE-MAP.md` when files are added.
5. **Definition of done travels with the change.** When an item closes a gap listed in
   `docs/dod/GAP-ANALYSIS.md`, flip the criterion to `met` with resolvable evidence in the
   same PR and regenerate with `python scripts/dod_check.py`.
6. **Quantified sentences on `README.md` and `docs/RELEASING.md` carry a claims tag**
   (`[measured]` with n, method, apparatus; or `[hypothesis]`, `[aspiration]`, `[gap]`).
   `python scripts/claims_check.py --check` must pass.
7. **Run the local gates before pushing:**
   ```
   uv venv .venv --python 3.12 && uv pip install -e '.[server,postgres,mcp,dev]' --python .venv/bin/python
   .venv/bin/ruff check src tests && .venv/bin/ruff format --check src tests
   .venv/bin/mypy
   .venv/bin/lint-imports
   .venv/bin/pytest -q -m "not sandbox_images"
   python scripts/code_map.py --check && python scripts/dod_check.py --check && python scripts/claims_check.py --check
   cd ui && npm ci --legacy-peer-deps && npm run typecheck && npx vitest run
   ```
8. **Do not fix a finding by editing the test that exposes it.** Write the failing test
   first, then the change.
9. **Nothing here is a licence to publish numbers.** A measurement item ends with ledger
   rows committed and a `[measured]` sentence, or with a `[gap]` sentence, never with prose.

## 1. Baseline the assessment verified

| Gate on a fresh clone | Result |
|---|---|
| `ruff check`, `ruff format --check` | pass |
| `lint-imports` (stdlib core, downward layers) | pass |
| `mypy --strict` | **fail**, 8 `var-annotated` errors under mypy 2.3.1 |
| `pytest -m "not sandbox_images"` (no docker, root uid, 26 min) | 4044 tests: 4027 pass, 17 fail, 94 skip; coverage 93 % (gate 70) |
| `ui`: `tsc -b`, `vitest run` | pass, 537 tests |
| `crb doctor` | boots; fails closed without docker, secret key, database |

All 17 failures are the environment, not the product, and all would pass on the CI runner
(non-root, docker present, network): 12 are the root-uid cascade (`BuilderContainerSettings`
refuses `user='0:0'` in `tests/test_builders_container.py` and, through the
`sealed_unconfirmed` fixture, the four reaper tests in `tests/test_worker.py`); one is
`tests/test_cli_doctor.py` expecting `overall: warn` while the sandbox line reads `fail`
without a daemon; four are `@pytest.mark.network` installs (`uv pip install`, `npm install`)
that the proxy here refused or timed out. The suite is therefore not hermetic to uid 0 or
to an absent daemon; E2 below covers that **[hypothesis — recorded at the time; not re-checked since]**.

The rest of this document is the work, grouped A to F. Within a group the order is the
recommended order. Each item names the evidence, the change, and what proves it done.

---

## A. Evidence integrity: make the code's `deliver` bar equal the README's bar

These change verdict semantics. Each needs an ADR, an apparatus bump, and a policy
version bump. Do A1 to A3 in one ADR ("routing.v2") if they land together.

### A1. Gate routing and sign-off on distinct tasks, not attempts

- **Problem.** `CellStats.n = len(eligible)` (`src/crb/core/ledger.py:1060`). Ladder rungs
  and repeated runs of one task each add a row. `n_tasks` exists (`ledger.py:1191`) but
  neither `route()` (`src/crb/core/routing.py:437-539`) nor `SignoffPolicy.n_min`
  (`src/crb/core/signoff.py:394`) reads it. One task run ten times clears n ≥ 10, and the
  Wilson interval treats clustered attempts as independent **[hypothesis — recorded at the time; not re-checked since]**.
- **Change.** Add `min_tasks` to `RoutingPolicy` and `SignoffPolicy` (default 10). In
  `route()`, before the n clause, refuse `deliver` with a new reason code
  `REASON_TASKS_BELOW_MIN` when `stats.n_tasks < policy.min_tasks`. Do the same in
  `signoff.py` with a `thin_tasks` refusal clause. Report the interval on the per-task
  success rate (one row per task: clean if any eligible attempt was clean, or the first
  attempt only; pick one, state it in the ADR) alongside the per-attempt interval, and
  route on the per-task one.
- **Acceptance.** `tests/test_routing.py`: a cell of 12 rows over 3 tasks routes
  `calibrate` with `REASON_TASKS_BELOW_MIN`; 12 rows over 10 tasks passes that clause.
  `tests/test_signoff.py`: same for sign-off. `README.md` "Not a licence to deploy"
  sentence and the routing help text name the task minimum. The capability map and
  `ui/src/screens/Capability` show `n_tasks` next to `n` with the reason code **[hypothesis — recorded at the time; not re-checked since]**.

### A2. Refuse `deliver` when oracle strength or controls are unmeasured

- **Problem.** `routing.py:470` is `if strength is not None and strength < …`, so a cell
  with no mutation score can route `deliver`. Controls clauses are skipped when
  `controls=None` (`routing.py:451, 477, 508, 516`). `task_oracle_strength` returns
  `None` when unmeasured (`src/crb/core/capability.py:382-394`). The README says the
  bar is "oracle ≥ 0.80, controls passed".
- **Change.** `strength is None` routes `calibrate` with `REASON_ORACLE_UNMEASURED`;
  `controls is None` routes `calibrate` with `REASON_CONTROLS_UNMEASURED`. Keep the
  existing weak and escape clauses. `crb route` prints which measurement is missing and
  the command that produces it.
- **Acceptance.** `tests/test_routing.py` cases for both `None` paths. The CLI test
  `tests/test_cli.py` shows `crb route` over a ledger with no controls never prints
  `deliver`. The map's reason code renders in `ui/src/screens/Capability/ReasonCode.tsx`
  with a hint entry.

### A3. Distinguish "no linter" from "linter disabled" in belt 5

- **Problem.** `lint_plan` returns `None` for both `lint: {disabled: true}` and
  "no linter detected" (`src/crb/core/runners/base.py:641-646`). Both write
  `repo_lint_clean=None`; the ledger cannot tell an operator's opt-out from an absent
  toolchain. README says belt 5 is "never a silent pass".
- **Change.** Record why belt 5 was not evaluated. Add a `lint_status` field to the
  evidence pack and a `lint_reason` label on the `GradeRow` with values
  `evaluated | none_detected | disabled_by_config | error`. `disabled_by_config` rows are
  excluded from any cell that routes `deliver` (treat as `calibrate` with
  `REASON_LINT_DISABLED`), because the operator switched a belt off.
- **Acceptance.** `tests/test_lint.py` and `tests/test_grade.py` pin all four values.
  `tests/test_routing.py` shows a cell with a disabled-lint row cannot route `deliver`.
  The Ledger and Task detail screens show the reason **[hypothesis — recorded at the time; not re-checked since]**.

### A4. Commit the ledger rows behind every `[measured]` sentence

- **Problem.** The README's NHS and cobra numbers cite rows that are not in the
  repository; only `data/census-2026-07-08` is vendored. `[measured]` promises rows that
  "can be re-derived" and "where the rows are".
- **Change.** Export the ledger rows for each measured claim with
  `crb ledger export` (JSONL plus the evidence-pack manifest, redacted per
  `docs/DATA-RETENTION.md`) into `data/<campaign>-<date>/` with a sha256 manifest, the way
  the census is vendored. Add a `tests/test_measured_claims.py` that walks the
  `[measured]` sentences the claims checker finds and asserts each names a data path that
  exists and verifies (`verify_chain` passes, `false_q1 == 0`). Extend
  `scripts/claims_check.py` to require a `rows:` locator in every `[measured]` tag on
  README.
- **Acceptance.** `crb ledger verify --path data/<campaign>` exits 0 in CI for every
  vendored campaign. A `[measured]` sentence without a resolvable `rows:` fails the
  `claims` job.

### A5. Ledger verification binds packs and detects truncation

- **Problem.** `crb ledger verify` over JSONL never opens a pack, it only checks the pack
  hash is non-empty (`src/crb/cli/commands/ledger.py:313-317`); `JsonlLedger.append` does
  not check the pack exists (`ledger.py:809-820`). The store path does re-hash packs
  (`src/crb/store/ledger.py:290-308`). Tail truncation is undetectable and acknowledged
  (`tests/test_ledger.py:472-481`). `assert_append_only` probes only `grades` and treats
  any exception as "trigger fired" (`store/ledger.py:354-370`).
- **Change.** (a) `JsonlLedger.append` refuses a clean row whose pack is absent or whose
  hash mismatches; `verify` re-hashes packs when a pack dir is given. (b) Add a signed
  anchor: on every `append` batch and on worker heartbeat, write the tail `row_hash`,
  row count and timestamp as an HMAC under `CRB_SECRET_KEY` to `<CRB_HOME>/ledger.anchor`
  and to the `events` table; `verify` compares. (c) `assert_append_only` probes every
  table in `APPEND_ONLY_TABLES` and matches the trigger's error text; any other exception
  propagates. (d) `/health` carries the last verify result and age.
- **Acceptance.** `tests/test_ledger.py`: truncating the tail now fails verify against an
  anchor. `tests/test_store_ledger.py`: one UPDATE and one DELETE per append-only table
  is refused on SQLite and PostgreSQL. `tests/test_server_system.py`: `/health` reports
  `ledger_verify` with `ok|stale|broken`.

### A6. Stats and oracle details

- **Mutant prefix truncation.** `planned[:max_mutants]` (`src/crb/core/oracle/mutation.py:785`,
  default 20 in `mutant.py:38`) after concatenating files in `src_files` order biases
  multi-file commits to the first file's earliest lines. Sample deterministically across
  files and line ranges (seeded by task sha, round-robin per file). Test in
  `tests/test_oracle_mutation.py` with a two-file fixture.
- **Timeouts count as kills.** `mutation.py:897`. Record `timeout` as its own outcome,
  exclude it from the kill numerator and denominator, report the count. Same for
  `rc=0` with `parse_error`, which is currently a kill.
- **Belt 4 reads post-run tree.** `grade.py:483` recomputes `touched_files()` after tests
  ran; `touched_pre` exists at `grade.py:345`. Use `touched_pre` for belt 4 and belt 5's
  file list; keep the post-run set as a diagnostic in the pack. Guard in
  `tests/test_grade.py` with a runner that writes an artefact into the tree.
- **`gold_clean=None` rows are eligible** (`ledger.py:626-631`). Decide in the A1 ADR:
  either exclude them from cells that may route `deliver`, or keep them and say so on the
  map. Recommended: exclude.
- **Harness rows re-read as outage by string match** (`ledger.py:584-586`) changes a
  hashed row's classification at read time. Stamp `failure_kind` at write time
  (`GradeRow` field, in the hash) and stop re-deriving it.

---

## B. Leakage and posture: measure what the product actually claims

### B1. Stop embedding the held-out commit's sha in the working directory

- **Problem.** Trial, mining and control worktrees are named with `task.short_id`, the
  first ten hex characters of the future commit: `src/crb/core/run.py:253`,
  `src/crb/core/mine.py:185`, `src/crb/core/oracle/controls.py:1214, 1294`. On the host
  posture `pwd` hands the builder the answer key's address and `git worktree add` shares
  the object store, so `git show <sha>` resolves. The only barrier is a prefix denylist
  on shell commands (`src/crb/builders/claude_code.py:227-260`).
- **Change.** Name worktrees by an opaque per-run token (`secrets.token_hex(6)` or a
  blake2 of task id + run id + salt kept out of the tree). Keep the mapping in the run's
  events, not in the path. Grep for `short_id` in anything that ends up in the builder's
  environment, prompt or cwd, and remove it.
- **Acceptance.** `tests/test_run.py`, `tests/test_mine.py`, `tests/test_oracle_controls.py`:
  the worktree path and the builder's environment contain no substring of the task sha
  (assert with the fixture's real sha). Add a `tests/test_builders_guard_corpus.py` case
  where the builder runs `pwd` and `basename` and the transcript scan finds nothing.

### B2. Refuse the host builder and the local executor in production

- **Problem.** `CRB_BUILDER__EXECUTOR` defaults to `host` (`src/crb/server/settings.py:300`)
  and in `prod` only warns (`settings.py:588-592`); same for `CRB_SANDBOX__EXECUTOR=local`.
  In host mode `claude -p` runs with Bash, `--permission-mode dontAsk`, the API key in
  its environment and the gold commit reachable, as the worker user.
- **Change.** In `Settings` validation, `env == "prod"` with `builder.executor == "host"`
  or `sandbox.executor == "local"` raises unless `CRB_ALLOW_UNSEALED_PROD=1` is set, and
  the override is stamped into the run's apparatus and shown on the Posture page and
  `/health`. Default `builder.executor` to `docker` when `env == "prod"`.
- **Acceptance.** `tests/test_settings_home_guard.py` (or a new `tests/test_settings_posture.py`)
  pins the refusal and the override. `docs/SECURITY.md` §5 and `docs/DEPLOYMENT.md` name
  the override. `deploy/docker-compose.yml` and the Helm values default to the sealed
  posture for the worker.

### B3. Take one measurement on the sealed posture and publish it

- **Problem.** Every ledger row to date is `executor: local` (CHANGELOG "Evidence caveat
  for this release"). The sealed builder (`src/crb/builders/container.py`) and the docker
  executor have never produced a published number. This is the single most important
  gap for the product's claims.
- **Change.** After B1 and B2: run the cobra `bug.fix` XS and S cells (the cells the
  README leans on) on `CRB_SANDBOX__EXECUTOR=docker` plus `CRB_BUILDER__EXECUTOR=docker`
  with the shipped Go sandbox image and the sealed builder image, same builder, same
  budget rung, one attempt per task, at least 10 distinct tasks per cell. Vendor the rows
  per A4. Replace the README's "What has been measured" section with the sealed numbers
  and move the host-posture numbers to a "superseded" subsection with their caveat **[hypothesis — recorded at the time; not re-checked since]**.
- **Acceptance.** A `docs/reviews/<date>-sealed-posture.md` with n, n_tasks, point,
  Wilson interval, cost, apparatus, and the deltas against the host rows. `[measured]`
  tags on README resolve to the vendored rows. The "Open, honestly" paragraph no longer
  says nothing was measured on the sealed posture.

### B4. Mining bias is stated

- **Problem.** `mine.py:105-130` and `git.py:140-147` take the newest 3000 non-merge
  commits that touch both source and test files within caps. This is a recency and
  "well-tested commits only" bias not stated on the README or the Results screen **[hypothesis — recorded at the time; not re-checked since]**.
- **Change.** One `[hypothesis]`-tagged paragraph in README "The instrument in six steps"
  step 1 and in `docs/EVIDENCE-AND-CLAIMS.md` naming the selection rule and what it
  excludes. Show the pool's date range and the share of history it covers on the Results
  screen's oracle card.

### B5. Executor edge cases

- `make_executor("")` returns `LocalExecutor` (`src/crb/core/execution.py:962-963`).
  Make the empty string an error; `local` must be spelled.
- Exit code 125 is read as `SandboxUnavailable` (`execution.py:531-535`); a suite that
  exits 125 itself is misread. Distinguish the docker CLI's own 125 (check stderr for the
  daemon's message) from a container process exit.
- `write_pack` shares one `<hash>.json.tmp` (`src/crb/core/run.py:176-186`) and
  `restore_exclude` rewrites the main clone's `info/exclude` (`workspace.py:288-296,
  322-347`); both race under concurrency. Use a per-process temp name and a per-worktree
  exclude via `core.excludesFile` in the worktree's config.
- Baseline `parse_error` still qualifies a task (`mine.py:239-245`) and later fails belt 3
  spuriously. Disqualify at mining with reason `baseline_unparseable`.

---

## C. Forward mode: close the oracle-quality gap before the PR exists

### C1. Review before delivery; the PR never opens on an unreviewed build

- **Problem.** `FactoryLoop.run_item` orders `_deliver` before `_review`
  (`src/crb/factory/loop.py:682-683`), so the pull request is public before the
  mutation-strength probe runs. On a `weak_oracle` verdict the item stops but the PR
  stays open with the weak build (`loop.py:625-653`; no close path in
  `src/crb/factory/delivery.py`).
- **Change.** Reorder to assess → oracle → prove → build → review → deliver. A verdict
  other than `accept` never reaches `_deliver`. Add `close_pull_request` to
  `delivery.py` (with a comment naming the verdict) for the rework path when a delivered
  PR is later found weak.
- **Acceptance.** `tests/test_factory_loop.py`: with `MajorProbe` no delivery call is
  made; the item's outcome is `oracle_needs_strengthening` and no branch was pushed.
  `docs/adr/` supersedes the relevant part of ADR-0003's factory amendment. The Factory
  screen's stage strip reads in the new order.

### C2. The strength probe is required and scoreable, or the item stops

- **Problem.** `MutationStrengthProbe` is `required=False`, `max_mutants=12`, text-level
  on changed lines only; "not scoreable" produces an `info` finding and `accept` is
  still possible (`src/crb/factory/review.py:341-437, 385-396, 421-434`).
- **Change.** `required=True` by default. `not_scoreable` becomes a stop
  `oracle_not_scoreable` with the way forward drafted (the same mechanism DL-050 uses).
  Raise `max_mutants` to the core default and sample per A6. Add the `hardcode_cheat`
  and `stub` controls from `core/oracle/controls.py` as review probes against the
  authored test, so a test that only asserts on the changed lines' literals is caught.
- **Acceptance.** `tests/test_factory_review.py`: an unscoreable probe stops the item;
  a stub-passing test is rejected. `docs/OPERATOR.md` §10 says the probe is required and
  how to override per run (`required=false` must be an explicit, evented act).

### C3. Author and builder are distinct models, not distinct labels

- **Problem.** `assert_distinct_identity` compares rung labels
  (`src/crb/factory/testfirst.py:89-105`); `author.py:21-27` says the same model under
  another builder name is allowed. The review doc claims correlated judgement is avoided.
- **Change.** Parse the model half of the rung and refuse when the author's model equals
  any build rung's model (normalise aliases via the pricing table in
  `src/crb/builders/budget.py`). Make the refusal reason say which rung to change.
- **Acceptance.** `tests/test_factory_author.py`: `editblock:claude-sonnet-5` authoring
  for `claude_code:claude-sonnet-5` is refused; different models pass. DL-050's
  "limitation we write down" paragraph is updated to say it is now enforced.

### C4. The route gate and the ledger row agree on the cell

- **Problem.** The gate keys on `item.capability_class|item.size_estimate`
  (`src/crb/server/worker.py:2013`); no story points means `S`
  (`src/crb/intake/draft.py:461-467`). The build writes the row in the measured churn
  size (`src/crb/factory/build.py:451-456`). Nothing compares them, so an L change can
  ship under an S licence.
- **Change.** After the build, compute `size_tier(churn)`; if it is larger than
  `size_estimate`, re-run the route lookup on the measured cell before delivery and stop
  `size_exceeds_licence` if that cell is not `deliver`. Record both sizes on the item's
  evidence. An item with no points is `unsized` and routes `human` until an operator
  sizes it or the tracker supplies points.
- **Acceptance.** `tests/test_factory_loop.py`: an S-estimated item that builds to M
  against a map where only S is `deliver` stops without delivery.
  `tests/test_intake_draft.py`: no points gives `unsized`, not `S`.

### C5. A real reviewer, wired

- **Problem.** The default `Reviewer` is `MechanicalReviewer` with "no opinion"
  (`review.py:481-492`, `loop.py:175`); `worker.py` never wires another.
- **Change.** Add `CRB_FACTORY__REVIEWER` as a rung, distinct-model checked like C3, whose
  only outputs are findings with file and line, never a verdict (the probes decide). The
  worker builds the `FactorySpec` with it. Keep the mechanical reviewer as the default
  when unset and show "no independent review" on the Factory screen in that case.
- **Acceptance.** `tests/test_worker_*`: the spec carries the reviewer; a run with none
  shows the state. ADR-0013's advisory rule is cited in the file header.

### C6. Intake: an operator approves the draft, and the pass takes a lease

- **Problem.** A ticket whose slots are filled is registered and queued with no human
  step (`src/crb/server/intake.py`, the `ready_to_register` path). Its title becomes the
  branch and PR title, and its acceptance criteria are emitted verbatim into the PR body
  (`delivery.py:252-254, 273-299, 617`). No lease guards concurrent polls
  (`server/intake.py:471-488`). HTTP 429 maps to `unreachable` with no backoff
  (`src/crb/intake/http.py:65, 98-140`). `http.py:113` would send the tracker token to
  any absolute URL a future caller passes **[hypothesis — recorded at the time; not re-checked since]**.
- **Change.** (a) `CRB_INTAKE__REQUIRE_APPROVAL=true` by default: a ready ticket lands as
  a draft on the Intake screen with an operator "Register" act (evented); an explicit
  allowlist of tracker authors may bypass it. (b) Render ticket-derived text in the PR
  body inside a fenced block with markdown escaped, and sanitise the branch name to
  `[a-z0-9-]`. (c) Take a per-repository lease row (`workers` table already exists) for
  the poll. (d) Honour `Retry-After` on 429 with capped backoff. (e) Assert the request
  URL's origin equals `base_url` in `http.py`.
- **Acceptance.** `tests/test_intake_service.py`: a ready ticket is not registered until
  approved; two concurrent passes register once. `tests/test_factory_delivery.py`: a
  title containing markdown and a backtick renders escaped. `tests/test_intake_adapters.py`:
  an absolute URL on another origin is refused **[hypothesis — recorded at the time; not re-checked since]**.

### C7. Say what the learning loop is

- **Problem.** `src/crb/core/learn.py` is three pure derivations that never act; every
  actuator is a human. README calls it a "self-improvement loop" **[hypothesis — recorded at the time; not re-checked since]**.
- **Change.** Either build the three write paths G-532 names (accept a refusal line,
  register a strengthening item, queue a re-measurement) behind a named-person decision,
  or rewrite README's "What the product is" to say the loop proposes and a person acts.
  Do the first if wave 2 is funded; do the second now regardless **[hypothesis — recorded at the time; not re-checked since]**.

### C8. Budgets: a cost cap that is on by default

- **Problem.** `Budget` defaults `max_cost_usd=0` and `max_tokens=0`, meaning uncapped
  (`src/crb/builders/base.py:338-352`); Claude Code gets `--max-budget-usd` only when > 0
  (`claude_code.py:827-845`); unknown models price at `$0` with `cost_known=False`.
- **Change.** A deployment-level `CRB_BUILDER__MAX_COST_USD` default (suggest 2.00) that
  every rung inherits unless overridden per run; refuse a run whose model has no pricing
  row unless `cost_known=false` is acknowledged on the run request. This is backlog F5b.
- **Acceptance.** `tests/test_builders_base.py` and `tests/test_server_routes_runs.py`.

---

## D. Security

### D1. Push token off the argv

- **Problem.** `src/crb/factory/delivery.py:377-384` passes
  `-c http.<remote>.extraheader=Authorization: Basic <token>` on the git argv; it is
  visible in `/proc` and stored in `GitError.argv`. `clone_repo` already does it right
  with `GIT_CONFIG_COUNT` (`src/crb/server/worker.py:1304-1311`). `docs/SECURITY.md` §3.3
  says "never argv".
- **Change.** Pass the header through `GIT_CONFIG_COUNT/KEY_0/VALUE_0` in `repo.run(env=…)`;
  redact `extraheader` values in `GitError`.
- **Acceptance.** `tests/test_factory_delivery.py` asserts the argv contains no
  `Authorization` and the env does; a forced `GitError` repr contains no token.

### D2. Constrain `clone_path`

- **Problem.** `schemas.py:249-276` accepts any host path; `worker.py:1190-1193` uses it if
  it is a git repo. Reachable from the MCP write tools (`src/crb/mcp/server.py:146-160`).
- **Change.** Resolve and require `clone_path.is_relative_to(CRB_HOME / "repos")`, or
  make a path outside it admin-only and evented. Reject symlinks that escape.
- **Acceptance.** `tests/test_server_routes_repos.py` and `tests/test_mcp_server.py`.

### D3. The `setup-token` helper runs with a minimal environment

- **Problem.** `src/crb/server/claude_login_driver.py:131-139` execs `claude setup-token`
  with the API process's full `os.environ` (secret key, database URL, OIDC secret).
- **Change.** Exec with `PATH, HOME, TERM, NO_COLOR, BROWSER` plus a throwaway
  `CLAUDE_CONFIG_DIR`.
- **Acceptance.** `tests/test_server_claude_login.py` asserts the child env keys.

### D4. Sessions, CSRF, rate limit, OIDC role

- Stateless sessions cannot be revoked (`src/crb/server/auth.py:386-412`;
  `routes/auth.py:132-140`). Add a per-user `session_nonce` column (new Alembic
  revision), include it in the credential version, rotate on logout and on
  "sign out everywhere"; the password-change path already revokes, reuse it.
- CSRF token is not bound to the session (`app.py:276-305`; `routes/auth.py:155-160`).
  Derive it as HMAC(secret, uid, nonce) and use `__Host-` cookie names when secure.
- Login rate limit is per `(username, ip)` and per process (`auth.py:548-597`). Add a
  per-IP bucket and document the proxy limiter as required in prod.
- OIDC role is overwritten from claims on each login (`auth.py:791`), silently reverting
  an admin's role change. Make claims mapping apply only on first login unless
  `CRB_OIDC__ROLE_FROM_CLAIMS=always`; log a `user.role_overridden` event when it does.
- Tests in `tests/test_server_auth.py` for each.

### D5. Record the critical friend's open actions

- `docs/reviews/2026-09-13-critical-friend.md` action #8 (independent human review of
  `grade`, `ledger`, `controls`, guards before external demonstration) and #9 (rotate the
  pasted OAuth token) have no recorded closure in CHANGELOG or DECISION-LOG.
- Add a DL entry that either records the review (who, when, what they read) and the
  rotation date, or states both as `[gap]`. The claims checker should not let a review
  action disappear without a record.

---

## E. Engineering hygiene

### E1. Pin mypy and fix the eight errors

- **Problem.** `pyproject.toml` has `mypy>=1.11`; mypy 2.3.1 reports 8 `var-annotated`
  errors: `src/crb/server/routes/signoffs.py:461, 476, 562`, `routes/ledger.py:425`,
  `routes/system.py:244`, `routes/grades.py:185`,
  `store/migrations/versions/v0002_belt5_repo_lint_clean.py:71`, `v0003_reviews.py:110`.
  CI is green only because its cache resolved an older mypy **[hypothesis — recorded at the time; not re-checked since]**.
- **Change.** Annotate the eight. Pin `mypy==<the version CI passes on>` in the dev extra,
  and pin `ruff` the same way; let Dependabot bump them.
- **Acceptance.** `mypy` passes on a fresh `uv venv`.
- Also add `.coverage` and `coverage.xml` to `.gitignore`; the CI coverage command
  leaves `.coverage` untracked in every local clone.

### E2. Make the suite hermetic to uid 0 and to an absent docker daemon

- `tests/test_builders_container.py:372` expects the `docker.sock` refusal but under uid 0
  the root refusal fires first (the default user is `os.getuid()`). Pass an explicit
  non-root `user=` in that assertion and in the `sealed_unconfirmed` fixture of
  `tests/test_worker.py`; make the final `s.user == f"{getuid()}:{getgid()}"` assertion
  use a non-root fixture. 12 tests fail under uid 0 today **[hypothesis — recorded at the time; not re-checked since]**.
- `tests/test_cli_doctor.py:537` asserts `overall: warn` on a store-only fixture but the
  sandbox line is `fail` without a daemon. Either stub the sandbox probe in that test or
  mark it `docker`.
- The four `@pytest.mark.network` setup tests are selected by the default run. Add
  `-m "not sandbox_images and not network"` to the documented local command, or gate
  them on a reachability probe with a reason in the skip **[hypothesis — recorded at the time; not re-checked since]**.
- Acceptance: `pytest -m "not sandbox_images"` passes in a root container with no docker
  and no outbound network, with every environment-dependent test skipped by reason.

### E3. UI client duplication and the hint ratchet's proportion

- `ui/src/api/client.ts`: `fetchBounded` and `api<T>` duplicate ~40 lines of
  timeout/abort logic. Extract one helper.
- The hint layer (`ui/src/help/hints.ts`, 694 entries; `MIN_HINTS` floors per route in
  `hints-ratchet.test.tsx`) makes every new element a three-file change. Keep the
  registry and the `title=` allowlist; replace the numeric per-route floors with a
  coverage rule that only requires hints on the `SHARED_IDS` classes (routes, belts,
  failure kinds, reason codes, pills) and on any control whose label is a term in the
  glossary. Record the decision as a DL entry; the DoD artefacts for pages cite the
  ratchet, so update them in the same PR **[hypothesis — recorded at the time; not re-checked since]**.
- Add `ui/src/screens/Repos/ReposPage.test.tsx` (gap G-230).

### E4. Documentation for the customer

- Write `docs/SUMMARY.md`, two pages, for an NHS engineering and assurance reader: what
  it is, what it measures, what it refuses to claim, what it costs to onboard a
  repository (`docs/ONBOARDING-A-REPO.md` says a developer day and under £20), what the
  current evidence licenses, and the open gaps. Tables and bullets. Put it first in
  README's "Start here" and stop pointing the "Anyone" row at an external claude.ai
  artifact **[hypothesis — recorded at the time; not re-checked since]**.
- Freeze `CHANGELOG.md` growth: one paragraph per PR, link the PR for detail. Move the
  "Unreleased" narrative (about 12,900 words) into `docs/reviews/` as a dated wave report.
- Commit subjects: Conventional Commits already require an imperative subject ≤ 72
  characters; enforce it with a commit-msg check in CI (`scripts/check_commit_subject.py`).
- Do not add another Navigation header rule; do consider trimming the header template to
  the four fields the code-map checker reads **[hypothesis — recorded at the time; not re-checked since]**.

---

## F. Order of work and what "done" means

Recommended sequence, one PR each unless noted:

| # | Item | Size | Depends on |
|---|---|---|---|
| 1 | E1 pin mypy, fix errors; E2 uid test | XS | none |
| 2 | D1 push token; D2 clone_path; D3 setup-token env | S | none |
| 3 | B1 opaque worktree names | S | none |
| 4 | B2 refuse unsealed prod | S | none |
| 5 | A1 + A2 + A3 as one ADR "routing.v2", apparatus 2.3 | M | none |
| 6 | C1 + C2 review before delivery, probe required | M | 5 |
| 7 | C3 distinct model; C4 size agreement; C8 cost cap | S each | 6 |
| 8 | C6 intake approval, lease, backoff, origin check | M | none |
| 9 | A5 pack binding, anchor, append-only probe | M | none |
| 10 | A6 and B5 engine details | S each | 5 |
| 11 | D4 sessions, CSRF, rate limit, OIDC | S each | none |
| 12 | B3 sealed-posture measurement; A4 vendor the rows | L, costs model spend | 3, 4, 5 |
| 13 | C5 reviewer rung; C7 learn write paths or README rewrite | M | 6 |
| 14 | E3 UI; E4 docs; D5 record | S each | none |

The assessment counts the product as trustworthy for its stated purpose when:

- item 12 has produced a `[measured]` README section whose rows are vendored and verify;
- `route()` cannot return `deliver` without ≥ 10 distinct tasks, a measured oracle
  ≥ 0.80 and passed controls, on rows produced under the sealed posture; **[hypothesis — recorded at the time; not re-checked since]**
- the factory never opens a pull request before an accepted review with a required
  strength probe, from an author model distinct from the build model;
- production refuses the host builder and the local executor without an explicit,
  evented override;
- `mypy`, `pytest`, `vitest` and every script gate pass on a fresh clone with pinned
  tool versions.
