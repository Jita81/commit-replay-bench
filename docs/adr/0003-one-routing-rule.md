# ADR-0003 — One routing rule

**Status:** Accepted · **Amended 2026-09-13** (controls gate), **2026-09-16** (the rule gates the factory), **2026-09-19** (the gate reads the pre-run map; a rework updates its pull request) — §"Amendment" below · **Section added 2026-09-28** (the inputs the rule does not read: merge outcomes and review verdicts — §"Inputs the rule does not read") · **Superseded in part by [ADR-0021](0021-factory-review-before-delivery.md)** (2026-09-25: the review precedes delivery; a rework no longer re-delivers inside a run) · **Superseded in part by [ADR-0026](0026-the-context-standard.md)** (2026-09-27: a cell with no proven standard stops a ticket before any spend; `deliver_override` lifts only a missing sign-off) · **Superseded in part by [ADR-0025](0025-routing-v2.md)** item 12 (2026-09-28: a change smaller than its estimate is licensed by its measured cell, not the estimate's — decision 3's last sentence)
**Date:** 2026-09-13
**Apparatus impact:** defines `routing.POLICY_VERSION = "routing.v1"` (stamped on every `RouteDecision`) and, from the amendment, `routing.CONTROLS_POLICY_VERSION = "controls-gate.v1"` (stamped as `controls_policy` on every decision that evaluated a controls verdict)

## Context

Upstream carried **two** routers with different bars and no shared consumer:

