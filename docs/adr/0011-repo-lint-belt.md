# ADR-0011 — Belt 5: the repository's own formatter/linter (`repo_lint_clean`)

**Status:** Accepted
**Date:** 2026-09-14
**Apparatus impact:** bumps `APPARATUS_VERSION` to `2.2`; new ledger belt set `v5`; new
failure kind `lint`; amends ADR-0001 (belt list) and ADR-0002 rule 2 (the hashed body)

## Context

ADR-0001's four belts say whether the repository's **held-out tests** accept a patch. They
say nothing about whether the **repository** would. `[measured]` The critical-friend review
(`docs/reviews/2026-09-13-critical-friend.md` §3.2, finding 1; §7 item 2; action #2)
re-ran cobra #1559 with the worktree kept: the AI's patch graded **clean** under all four
belts — and `gofmt -l` flagged `completions.go`. cobra's `.golangci.yml` enables `gofmt`
and its `.github/workflows/test.yml` runs `golangci-lint` on every PR: **the repository's
own CI would have rejected the patch before any human saw it**, and the capability map
called it deliverable.

"Clean" must therefore also mean *the repository's own definition of acceptable
formatting/lint holds on the files the builder changed*. That definition is the
repository's, never ours: the product runs the linter the repository configures, or
nothing. Imposing a linter a repository does not run (a `pyflakes` fallback, a house
`eslint` config) would measure our taste, not the repository's gate, and would fail
honest patches the repository would merge.

## Decision

1. **Belt 5, `repo_lint_clean`**, is evaluated in `crb.core.grade.grade()` after belt 4 on
   the **changed non-test files that still exist** in the trial worktree
   (`GradeResult.changed_files` minus deletions; test files and test infrastructure are
   belt 1's business). Its plan comes from ONE of:
   - `RepoConfig.lint` — the operator's declaration
     (`{"command": [argv…], "paths": "changed"|"all", "exts": […], "findings_rc": [1],
     "stdout_is_findings": false, "unrunnable_re": "", "timeout": 600}`), validated at
     config construction by `crb.core.lint.plan_from_config`; `{"disabled": true}` switches
     the belt off for the repo (an explicit `None`, never a default);
   - else the runner's language default, `BaseRunner.detect_lint` → `crb.core.lint.*_plan`,
     detected **only from the repository's own configuration** (table below);
   - else nothing: **the belt is not evaluated**.
2. **The value semantics** (`crb.core.lint`, the module docstring is normative):
   - `None` — *not evaluated*: no linter configured or detected, or (for a
     `paths="changed"` plan) no lintable changed file. **Neither a pass nor a fail.**
     `GradeResult.lint_run` is `None` (or carries the note) and no `grade.belt` event is
     emitted for a plan-less repo.
   - `True` — every step of the plan accepted the changed files.
   - `False` — a step **rejected** them (the tool ran and reported findings) or **timed
     out** (a timeout is a failure, as for belts 2 and 3). `False` is never clean.
   - A step that **could not run** (binary missing, rc 126/127, the tool's own abnormal
     exit code — `ruff` 2, `eslint` 2 — or output matching the tool's `unrunnable_re`) is a
     **harness error**: belt `False`, `GradeResult.error = "lint: …"`, and the row's
     `failure_kind` is `harness`. `[measured 2026-09-14]` a rustup proxy answers
     `cargo fmt --check` with **rc 1** (the findings code) and
     `'cargo-fmt' is not installed for the toolchain` when the component is absent;
     without `unrunnable_re` that reads as "the patch is unformatted". Exit codes are
     interpreted in exactly one place, `crb.core.lint._read_exit`, and anything the tool
     table does not name is not a pass.
3. **The clean rule, as amended** (`Belts.all_true`, `derive_clean`,
   `GradeRow.belts_all_true`):

   > `clean ⇔ belts 1–4 all True ∧ belt 5 is not False ∧ not disqualified ∧ no error ∧ an
   > evidence pack exists`.

   Every belt that was **evaluated** must hold; a belt that was not evaluated does not
   block. `Belts.evaluated` names the belts a result carries. The false-Q1 invariant is
   extended verbatim: a row with `repo_lint_clean=False` can never be clean —
   `FalseQ1Violation` at construction (`GradeResult`) and at write (`GradeRow`,
   `JsonlLedger.append`, `DbLedger.append`), plus the read-time SQL re-check in
   `/health` (`(belt_set = 'v5') AND repo_lint_clean IS FALSE`).
4. **The ledger records which belts a row's apparatus had.** `belt_set="v5"` for every
   row written by apparatus ≥ 2.2 (`grade_row_from_result`, the factory); `v4` and
   `v3-legacy` keep their meaning. Under `v5`, `repo_lint_clean` may be `None` (*not
   evaluated*) and that fact is **hashed**. Under `v4`/`v3-legacy` belt 5 is
   **unrecorded**: `GradeRow` refuses a non-`None` value there ("never re-interpreted"),
   `recorded_belts()` excludes it, and — **ADR-0002 rule 2, amended** — the hashed body
   `GradeRow.body()` is every field except `row_hash` *minus any belt added after the
   row schema froze that the row's belt set does not record*. A `v4`/`v3-legacy` row
   therefore hashes byte-for-byte as before (its `source_changed`, `None` on
   `v3-legacy`, was always in the body and stays there): an existing ledger — the
   census, an NHS deployment's store — keeps verifying after the upgrade.
   `to_dict()` still writes the unrecorded belt as `null` (the honest value); it is
   simply not part of the hash. `tests/test_census_gate.py` is unchanged and green.
5. **Failure kind `lint`** (`crb.core.ledger.FAILURE_LINT`): belts 1–4 held and belt 5
   rejected — *the model wrote working but non-conforming code*. Rule 6 of
   `derive_failure_kind`, after `budget` (a patch the model never finished is not
   evidence about its formatting) and before `builder_red` (a patch that fails a core
   belt is `builder_red` whatever the linter said). `FailureSplit` gains `lint` and
   `lint_evaluated` (how many of the `n` rows carried belt 5 at all — the denominator a
   reader needs before quoting `lint`); `model_n = clean + builder_red + lint`
   (a lint failure is a fair, finished attempt). `CellStats` gains `n_lint` /
   `n_lint_evaluated`; the API's split and cell shapes carry them; the UI shows `lint`
   wherever the split is shown.
6. **The store**: `grades.repo_lint_clean BOOLEAN NULL`, added in place by revision
   `0002` (`ALTER TABLE … ADD COLUMN`; no row rewritten, no trigger fired, triggers
   re-asserted). Its downgrade is refused while any `v5` row exists. Adoption of an
   unversioned `init_db` database is now revision-aware (`crb.store.migrate.
   REVISION_MARKERS`): a database created by an older release is stamped at the revision
   it is at and receives the missing revisions; one created by this release is stamped
   at head; one matching no release is refused.
7. **The negative controls do not evaluate belt 5** (`grade(..., evaluate_lint=False)`,
   the only caller). They measure the four *oracle* belts (ADR-0010) with synthetic
   edits that are not written in the repository's style: `[measured 2026-09-14]` with
   belt 5 live, the Go `env_poison` control — an oracle **escape** on the fixture — graded
   `repo_lint_clean=False` and read as `VIOLATION` ("unexpected outcome"), i.e. the
   formatter hid the escape; and a `gold` commit that predates the repository's linter
   would read as an instrument bug. A control row therefore records belt 5 as *not
   evaluated*; nothing about it is a builder trial.
8. **The UI** renders **five** belt pills when `belt_set == "v5"` and **four** otherwise
   (`BeltPills` / `beltNamesFor`); a belt the row's apparatus never had is not rendered,
   so it can never read as failed; a `v5` `None` reads "not evaluated — no linter
   configured for this repository". The evidence drawer shows the lint run (tool, files,
   redacted tail) as "Lint run (belt 5)". `RunTaskRow` carries the decisive attempt's
   `belt_set` for this.

### Per-language defaults and the CI evidence they rest on

Detection reads configuration files only (no network, no command runs); a binary without
its configuration is **not** evidence. `lint_run.detected` records which default applied.

| Language | Default plan (`detected`) | Detected when | Verdict reading | Evidence in the census clones (`~/.expansion-bench/repos`) |
|---|---|---|---|---|
| Go | `gofmt -l <changed .go>` (`gofmt`) | `go.mod` present (gofmt ships with every Go toolchain) | stdout non-empty ⇒ rejected (gofmt exits 0 and lists files); rc 2 (parse error) ⇒ rejected | **cobra** `.golangci.yml` → `formatters.enable: [gofmt, goimports]`; `Makefile fmt: test -z $(gofmt -l $(SRC))`; `.github/workflows/test.yml` job `golangci-lint` (`golangci/golangci-lint-action`) |
| Python | `ruff check --no-fix <changed .py>` then `ruff format --check <changed .py>` when the formatter is evidenced (`ruff`, `ruff+ruff-format`) | check: `[tool.ruff]` in `pyproject.toml`, or `ruff.toml` / `.ruff.toml`, or a `ruff`/`ruff-check` pre-commit hook; format: a `ruff-format` pre-commit hook or `[tool.ruff.format]` | rc 1 ⇒ rejected; rc 2 ⇒ harness (ruff's own error). `--no-fix` because click sets `fix = true` — the linter must never edit the builder's patch | **click** `pyproject.toml [tool.ruff]` (+ `[tool.ruff.lint] select = [B, E, F, I, UP, W, ICN]`); `.pre-commit-config.yaml` hooks `ruff-check` + `ruff-format`; `.github/workflows/pre-commit.yaml` runs `pre-commit run --all-files` on every PR |
| JavaScript / TypeScript | 1. `eslint <changed>` then `prettier --check <changed>` (`eslint`, `eslint+prettier`, `prettier`); 2. else `standard <changed>` (`standard`) | eslint: a flat or legacy ESLint config file or `package.json#eslintConfig` **and** `node_modules/.bin/eslint`; prettier: a prettier config or `package.json#prettier` **and** the binary; standard: `package.json#scripts.lint` starts with `standard` **and** the binary | rc 1 ⇒ rejected; rc 2 ⇒ harness (eslint config error) | **koa** `package.json scripts.lint = "standard"`, `.github/workflows/node.js.yml: npm run lint`. koa has **no** ESLint config — `node_modules/.bin/eslint` is present only as `standard`'s dependency; running it directly fails on "no configuration", a harness error dressed as a verdict. Hence *binary alone ≠ evidence* |
| JVM (Maven) | `mvn -o -q -B [flags] spotless:check` and/or `checkstyle:check` (`spotless`, `checkstyle`, `spotless+checkstyle`), module-wide (`paths="all"`) | `pom.xml` declares `spotless-maven-plugin` / `maven-checkstyle-plugin` | rc 1 ⇒ rejected | **gson** `pom.xml`: `spotless-maven-plugin` with the `check` goal bound; **petclinic** `maven-checkstyle-plugin` (`check` at `validate`); **commons-lang** `defaultGoal` includes `checkstyle:check` |
| Rust | `cargo fmt --check` and/or `cargo clippy --offline -- -D warnings` (`cargo-fmt`, `clippy`, `cargo-fmt+clippy`), crate-wide | fmt: `rustfmt.toml` / `.rustfmt.toml` or a CI workflow/Makefile line containing `cargo fmt`; clippy: `clippy.toml` / `.clippy.toml` or CI mentioning `clippy` | fmt rc 1 ⇒ rejected; clippy rc 101 ⇒ rejected; rustup "is not installed for the toolchain" ⇒ harness (`unrunnable_re`) | **clap** `.clippy.toml`; `.github/workflows/ci.yml` jobs `rustfmt` (`cargo fmt --check`) and `clippy` |

Not chosen, and why: a `pyflakes`/`pycodestyle` fallback for Python repos without ruff
(measures our taste); `npm run lint` as a generic JS default (arbitrary scripts cannot
take file arguments predictably; `standard` is the one evidenced script and is named
explicitly); `go vet` / `golangci-lint` by default (not shipped with the toolchain and
slow; declare them: `{"command": ["golangci-lint", "run"], "paths": "all"}`).

Tool versions: the belt runs the ruff/eslint/prettier the repository's environment
provides (the setup venv's `ruff`, `node_modules/.bin`); only when absent the host's, and
under a sandbox the image's. A version drift from the repository's pinned CI tool can
change a verdict at the margin; `RepoConfig.lint.command` pins it when that matters. The
resolved argv is recorded on every step.

## Consequences

- **The honest asymmetry.** A repository with no lint configuration has **no belt 5**: its
  rows are `v5` with `repo_lint_clean = null`, its cells show `lint_evaluated = 0`, and
  no claim about lint-cleanliness can be made for it. The capability map shows the
  coverage (`n_lint_evaluated` next to `n_lint`) so a reader never mistakes "no linter"
  for "lint-clean". A repository *with* a linter now has a stricter `clean` than before —
  which is the point: its `clean` now means what its CI means.
- **Pre-existing lint debt in a changed file counts against the patch**, exactly as the
  repository's CI counts it against the PR — the belt reproduces the CI verdict on the
  changed files, not a diff-scoped one. Such a row is `lint`, attributed to the model,
  although the debt was not the model's. The fair correction is the gold check: a task
  whose *maintainers' own* patch fails belt 5 is not a lint observation and should be
  `gold_clean=False` (excluded from the denominator, like a task whose gold fails belt 3).
  **Follow-up (not in this ADR's file set):** extend `crb.core.mine.gold_check` to run
  the same plan on the overlaid gold; until then the ADR names the residual.
- **`clean` rows from apparatus 2.1 and 2.2 are two populations.** `apparatus_versions` /
  `belt_sets` on every cell keep them apart; no number blends them (EVIDENCE-AND-CLAIMS
  §4–5). Cobra, click and koa must be re-measured under 2.2 before any 2.1 rate on them
  is quoted as current (Wave B14).
- **Cost.** One more command per graded trial (gofmt/ruff/eslint on a handful of files:
  sub-second; `mvn spotless:check`/`cargo clippy`: a build). The plan's `timeout`
  bounds it; a timeout is a `False`, never a hang.
- **What we must never do:** treat `None` as a pass in any aggregate; render an
  unrecorded belt as failed; let a linter *fix* the worktree (every default is a
  check-only invocation); read an exit code anywhere but `_read_exit`; re-derive belt 5
  for a `v4`/`v3-legacy` row.

## Alternatives considered

- **Lint the whole tree and diff findings against the parent (`golangci-lint
  --new-from-rev` style).** Rejected for now: needs per-tool finding parsers and line
  attribution; the CI-faithful whole-file verdict is what the repository itself applies,
  and the gold check is the honest place to exclude pre-existing debt.
- **A fixed house linter per language regardless of the repo.** Rejected: measures our
  taste, fails patches the repository would merge, and is not "the repo's own definition".
- **Make belt 5 fold into `builder_red`.** Rejected: the split must show *working but
  non-conforming* separately — it is the finding the review made, and it routes
  differently (a formatter pass fixes it; a red belt does not).
- **Belt 5 `None` ⇒ not clean (require every repo to configure lint).** Rejected: a
  repository with no lint gate would be failed for a gate it does not have; the honest
  statement is "no belt 5 for this row", made visible.
- **Hash `repo_lint_clean` on every row (including `v4`).** Rejected: every ledger written
  before this ADR would stop verifying; ADR-0002's tamper-evidence must survive the
  apparatus growing.
