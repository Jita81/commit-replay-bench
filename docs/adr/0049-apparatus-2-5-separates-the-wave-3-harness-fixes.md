# ADR-0049 — Apparatus 2.5 separates rows graded after the Wave 3 harness fixes

**Status:** Accepted (DL-417; the operator, Paul Glover, on 2026-11-10)
**Date:** 2026-11-10
**Apparatus impact:** bumps `APPARATUS_VERSION` to **2.5**. Nothing else moves: the belt set
stays `v5`, the failure rule is unchanged (its golden hash at 2.5 equals 2.4's), the mutation
scorer stays `mutation.v2`, and there is no migration and no schema change. What moves is the
stamp, and with it every posture id. Rows stamped 2.4 keep their meaning, are never re-graded
and are never pooled with 2.5 rows.

## Context

Wave 3 stage 1, graded at apparatus 2.4, showed three harness effects that change what a
measured row means **[hypothesis — read from the Wave 3 stage-1 report (#111) and its build
transcripts; the campaign's rows are not in this repository]**:

1. The Go toolchain's scratch files in the builder's `/tmp` disqualified builds under belt 1b.
   Pull request #113 mounts the builder's `/tmp` exec so the scratch files run where the
   toolchain expects them.
2. The builder's git guard refused `git -C <worktree>`, so a builder that names its worktree
   that way lost commands a builder that `cd`s first did not.
3. A row's `cost_usd` was the builder CLI's figure, not the product's price table: the Wave 3
   tally read $52.71 against about $21 at the table's prices **[hypothesis — the Wave 3 stage-1
   report's section 1, read from the campaign's tally and the stack's `grades` rows on
   2026-11-10, apparatus 2.4; those records are not in this repository]**.

The fixes for 2 and 3 are separate pull requests. Rows graded before and after these fixes are
different measurements, and nothing on a row can tell them apart. Economics and the forecast
separate rows only by apparatus, posture class, checks arm, context arm and class-set version
(`crb.core.economics`). The reserved-reading treatment fingerprint hashes the builder's settings
(`crb.server.worker._container_projection`), not the command line the builder code assembles
from them, so a fix in that code does not move it. No row label separates the waves.

DL-414 rejected an earlier 2.5 because there were no rows to separate. Now there are.

## Decision

1. `APPARATUS_VERSION` is `"2.5"` (`src/crb/core/version.py`). Every row graded from this
   change on is stamped 2.5.
2. Nothing else changes: belt set `v5`, the failure rule, `mutation.v2`
   (`crb.core.oracle.mutation.mutation_version` reads 2.4 and later as v2), routing.v2, the
   store schema. No migration.
3. The operator decided it on 2026-11-10, answering "Yes or no to bumping the apparatus version
   to 2.5 with a short ADR." with "yes to all four, go ahead".

## Consequences

**Easier.** A 2.5 row is graded with the harness fixes in force wherever they are deployed with
it; a reader separates the waves by the apparatus axis it already reads, and no reader changes.

**Harder.**

- The apparatus is part of a posture's identity (`Posture.apparatus_version`,
  `src/crb/core/posture.py`), so every posture id moves. Every task's qualification is missing
  at 2.5, and the run's posture gate (`Worker._posture_gate`, ADR-0019) qualifies it again
  before anything is built: test runs only, no model money. Some tasks qualified at 2.4 may not
  qualify again.
- Oracle scores, negative controls and sign-offs are read at one apparatus
  (`crb.server.factory_standard`, `crb.core.signoff`), so at 2.5 they are unmeasured or stale
  until they are redone. Only routing to `deliver` needs them.
- A reserved reading registered at 2.4 pinned its pool to a 2.4 posture. A run filed under it
  now grades in another posture, and the worker refuses it `pool_drift` before anything is built
  (`src/crb/server/worker.py`, P-797). The 2.4 readings are frozen.

**Must never.** Deploy this change to a stack while a 2.4 campaign on it is open: its remaining
runs would be refused. Close the 2.4 campaigns first. Deploy 2.5 to a stack without all three
harness fixes: rows graded at 2.5 without them would pool with rows graded with them, which is
the blend this version exists to prevent. This change merges after, or with, the three fixes.

**Open.** A 2.5 replay row still marks its commit seen for a future reserved reading
(`POOL_SEEN_FROM = (2, 4)` in `src/crb/core/reading.py` admits every later apparatus), so the
pool for a later reading shrinks as 2.5 rows are graded, as it did at 2.4.

## Alternatives considered

- **A row label for the harness fixes instead of a bump.** Every reader would need a new axis,
  and rows graded before the label existed would carry none, so they could not be separated
  from rows graded after it.
- **Fold the harness into the treatment fingerprint.** It covers reserved readings only, not
  economics or the forecast, and it still cannot tell an old row from a new one.
- **No bump.** The waves pool silently, which is the reason the apparatus stamp exists.
