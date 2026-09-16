# NHS public repositories on Commit Replay Bench — first measurement

**Date:** 2026-09-14 · **Apparatus:** 2.1 for every build row below (2.2 — the repo-lint belt — went live after these runs, so under `crb learn remeasure` all of them are already due for renewal) · **Builder:** Claude Sonnet 5 via Claude Code, `auth: cli` · **Executor:** local (dev stack) · **Retention:** every attempt's worktree and transcript kept.
**Status of the numbers:** [measured], tiny n, single run per task, no cell reaches the routing rule's n ≥ 10. Nothing here licenses a per-class claim about NHS code. It licenses statements about the *instrument on NHS code*, which is what this note is for.

## 1. The three repositories and what each needed before a single task could be graded

| Repo | Shape | What it took |
|---|---|---|
| **nhsuk/nhsuk-frontend** | Design-system monorepo; jest with multiple projects (unit, jsdom behaviour, browser); node 24 | Pin node@24 on PATH; `--selectProjects "JavaScript unit tests" "JavaScript behaviour tests"` to keep the browser project out of the belt; `test_mode: suffix` (`.unit.test.mjs`, `.jsdom.test.mjs`); explicit belt scope `packages/nhsuk-frontend/src` |
| **NHSDigital/nhsuk-react-components** | React + TypeScript; jest with `.snap` snapshots; older commits incompatible with HEAD's `node_modules` (ts-jest → babel) | Snapshot-only commits mapped to their test files; `.snap` in the test suffixes; hard pool only (3 gold-clean of 14 mined); **instrument defect found**: the repo's `.gitignore` says `node_modules/` (directory-only) which does not match the symlink the harness plants, so the link surfaced as an untracked edit and was deleted before grading — every grade failed with `FileNotFoundError: 'jest'` (fixed, `31e1d31`) |
| **NHSDigital/mesh-client** | Python client whose integration tests need the **MESH sandbox** service on `localhost:8701` over TLS with per-repo test certificates | The repo's pinned sandbox (`v1.0.27`) **no longer builds** (Debian bullseye security archive 404); the latest release (`v1.0.110`) does; the VM cannot bind-mount `/private/tmp`, so fixtures moved under `$HOME`; commits before 2025-08 committed their certs and Python 3.13 rejects them, commits after generate them — the sandbox has to present the *era's* certs; and `test_get_version` asserts the package reports a real version while the harness imports the code from the worktree — solved with a metadata-only `dist-info` stub in the environment. 10 of 11 tasks were "gold-dirty" until all four of those were in place |

The mesh-client column is the finding a governance community should weigh most: **the oracle for real NHS integration code is a running service plus its secrets, and both bit-rot at the commit's own pin.** The product has no first-class notion of "services the oracle needs" yet (Wave B15); tonight it was done by hand and is therefore not reproducible from the repo config alone.

## 2. Mining, oracle strength, negative controls

| Repo | Mined | Gold-clean | Classes | Oracle strength (mutants) | Controls |
|---|---|---|---|---|---|
| nhsuk-frontend | 8 | 6 | `bug.fix` only | **0.36** (14; 2 of 6 tasks scoreable) | passed · 42 rows · 0 escapes · 24 not-constructible (2.0 apparatus: 3/7 controls on JS) |
| nhsuk-react-components | 14 | 3 | `frontend.component.add`, `bug.fix` | 0.67 (43) | passed · 21 rows · 0 escapes · 12 not-constructible |
| mesh-client | 12 | 3 | `bug.fix` only | 0.76 (41) | passed · 21 rows · **0 escapes** on 2.1 (1 escape on 2.0 — the `conftest.py` poison, now caught by belt 1) · 4 not-constructible |

nhsuk-frontend's tests catch about a third of injected faults: under the routing rule this repo routes `human` whatever the clean rate says, and that is the right answer for a design system whose behaviour lives partly in SCSS and Nunjucks templates the jest oracle never executes (see §4).