| Source | Rule for auto-delivery | Consumer |
|---|---|---|
| `tuning/catalog_router.py` — the **published** rule (the essay's "≥ 90% point and ≥ 80% lower bound on enough samples") | `n ≥ 10 ∧ point ≥ 0.90 ∧ Wilson-lower ≥ 0.80` | none |
| `tuning/change_router.py` / `benchmark_capability.py` — the **SPC** rule | `yield ≥ 0.85 ∧ σ ≤ 0.10 ∧ n ≥ 20` | change router |

The oracle-adequacy gate (`scripts/oracle_challenge/adequacy_gate.py`) existed but was wired
to nothing, although `[measured]` (upstream AthenaClaude, pre-`crb` apparatus; method:
`scripts/oracle_challenge/mutation_strength.py` — AST mutants on the changed lines, strength
= killed / mutants per task; n = 19 tasks) showed oracle strength varies enough across tasks
that a clean grade alone must not license auto-delivery. Two rules with
different thresholds cannot both be "the" published bar; an auditor asking "why was this
class auto-delivered?" needs one answer.

## Decision

The single rule lives in `crb.core.routing.route(stats, *, oracle_strength=None,
policy=DEFAULT_POLICY)` and is evaluated **in this order**, first match wins:

| # | Condition | Route | Reason recorded |
|---|---|---|---|
| 1 | `stats.false_q1 > 0` | `do_not_ship` | "N false-Q1 row(s) in cell — evidence untrusted" (structurally impossible under ADR-0001; kept as the read-time re-check) |
| 2 | `stats.cell.size ∈ policy.granularize_sizes` (`("XL",)`) | `granularize` | XL is split before it is attempted |
| 3 | `stats.n < policy.min_n` (10) | `calibrate` | not enough evidence |
| 4 | oracle strength measured **and** `< policy.min_oracle_strength` (0.80) | `human` | green cannot license auto-delivery on a weak oracle |
| 5 | `stats.point < policy.min_point` (0.90) | `calibrate` | point below the bar |
| 6 | `stats.ci.low < policy.min_ci_low` (0.80) | `calibrate` | point ok, Wilson interval too wide |
| 7 | otherwise | `deliver` | `n`, point, `ci_low`, `false_q1=0`, oracle strength if measured |

So the published rule is: **`deliver` iff `n ≥ 10 ∧ point ≥ 0.90 ∧ Wilson-low ≥ 0.80 ∧
false_q1 = 0 ∧ (oracle strength ≥ 0.80 when measured)`**. Oracle strength is taken from the
explicit argument or, failing that, `stats.oracle_strength_mean`; when neither is measured
the condition does not apply and the decision's reason omits it, so an unmeasured oracle
is visible as an absence, not a pass.

**Reconciliation with the SPC rule.** The SPC variant (`σ ≤ 0.10`, `n ≥ 20`) becomes
**advisory**: `crb.core.stats.stddev` is available, σ is shown on the capability map beside
the Wilson interval, and a cell may carry an advisory "SPC not met" flag — but σ **never
gates** a route. The Wilson lower bound already penalises small `n` and high variance in
one published quantity; a second threshold on a second statistic would make the bar
unexplainable.

Every `RouteDecision` records the route, the reason string, the cell, `n`, `point`,
`ci_low`, `false_q1`, `oracle_strength` (or `None`) and `policy_version`. Thresholds live in
the frozen `RoutingPolicy` dataclass; a deployment may configure a **stricter** policy, and
the policy version it used is stamped on each decision.

## Consequences

- One rule, one function, one version string: an auditor can reproduce every route from
  the ledger rows and the policy.
- A cell with no measured oracle strength can still reach `deliver`. That is deliberate
  for P1–P2 (strength is measured from P2), but the UI must display "oracle: not measured"
  on such cells, and the operator guide says so.
- `calibrate` is the default outcome for anything under-evidenced; "the system must be
  capable of becoming less autonomous" — a later ledger row can move a cell from
  `deliver` back to `calibrate` or `do_not_ship` with no code change.
- Changing any threshold, the order of conditions, or the meaning of a route bumps
  `POLICY_VERSION` (and, because routing is part of the apparatus, `APPARATUS_VERSION`).
  The controls clauses are versioned separately as `CONTROLS_POLICY_VERSION` (see the
  amendment) so a decision names exactly the clause sets it was evaluated under.
- The SPC rule's consumers upstream are not ported; `change_router`'s decision *names*
  (`deliver`, `granularize`, `calibrate`, `do_not_ship`) are kept, plus `human`.

## Amendment (2026-09-13) — the negative-controls gate is a routing input

**Why.** The critical-friend review (`docs/reviews/2026-09-13-critical-friend.md`, §4.2
readings 2, 3, 6; action #4) found that the negative-controls gate had **failed** on
pallets/click (regression 7/7 violations under `TARGET_ONLY` belt scope — belt 3 blind)
while replay runs proceeded and the capability map showed their clean rows without
that caveat; and that on Go/JS repos only 3 of 7 controls are constructible, so "controls:
passed" meant "the three easy ones passed". Nothing in the rule above looked at the gate:
a cell could in principle reach `deliver` on a repo whose instrument was demonstrably
broken. The same review found 13 of 15 non-clean rows were the harness's doing, not the
model's — so every rate the product shows now carries the `failure_kind` split
(`builder_red · budget · protocol · harness · disqualified`, `crb.core.ledger`) and a
`model_point` **next to** the all-rows point. **The all-rows point stays the routing
input**: instrument errors count against autonomy until the instrument is fixed
(fail-closed); `model_point` is diagnostic, never a gate.

**Decision.** `route(stats, *, oracle_strength=None, controls=None, policy)` takes the
repo's `ControlsVerdict` — `passed` (no VIOLATION), `constructible`/`total` (control rows
actually built and graded over rows with a RED oracle), `escapes` (measurement controls
that graded clean), `run_id`, `created`, `complete`, `measured`. The rule is evaluated
**in this order**, first match wins (the numeric clauses are unchanged from the table
above; the controls clauses are inserted where their severity belongs):

| # | Condition | Route | Reason code |
|---|---|---|---|
| 1 | `false_q1 > 0` | `do_not_ship` | `false_q1` |
| 2 | size ∈ `granularize_sizes` | `granularize` | `granularize` |
| 3 | controls measured **and** `not passed` | `human` | `controls_failed` — an instrument defect on this repo; **outranks n**, so every cell of the repo carries the caveat, not only the green ones |
| 4 | `n < min_n` (10) | `calibrate` | `n_below_min` |
| 5 | oracle strength measured and `< 0.80` | `human` | `oracle_weak` |
| 6 | controls measured **and** `escapes > max_controls_escapes` (0) | `human` | `controls_escapes` — a deterministic cheat graded clean: the oracle cannot tell an implementation from a lookup table; green cannot license auto-delivery until the oracle is hardened and the controls re-measured |
| 7 | `point < 0.90` | `calibrate` | `point_below_bar` |
| 8 | `ci_low < 0.80` | `calibrate` | `ci_low_below_bar` |
| 9 | controls evaluated but **unmeasured** (no report for the repo) | `calibrate` | `controls_unmeasured` |
| 10 | controls measured and `constructible / total < min_controls_share` (0.5) | `calibrate` | `controls_thin` — "passed" means the easy controls passed; the load-bearing ones never ran |
| 11 | otherwise | `deliver` | `deliver` — reason records `controls=passed k/N escapes=0` |

So the published rule becomes: **`deliver` iff `n ≥ 10 ∧ point ≥ 0.90 ∧ Wilson-low ≥ 0.80
∧ false_q1 = 0 ∧ (oracle ≥ 0.80 when measured) ∧ (controls passed ∧ constructible/total ≥
0.5 ∧ escapes = 0, when a verdict is evaluated)`**. Thresholds live on `RoutingPolicy`
(`min_controls_share`, `max_controls_escapes`, `controls_version`).

**Escapes — the conservative option.** An escape is a finding about the oracle, not a
grader bug (ADR-0001, `crb.core.oracle.controls`), and the mutation score does not see it.
We chose the strictest reading the review allows: **any** escape on the repo withholds
`deliver` (route `human`) until a later controls run reports `escapes = 0`. The laxer
option — discount oracle strength by the escape rate — was rejected because it turns a
demonstrated hole into a number that can be averaged away; a deployment that wants it can
raise `max_controls_escapes` and the policy version stamped on each decision says so.

**Two clause sets, two versions — and what "not evaluated" means.** The numeric clauses
keep `routing.v1` (nothing about them changed; every decision that evaluates no verdict is
byte-identical to before). The controls clauses are `controls-gate.v1`, stamped on the
decision as `controls_policy` **only when a verdict was evaluated**; a decision made with
`controls=None` carries `controls_policy=""` and `controls=null`. That absence is a
deliberate, visible state, never a pass: the server's capability map and `/routes`
**always** evaluate a verdict — the repo's latest `controls.report` (the same source
`/oracle/{repo}/controls` serves), or `ControlsVerdict.unmeasured()` when there is none —
so the product surface is fail-closed. Callers that build a map from rows alone (the CLI
over a JSONL ledger, `crb.core.forecast`, the sign-off write path) do not evaluate one
today; ADR-0003's "one rule" stays one function, and the decision says which clauses it
was evaluated under. (Wave B's sign-off policy bar consumes the verdict at write time.)

**Verdict provenance.** The verdict is derived from the worker's `controls` run counts
(`rows − skipped` = total, `− not_constructible` = constructible, `escapes`, `passed`,
`complete`) by `ControlsVerdict.from_counts`; a cancelled (incomplete) run is still the
latest measurement and is reported as such — it is never silently upgraded to a complete
one. Every decision records `controls.run_id` and `controls.created` so an auditor can
re-read the report the route was taken under.

## Amendment (2026-09-16) — the rule gates the factory, and a policy names its bar

**Context.** The external review of 2026-09-16 (docs/reviews/2026-09-16-external-assessment.md,
points 9 and 36) found two gaps between what this ADR says and what the code did. (1) The
forward-mode factory delivered any clean build when `deliver` was on: the route decision was
rendered in the pull-request body but never consulted — the capability map described the
factory's boundary without enforcing it. (2) A `RoutingPolicy` could be built with looser
thresholds under the unchanged published version string, so a decision could read
`routing.v1` while clearing a lower bar, and a decision carried only the version name, not the
numbers.

**Decision.**

1. **The route gates delivery.** `FactoryLoop._deliver` asks the capability map for the
   item's (class × size) cell — the same signed map `GET /capability-map` serves, sighted rows
   of the current apparatus under the repository's latest controls verdict — and opens a
   branch and pull request only when it reads `deliver`. Any other route, or a cell nobody has
   measured, withholds delivery: the build is still graded and reviewed, the withholding is a
   `delivery.refused` event carrying the measured route, its reason code and the policy
   version, and no branch is pushed. An **approver** may override the gate for one run
   (`POST /runs {kind: factory, deliver: true, deliver_override: true}` — 403 for any lower
   role); the override is itself a `route.decided` event naming who overrode and the route
   they overrode, so the chain shows the human act, never a silent bypass.
2. **A policy names its bar.** `RoutingPolicy` refuses to be constructed looser than the
   published defaults on any clause under `POLICY_VERSION`; loosening needs its own version
   string (`crb route --policy-json '{"min_n": 3}'` is refused until it carries `"version"`).
   Tightening keeps the name — the rule holds and more. Every `RouteDecision` now carries
   `policy_thresholds` (the numbers) beside `policy_version` (the name), the symmetry
   `SignoffPolicy` already had.

**Consequences.** `deliver` on the map is now what it says: the boundary the factory
operates inside. A deployment that wants to ship under a relaxed bar can, and every decision
it produces says so by name and by number. The override path exists because an organisation
may have grounds the instrument cannot see; it is an accountable act, not a switch. Tests:
`tests/test_factory_loop.py` (withheld on `human`, withheld on no measurement, override on the
record), `tests/test_worker.py` (the worker feeds the signed map), `tests/test_routing.py`
(naming rule, thresholds stamped), `tests/test_server_routes_factory.py` (approver-only).

## Amendment (2026-09-19) — the gate reads the map as it stood before the run

**Context.** The first real factory run (B-1b, docs/reviews/2026-09-19-b1b-first-factory-pull-request.md,
findings 1 and 2; DL-045) showed two things the 2026-09-16 amendment left open. (1) The
gate was evaluated at delivery, after the item's own build had been graded and its
`process_step=factory` row appended: both pull-request bodies quoted `n=27` for a cell the
freeze had seen at `n=26`. It changed nothing there (26 and 27 both route *deliver*) but it
is circular at the margin — a clean build nudged the cell that licensed its own delivery.
(2) A rework after `accept_with_edit` could not reach the pull request it answered: the
re-push used a bare `--force-with-lease`, which has no remote-tracking ref to hold when the
push goes to a URL (git: `stale info`), and had it succeeded the loop would have opened a
second pull request for the same branch. One rework was one wasted build.

**Decision.**

1. **The route is read once per item, at readiness, before any build.** `FactoryLoop`
   asks the map (`route_decision_for`) in `_assess`, records the reading on the item's
   `route.decided` event as `cell_route` (`route`, `reason`, `reason_code`, `n`, `point`,
   `ci_low`, `false_q1`, `policy_version`, `apparatus_versions`; `null` when nobody measured
   the cell) and carries that one reading to the gate and into the pull-request body — a
   rework does not re-read it. The worker's lookup (`Worker._route_lookup(repo, run_id)`)
   **excludes the run's own ledger rows**, so the map that licenses a delivery is the map as
   it stood before the run; rows of every earlier run count as before. The API's
   `cell_route` on `GET /factory/{repo}/tasks` is the same reading (no run in flight, nothing
   to exclude).
2. **A re-delivery updates the pull request it already opened.** `deliver(previous=…)` pushes
   with `--force-with-lease=<branch>:<previous commit>`, refuses a different branch or base,
   opens no second pull request (url and number are carried over) and, through the
   `comment_pr_fn` seam (GitHub: `POST /repos/{owner}/{repo}/issues/{n}/comments` with the
   installation token), tells the reviewer which rework moved the branch, from which commit
   to which, under which verdict and pack. The chain records it as `delivery.updated`
   (the `delivery.opened` payload plus `previous_commit_sha`, `updated: true`, `rework`,
   `after_verdict`). A first push keeps the bare lease: it is what makes the factory refuse
   a branch that already exists on the remote. The comment is the optional step and it runs
   after the push has moved the remote branch, so its failure (a rate limit, a 5xx, a
   timeout) is **not** a delivery failure: the chain still records `delivery.updated`, with
   the redacted failure as `comment_error` (and `body_sha256` empty), the trace carries a
   `delivery.comment_failed` warning, and the item goes on to review the branch the pull
   request now carries — the record must agree with the remote, never say "refused" of a
   rework the pull request already shows.

**Consequences.** The pull-request body and the chain quote the same pre-run map, so a
reader can check the gate against `GET /capability-map` as it was at the freeze. A rework
costs one build and lands where the reviewer looks. The bare-repository test in
`tests/test_factory_delivery.py` reproduces the `stale info` refusal under real git before
proving the fix; `tests/test_factory_loop.py` pins one read per item before the first
build and one pull request across a rework; `tests/test_worker.py` pins the own-run
exclusion. The third B-1b rule (a `weak_oracle` verdict never triggers a rebuild against an
unchanged oracle) is DL-045's and is not part of this ADR.

## Amendment (2026-09-27) — the override has a floor and a second person, and the licence is for the change delivered

**Context.** An internal governance review of the delivery path (2026-09-27) found three
ways the 2026-09-16 gate could be passed that the rule never meant to allow. (1) GOV-1: the
one-run override delivered on any route the map refused, including `do_not_ship` for a
false-Q1 row — while a sign-off can never relax false-Q1 (`NON_OVERRIDABLE_REFUSALS`), one
approver could relax it for delivery. (2) GOV-4: the override was granted at enqueue by the
person queueing the run, so one approver both produced the build and licensed it past the
map, with no second person — unlike a sign-off (ADR-0016). (3) GOV-2: the route was read on
the item's DECLARED size (a ticket's story points), never checked against the MEASURED size
of the change delivered, so a ticket declaring XS could choose the cell whose evidence
licenses a much larger change.

