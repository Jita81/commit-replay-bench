# ADR-0025 — routing.v2: a route reads one apparatus, counts each distinct change once by its first observed attempt, and never delivers on an unmeasured oracle or unmeasured controls

**Status:** Accepted (the operator's standing direction of 2026-09-26, recorded as DL-095;
north-star Wave 2, streams G, I, R and F)
Amended by ADR-0026 (the context standard) before it was committed: items 2, 8, 9, 10, 12 and 15
below are read as ADR-0026 item 6 rewrites them, and each carries a note saying how.
**Date:** 2026-09-27
**Apparatus impact:** bumps `APPARATUS_VERSION` to **2.4**, and with it
`routing.POLICY_VERSION` → `routing.v2`, `routing.CONTROLS_POLICY_VERSION` →
`controls-gate.v2`, `signoff.SIGNOFF_POLICY_VERSION` → `signoff-policy.v4`,
`signoff.SIGNOFF_SCHEMA` → `crb.signoff.v5` (the v4 body frozen) and
`oracle.mutation.mutation_version()` → `mutation.v2` (`MUTATION_V2`). Every row of 2.4 also
stamps its context arm (`labels.context_arm`) and its class-set version (`labels.taxonomy`) —
ADR-0026 items 1 and 9 ride this one bump. No belt, no belt set (`v5`), no size tier, no global
class and no `CELL_FIELDS` entry moves, so a clean row means at 2.4 what it meant at 2.3. What
moves is what rows license: which rows a route reads, how it counts them, what else
must have been measured, and what the factory may deliver on them. Routing is part of the
apparatus (ADR-0003, Consequences), and rows of two apparatus versions are never pooled.

**Supersedes in part** ADR-0003 (the numeric rule; the "when a verdict is evaluated" escape
of the controls clauses; its 2026-09-19 note that every earlier run's rows count, for factory
rows), ADR-0015 §3 (the pooled `?apparatus=all` reading) and ADR-0013 decision 3 (for a model
reviewer). **Amends** ADR-0021 (the strength probe is required) and ADR-0002 (the ledger's
tail is anchored). Chosen by judging three independent designs — integrity first, operator
first, simplicity first — with the simplicity-first design as the spine and the other two
designs' integrity and operator mechanisms grafted on (see Alternatives considered).

## Context

