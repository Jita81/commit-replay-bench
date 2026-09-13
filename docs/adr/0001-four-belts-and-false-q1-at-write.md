# ADR-0001 — Four belts and false-Q1 = 0 enforced at write

**Status:** Accepted
**Date:** 2026-09-13
**Apparatus impact:** defines `APPARATUS_VERSION = "2.0"` (belt 4 added relative to the three-belt census apparatus)

## Context

The product's only claim to honesty is that a verdict of `clean` cannot be wrong about
the mechanical facts it asserts. Upstream (AthenaClaude) the grader existed in three
divergent copies (`bench.py:grade` with four belts, `scripts/factorial/grade.py`,
`commit_replay.grade` with a three-bucket verdict), and the ledger's false-Q1 check ran at
**read** time only — a bad row could be written and would sit in the file until someone
read it back through the checking path. The census ledger also contains 706 rows graded
before the fourth belt existed.

A builder that can edit the tests it is graded against can pass trivially; a "pass" with
no source change is a build-cache ghost; a green target with a broken neighbour is a
regression; a harness error that surfaces as rc=0 is a silent pass. Each of these has been
observed upstream. `[measured]`: the negative-control matrix run 1 (upstream, 3 commits × 4
controls) agreed 12/12 with expected verdicts only because tamper and no-op were mechanical
checks, not judgement calls.

## Decision

1. **Exactly four belts**, defined in `crb.core.grade.BELT_NAMES`, all of which must be
   `True` for `clean`:
   - `tests_unmodified` — every target test file is byte-identical to the commit's own
     version (`Workspace.tests_byte_identical`: `git diff <sha> -- <paths>` **and** a SHA-256
     compare). A modified oracle **disqualifies** the trial (`disqualified=True`).
   - `target_green` — the target scope passes; a timeout is a failure (`TestRun.green`
     requires `returncode == 0 and not timed_out and not parse_error`).
   - `no_new_failures` — the belt scope's failing set minus the task's `baseline_failing`
     is empty; a belt run that timed out or produced unattributable output
     (`parse_error`) sets the belt `False`.
   - `source_changed` — `Workspace.touched_files()` minus test files is non-empty.
2. **Belt 0 (blind mode only):** if any test file was touched before the held-out tests
   are overlaid, the trial is disqualified (`dq_reason="blind: builder modified test files
   pre-overlay"`), because the overlay would otherwise silently erase the edit.
3. **Malformed oracle** (`runner.is_valid_oracle` false for any target test file) is a
   disqualification, never a pass or a fail.
4. **false-Q1 = 0 at construction:** `GradeResult.__post_init__` raises `FalseQ1Violation`
   whenever `clean=True` is requested with any belt not `True`, or with
   `disqualified=True`, or with a non-empty `error`.
5. **false-Q1 = 0 at write:** `GradeRow.assert_invariants` (called from `__post_init__` and
   again from `JsonlLedger.append`) refuses a `clean=True` row whose *recorded* belts are
   not all `True`, or that is disqualified / errored, or that lacks an
   `evidence_pack_hash` ("no pack ⇒ no Q1").
6. **Fail closed:** any exception inside `grade()` other than `SandboxUnavailable` is
   recorded as `error` (redacted, capped) with `clean=False`; `SandboxUnavailable`
   propagates so that the **run** stops (see ADR-0005).
7. **Legacy rows** carry `belt_set="v3-legacy"`; the invariant applies to the three belts
   they recorded (`GradeRow.recorded_belts`), and they are reported as a separate apparatus.
8. `derive_clean(belts, disqualified=, error=)` is exported so that imported rows can be
   re-derived and audited; `false_q1_total(rows)` is "the number everything else defends".

## Consequences

- No code path in any layer can produce a false-Q1 row; the product does not need a
  clean-up job, and a read-time re-check (`cell_stats.false_q1`, `route() → do_not_ship`)
  is belt-and-braces rather than the line of defence.
- A harness bug shows up as **errors** or **disqualifications** in the ledger, never as
  inflated pass rates. Operators must therefore watch `errors` and `disqualified` counts,
  which the UI shows beside `n`.
- Adding a fifth belt, or changing the meaning of one, is an apparatus change: bump
  `APPARATUS_VERSION`, add an ADR, and the ledger's `apparatus_versions` on every cell
  makes the boundary visible.
- Timeouts count as failures. A slow-but-correct change is scored as a failure at the
  configured timeout; the timeout is part of the apparatus stamp.
- The three-belt census rows cannot be re-graded into four-belt rows without re-running
  them; until then they are a separate population.

## Alternatives considered

- **Three belts (the census apparatus).** Rejected: `[measured]` build-cache ghosts —
  greens with no source change — were observed upstream and are not a legitimate
  observation of builder capability.
- **Enforce at read time only (upstream `BenchmarkRow`).** Rejected: a false row can be
  written, exported, and quoted before anyone reads it through the checking path.
- **A verdict enum (`ai_can` / `needs_human` / `fails`) instead of belts + `clean`.**
  Rejected: the enum hides *which* mechanical fact failed; the four booleans are the
  evidence, the enum was a summary. The routing layer, not the grader, decides what a
  failure means for delivery.
- **Let a model judge borderline cases.** Rejected on principle: the product is not an AI
  opinion of AI work.
