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

---

## Amendment — Belt 1 covers test infrastructure (2026-09-13)

**Status:** Accepted (wave A, critical-friend review action #1)
**Apparatus impact:** the meaning of `tests_unmodified` changes → `APPARATUS_VERSION`
must be bumped when this lands (the wave lead bumps once for the whole wave).

### Context

Belt 1 protected the *test files*: byte-identical to the commit's own version (sighted),
plus, in blind mode, no `config.is_test` file touched before the overlay. But the oracle
is the test **run**, not the test **files**. For pytest that run executes every
`conftest.py` between the rootdir and the target, reads the first `pytest.ini` /
`pyproject.toml [tool.pytest]` / `tox.ini [pytest]` / `setup.cfg [tool:pytest]` it finds,
and imports `sitecustomize` from anything on `PYTHONPATH` (the worktree root is). For
jest the run loads `jest.config.*`, `package.json#jest` and the babel transform; for
`go test`, `go.mod replace` and every sibling `_test.go` (a `TestMain` that calls
`os.Exit(0)` is a green run); for Maven, `./mvnw`, `.mvn/maven.config` and everything
under `src/test`; for cargo, `build.rs` and `Cargo.toml [[test]]`.

`[measured]` The `env_poison` negative control — the source tree left as at the parent plus a
new root `conftest.py` that `exec`s the gold source into the module under test at
collection time — **escaped 3 of 7 times on click** (2026-09-13 review, §4.3). The
product's own docstring called that "a measured oracle escape — a finding, never a
violation". The reviewer disagreed, and was right: the control had modified the
instrument, not exposed a weak test. A motivated or merely confused builder could earn a
clean grade the same way, and the census `bug.fix` cells on Python repos would carry it.

### Decision

1. **Belt 1 = test files byte-identical AND no test-infrastructure file touched.** The
   check runs in both modes on the pre-run worktree — alongside belt 0 in blind mode
   (before the overlay), alongside the byte-identical check in sighted mode. Any touched
   file (tracked or untracked; added, modified, deleted, or either half of a rename)
   that `crb.core.test_infra.is_test_infra(path, language, runner=)` recognises fails the
   belt: `tests_unmodified=False`, `disqualified=True`,
   `dq_reason="test infrastructure modified: [...]"`, `tamper_files=[...]`, and a
   `grade.tamper` event with `kind="test_infra"`. The task's own test files are excluded
   from the check (the harness overlays them; belt 1a already holds them byte-for-byte).
2. **The pattern table is `crb.core.test_infra.INFRA_RULES`** — one row per pattern, per
   language, optionally per runner, each carrying the *reason* it is oracle-relevant.
   Matching is glob-over-path, case-insensitive, fail-closed. `tests/test_test_infra.py`
   holds a positive and a negative case for every row.
3. **Section-aware files are tamper only when their oracle-relevant sections change.**
   `pyproject.toml` (`tool.pytest`, `project.entry-points.pytest11`), `setup.cfg`
   (`[tool:pytest]`), `tox.ini` (`[pytest]`), `package.json` (`jest`, `mocha`, `babel`,
   `scripts.test|pretest|posttest`), `go.mod` (`replace`, `exclude`, `godebug`,
   `toolchain`), `pom.xml` (`<build>`, `<profiles>`, `<properties>`, `<parent>`) and
   `Cargo.toml` (`dev-dependencies`, `[[test]]`, `patch`, `replace`, `profile`,
   `package.build`, `lib.*`). A version bump or a new runtime dependency is an honest
   edit and grades on; `infra_sections_changed` decides. Unparsable, oversized or
   DOCTYPE-bearing content on either side is *changed* (fail closed).
4. **`Workspace.touched_files()` is "what the builder changed"**, and now guarantees:
   renames reported as deletion + addition (`--no-renames`); untracked files at any depth;
   git-ignored paths excluded *unless* the ignore rule is the builder's own (a rule added
   to a `.gitignore` since the parent, or a `.gitignore` the builder created, is pierced
   via `git check-ignore -v`); files the harness itself wrote at create time
   (`post_create` hooks, the `node_modules` link) excluded while byte-identical to what
   was written.
5. **The false-Q1 invariant is untouched.** A disqualified row was never clean; the belt
   is evaluated before any test runs, so a poisoned run is never executed at all.

### Consequences

- `env_poison` now grades `disqualified` on every constructible task; its verdict is
  `ok` (caught), never `ESCAPE`. `[measured]` on the Python fixture: root conftest → DQ in
  both modes; nested `tests/conftest.py`, `src/sitecustomize.py`, an edited, deleted or
  renamed `pytest.ini` → DQ; an honest `pyproject.toml` version bump or extra → clean.
  The same holds on the JavaScript (jest / mocha / vitest / node), Go, JVM and Rust
  fixtures (`tests/test_grade.py`, belt-1b section). The click controls must be re-run
  after the merge: the review's action #1 expects escapes → 0.
- Three assertions in `tests/test_oracle_controls.py` that encoded the old reading
  (env_poison = escape / regressed) must be updated to `disqualified` when this merges.
- Honest edits to a *whole-file* infra path (a legitimate `conftest.py` fixture, a real
  `jest.config.js` change) are lost observations, never false Q1s; a task whose commit
  itself touches such a file carries it in `test_files` and is graded on the overlaid
  bytes. Operators will see these as `disqualified` with the file named.
- Per-runner narrowing (`jest.config.*` is not the oracle under mocha) keeps the lost
  observations to files the configured runner actually reads; with no runner given the
  table is applied as the fail-closed union.
- Known residuals are listed in the module docstring: files a config *references*
  (`setupFiles`, `--require`), `package.json` `exports`/`main`/`type`, the `go` directive,
  module shadowing under `pythonpath_suffix` roots, and dependency trees (a sandbox
  concern, ADR-0005). Sighted-mode edits to *other* test files of the same language
  layout remain belt 3's problem unless a rule (Go `*_test.go`, JVM `src/test/**`, Rust
  `tests/**`) names them; a "belt-scope test files unmodified" rule is a candidate
  follow-up.
