# ADR-0058 — Mapping quote: a read-only price, time and precision for a first mapping

**Status:** Proposed (DL-426)
**Date:** 2026-11-18
**Apparatus impact:** none. APPARATUS_VERSION stays 2.6. No row, verdict, route, reading, set
digest or sign-off changes. The quote writes nothing and is read by nothing.
**Builds on:** ADR-0003 (one routing rule; the quote routes nothing), ADR-0025 and ADR-0026 (the
look rule; its first look is the default n), ADR-0024 and ADR-0019 §8 (the served arm and the
posture view the quote reads rows through) and ADR-0030 (the spend cap; `model_priced` reuses
its price check).

## Context

Before an operator maps a repository they need three figures: how many tasks would run, what
they would cost and how long the builder would take, and how precise the result would be. No
reader serves them for a first mapping.

`GET /forecast/build` prices only cells that already have rows; every other cell is listed as
unmeasured and priced at nothing. The remeasure plan handles only cells with rows or a reading,
and gives a cell with no reading an estimated cost of 0. A first mapping is exactly the
never-measured case. The Measure page shows a band computed in the browser, over the whole
repository rather than per cell, from a figure the server never checks.

A replay with no ladder runs one attempt per task (`["r1"]`), and every task it grades becomes
seen: a reserved reading registered later refuses it (`pool_seen`). So the quote also has to
say what is left for a reading after the mapping.

## Decision

1. **Read-only.** `GET /quote/mapping` (viewer) and the MCP reader `crb_mapping_quote` start
   nothing, write nothing and call no model and no network. The response carries no timestamp,
   so two reads of the same data give the same bytes. It prices a sighted replay, ladder
   `["r1"]`, one attempt per task, and says so in `run`.
2. **The request.** `repo` and `builder` are required. `model` defaults as `POST /runs` does
   (422 when the builder has none). `n` defaults to the first look of the routing rule and is
   1 to 1000. `cells` uses the forecast's `class:size:count` grammar (`*` means every size of
   the class; each count 1 to 1000; a size named on its own beats `class:*` for that size);
   empty means every cell with a task. `n` and `cells` together are refused (422): `cells`
   names each cell's count. `pool` is `standard`, `hard` or empty. `declared` is the caller's
   own `low:high` band in USD per attempt.
3. **Tasks.** Per cell, the tasks to run are the smaller of the count asked for and the
   gold-clean tasks available, the pool a replay draws from. The response serves `shortfall`
   and `left_after`. Only when the repository has no mined task at all are the cached change
   profile's counts used, served as an `[upper bound]`; a profile cannot split pools, so a
   `pool` is refused there. The route answers 409 `no_tasks` with no task and no profile, with
   a `pool` under the profile, and when tasks are mined but none is available and no cell is
   named (a named cell is served with 0 available).
4. **One cost basis per cell, best first.** A candidate row is a row a first mapping would
   write: it matches the cell, the builder and the model, and is a sighted replay row on rung
   `r1` under the `S3` brief (a row from before 2.4 carries no arm and is kept at its own
   apparatus). An imported row is another deployment's measurement and is never a candidate.
   A later rung holds only tasks that failed the first, and another arm carries a
   bigger brief, so neither is a first mapping's cost. Every candidate, this repository's and
   every other's, is read under the TARGET repository's checks arm and posture class (ADR-0024,
   ADR-0019 §8). `repo_cell` reads this repository's rows; `deployment_cell` (`[hypothesis]`,
   with `n_repos`) reads every other repository's; `declared` echoes the caller's band (low
   and high only); `unknown` serves `null` with a reason. A tier reads only the newest
   apparatus among its metered rows and needs at least 2. A metered row has a known cost and
   metered something (a cost or a token): a refused call such as an outage records $0 with no
   token and observed no cost, so it is left out rather than read as a free attempt. An
   unknown cost is never read as 0, and an unknown cell is never priced at $0. Every metered
   attempt counts, whatever its outcome, because the money was spent.
5. **The range.** With k known per-attempt values (mean m, sample sd s) and A attempts, the
   expected figure is A·m and the half-width is t975(k−1)·s·√(A + A²/k), low floored at 0: the
   Student-t 95% prediction interval for the sum of A new attempts. The method string and the
   per-attempt `mean_estimate` are served with it. A band from rows that are all the same has
   no width, and one from fewer than 5 rows is thin: its `reason` says so, because a narrow
   band there is not certainty.
6. **Time.** Minutes use the same formula on the same tier's rows with a recorded latency (2 or
   more, else `null`), divided by 60. Time never falls through to another tier. It is builder
   wall clock, summed as if run one after another; grading, set-up, mining and queue time are
   not included, and the response says so.
7. **Precision.** Each cell serves the Wilson 95% half-width at an assumed p of 0.5 for the
   tasks that would run, as a projection of precision, never a rate.
8. **Blind and never evidence.** The core reads a row only through a whitelist of fifteen
   fields (`CostRow`), none of them an outcome; the rung and the arm are read only to filter
   (item 4). No response key names a verdict, an arm, a route or a reading. The quote is
   `[hypothesis]`, routes nothing, licenses nothing and feeds no other reader. Totals add only
   the cells they count and name the rest; the expected total is `null` while any priced cell
   has no expected figure (a declared band), so it never sums fewer cells than low and high.

## Consequences

- An operator can see, per cell and before any spend, what a first mapping would run, cost and
  buy in precision, with the basis behind each figure and its row count.
- The quote's accuracy has never been checked against a real mapping [gap]. The first real
  mapping should be compared with its own quote: is the recorded spend inside low to high?
  Until then every figure stays `[hypothesis]`.
- Costs are right-skewed, so with few rows the normal-theory range can under-cover. The t factor
  and the served row count are the hedges.
- A fresh deployment gets `unknown` in every cell unless the caller declares a band. That is
  honest, but the first quote on a new install says "no basis".
- `deployment_cell` assumes cost per attempt transfers between repositories, although their
  size and language differ; it is tagged `[hypothesis]` and serves `n_repos`.
- Tasks already replayed are not subtracted: `available` counts them, so `tasks_to_run` may
  include tasks already graded and `left_after` may overstate what is still unseen for a
  reading [gap].
- The basis is the `S3` arm's rows. On a deployment that holds a blinded wave with an `S3` arm,
  the quote serves that arm's mean cost per attempt. It is a cost, not an outcome, but it is a
  figure by arm; query the quote outside the wave until a guard refuses such a basis [gap].
- Only `["r1"]` is priced. A multi-rung quote needs an escalation rate, an outcome [gap].
- A cell-targeted mapping needs `task_ids`, because `limit` does not target a cell; the quote
  does not yet serve them [gap].
- The Measure page still shows its own band. Replacing it with this quote is a UI follow-up
  [gap].

## Alternatives considered

- **Extend `forecast_build`.** Rejected: it routes, needs measured cells and would mix a
  projection into a forecast.
- **Empirical quantiles times n.** Rejected: it assumes every attempt sits at the extreme and
  makes the range far too wide.
- **A bootstrap interval.** Rejected: not byte-stable without a seed, and it costs more CPU.
- **The price table times assumed tokens.** Rejected: tokens come only from recorded rows.
- **Group attempts per task.** Rejected: under a ladder it shows which tasks escalated, and an
  escalation is a first-rung failure, an outcome.
- **A server-side default band.** Rejected: it would be a made-up number. The caller declares
  one instead, and it is echoed as theirs.