**Decision.**

1. **The override has a floor.** `FactoryLoop._deliver` never honours an override on a cell
   that routes `do_not_ship`, carries `reason_code: false_q1`, or counts any false-Q1 row
   (an unreadable count is not a clean one): the delivery is withheld as `delivery.refused`
   with `override_refused: false_q1` and `override_by`, and the refusal names the floor.
   Every other reason code stays overridable.
2. **The override is a second approver's evented act.** `POST /runs` with
   `deliver_override: true` is refused 409 `same_actor` and queues nothing. The override is
   granted afterwards by another approver, `POST /runs/{id}/deliver-override` on a queued or
   running factory run that delivers: 409 `same_actor` for the run's own actor,
   `not_a_factory_run`, `run_terminal`, `delivery_off`, `override_already_granted`; the grant
   stamps `params.deliver_override_by` and appends a `system/run.deliver_override` event on the
   run's trace in one transaction. The worker reads the grant live at each item's gate
   (`FactorySpec.deliver_override_for`), honours it only for an account that holds the
   approver role at that moment, and the loop refuses one that names the run's own actor
   (`override_refused: same_actor`) — so no route can deliver on an override by the run's
   actor.
3. **The licence is for the size of the change delivered.** After the build, the final
   attempt's measured tier (`size_tier` of its source churn) is compared with the item's
   estimate. When it is larger, the route is read again for the (class × measured size) cell
   from the same pre-run map (DL-045's single reading), and that answer licenses the
   delivery; a measured cell that does not route `deliver` withholds it as
   `reason_code: size_exceeds_licence` with `size_estimate` and `size_measured` on the chain.
   The pull-request body names both sizes and the cell the licence was read on. A smaller
   change keeps the estimate's cell (a larger licence covers it). *Superseded by
   [ADR-0025](0025-routing-v2.md) item 12 (P-335): a smaller change is licensed by its
   measured cell too, so the measured cell's route is read whenever the sizes differ.*

**Narrowed at the Wave 2 integration (2026-09-28) by [ADR-0026](0026-the-context-standard.md)
item 8.** The route gate has no override any more: `deliver_override` lifts only a missing
sign-off, at the entry gate, before any spend. Decisions 1 and 2 govern that narrowed
override — its floor (`override_refused: false_q1`) and its second approver, read live at each
item's entry gate (`override_refused: same_actor`) — and decision 3 still governs the route
gate, after the delivered change's own licence (ADR-0025 item 12) has held.

**Consequences.** false-Q1 = 0 is a floor for delivery as it is for a sign-off; the
override is an accountable act by a person other than the one whose run produced the
evidence; and story points choose which cell is read first, never which cell licenses a
larger change. Tested by `tests/test_factory_loop.py`
(`test_no_override_lifts_anything_on_a_false_q1_cell`,
`test_the_sign_off_override_is_never_the_runs_own_actor`,
`test_a_change_larger_than_its_licence_is_withheld_size_exceeds_licence`,
`test_a_larger_change_is_delivered_when_its_measured_cell_routes_deliver`),
`tests/test_server_routes_factory.py::test_factory_delivery_fields_and_the_second_approver_override`
and `tests/test_worker.py::test_the_worker_honours_an_override_only_from_a_second_approver`;
DL-082.

## Inputs the rule does not read

*Added 2026-09-28 (DL-303, G-535).* The rule reads a cell's graded rows, its oracle, its negative
controls, its registered reading and the policy — nothing else. Two things a person might expect it
to read, it does not:

- **Merge outcomes.** Whether a delivered pull request was merged, closed or reverted
  (`outcome`, B-9) is recorded on the factory chain and shown on the Factory page. It feeds no
  clause of the rule in force.
- **Review verdicts.** A person's review of a kept patch (`accept`, `accept_with_edit`,
  `reject`) raises a rework row on the Decisions inbox and is kept as evidence. It feeds no
  clause either.

