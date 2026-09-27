# ADR-0043 — A run keeps the spend cap it declares, and stops before the work that could pass it

**Status:** Proposed (north-star Wave 2, stream H — F5b)
**Date:** 2026-09-27
**Apparatus impact:** none. No belt, size, class, route or threshold changes meaning. An
attempt the cap refuses is never started, so it writes no row; the rows a capped run writes
are graded exactly as an uncapped run's are.

## Context

A `Budget` caps one attempt: turns, tool calls, wall clock, and a cost the operator may set.
Nothing capped a run. A measurement of thirty attempts had no ceiling, so the Measure and
Factory pages could only state an estimate, and their copy said so ("no spend cap yet").
The per-attempt cost cap alone is not a run cap. It also changes the experiment: a row's
`budget_tier` carries it, and two attempts that differ only in a cost cap are not the same
experiment. So a run cap must not be kept by quietly shrinking each attempt.

## Decision

1. **A build run (replay, blind, factory) may declare `max_cost_usd`**, the most its attempts
   may cost together. `POST /runs` stores it as `params.max_cost_usd`
   (`crb.server.routes.runs.new_run`), serves it as `RunOut.max_cost_usd`, and refuses it on
   a kind that makes no attempt.
2. **Spent is what the run's rows cost**, `cost_usd` summed over the run's `grades` rows, as
   the run page shows it (`crb.server.spend_cap.Spend.of_rows`). A reclaimed run counts
   what its first claim spent.
3. **Before every attempt the worker asks** (`RunSpec.admit` in `crb.core.run`, answered by
   `SpendCap.check`). It adds what the run has spent to the reserve for the next attempt.
   The reserve is the attempt's own cost cap when it has one: the builder stops there, so a
   run whose attempts are all capped never passes its cap. An attempt with no cost cap of
   its own is reserved at the dearest attempt the run has made so far. That is a guard, not
   a guarantee, and every page that names the cap says so. When the sum would pass the cap
   the run stops there. It stops before a worktree exists and before the builder is called.
4. **A factory run asks before every item** (the factory loop's `stop`). An item may take
   every rung, and every rung again for each rework, so it is reserved at all of them
   (`item_reserve`). The factory loop itself is unchanged.
5. **A stopped run is `failed`**, like the other stops a run makes itself (`outage_stop`,
   `env_stop`). It carries `counts.stopped_code: spend_cap`, the reason in `error` and
   `counts.stopped_reason`, and a `system/run.spend_cap` event. The event names the cap,
   what was spent, the reserve and where the reserve came from.
6. **A cap that cannot see a cost cannot be kept.** `POST /runs` refuses a capped run with a
   rung whose model has no known price: 422 `spend_cap_unpriced`, nothing queued
   (`spend_cap_refusal`, `unpriced_rungs`). On the worker, an attempt whose cost was not
   known stops a capped run at once.
7. **The pages name the cap they send.** The Measure page starts the cap at the top of its
   estimate and names it on the button. After a run stops at its cap, the page says so with
   the reason and a link to the run. The Factory page and the run form take a cap that is
   blank unless the operator types one.

## Consequences

- The Measure page's red button names a ceiling the run keeps, not only an estimate
  (`journey-measure.recovery.14`, `factory.actions.8`, `journey-operate.actions.15`).
- Near its cap a run stops early: it will not start an attempt whose own cap does not fit
  what is left. A run of uncapped attempts can pass its cap by the amount one attempt costs
  above the dearest attempt the run had seen. Set a cost cap per attempt when the ceiling
  must be exact.
- We must never keep the run cap by changing an attempt's own caps mid-run. The row's
  `budget_tier` would then describe an experiment that did not run.

## Alternatives considered

- **Clamp each attempt's cost cap to what is left of the run's.** Rejected. It changes the
  experiment mid-run and stamps rows with tiers no one declared (ADR-0004's budget tier).
- **Stop only once the cap is reached.** Rejected. The last attempt could then pass the cap by
  a whole attempt even when its own cost cap was known, which is the promise the page makes.
- **A deployment-wide cap per attempt (`CRB_BUILDER__MAX_COST_USD`, the assessment's C8).**
  Out of scope here. It caps an attempt, not a run. The definition of done names no criterion
  for it.
- **A new run status `stopped`.** Rejected for now. Every consumer of `RUN_TERMINAL` would
  change, and the run's self-stops are already `failed` with a named reason.
