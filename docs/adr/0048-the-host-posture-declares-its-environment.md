# ADR-0048 — The host posture declares its test environment, and a package that names no failing test never subtracts

**Status:** Proposed (DL-143, DL-150; stream Q2, P-210 to P-219)
**Date:** 2026-09-27
**Apparatus impact:** rides apparatus 2.4 (the Wave 2 bump). The host posture's identity gains
a field, so every host-posture qualification is stale and is measured again for no model money
(ADR-0019 §3). Belt-3 cases move from `True` to `False`: a Go run in which a package fails
without naming a test while every test it names is in the baseline; a Go belt narrower than
the module while a package outside it no longer builds; and a Go or pytest run whose test
process stopped before every test reported. A target run whose process ended before its tests
reported moves from green to not green. No 2.3 row is re-derived.

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
   - Nothing can be put over the declaration (DL-150, P-215). A `runner_opts.env` that sets
     `PATH` or a library-loader variable (`LD_PRELOAD`, `LD_LIBRARY_PATH`, `DYLD_*`) is
     refused with a `ValueError` before any test runs, as a malformed `tools` is. A pinned
     toolchain is named in its own field (`go`, `python`, `node`, `npm`), which is declared
     and digested. A pinned `node` also leads the `PATH` of the node runners' setup, so an
     engine-strict repository's `npm` runs under it.
   - No host configuration file is read (P-216). Every declared environment sets
     `GIT_CONFIG_NOSYSTEM=1`, `GIT_CONFIG_GLOBAL=/dev/null` and `PYTHONNOUSERSITE=1`, and the
     Go runner sets `GOENV=off`, so a `go env -w GOARCH=…` file, a `~/.gitconfig` or a
     per-user `site-packages` under `HOME` never changes a result. `HOME` is still passed
     through, for the caches that live under it. The settings a deployment needs (`GOPROXY`,
     `GOPRIVATE`) arrive as passthrough names and are hashed by value.
   - The farm root sits in a shared temporary directory by default, so it is made `0700`,
     and it is refused when it is a link or belongs to another user (P-215).
2. **The environment has an identity, and the posture carries it.** Each tool is recorded with its
   resolved path, its version line and the SHA-256 of its bytes. The digest covers each tool's name,
   version and bytes, the value of every passed name that is not a location (a locale, a time zone,
   `GOPROXY=off`), which names are present, and what each directory after the farm on `PATH`
   holds: each executable entry's name and SHA-256. That directory is the repository's own
   virtualenv `bin`, when `runner_opts.python` or the setup venv names the interpreter, so a
   console script added there moves the digest. With no interpreter configured the tests run
   under crb's own, and only `python` and `python3` are linked: crb's own `bin` (ruff, mypy,
   crb) never reaches a repository's tests (P-215). A bare interpreter name is looked up on the
   executor's `PATH`, not the process's. `Posture.environment` is `declared:sha256:<digest>`
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
   a patch that leaves another package unable to compile fails belt 3, including a package
   outside a target-only belt (item 5). Such a task can never grade clean on a wrong patch.
5. **A belt narrower than the module still sees every package build (DL-150, P-214).** A Go
   belt scope that is not the whole module (the pilot's cobra shape: the target package alone)
   runs a module build gate after the belt: `go test -json -run ^$ -vet=off ./...`, which
   compiles and links every package and its tests, offline as the belt is, and runs no test.
   A gate that fails makes the belt run unattributed, so belt 3 is `False`. Every belt-scope
   run goes through `BaseRunner.run_belt_for` (the grade, the qualification's baseline and
   gold, the gold witness's belt control, the miner and the factory), and a test refuses a
   belt-scope run that bypasses it. The gold must pass the gate at qualification, so a module
   that does not wholly build in a posture has its tasks refused there
   (`QUAL_BASELINE_UNATTRIBUTED` for a RED that names its tests, `QUAL_GOLD_NEW_FAILURES`
   otherwise), never graded against a patch.
6. **A test process that stops before every test reported is unattributed (DL-150, P-217).**
   The Go parser names a test that has a `run` event and no `pass`, `fail` or `skip` (its
   binary died during it: `os.Exit`, a background goroutine's panic) as failing, and makes
   the run unattributed: the tests after it never ran. A package with named failures whose
   binary never printed its own `FAIL` line died after a failure it reported (a test that
   panics), so it is unattributed too. A Go package that passed without its
   binary's own `PASS` line (an `init` that calls `os.Exit(0)`) is unattributed, so a target
   with no test run is never green. The pytest parser makes a session unattributed when it
   exits with a code other than 0 or 1, prints a stop banner (`KeyboardInterrupt`,
   `pytest.exit`, `stopping after N failures`), or exits 0 with no result line at all
   (`os._exit(0)`).

## Consequences

- Every host-posture pool is qualified again before its next replay (no model money). Host
  counts from the pilot do not carry over, as the pilot report already said for the sealed
  posture.
- A Go repository whose tests call a tool outside the list fails in the host posture until the
  repository declares it. That is the point: the measurement names what it depends on.
- The Maven and Cargo runners declare nothing yet. Their host commands still inherit the
  worker's allowlist, `PATH` included (P-212, G-791). Maven's reactor stops at the first
  module that fails, so modules after one with a baseline failure are never observed at the
  parent or after a patch (P-213, G-792, not yet reproduced).
- The oracle controls' compile checks (`crb.oracle.controls`) and belt 5's lint plan
  (`crb.core.lint.run_plan`) still run with the executor's inherited `PATH`, so an installed
  tool could still move an oracle-strength or a lint verdict (P-219, G-793). The builder's tool
  runs are not the grade, so its environment is not the declared one, and the builder's brief
  still shows the runner's own command.
- The node runners' parsers have not been checked for a test process that exits before every
  test reported (P-218, G-794, not yet reproduced).
- The module build gate costs one more `go test` per belt-scope run of a narrow belt, and a
  module with a package that does not build in the posture (one needing cgo on a host without
  it) loses its tasks at qualification instead of grading them.
- The pilot's 17 D6 cobra tasks were not "safe to freeze" under their target-only belt before
  the gate: a patch that broke `./doc`'s build through the root package's API would have
  graded clean. They are qualified again with the gate before any pool is frozen.

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