## 3. Sonnet 5 results on apparatus 2.1

Rows from the two usage-limit outages (`model_error: You've hit your limit`) are excluded — they are `harness` rows in the ledger and measure the operator's quota, not the model. Everything else is in.

| Repo | Mode | n | clean | model red | budget | protocol | harness | mean $ | mean s |
|---|---|---|---|---|---|---|---|---|---|
| nhsuk-frontend | sighted | 5 | **5** | 0 | 0 | 0 | 0 | 0.29 | 70 |
| nhsuk-frontend | blind | 3 | 1 | 0 | 1 | 1 | 0 | 0.55 | 226 |
| nhsuk-react-components | sighted | 3 | 2 | 0 | 0 | 1 | 0 | 0.58 | 413 |
| nhsuk-react-components | blind | 3 | 0 | 0 | **3** | 0 | 0 | 0.62 | 398 |
| mesh-client | sighted | 3 | 2 | 0 | 0 | 1 | 0 | 0.25 | 69 |
| mesh-client | blind | 3 | 0 | 0 | 2 | 0 | 1 | 0.33 | 900 |
| **all** | | **20** | **10** | **0** | **6** | **3** | **1** | | |

Total NHS spend across every attempt including outages and the 2.0 runs: 68 rows, **$15.18**. False-Q1 across the whole ledger, belt-set aware: **0**.

Readings:
- **Sighted: 9 of 11 clean; the two misses are protocol refusals** (`git stash` — kept refused on measured evidence that a stash is reachable from other worktrees; and a `.git`-mentioning grep filter that was a guard false positive, fixed in `90bf171`). **Zero rows where the model produced a wrong patch.**
- **Blind: 1 of 9 clean, and 6 of the 8 misses are `budget`** — the builder exhausted 25 turns/tool calls (react-components, two at 107–187 s) or the 900 s wall clock (mesh-client) before finishing. Blind mode on NHS code is currently a budget experiment, not a capability measurement; a 50/100-tool-call sweep is the cheap next step.
- Cost: $0.25–0.62 per sighted attempt; 1–7 minutes.

## 4. What the accepted patches look like (worktrees retained; a human can read every one)

- **nhsuk-frontend `b1e02b4e81` "Add scroll JavaScript for older browsers" (L, sighted, clean):** the AI wrote a 127-line `Scroll` component (gold: 151) that passes the maintainers' 101-line jsdom test — a real reconstruction of a design-system component from its test. But the gold commit also changed `_index.scss` (29 lines) and `template.njk`; neither is a `.mjs` source file, so the oracle cannot see them and the size tier does not count them. **Clean here means "the JavaScript half of the feature"** — the mergeable change is JS + SCSS + template, and a human must supply the other half or the review.
- **nhsuk-react-components `ad8131a6f9` "numbered pagination" (L, clean):** AI touched 3 source files where the gold touched 6 (224+/47−); **`2da48ca336` "HTML in legend/label/error" (M, clean):** 4 vs 6 files. Same pattern: test-visible behaviour reproduced; peripheral changes (types, stories, docs) not.
- **mesh-client `0b0457d694` / `632e2de319` (XS, clean):** 2-line changes matching the gold line-for-line in shape.

Consistent with the cobra finding in the critical-friend review: mechanically clean, plausibly *not* the PR a maintainer would merge as-is, and the gap is exactly what the oracle does not cover.

## 5. Instrument defects found by NHS code (all fixed today, all with regression tests)
1. `node_modules/` gitignore pattern vs planted symlink → harness deleted it → `FileNotFoundError: 'jest'` (`31e1d31`).
2. Guard false positives on honest shell: quoted parentheses in a grep pattern (`95a4f2e`), a `.git`-mentioning grep filter (`90bf171`), a single quote inside a double-quoted `$( … )` (`c85dd2e`) — three classes in one day, on top of A10's corpus that had already removed 45. Shell parsing is a long tail; the structural fix is the builder-in-container plan (P5) with a clone that does not contain the gold commit.
3. Oracle service dependency (MESH sandbox) with no product support → Wave B15.
4. Packaging-metadata tests (`test_get_version`) under the worktree-import scheme → metadata stub, to be productised as a runner option.