They are left out because neither is graded the way the rule's inputs are. A merge is a team's
choice under pressures the instrument does not see; a review verdict is one person's reading,
not yet anchored against a second. Either may only ever move a route through a **new,
pre-registered policy version** whose clause is graded on anchored reviews (two people, the same
patch, agreement measured), published as an amendment here with its own version string. Until
then a cell's route is the same whatever happened to the changes delivered from it. Tested by
`tests/test_routing.py::test_the_rule_reads_no_merge_outcome_or_review_verdict`, which fails if a
parameter of `route` or a field of any input it reads is named for an outcome, a merge, a review
or a verdict.

## Alternatives considered

- **Keep both rules and report both.** Rejected: two bars invite choosing the one that
  flatters a cell.
- **Adopt the SPC rule as the gate.** Rejected: σ of a 0/1 outcome is a function of the
  point estimate and adds no information beyond `n` and `p`; `n ≥ 20` alone would keep
  every small repository in `calibrate` forever without making the bar safer.
- **A learned / tunable threshold per repository.** Rejected for now: a bar that moves is
  not a published bar. A deployment may set a *stricter* `RoutingPolicy`.
- **Route on `point` alone.** Rejected: `[measured]` small-n cells routinely show 100%
  point with a Wilson lower bound far below 0.80.