The external assessment of 2026-09-25 (items A1–A3, A5, A6, B5, C2, C4, C5) found that the
bar the code applies is not the bar README publishes. README's "Not a licence to deploy"
reads "n ≥ 10, point ≥ 0.90, Wilson-low ≥ 0.80, false-Q1 = 0, oracle ≥ 0.80, controls
passed". Read against `origin/feat/value` (`8fabbd7`, PR #57, which holds main and #50) and
`origin/feat/posture` (`b1fd424`, PR #56, apparatus 2.3), the code applies something weaker
**[measured — n = 2 branches read (`8fabbd7`, `b1fd424`), method: reading both branches on
2026-09-26; apparatus 2.3, the code read — each point is a fact about the code, not a
rate]**:

- **`n` counts attempts.** `CellStats.n` is every eligible row: every ladder rung and every
  rerun of one commit adds one, and the Wilson interval treats them as independent.
  `CellStats.n_tasks` exists and is shown, but neither `route()` nor `SignoffPolicy` reads it.
- **An unmeasured oracle passes.** `route()` applies the oracle clause only
  `if strength is not None`. The server feeds it the latest `oracle.score` event of each
  task, whatever its apparatus or scoring rule, averaged over whichever tasks happen to have
  one — one scored task in ten makes a measured cell. Without events (the CLI) it falls back
  to the rows' own `oracle_strength`, which is empty on every row of the operator's export
  **[measured — n = 618 rows, the operator's ledger export of 2026-09-25; apparatus
  2.0–2.2]**.
- **Unevaluated controls pass.** With `controls=None` every controls clause is skipped, and
  `crb route`, `crb.core.forecast` and the value scorecard's prospective routing call it so.
  Where a verdict is read (`latest_controls_verdict`) it is the latest report of any
  apparatus, and a cancelled run that found nothing counts as passed: `complete` is carried
  on the verdict and never read.
- **Readings pool.** `crb route` reduces the whole JSONL ledger, every apparatus and sighted
  with blind; `?apparatus=all` pools on purpose (ADR-0015 §3); the forecast and the
  strengthening backlog read every apparatus.
- **A stored row's classification can move.** A row pinned `harness` is re-read as `outage`
  when its error matches `OUTAGE_ERROR_MARKERS`, a tuple anyone can edit, and a row without
  the label is re-derived under whatever the rule is that day. `outage` leaves `n`, so an
  edit to that tuple moves denominators — and the prevention register (ADR-0020) keys its
  classes, before-windows and decisions on `failure_kind`.
- **Rows that cannot license still do.** A row with `gold_clean=None` is eligible. A factory
  row has no gold and is graded against a model-authored test, yet it counts in the
  class × size cell the factory's gate reads (the B-1b pull requests quoted n = 27 against the
  26 the freeze saw, ADR-0003's 2026-09-19 amendment). That projection also pools models, so
  one model's evidence licenses another model's build.
- **Belt 5 does not say why it was not evaluated.** `lint_plan` returns `None` both for
  `lint: {disabled: true}` and for "no linter found", so an operator's opt-out reads like an
  absent toolchain.
- **The scorer's sample is biased and generous.** `mutation.v1` keeps a stable prefix of the
  candidates (`planned[:max_mutants]`), so a multi-file commit is scored on its first file's
  first lines, and it counts a timeout and an exit-0 parse error as kills.
- **The ledger cannot see its own tail.** A truncated tail still verifies, `crb ledger
  verify` checks that a pack hash is present but never opens the pack, and
  `assert_append_only` probes one table and reads any exception as the trigger firing.
- **The factory can deliver outside its licence.** The strength probe is optional
  (`required=False`, 12 mutants) and "not scoreable" is an info finding; an item with no
  points is sized `S`; nothing compares the built change's size with the size the gate
  licensed; and the `Reviewer` protocol lets an opinion tighten a verdict (ADR-0013
  decision 3), so a model reviewer's major finding would force a rework.
- **The executor has edges.** `make_executor("")` returns the local executor; a suite that
  exits 125 is read as the sandbox failing to launch; `write_pack` shares one temporary name;
  the harness rewrites the clone's shared `info/exclude` under concurrent worktrees.

The clustering is not hypothetical. Of the 16 (repository × class × size × mode) groups with
at least ten eligible attempts at apparatus 2.2, 13 rest on fewer than ten distinct commits;
one click commit carries 31 rows; 149 of the 618 rows are escalation rungs (`r2`, `r3`)
**[measured — n = 618 rows, the operator's export of 2026-09-25, outage and disqualified rows
left out of the eligible counts; grouped without the builder, which the export does not
carry, so these are the class × size groups the factory's gate reads; apparatus 2.0–2.2]**.
The cobra `bug.fix` × XS cell that routed `deliver` on 2026-09-15 rested on 22 attempts at 9
commits **[measured — README, "What has been measured (2026-09-15)"; apparatus 2.2]**, and 9
of 9 all clean has a Wilson lower bound of 0.70.

What already holds, and is kept: belts 4 and 5 read the builder's changes as they stood
before the first test ran (ADR-0019 §7); a sign-off refuses an unmeasured oracle and cannot
be relaxed (`signoff-policy.v2`); the server's map passes `ControlsVerdict.unmeasured()` when
a repository has no report; the checks arm is a stamp and a filter that never pools
(ADR-0024); the posture class is a filter (ADR-0019 §8); non-clean rows already carry a
hashed `failure_kind`; qualification refuses an unattributed baseline
(`QUAL_BASELINE_UNATTRIBUTED`); the factory reviews before it delivers, and the test author's
model is distinct from every build rung's (ADR-0021; DL-050 as updated).

**Constraints.** The ledger is append-only (ADR-0002): nothing is re-graded or re-derived.
Rows of two apparatus versions are never pooled. No gate is weakened (CONTRIBUTING). A
model's words never decide a verdict (EVIDENCE-AND-CLAIMS §2). Every refusal names what to
measure next. The core stays standard-library only (ADR-0008).

## Decision

1. **A reading has one apparatus, and a cell cannot hold two.** `crb.core.ledger.cell_stats`
   raises `ApparatusPooled` when its rows carry more than one `apparatus_version`, as it
   raises `ChecksArmsPooled` for two arms (ADR-0024 §6); `all_cell_stats` returns one cell per
   key, arm and apparatus. `GET /capability-map` and `GET /routes` read one apparatus —
   `current` by default, or a named version — and `?apparatus=all` is refused with 422
   `apparatus_pooling_refused` naming the versions present (superseding ADR-0015 §3). The
   oracle scores and the controls report a route reads belong to the same apparatus (items 3
   and 4). `crb route` defaults to `--apparatus current --mode sighted` and exits 2, naming
   them, rather than pool two posture classes; `crb ledger stats`, the forecast, the
   strengthening backlog, the federated export and the value scorecard's prospective routing
   split by apparatus. A reading of an earlier apparatus is served as history
   (`apparatus: {current, read, superseded_rows, superseded_versions}` on the map) and
   licenses nothing: the factory's gate and the sign-off write path read the current one.
   *As ADR-0026 item 6 amends it:* one reading also has one context arm and one class-set
   version: `cell_stats` raises `ContextArmsPooled` and `ClassSetsPooled`, and `?arm=` and
   `?taxonomy=` select, refusing `all` with 422 as `?apparatus=all` is refused. `?arm=standard`
   (the map's default) reads each cell on its own proven standard arm, and a cell with no
   standard on `S3`, the arm every sighted replay row of 2.4 carries, which never delivers.

2. **The unit is a distinct commit, counted once, by its first observed attempt.** Reading a
   cell's rows in ledger order (the JSONL file's order; the store's `seq`), a task's **first
   attempt** is its first row that is eligible (not disqualified, not an outage, gold not
   dirty), is not an escalation rung (`r2` and later — `crb.core.ledger.is_escalated_trial`,
   which `crb.core.spend` now re-exports) and **observed the builder**: its failure kind is not
   `harness`. A task whose non-escalated eligible rows are all `harness` counts as a failed
   task until an attempt observes the builder — the instrument's failure is held against
   autonomy until the instrument is fixed and the commit measured again (ADR-0003's fail-closed
   rule), never against that commit for the whole apparatus. The task **routes** when its first
   attempt was gold-checked (`gold_clean is True`) and is not an attempt belt 5 could have
   changed while switched off by configuration (one that passed every other belt); a
   lint-disabled attempt that failed another belt is the miss it is (P-342). Any other first
   attempt is left out, and counted. `CellStats`
   gains:
   - `n_tasks` — the routing tasks, the number the bar reads (the old count of distinct
     eligible tasks is kept as `n_tasks_eligible`);
   - `task_clean`, `task_point` and `task_ci` (Wilson 95 % over `task_clean / n_tasks`);
   - `n_tasks_gold_unchecked`, `n_tasks_lint_disabled` and `apparatus_version`.

   `n`, `clean`, `point` and `ci` stay: the per-attempt numbers are shown beside the task
   numbers and route nothing. `REASON_N_BELOW_MIN` stays in the vocabulary only so that
   decisions stamped `routing.v1` still validate. A factory row (`gold_clean=None`, a
   model-authored oracle) is never a routing first attempt: the factory never licenses itself.

   **Distinct means distinct change.** The unit is the distinct CHANGE, counted once — the
   `change_id` stream G stamps on every 2.4 row (`git patch-id --stable`, a revert's that of
   its original; DL-093) — never the commit id. The commit census found click `bug.fix` × S
   holding two cherry-picks of one change with opposite outcomes: counted by commit they were
   two readings of one change. A row without a `change_id` (below 2.4) is its own change.

   **The sealed posture.** A replayed arm's first attempt counts toward a reading only when it
   was graded in the sealed posture: the tests in the docker sandbox's sealed mode (a
   `docker/<tree>/sealed` posture class, #56 and ADR-0019) and the builder in its sealed
   container (ADR-0012; the row keeps `labels.builder_executor`). A cell holding any eligible
   row graded otherwise routes `calibrate` with its own reason code, `posture_unsealed`, and the
   next act `seal` — never `deliver` (item 8's row 3a). `S2` rows read ADR-0026 item 8's
   held-out rule instead.

   *As ADR-0026 item 6 amends it:* inside a registered reading the first-attempt rule stands,
   read only over rows graded after the registration, at rung `r1`, in the seeded order; a
   commit the instrument cannot grade leaves the pool with its reason instead of counting as a
   miss (ADR-0026 item 2), and a disqualified first attempt (the builder touched the oracle) is
   the builder's miss, never a re-run. `min_tasks` is replaced by the look rule. The
   "never a routing first attempt" rule holds for every factory row except an `S2` row graded
   on held-out acceptance tests (ADR-0026 item 8).

3. **Nothing unmeasured delivers: the oracle.** A route reads `OracleEvidence`
   (`crb.core.routing`). For each task it takes the **minimum** strength over that task's
   scoreable `oracle.score` events whose provenance names `mutation_version ==
   mutation_version()` (`mutation.v2`, item 7) and the reading's apparatus. A minimum cannot
   rise when a task is scored again, so re-scoring a flaky suite until it reads higher does
   nothing; "latest wins" is gone. The cell's strength is the mean of those minimums over its
   routing tasks that have one, and `scored_tasks / n_tasks` is its share. No scored task
   routes `calibrate` with `oracle_unmeasured`; a share below `RoutingPolicy.min_oracle_share =
   0.5` routes `calibrate` with `oracle_thin` — the majority rule `min_controls_share` already
   applies, because a mean over a minority of a cell's commits describes those commits, not
   the cell. The rows' own `oracle_strength` column never feeds a route again, and
   `route(stats, oracle=None)` reads `None` as unmeasured.

4. **Nothing unmeasured delivers: the controls.** `route(…, controls=None)` is read as
   `ControlsVerdict.unmeasured()`: the "caller evaluated none" escape is deleted and every
   decision stamps `controls_policy`. `latest_controls_verdict` reads the latest
   `controls.report` of the reading's apparatus; a report of another apparatus is served as
   history and routes as unmeasured. A report whose run was cancelled (`complete: false`) can
   fail and can escape — a violation found is a violation — but it cannot pass: an incomplete
   run that found nothing is unmeasured, and an older pass is never read in its place.
   `ControlsVerdict` gains `apparatus_version` and a `detail` saying why a verdict is
   unmeasured.

5. **Belt 5 says why.** `crb.core.lint.LINT_STATUSES` is `evaluated` | `none_detected` |
   `disabled_by_config` | `error` | `not_reached` (the grade stopped before belt 5) |
   `not_requested` (`grade(evaluate_lint=False)`: the negative controls, which write no row).
   `GradeResult.lint_status` carries it, the evidence pack records it, and every measured row
   of apparatus 2.4 or later carries the hashed label `lint_reason`. The ledger refuses such a
   row without the label, with `not_requested`, with `evaluated` while `repo_lint_clean` is
   `None` (or the reverse), or with `error` on a clean row. A task whose first attempt ran
   with belt 5 switched off, and that passed every other belt, does not route (item 2) — a
   lint-disabled miss still counts (P-342) — and a cell whose reading has not
   delivered that holds such a task routes `calibrate` with `lint_disabled`. The fix is a
   person's — the loop may never write `lint.disabled` (ADR-0020 §1) — and it is to switch
   belt 5 back on and measure new commits. Switching belt 5 off can therefore never help a
   cell, and switching it back on recovers the cell. `none_detected` routes and is shown on
   the cell.

6. **A row carries its own classification.** Every measured row of apparatus 2.4 or later
   carries `labels.failure_kind` — the empty string on a clean row
   (`crb.core.ledger.V2_APPARATUS = (2, 4)`; `grade_row_from_result` and
   `crb.factory.build.factory_row` stamp it through one helper) — and `GradeRow.failure_kind`
   returns it verbatim. Rows below 2.4 are read by the rule as it stood at 2.3: the `harness`
   → `outage` re-reading survives only there, against `OUTAGE_ERROR_MARKERS_V1`, a frozen copy
   whose SHA-256 a test pins. The live marker list and `derive_failure_kind` are pinned to
   `APPARATUS_VERSION` by a golden table, so changing either fails that test until the
   apparatus moves and the old rule is frozen beside the V1 copy. A measured `replay` row of
   2.4 or later must carry `gold_clean=True`: qualification already makes it so (ADR-0019 §4),
   and the ledger now refuses anything else. An `outage` row of 2.4 or later also pins why the
   call never happened — `labels.outage_cause`, `auth` (the login this deployment presented
   was refused) or `provider`, by one pinned rule (`crb.core.ledger.derive_outage_cause`) at
   write, inside the row hash; the kind stays `outage`, outside every `n` (pilot D1, DL-233).
   The labels only 2.4 defines are one list, `crb.core.ledger.V2_ONLY_LABELS`: `lint_reason`,
   `change_id`, `context_arm`, `taxonomy` and `outage_cause`. A row below 2.4 carrying any of
   them is refused at write and on read, and a row rewritten below 2.4 drops them all
   (`labels_at_apparatus`).

7. **Oracle scoring v2** (`crb.core.oracle.mutation`, `MUTATION_V2 = "mutation.v2"`, read
   through `mutation_version()`).
   - Every candidate of every changed file is generated, with no cap per file. Within a file
     the candidates are ranked by the SHA-256 of `task_id|path|line|col|op`; files are taken
     in path order, one candidate each in turn, up to `max_mutants` (default 20), or one per
     file when more files than that hold a candidate (P-343). The sample is deterministic,
     seeded by the commit, and reaches every file; the provenance records the
     sampler (`hash-rr.v1`) and the candidates per file.
   - A mutant whose run timed out is `timeout`, and one whose run exited 0 with a parse error
     is `unattributed`. Neither is a kill or an escape: both leave the numerator and the
     denominator and are counted (`timeouts`, `unattributed`). When excluded outcomes (errors,
     uncompilable, timeouts, unattributed) exceed half of the planned mutants, the task is not
     scoreable, with a note naming the causes.

8. **The rule, its order, and every shortfall at once.** `route()` is still first-match for
   the route and its reason code, in this order (the look rule `look.v1`,
   `min_oracle_strength` 0.80, `min_oracle_share` 0.5, `max_controls_escapes` 0,
   `min_controls_share` 0.5 — as ADR-0026 item 6 amends it):

| # | Condition | Route | Reason code | Next measurement |
|---|---|---|---|---|
| 1 | `false_q1 > 0` | `do_not_ship` | `false_q1` | `audit` |
| 2 | size in `granularize_sizes` (`XL`) | `granularize` | `granularize` | `split` |
| 3 | controls measured and not passed | `human` | `controls_failed` | `controls`, after the fix |
| 3a | a replayed arm's cell holds a row graded outside the sealed posture | `calibrate` | `posture_unsealed` | `seal` |
| 4 | `n_tasks_lint_disabled > 0` and the reading has not delivered | `calibrate` | `lint_disabled` | `config` |
| 5 | no registered reading reads the arm; the arm is descriptive; its look is pending | `calibrate` | `reading_unregistered`, `descriptive`, `look_pending` | `register`; none; `replay`, `qualify` or `mine` with the commits still needed |
| 6 | no routing task scored under `mutation.v2` | `calibrate` | `oracle_unmeasured` | `oracle` |
| 7 | scored share `< min_oracle_share` | `calibrate` | `oracle_thin` | `oracle` |
| 8 | oracle strength `< min_oracle_strength` | `human` | `oracle_weak` | `strengthen` |
| 9 | controls escapes `> max_controls_escapes` | `human` | `controls_escapes` | `strengthen` |
| 10 | the reading read `insufficient`; `undecided` | `human`; `calibrate` | `insufficient`; `undecided` | a richer arm in a new reading within the budget, a split or a person; `mine` |
| 11 | the arm delivered but is `S3` (a ceiling); or is not the cell's standard | `calibrate` | `ceiling`; `leaner_standard` | calibration builds toward `S2`; build on the standard |
| 12 | no complete controls report at this apparatus | `calibrate` | `controls_unmeasured` | `controls` |
| 13 | constructible share `< min_controls_share` | `calibrate` | `controls_thin` | `controls` |
| 14 | otherwise | `deliver` | `deliver` | — |

   *As ADR-0026 item 6 amends it:* rows 5, 10 and 11 were `tasks_below_min`,
   `point_below_bar` and `ci_low_below_bar`; the look rule replaces `min_tasks` 10 and the
   fixed point and Wilson bars, and `route()` returns `deliver` only for the arm that is the
   cell's standard and not a ceiling. Row 3a is the sealed-posture clause (item 2).

   Every clause that fails is also listed, in that order, on `RouteDecision.shortfalls` as a
   `Shortfall(code, route, observed, threshold, next, count, model_money)`, so an operator
   never pays for `look_pending` to discover `oracle_unmeasured` next. Only `replay` and
   calibration builds spend model money. For `replay`, `count` is the commits still needed to
   the next look (ADR-0026 item 6 — what `tasks_to_bar` became); for `oracle` it is the counted
   commits still unscored. The server adds the pool: when the cell's class and size hold fewer
   qualified commits not yet attempted at this apparatus than `count`, `next` reads `qualify`
   (unqualified ones exist) or `mine` (they do not: mine further back, or leave the class to a
   person). Under the look rule the smallest cell that can deliver is 20 distinct commits in a
   registered reading, all clean on their first observed attempt in the sealed posture
   (ADR-0026 items 3 and 6).
   `RouteDecision` gains `n_tasks`, `task_clean`, `task_point`, `task_ci_low`, `task_ci_high`,
   `basis = "first_observed_attempt"`, `oracle_scored_tasks`, `oracle_share` and
   `shortfalls`; `n`, `point`, `ci_low` and `ci_high` stay, per attempt, for display.
   `RoutingPolicy` refuses the name `routing.v1`, so an old policy file cannot pose as the
   published bar, and refuses to relax the look rule or `min_oracle_share` under any name.

9. **A sign-off reads the same evidence.** `resolve_oracle_strength` reads only the
   `OracleEvidence` the route reads, never the rows' mean. *As ADR-0026 item 6 amends it:* a
   sign-off may be written only for the cell's standard arm, when its registered reading reads
   `deliver` (`thin_tasks` became `look_pending`; any other arm is refused `not_standard`, and
   neither can be relaxed); the record also stamps, under its `row_hash`, the `context_arm`,
   the `taxonomy` and the reading's id, and `apply_signoffs` lifts only a cell read on that
   same arm, class-set version and reading. `signoff-policy.v4`; a
   `crb.signoff.v5` record stamps `n_tasks`, `task_clean`, `task_ci_low`, `task_ci_high`,
   `oracle_scored_tasks`, `oracle_share` and the controls report's apparatus, and
   `_V4_BODY_FIELDS` is frozen so a v4 record keeps verifying. A relaxed sign-off never
   licenses a delivery the route refuses: where ADR-0018 is in force the gate reads the route
   first.

10. **The published bar is generated.** `RoutingPolicy.describe()` renders the bar as one
    sentence — *as ADR-0026 item 6 amends it,* the look rule, the hierarchy and the budget.
    README's "Not a licence to deploy" carries it between
    `<!-- routing-bar:begin -->` and `<!-- routing-bar:end -->`, `crb route --help` and the
    Capability screen's route hint quote it, and `scripts/claims_check.py --check` fails on
    any byte of difference. The class of defect this ADR fixes — the code's bar drifting from
    the README's — gets a gate, not a sentence (docs/PREVENTION.md).

11. **The evidence cannot move under a route unseen.** *Deferred, except the append-only
    probe:* the pack binding and the HMAC anchor below are not in the definition of done;
    stream I builds only the append-only probe of every table (G-601). The text is kept as the
    design a later decision starts from, not as a commitment.
    - **Packs are bound.** `JsonlLedger(path, packs_dir=…)` (default `<ledger dir>/evidence`)
      refuses to append a clean measured row whose pack is absent or does not re-hash to its
      `evidence_pack_hash` (`FalseQ1Violation`: no pack, no Q1); imported rows are exempt and
      counted. `crb ledger verify` re-hashes every pack; `--no-packs` prints "packs NOT
      verified".
    - **The tail is anchored.** `crb.core.anchor` signs `{schema: crb.anchor.v1, ledger,
      count, tail_row_hash, at, key_id}` with HMAC-SHA256 under a key derived from
      `CRB_SECRET_KEY` (`HMAC(key, "crb.ledger.anchor.v1")`). The store writes one
      `ledger.anchor` event in the same transaction as every append batch, then
      `<CRB_HOME>/ledger.anchor` atomically; a JSONL ledger keeps `<ledger>.anchor` beside it
      and refuses to append when its tail is not the anchored row, so a truncation is caught at
      the next append. Verify takes the highest authentic count of the two copies: fewer rows
      than that, or another hash at that position, is `broken`. With no key the anchor is
      unsigned and reads `stale` (it still catches an accidental truncation); an anchor under
      another key reads `stale` until an operator re-anchors after a full verify
      (`crb ledger anchor --reanchor`, evented). Truncation before the first anchor stays
      undetectable; the first boot at 2.4 writes that anchor after a full verify.
    - **Append-only is proven per table.** `assert_append_only` checks the catalog for both
      triggers of every table in `APPEND_ONLY_TABLES` and, where a table holds a row, probes one
      `UPDATE` and one `DELETE` inside a savepoint, expecting the trigger's own text
      (`"<table> is append-only"`, one constant used by both dialects). Any other exception
      propagates.
    - **The state is served.** `crb.store.integrity` verifies in full at API boot and every
      `CRB_LEDGER__VERIFY_INTERVAL_S` (600), re-hashing packs, and appends `ledger.verified`
      when the state changes. `/health` serves `ledger_verify` (`state`: `ok` | `stale` |
      `broken`, with `code`, `verified_at`, `rows` and `anchor_count`): `stale` past
      `CRB_LEDGER__VERIFY_MAX_AGE_S` (900) or on an unsigned or foreign-key anchor; `broken`
      makes `/health` `down`. The factory's delivery gate runs the O(1) anchor check itself,
      reads the last state, and withholds a pull request on `broken` (`ledger_unverified`).

12. **The factory delivers only what its own cell licenses.** *Stream F builds this item as
    ADR-0026 items 6 and 8 amend it:* `not_licensed` becomes `no_proven_standard` and applies
    whether or not delivery is on, and `deliver_override` lifts only the sign-off clause of a
    proven standard, never `no_proven_standard`, `size_exceeds_licence` or
    `cell_not_licensed`. The advisory model reviewer (assessment C5, the last bullet) is
    **deferred**: it strains the non-goal "not an AI's opinion of an AI's work", and no
    criterion names it. The two review probes built from negative controls and the evented
    operator sizing (`intake.sized`) are **deferred** too: no criterion names them and
    nothing builds them yet (P-333); the bullets below say so where they appear.
    - **The strength probe is required** (amending ADR-0021). `MutationStrengthProbe` runs
      with `required=True` and `max_mutants=DEFAULT_MAX_MUTANTS` under the v2 sampler. A build
      it cannot score stops `oracle_not_scoreable` — no rework, no delivery — with the
      superseding item drafted (the DL-050 mechanism). The one exception is an approver's
      waiver for one item (`POST /factory/{repo}/items/{item_id}/probe-waiver` with a reason;
      403 below approver), recorded as `review.probe_waived` on the factory chain with the
      authored test's SHA-256: it holds only while that test is byte-identical, and the pull
      request names the approver and the reason. The waiver is a second approver's act
      (ADR-0016's two-person rule, as GOV-4 applies it to the route-gate override): the API
      refuses it 409 `same_actor` to an approver who queued a factory run on the repository
      that is still queued or running, and the loop ignores a waiver that names the run's own
      actor and records `review.waiver_refused` (P-339).
    - *Deferred:* **Two negative controls become review probes.** `HardcodeCheatProbe` and
      `StubProbe` build `hardcode_cheat` and `stub` (`crb.core.oracle.controls.construct_control`)
      against the authored test on the base tree. A test that passes a cheat or a stub is a
      major `weak_oracle` finding and takes the existing `oracle_needs_strengthening` stop
      (ADR-0013, amendment of 2026-09-21); a control the language cannot construct is an info
      finding.
    - **An item without points is `unsized`.** `crb.intake.draft.size_for` returns `unsized`
      when there are no points, never `S`, and readiness routes the item `human` until the
      ticket gains points or an operator registers the item with a `size_estimate` (the
      evented `intake.sized` act is deferred).
    - **The licence is the delivered change's own cell.** The gate reads the map once per run,
      before any build, with the run's own rows excluded (ADR-0003, 2026-09-19), in two
      projections: class × size for the record, and class × size × builder × model × provider,
      which licenses — the provider is one of the cell's seven fields (P-340). With delivery
      on, an item for which no rung of the ladder holds a `deliver` cell at its estimated size
      stops before any build (`not_licensed`, $0). After an
      accepting review, the change's own cell — its class, the size tier of the build's churn,
      and the final rung's builder, model and provider — must route `deliver` in that same
      map, or the item stops `size_exceeds_licence` (the build is larger than the estimate) or
      `cell_not_licensed`; when the measured size differs from the estimate, larger or
      smaller, the route gate reads the measured cell's route (P-335). This supersedes the
      last sentence of ADR-0003 decision 3 ("a smaller change keeps the estimate's cell"):
      a smaller change is licensed by its measured cell, never by the estimate's. Both sizes and both
      cells go on the evidence and in the stop. No override lifts this: `deliver_override`
      lifts only the sign-off clause at the entry gate (ADR-0026 items 6 and 8), never
      `cell_not_licensed` or `size_exceeds_licence`.
    - **A reviewer model leaves findings, never a verdict** (superseding ADR-0013 decision 3
      for a model). `CRB_FACTORY__REVIEWER` (a rung label; unset by default) is refused when
      its model is the test author's or any build rung's (`canonical_model`, C3).
      `crb.factory.reviewer.ModelReviewer` sends the diff and the authored test — no ticket
      text — and keeps only `AdvisoryFinding(file, line, text)` values whose file is in the
      diff (at most 20, 300 characters each). `AdvisoryFinding` is a separate type that
      `derive_verdict` does not accept: it reaches no verdict, no rework, no route and no
      sign-off. Findings go on the chain (`review.advisory`) and, escaped, into the pull
      request under "Independent review (advisory — no verdict)". With no reviewer set, the
      factory state and the pull request say "No independent review". README's "Not an AI
      opinion of AI work" is amended to say so.

13. **The instrument's edges** (`crb.core.execution`, `run`, `workspace`, `mine`, `grade`).
    - `make_executor` accepts `local` or `docker` only; `""`, `none` and `host` raise
      `ValueError` naming the setting.
    - Exit 125 is the sandbox failing to launch only when the docker CLI said so on stderr
      (a line starting `docker: `, `Error response from daemon`, `Unable to find image`, an
      unknown flag) or the run printed nothing; otherwise it is the suite's own exit code. One
      test serves all three launch paths, pinned against captured docker 24–28 output. A
      misread fails closed (the run stops), and a model is still blamed only with a witness
      (ADR-0019 §5).
    - `write_pack` writes `<hash>.json.<pid>.<8 hex>.tmp` and renames it.
    - Harness patterns go in a per-worktree `core.excludesFile` (`extensions.worktreeConfig`,
      git 2.20 or later); the clone's shared `info/exclude` is never rewritten again, and the
      tamper check reads both.
    - The non-gold mine path skips a candidate whose baseline carries a parse error, with the
      skip text of `QUAL_BASELINE_UNATTRIBUTED`: one vocabulary with ADR-0019, and no
      `baseline_unparseable` code.
    - The grade records the files touched after the tests ran as `touched_post_run` in the
      pack, a diagnostic that no belt reads.

14. **What is stamped.** `APPARATUS_VERSION = "2.4"`, with a history line in
    `crb.core.version`; `routing.v2` and `controls-gate.v2` on every decision, with
    `policy_thresholds` now holding the look rule, its looks, the per-cell budget and
    `min_oracle_share`; `labels.context_arm` and `labels.taxonomy` on every row of 2.4;
    `signoff-policy.v4`
    and `crb.signoff.v5` on every new sign-off; `mutation.v2` on every score. `posture_id`
    hashes the apparatus version (ADR-0019 §1), so every task is qualified again.

15. **Migration. Nothing is rewritten, re-graded or re-derived.**
    *As ADR-0026 item 6 amends it,* the smallest cell that can deliver is 20 distinct commits in
    a registered reading, all clean on their first observed attempt in the sealed posture.

    - **Before.** PRs #51–#57 are merged. The merge keeps #56's `touched_pre` in `grade.py`,
      composes #56's posture filter with #57's arm filter in the worker and the capability
      routes, renames the short-id worktrees #56 added (which #53's ratchet names), and gives
      ADR-0019, 0021, 0022 and 0023 their decision-log rows so `tests/test_adr_shape.py`
      passes. The operator's stack runs 2.2 today: ship 2.3 and 2.4 as one upgrade, and run
      Wave 3's paid campaign at 2.4 — a campaign run at 2.3 stays valid within 2.3 and
      licenses nothing after the upgrade.
    - **Runbook.** Export the ledger (`crb ledger export`) and save
      `GET /routes?repo=<repo>` for each repository (the routing.v1 record); drain the queue,
      since a run queued before the upgrade fails `POSTURE_DRIFT` at $0; deploy; the API's
      first boot verifies in full and writes the genesis anchor; qualify, score and control
      each repository (no model money); replay what each cell's shortfalls name; re-sign.
    - **Rows.** Rows of 2.0–2.3 keep verifying and stay readable at `?apparatus=<version>`,
      routed under routing.v2 as history; none can deliver, because no `mutation.v2` score and
      no controls report exists at their apparatus. The current map starts `not_yet_measured`
      in every cell. Rows below 2.4 keep the frozen v1 failure rule.
    - **Oracle and controls.** Every existing score (`mutation.v1`) and every report of an
      earlier apparatus is served as history (`current: false`) and read as unmeasured.
    - **Sign-offs.** Every record goes stale with the apparatus (ADR-0015) and is listed under
      Decisions; v4 records keep verifying under the frozen body. Re-signing needs a 2.4
      `deliver`.
    - **Factory.** Pull requests opened under routing.v1 are not closed automatically; the
      Factory screen lists them with the `policy_version` from their chain. Registered
      backlogs keep their sizes; a new draft without points is `unsized`.
    - **Spend** (hygiene stream, DL-063). A build run carries a per-attempt cap of $2.00
      (`CRB_BUILDER__MAX_COST_USD`) unless it sets another; `0` is refused; a model with no
      pricing row needs an acknowledgement and `max_tokens`.
    - **CLI.** `crb route` reads the current apparatus and sighted rows by default and never
      prints `deliver` without `--oracle` and `--controls` exports at 2.4; `crb ledger verify`
      re-hashes packs.
    - **Value scorecard.** Prospective routing under routing.v2 finds no delivery on history
      (no `mutation.v2` oracle, no 2.4 controls); the 2026-09-25 baseline keeps its routing.v1
      stamp and is not compared across policy versions.
    - **What the operator reads**, on the Capability, Routing, Decisions and Factory screens:

    > **Apparatus 2.4 is in force (routing.v2, ADR-0025).** The bar in the code is now the bar
    > in the README, and it counts commits, not attempts. Nothing was deleted, edited or
    > re-graded: rows from 2.0 to 2.3 still verify and stay readable under Apparatus. None of
    > them licenses a pull request, because:
    > 1. evidence expires with the apparatus, and two versions are never pooled;
    > 2. no commit has an oracle score from the new scorer (mutation.v2), and oracle and
    >    controls results now count only at the apparatus of the rows they judge;
    > 3. each change now counts once, by its first attempt, in a reading registered before its
    >    first attempt and read only at its looks. The smallest cell that can deliver is 20
    >    distinct commits, all clean, graded in the sealed posture.
    >
    > Sign-offs made before 2.4 have expired and wait under Decisions. Every task is qualified
    > again in the 2.4 posture; runs queued before the upgrade stopped at no cost.
    >
    > To earn `deliver` back for a cell, follow its list; each step names its count:
    > 1. qualify the repository (no model money);
    > 2. run an oracle run and a controls run (no model money; machine time);
    > 3. register a reading on the cell, then replay its pool in the sealed posture, one first
    >    attempt each, on the builder and model you want licensed (about $0.14–$0.23 an
    >    attempt so far);
    > 4. ask a second person to sign the cell's standard arm.
    >
    > If a cell says its pool is short, mine further back or leave the class to a person. The
    > factory still builds, grades and reviews; it opens a pull request only for a change whose
    > own cell (class, measured size, builder and model) routes `deliver` at 2.4.

    Shipped in the same wave but decided elsewhere: the cost cap and the committed `uv.lock`
    (DL-063), and the bounded wait for a container to leave `docker ps` (docs/PREVENTION.md).

## Consequences

**What becomes easier.**
- A `deliver` is defensible from the ledger: at least 20 distinct changes (the first look of
  `look.v1`), in a reading registered before the first attempt, each counted once
  by its first observed attempt, at one apparatus, with an oracle scored on at least half of
  them and a complete controls report — the sentence README prints, because README prints
  what `RoutingPolicy.describe()` returns.
- An operator sees every missing measurement of a cell at once, with its count and whether it
  costs model money; qualifying, scoring and controlling cost none.
- A stored row's failure kind cannot move, so the prevention register's classes,
  before-windows and decisions (ADR-0020) stand on rows that do not change under them.
- A truncated ledger is caught at the next append (JSONL) or the next verify (store), and a
  broken ledger licenses no pull request.
- The factory cannot deliver a change larger than its licence, built by a model its licence
  does not cover, on a test nobody could score, or on a test a hard-coded cheat passes.

**What becomes harder.**
- Every current `deliver` route goes, and nothing licenses a pull request until a cell is
  measured again at 2.4. The smallest cell that can deliver is 20 distinct commits, all clean
  on their first attempt in the sealed posture, in a registered reading, per builder and model
  the factory will use: about $2.80–$4.60 of model money per arm of a cell **[hypothesis —
  $0.14–$0.23 per attempt, measured on cobra, koa and click at apparatus 2.2 (README;
  ADR-0019); other cells and models will differ]**, plus machine
  time to qualify (62 s for one cobra task on a cold cache **[measured — n = 1, ADR-0019;
  apparatus 2.3]**), score and control.
- A repository with fewer than 20 qualified commits in a class and size never reaches
  `deliver` there. That is the honest reading; the cell says `mine`, or the class stays with a
  person.
- Repositories whose commits the text mutators cannot score stay `oracle_thin` (the NHS
  reading: 2 of 6 tasks scoreable **[measured — n = 6 tasks, 2026-09-14; apparatus 2.2]**),
  and the factory stops more items `oracle_not_scoreable`, until the mutators or the tests
  improve.
- An escalation to a model whose own cell is unmeasured withholds the pull request.
- A cell that took first attempts with belt 5 switched off is measured again on new commits
  once belt 5 is back on.
- A run on a model with no pricing row needs an explicit acknowledgement and a token cap.
- Worktrees need git 2.20 or later. The anchor is as strong as the custody of
  `CRB_SECRET_KEY`: whoever holds it can re-anchor a truncated ledger.

**What we must never do.**
- Reduce a cell over two apparatus versions, two modes, two arms or two posture classes.
- Route on anything but each distinct commit's first observed attempt.
- Let an unmeasured, thin or other-apparatus oracle or controls report reach `deliver`.
- Re-derive the failure kind of a row of 2.4 or later, or edit the frozen v1 rule.
- Let a model's words reach a verdict, a rework, a route or a sign-off.
- Count a factory row as evidence that licenses the factory.
- Deliver a change whose own cell does not route `deliver`.

**What is still open [gap].**
- Oracle scores and controls reports are filtered by apparatus and scoring rule, not yet by
  posture class (ADR-0019 §8 filters rows only). A deployment that changes posture class
  within 2.4 must run oracle and controls again; the next wave stamps and filters the class.
- The priced recovery plan across cells (one ordered list of qualify, oracle, controls and
  replay runs, with a cost) is a follow-up on `crb.core.learn.remeasure_plan`; this wave serves
  the per-cell shortfalls it would be built from.
- A JSONL anchor sits beside its ledger, so whoever can replace both is caught only by an
  outside copy; the store keeps its second copy in `events`.
- The store writes a grade and its pack in two transactions, so a failed pack write leaves a
  clean row whose pack is only on disk. Verify reports it `broken`; the append does not refuse
  it yet (the JSONL ledger does). Writing both in one transaction is the next wave's.
- The vendored rows behind README's `[measured]` sentences (assessment A4) and the
  sealed-posture measurement (B3) belong to Wave 3.

## Alternatives considered

- **Count a task clean when any attempt was clean (best of k).** Rejected: a replay ladder
  stops on the held-out tests, which the factory does not have, so any-clean counts selection
  by the answer key as capability. The cost of rejecting it is that a cell needs more commits.
- **Keep counting attempts, as routing.v1 did.** Rejected by the clustering above. The cost of
  rejecting it is fewer `deliver` cells.
- **Order first attempts by `created` and `row_hash`** (the integrity-first design). It is
  independent of read order, but an import or a clock skewed between two workers can append a
  row with an earlier `created`, and a task's first attempt then changes after the map
  licensed a delivery. Ledger order cannot move under an append. The cost: every reader must
  hand rows over in ledger order, which tests pin.
- **Count a `harness` first attempt as the task's result for the whole apparatus** (all three
  designs). Rejected: run `8d9c5e55`, queued with no API key, wrote one `harness` row on each
  of cobra's nine `bug.fix` × XS commits at $0 **[measured — n = 9 rows, the operator's
  export of 2026-09-25; apparatus 2.2]**; at 2.4 that would have ended the cell for the
  apparatus. The cost of rejecting it is a rule in two parts.
- **A per-task mean (each commit weighted once).** Rejected: re-running a failed commit raises
  its share, which rewards stopping when the numbers look good.
- **The latest oracle score per task, filtered for freshness** (the operator-first design).
  Rejected: a flaky suite can be re-scored until it reads higher; a minimum cannot. The cost:
  a flaky suite lowers a task for the whole apparatus.
- **Leave oracle coverage open** (the simplicity-first design) or **require as many scored
  tasks as `min_tasks`** (the operator-first design). The first lets one scored task carry a
  cell's "oracle ≥ 0.80"; the second is stricter than the controls gate for no stated reason.
  The cost of the middle rule: repositories the mutators cannot score stay `oracle_thin`.
- **Make `oracle` and `controls` required arguments of `route()`** (the integrity-first
  design). Rejected: reading `None` as unmeasured is as fail-closed and changes no caller; a
  caller that passes nothing gets `calibrate`.
- **A reason code `apparatus_superseded`** (the integrity-first design). Rejected: the filter
  and the served `apparatus` block say the same, and a reading of an earlier apparatus holds
  no `mutation.v2` score or report of its own, so it cannot deliver.
- **A frozen `routing.v1` router for a before-view, an upgrade record or an evidence epoch**
  (the integrity-first and operator-first designs). Rejected: a second rule in the code base
  that reads like a licence. The v1 decisions are on the factory chain (`route.decided` with
  `policy_version`), and the runbook saves `GET /routes` before the upgrade. The cost is no
  in-product list of what was lost.
- **A priced recovery endpoint and `crb upgrade plan`** (the operator-first design). Deferred
  (see What is still open): the per-cell shortfalls carry the counts it would add up.
- **Hold a cell in `calibrate` for any row graded with belt 5 off** (all three designs and the
  assessment's wording). Rejected: permanent for the apparatus once belt 5 is back on.
  Dropping, whatever their outcome, the commits whose first attempt ran with belt 5 off closes
  the same route — switching belt 5 off never helps — and recovers. The cost is a subtler rule.
- **Read exit 125 through `--cidfile` and `docker inspect`, without `--rm`** (the
  integrity-first design). Rejected: container lifecycle risk (containers the reaper must find)
  for a rare case, when the signature already fails closed and the witness keeps blame honest.
  The cost: the rule depends on the docker CLI's wording, pinned by captured output.
- **Anchor on the worker's heartbeat** (the assessment), or **a separate ADR-0026 for the
  anchor** (the integrity-first design). Rejected: the tail moves only on append, and the
  anchor serves this ADR's one rule, that a verdict cannot rest on evidence that moved.
- **A reviewer model whose findings may be `major`** (the operator-first design). Rejected: a
  major finding forces a rework, so a model's opinion becomes a verdict. **Capping the
  severity at `minor` on the existing type** (the simplicity-first design) is one edit away
  from the same; a separate type cannot reach `derive_verdict`.
- **Keep the gate on class × size.** Rejected: one model's evidence licensed another model's
  build. The cost: an escalation to an unmeasured model withholds delivery.
- **Treat routing.v2 as a policy change without an apparatus bump** (ADR-0016's reasoning).
  Rejected: that reasoning covers who may attest, not what rows license, and ADR-0003 puts
  routing inside the apparatus. The cost: every task is qualified again and every cell
  measured again.
- **Pool 2.3 and 2.4 rows because grading did not change.** Rejected by the house rule. The
  cost is the timing of Wave 3 (Migration).