## 6. What this licenses
- "On three public NHS repositories the instrument runs end to end — mines, checks gold, measures oracle strength, runs negative controls with 0 escapes on 2.1, grades Sonnet 5 with false-Q1 = 0 — and every row carries its failure kind." **[measured]**
- "Sighted Sonnet 5 reproduced 9 of the 11 NHS tasks it was allowed to finish, at $0.25–0.62; the two misses were the guard, not the model." **[measured, n = 11, single run]**
- **Not:** any blind capability claim (budget-capped), any per-class or per-repo rate, any `deliver` route (largest cell n = 5; nhsuk-frontend's oracle is 0.36), anything about the SCSS/template halves of design-system changes.

## 7. Next (priced by the product itself)
`crb learn remeasure` on the live ledger: 64 of 94 rows are stamped 2.0; renewing the ten stale public-repo cells to n ≥ 10 on the current apparatus is **82 rows ≈ $37 ≈ 4 h**; the NHS cells are of the same order. Then a blind budget sweep, then B15 (services) so mesh-client is reproducible from its config, then the human review of the accepted NHS diffs using `docs/reviews/human-review-guide.md`.

## 8. Restated on apparatus 2.2 (2026-09-15) — the repo-lint belt, dependency eras, support files

Every 2.1 row above is superseded (`crb learn remeasure`). What changed in the instrument between the two
measurements, all found by NHS code: **belt 5** (the repository's own linter/formatter/type checker at the
version the commit pins — ADR-0011 and amendments a–c); **JavaScript dependency eras** (a task commit whose
lockfile differs from HEAD gets its own `node_modules` — without it every nhsuk-react-components row read
`harness`: eslint `rc=2`, `@eslint/compat` missing from HEAD's tree); **support files** under the test layout
(`tests/mock_server.py`, `tests/helpers.py`) overlaid but never targets — as targets they disqualified a
mesh-client task and all three of its negative controls; **the `outage` kind** (usage-limit rows are neither
`harness` nor `n`); and the mesh-client sandbox now reproducible from `runner_opts.services` (both cert eras).

Sighted, Sonnet 5, one attempt per task (latest attempt where a task was re-run after an instrument fix):

| Repo | gold-clean tasks | attempted | clean | lint (belt 5) | budget | protocol | harness | $ / attempt | s / attempt |
|---|---|---|---|---|---|---|---|---|---|
| nhsuk-frontend | 6 of 8 | 6 | **4** | 1 (`feature.add` S) | 1 (`component.add` L, 25 turns) | 0 | 0 | 0.15–0.56 | 33–900 |
| nhsuk-react-components | 8 of 14 (was 3: eras recovered 4, one hard-pool task re-qualified) | 8 | **5** | 2 (prettier, `feature.add` M+L) | 1 (`component.add` L) | 0 | 0 | 0.40–0.61 | 87–199 |
| mesh-client | 4 of 14 | 4 | **3** | 1 (`ruff@0.1.15`, XS) | 0 | 0 (two refusals superseded — see below) | 0 | 0.11–0.40 | 21–102 |
| **all** | 18 | **18** | **12** | **4** | **2** | **0** | **0** | | |

Controls on 2.2: nhsuk-frontend passed 42 rows / 0 escapes / 19 not-constructible; nhsuk-react-components
passed 21 / 0 / 11; **mesh-client passed 28 / 0 / 5** (was FAILED with 3 violations before the support-file
rule). Oracle strength (task-level, the number the map and the sign-off now share): frontend 0.62 over 2 of 6
scoreable tasks, react-components 0.64 over 3 (the 5 newly gold-clean tasks are not yet scored), mesh-client
0.64 over 5. NHS spend to date, every row: **93 rows, $24.92**; 2.2 build rows $9.74. Ledger false-Q1: **0 of 532**.

Readings:
- **The tests pass more often than the repository would accept the patch.** Of the 8 non-clean attempts, 4 are
  belt 5: the builder reproduced the behaviour and did not run the maintainers' formatter (prettier on
  react-components twice, ruff on mesh-client, one on nhsuk-frontend). This is the cobra `gofmt` finding again,
  now measured on three NHS repositories with the maintainers' own tool at the commit's own pin. It is the
  cheapest lever there is (run the formatter before finishing) and it is the builder's, not the model's.
- **Two refusals on mesh-client were one instrument finding, now fixed and re-measured:** the builder tried to
  reach the MESH sandbox (`docker ps`, `curl localhost:8701`) to run the integration tests it was pointed at,
  and the sealed posture refused it — the grader had the service, the builder did not. A sighted build now
  brings the task's era services up first and exports their environment in the test command (`321287a`);
  re-run, both tasks graded **clean at $0.13 and $0.15** (the refused attempts had cost $0.55–0.58 each,
  spent on floundering). The refused rows stay in the ledger as `protocol` / `harness`, outside `n`.
- **Budget rows are both L `frontend.component.add`** — a 25-turn / 25-tool-call cap on a component that ships
  with stories, types and docs. The blind budget ladder (25 → 50 → 100) is the priced next step and it is
  the operator's call (DL-019).
- **Cells:** the largest is react-components `frontend.component.add` XS (3 of 3 clean) — n = 3, nothing
  routes. mesh-client's `bug.fix` XS is 2 of 3 clean (the miss is `ruff`), from 3 fair rows.
  No per-class or per-repo claim is licensed by n this small; §6's licence stands, restated on 2.2.

**Two re-qualification residues, deliberately left:** nhsuk-frontend `f3b6316d25` / `6aaae56e4f` and
react-components `97f19db5e3` are "gold target not green (rc=1)" even under their own dependency era — the
oracle needs something the worktree does not provide (a built asset, a browser); they stay out of the pool
with the note on the task. `35a4fdc306` is green at its parent (not RED) and was dropped.

## 9. Stage B (2026-09-15 evening) — the builder's own gate, re-measured: $3.68

The decider's staged plan (DL-027): before any blind spend, re-run the six sighted misses
with the **belt-5 pre-flight** on (DL-030: the repository's own fixers after an honest build,
then ONE bounded repair call — a distinct arm, `claude_code+preflight`), the two L
`component.add` budget misses at the reshaped rung `60/60/1800/$2`.

| Task | Was | Now | Pre-flight record | $ |
|---|---|---|---|---|
| react `2da48ca336` M feature.add | lint (prettier) | **clean** | fixers alone (`eslint:0+prettier:0`) | 0.53 |
| react `ad8131a6f9` L feature.add | lint (prettier) | **clean** | fixers left eslint rc=1 → repair turn → clean | 0.91 |
| mesh `632e2de319` XS bug.fix | lint (ruff UP038) | **clean** | ruff `--fix` could not → repair turn → clean | 0.23 |
| frontend `b65ca47124` S feature.add | lint (tsc type error) | builder_red | lint clean this time; the tests failed — the model's miss | 0.19 |
| react `15758d0587` L component.add | budget (25 turns) | protocol | refused: a computed command name (`$cmd …`) — the archaeology guard's fail-closed rule, before any pre-flight | 1.18 |
| frontend `b1e02b4e81` L component.add | budget (25 turns) | builder_red | 60 turns, lint clean, tests failed — not a budget question | 0.64 |

Readings:
- **The formatter lever is real and cheap: 3 of the 4 lint misses are clean under the
  pre-flight**, one by the fixers alone, two needing the single repair call ($0.23–0.91 per
  task, all-in). Recorded as its own arm, so the plain `claude_code` cells keep their meaning.
- **The two "budget" misses were not budget.** With 60 turns and 30 minutes neither task
  passed: one is the model's (tests red with clean lint), one a guard refusal of a computed
  command name. By the decider's own stop rule ("fewer than 3 budget-kind misses at the
  reshaped rung → cancel D"), **Stage D (rungs 1–2) is cancelled**; Stage C (blind rung 0,
  14 non-mesh tasks, pre-flight on, ≤ $8) is queued.
