# ADR-0003 — One routing rule

**Status:** Accepted
**Date:** 2026-09-13
**Apparatus impact:** defines `routing.POLICY_VERSION = "routing.v1"` (stamped on every `RouteDecision`)

## Context

Upstream carried **two** routers with different bars and no shared consumer:

| Source | Rule for auto-delivery | Consumer |
|---|---|---|
| `tuning/catalog_router.py` — the **published** rule (the essay's "≥ 90% point and ≥ 80% lower bound on enough samples") | `n ≥ 10 ∧ point ≥ 0.90 ∧ Wilson-lower ≥ 0.80` | none |
| `tuning/change_router.py` / `benchmark_capability.py` — the **SPC** rule | `yield ≥ 0.85 ∧ σ ≤ 0.10 ∧ n ≥ 20` | change router |

The oracle-adequacy gate (`scripts/oracle_challenge/adequacy_gate.py`) existed but was wired
to nothing, although `[measured]` (upstream, n=19 tasks) showed oracle strength varies enough
across tasks that a clean grade alone must not license auto-delivery. Two rules with
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
- The SPC rule's consumers upstream are not ported; `change_router`'s decision *names*
  (`deliver`, `granularize`, `calibrate`, `do_not_ship`) are kept, plus `human`.

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
