# ADR-0003 — One routing rule

**Status:** Accepted · **Amended 2026-09-13** (controls gate, §"Amendment" below)
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