- NHS sighted on 2.2, latest attempt per task, counting the pre-flight arm: **15 of 18 clean**
  (frontend 4/6, react-components 7/8, mesh-client 4/4); the three misses are two
  `builder_red` (both L `frontend.component.add` on nhsuk-frontend) and one `protocol`.
  Cells are still ≤ 8 tasks; nothing here reaches the sign-off bar.

## 10. Stage C (2026-09-15 night) — blind rung 0 with the pre-flight on: $8.42

The decider's plan after Stage B (DL-031): the 14 non-mesh NHS tasks blind — the builder
sees the commit message and the code, never the tests — at rung 0 (25 turns / 25 tool calls
/ 15 min / $1) with the belt-5 pre-flight on, ≤ $8. Two runs: the first stopped after three
consecutive provider refusals (the usage limit — the circuit breaker, DL-020's `outage_stop`,
worked as designed: 1 fair row, 3 `outage` rows outside `n`, $0.75); the remainder ran once
the limit reset.

| Repo | Fair rows | Clean | Misses | $ |
|---|---|---|---|---|
| nhsuk-frontend | 6 | **0** | 6 `builder_red` (tests red, lint clean) | 3.70 |
| nhsuk-react-components | 8 | **2** (`6d09861db2` XS, `16d417f596` XS — both `frontend.component.add`) | 6 `builder_red` | 4.72 |
| total | **14** | **2 (14 %)** | 12 `builder_red`, 0 protocol, 0 budget, 0 harness; +3 outage | **8.42** |

