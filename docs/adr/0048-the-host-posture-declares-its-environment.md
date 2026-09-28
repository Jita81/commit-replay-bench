# ADR-0048 — The host posture declares its test environment, and a package that names no failing test never subtracts

**Status:** Proposed (DL-143; stream Q2, P-210, P-211, P-212, P-213)
**Date:** 2026-09-27
**Apparatus impact:** rides apparatus 2.4 (the Wave 2 bump). The host posture's identity gains
a field, so every host-posture qualification is stale and is measured again for no model money
(ADR-0019 §3). One belt-3 case moves from `True` to `False`: a Go run in which a package fails
without naming a test while every test it names is in the baseline. No 2.3 row is re-derived.

## Context

The Wave 3 dress rehearsal (2026-09-27, apparatus 2.3, host posture `local/inplace/host-env`)
found two things about the instrument before any model was paid.

**D2 — the host's own tools reached the tests.** Homebrew `shellcheck` was on the worker's
`PATH`, so cobra's `TestBashCompletions` ran it at old commits and failed. 41 of 85 cobra
golds read red. Re-qualifying 25 of them with a `PATH` shim that hid `shellcheck` turned 17
green **[measured — n = 85 mined tasks, 25 re-qualified; method: the pilot's qualification
records; apparatus 2.3, host posture]**. The sealed Go image has no `shellcheck`, so the same
task qualified in one posture and not in the other, and no record said why. The host executor
passed an allowlist of variables through, but `PATH` was on it, and a posture's identity hashed
only the runner's own variables, so installing a tool changed neither the tests' world nor the
posture that named it.

**D6 — unattributed baselines.** 17 of the 46 gold-clean cobra XS and S tasks carried
`baseline_parse_error: unattributed failure (rc=1, no failing ids parsed)` and an empty
baseline **[measured — n = 46 tasks: XS 4 of 18, S 13 of 28; method: `cobra-tasks.json` from
the pilot store; apparatus 2.3, host posture]**. The cause is Go's normal red: the commit's new
test names a symbol the parent does not have, so the target package does not compile and
`go test -json` names no test. Checking how belt 3 treats such a task showed it is correct
(an empty baseline subtracts nothing, and a package that does not build is a `parse_error`
when nothing else is named). It also found one way it was not: the Go parser read only `fail`
events that name a test, so a package that failed to build *beside* a named failure was
dropped. When every named failure was in the baseline, belt 3 read "no new failures" while a
package no longer compiled. A fixture reproduced a clean grade on exactly that patch.

## Decision

1. **On the host executor, a runner's test environment is declared, never inherited.**
   - A runner lists the tools its tests may run by name (`BaseRunner.declared_tools`). Go:
     `go`, `gofmt`, `git` and the POSIX basics the sealed Debian image carries, plus the C
     toolchain when cgo is on. Python: the interpreter (as `python` and `python3`), `git` and
     the basics, with a virtualenv's own `bin` after them. Node: `node`, `npm`, `npx`, `git`
     and the basics.
   - A repository whose tests run another host tool declares it in `runner_opts.tools`.
   - `crb.core.runners.toolenv` links exactly those tools into a private, content-addressed
     directory. That directory is the whole `PATH`. Only `HOME`, `LANG`, `LC_ALL`, `TZ`,
     `TMPDIR` and the names the runner lists (Go: its caches and its module settings, such as
     `GOPROXY`) come from the executor's host environment. The command is marked
     `Command.declared_env`, and the host executor then passes nothing else, not even `PATH`.
   - The test run, the environment probe and the witness's probe all run in it. Under docker
     nothing changes: the image is the environment.
2. **The environment has an identity, and the posture carries it.** Each tool is recorded with its
   resolved path, its version line and the SHA-256 of its bytes. The digest covers each tool's name,
   version and bytes, the value of every passed name that is not a location (a locale, a time zone,
   `GOPROXY=off`), and which names are present. `Posture.environment` is `declared:sha256:<digest>`
   and is part of the `posture_id`; `Posture.environment_tools` names the tools for a reader and is
   not hashed, as `image_ref` is not. Both are on every qualification record (its `posture`) and
   every evidence pack (its `posture` block). A changed declared tool changes the posture, so the
   worker stops a run with `POSTURE_DRIFT` (whose fix now names a declared host tool beside
   ADR-0019's list) and the pool is qualified again. A tool that is merely installed changes
   nothing. A posture with no declared environment (a container, or a runner with no declaration
   yet) hashes exactly as before, so no sandbox record goes stale.
3. **A package that fails without naming a test fails belt 3, whatever else the run names.**
   The Go parser records every package whose `fail` event names no test of its own. With no
   test named anywhere, the base fail-closed rule applies as before. Beside named failures, the
   run carries `parse_error: unattributed failure (package … failed without naming a test)`,
   and belt 3 is `False` whatever the baseline holds. At qualification, a RED with such a part
   (a target package that did not build beside one whose test failed) is a build-failure RED:
   the probe must prove the posture can load it, and the belt scope's unattributed package is
   recorded as explained, never as a baseline id. The mine path without the gold check reads
   the same rule.
4. **What D6 tasks are, pinned.** A build-failure RED at the parent is qualified with its
   unattributed baseline recorded and an empty baseline. With that baseline, a patch that
   leaves another test failing fails belt 2 (Go's target scope is the package) or belt 3, and
   a patch that leaves another package unable to compile fails belt 3. Such a task can never
   grade clean on a wrong patch.

## Consequences

- Every host-posture pool is qualified again before its next replay (no model money). Host
  counts from the pilot do not carry over, as the pilot report already said for the sealed
  posture.
- A Go repository whose tests call a tool outside the list fails in the host posture until the
  repository declares it. That is the point: the measurement names what it depends on.
- The Maven and Cargo runners declare nothing yet. Their host commands still inherit the
  worker's allowlist, `PATH` included (P-212, G-758). Maven's reactor stops at the first
  module that fails, so modules after one with a baseline failure are never observed at the
  parent or after a patch (P-213, G-759, not yet reproduced).
- The builder's brief still shows the runner's own command. The builder's tool runs are not
  the grade, so its environment is not the declared one.

## Alternatives considered

- **A `PATH` of the declared tools' directories.** Rejected: on a Homebrew host `go`,
  `git` and `shellcheck` share `/opt/homebrew/bin`, so the directory is the leak.
- **Hash the worker's whole `PATH` into the posture.** Rejected as the guarantee: it would
  have made the pilot's pools drift instead of making them right, and any unrelated install
  would have staled every qualification.
- **Attribute a package's build failure as a synthetic test id.** Rejected for now: it changes
  every Go qualification's fingerprint and the RED's kind for the common D6 shape, and a
  `parse_error` already fails the belt closed. The cost is that a task whose belt scope holds
  a package broken at both the parent and the gold is refused (`QUAL_GOLD_NEW_FAILURES`)
  rather than qualified.
