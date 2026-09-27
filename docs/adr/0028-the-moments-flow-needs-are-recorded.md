# ADR-0028 — The moments the flow reading needs are recorded when they happen, never derived

**Status:** Proposed (DL-068; stream M, G-557 and G-558)
**Date:** 2026-09-26
**Apparatus impact:** none (no belt, size, class, route or threshold changes meaning; the
recorder only writes system events that the flow reading reads back).

## Context

The flow reading (`GET /flow`, stream M) folds each value stream's lead time, spend and counts
out of records the product already keeps. It stores nothing. Three moments that the streams'
MEASURE criteria name were not in any record:

- **the moment a cell first routed `deliver`** — the start of the decide stream's clock
  (`decide-and-license.measure.14`). The route is recomputed from the rows on every read, so
  the transition existed only while a page was open;
- **the install** and **the first green `/health`** — the run-the-platform stream's "time from
  install to first green `/health`" (`run-the-platform.measure.14`). Nothing stamped either.

The flow reading therefore served them as "not captured" (G-557, G-558). Deriving them from
neighbouring records would have produced numbers nobody measured: dating a cell's transition
from its tenth row ignores the controls verdict and the oracle strength the rule also reads,
and dating an install from the oldest row in the database dates an upgrade as an install.

## Decision

1. **Record each moment once, as a system event, when the product itself observes it.** One
   module, `crb.server.flow_record`, writes them; `crb.server.flow` reads them back.
2. **A cell first routes `deliver`.** After every finished run, the worker reads the map it
   serves by default (the same `_served_map` its route gate reads: sighted rows, the current
   apparatus, the repository's own checks arm, this deployment's posture class, the latest
   controls verdict) and hands the cells routing `deliver` to the recorder. A cell is
   stamped `cell.routed_deliver` once per scope (apparatus × posture class × checks arm),
   with the run after which it first routed. Rows change only through runs, so the end of the
   run is the moment the product first knew. The first look at a repository in a scope writes
   `flow.recorder_started` naming the cells already at `deliver`: their first moment passed
   before anything recorded it, so they are counted and never timed.
3. **The install.** At every server start, before the bootstrap admin writes the first row,
   `deployment.installed` is written if none exists — `moment: observed` when the database
   held no account, event or repository (this start is the install), else `moment: unknown`
   (an existing deployment upgraded to this release). An unknown install is never dated.
4. **The first green `/health`.** The first `/health` read whose status is `ok` writes
   `deployment.first_healthy`. `degraded` is not green. Concurrent first reads may both write;
   every reader takes the earliest. This one IS stamped on a read, because a read is how
   health is observed: the chart's readiness probe polls `/api/v1/health`, so under the chart
   the first green read follows the first green state by at most one probe period.
5. **Observability, never a verdict.** A recorder failure is logged; the run, the start and
   the health answer stand. Nothing here changes a route, a grade or a sign-off.
6. **A stamp is read only within its own scope** (amended 2026-09-27, after independent
   verification found a stamp of an old apparatus dating a current signature). Every
   `cell.routed_deliver` payload carries the apparatus, posture class and checks arm it was
   recorded in. A signature is paired only with a stamp of its own cell whose apparatus is
   one the record was stamped at, whose posture class is the record's and whose checks arm is
   the record's — the three things a sign-off must cover to lift a cell at all
   (`SignoffRecord.covers_apparatus` / `covers_posture` / `covers_arm`). A stamp or a record
   that names no scope pairs with nothing. So a cell already at `deliver` when recording
   began in the record's scope stays counted and never timed, whatever another scope
   recorded.
7. **The deployment's account figures are an admin's** (amended 2026-09-27). The platform
   stream's account counts and its recovery lead time are served only to an admin, the line
   `GET /users` already draws: with n = 1 the recovery lead time is one person's recovery,
   timed. Anyone else reads the lead time as unmeasured with that reason, and no account
   count.

## Consequences

- The decide stream shows "cell first routed deliver → cell signed" per sign-off, pairing
  each signature with the latest first-deliver stamp of its cell, in its own scope, at or
  before it; the
  platform stream shows "installed → first green /health" when both are observed. G-557
  and G-558 close; how many go-live lines are proven stays open under G-584.
- A deployment upgraded to this release shows its install as unknown, and cells already at
  `deliver` when it first ran as counted but not timed. Those figures fill in only from what
  happens next — the honest price of not back-dating.
- Every finished run now reads the served map once more (the same fold the route gate does
  for a factory run). A repository's first finished run writes one `flow.recorder_started`
  event.
- Must never: back-date a moment from a neighbouring record; time an inherited or unknown
  moment; pair a stamp with a signature of another scope; serve the account figures below
  admin; let the recorder fail a run or a start.

## Alternatives considered

- **Derive the transition by replaying the rows in time order** (as the value scorecard's
  prospective routing does). Rejected: that replay evaluates the numeric clauses only, not
  the controls verdict or oracle strength the served route reads, so it would date a
  transition the map never made.
- **Stamp on read** (when `GET /capability-map` first shows a cell at `deliver`). Rejected: a
  read that writes is a side effect a viewer triggers, and the moment would depend on when
  somebody happened to look.
- **Date the install from the oldest record.** Rejected: on an upgraded deployment that is
  the oldest surviving row, not the install.