Readings:
- **Blind is a different measurement, and the honest one for "could it have done the PR".**
  Sighted, the same 14 tasks read 12 of 14 clean on 2.2 (§9); blind, 2 of 14. The builder
  that can make a visible failing test pass cannot, from the commit message alone,
  reconstruct what the maintainer's tests will check — on these repositories the message is
  not a specification (ADR-0004; the upstream finding that the "specification lever" was
  leakage, `project_spec_lever_leakage`).
- Every miss is the model's (`builder_red`): the pre-flight kept lint out of the picture,
  no attempt hit its budget, no guard refused. Nothing here is an instrument defect.
- The two blind cleans are the two smallest component additions (XS) — the shape the map
  would route first if the cells were not ≤ 8 tasks.
- Spend of the approved $45 after Stage C: $3.68 (B) + $8.42 (C) + the three label runs
  (koa 32 / cobra 36 / click 36 tasks labelled by intent; ≈ $1) ≈ **$13**. The top-up (§11)
  follows; Stage D stays cancelled (§9).

## 11. The koa / cobra / click top-up (2026-09-16 night) — one attempt per NEW task: $7.48

DL-027's rule: no repetition of tasks that already carry 2.2 rows; mine wider, then one
sighted attempt (plain `claude_code`, no pre-flight, so the rows pool with the existing
cells) per NEW gold-clean `bug.fix` XS/S task, ≤ $10. The intent labels landed first
(koa 28 of 32, cobra 32 of 36, click 30 of 36 tasks labelled by intent — the rest keep the
path-derived class). 35 new tasks, a `$0.28` per-attempt cap.

| Repo | New tasks | Clean | Misses | $ / attempt | $ |
|---|---|---|---|---|---|
| cobra | 14 (6 XS, 8 S) | **13** | 1 `builder_red` (S) | 0.21 | 3.00 |
| click | 17 (7 XS, 10 S) | **14** | 2 `builder_red` (S), 1 `lint` (XS — the maintainers' formatter) | 0.21 | 3.53 |
| koa | 4 (2 XS, 2 S) | **2** | 1 **regression** (XS — belt 3: a neighbouring test went red), 1 `builder_red` (S) | 0.23 | 0.94 |
| total | **35** | **29 (83 %)** | 6 | | **7.48** |

The cells afterwards (sighted, apparatus 2.2, the live map — `crb.core.routing` v1 under
each repo's controls verdict):

| Cell | n (rows) | distinct tasks | clean | rate [Wilson 95 %] | oracle | route |
|---|---|---|---|---|---|---|
| cobra `bug.fix` XS | 22 | 9 | 22 | 100 % [0.85, 1.00] | 1.00 | **deliver** |
| cobra `bug.fix` S | 24 | 11 | 23 | 95.8 % [0.80, 0.99] | 0.94 | calibrate — `ci_low` 0.798 < 0.80 |
| click `bug.fix` XS | 19 | 10 | 17 | 89.5 % [0.69, 0.97] | 0.76 | human — controls FAILED |
| click `bug.fix` S | 13 | 13 | 11 | 84.6 % [0.58, 0.96] | 0.86 | human — controls FAILED |
| koa `bug.fix` S | 18 | 6 | 16 | 88.9 % [0.67, 0.97] | 0.82 | calibrate — point < 0.90 |
| koa `bug.fix` XS | 11 | 6 | 9 | 81.8 % [0.52, 0.95] | 1.00 | calibrate — point < 0.90 |

Readings:
- **cobra `bug.fix` XS keeps its `deliver` route on nine distinct tasks instead of three**
  (DL-029's concern): 22 of 22, every new task clean. cobra `bug.fix` S lost the route by
  one miss — Wilson-low 0.798 against the 0.80 bar — which is the rule doing exactly what it
  is for: a 95.8 % point on 24 rows is not yet 80 % with 95 % confidence.
- **click's cells were held at `human` by the instrument, not the model** — the live
  stack was still running the code from before PR #7, whose controls run picked a
  regression-poison target the belt never re-ran. **Re-run on the merged code (2026-09-16
  morning, $0): controls PASSED — 224 rows, 0 violations, 0 escapes, 43 not constructible
  (81 % constructible).** With a real verdict the two cells route on their own numbers:
  `bug.fix` S 11 of 13 → `calibrate` (point 0.846 < 0.90); `bug.fix` XS 17 of 19 →
  `human`, **`oracle_weak`** — the cell's task-level mutation strength is 0.76 against the
  0.80 bar, so a green on those tasks does not prove enough and the rule sends the change
  to a person. That is the reading the map is for: the model passes 89 % of these; the
  tests are not strong enough for the map to say so unsupervised.
- **koa produced the campaign's first belt-3 catch on a new task**: `ff25eb4a7f` made the
  target green and a neighbouring test red — `no_new_failures = False`, recorded as a
  regression, never as clean. That is the belt working, and the row the map shows a human.
- The per-attempt price of a small `bug.fix` on these repositories is **$0.21–0.23** at
  20–350 s (one click attempt hit the 900 s wall clock and still passed).
- Spend of the approved $45 after the top-up: **≈ $20.6** ($3.68 B + $8.42 C + ≈ $1 labels
  + $7.48 top-up). Remaining ≈ $24. Next paid step, when the merged code is deployed:
  re-run click's controls + oracle ($0, local), then the NHS blind cells are still ≤ 8 tasks
  and the sign-off bar (n ≥ 10 per cell, the task minimum the operator has yet to set —
  DL-029) is the decision in front of the operator, not another measurement.
