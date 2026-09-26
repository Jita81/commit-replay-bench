# Contributing to `crb`

This is a private product repository. Contributions follow the rules below; CI enforces
most of them, review enforces the rest. Read [ARCHITECTURE](ARCHITECTURE.md),
[EVIDENCE-AND-CLAIMS](EVIDENCE-AND-CLAIMS.md) and the [ADRs](adr/README.md) first.

## Development setup (uv)

```bash
# Python ≥ 3.12; uv on PATH (https://docs.astral.sh/uv/); git; docker for sandbox tests.
uv venv -q .venv --python 3.12
uv pip install -q -e '.[server,postgres,mcp,dev]' --python .venv/bin/python
# optional extras: '.[openai]' '.[claude]' or '.[all]'
```

The server, postgres and mcp extras are part of what the gates check: without them `mypy`
cannot see the server and store code, and the suite skips it. Run tools from the venv
(`.venv/bin/…`). Do not commit `.venv/`, `uv.lock` is not yet committed (see
[Known debt](ARCHITECTURE.md#93-known-debt-tracked)).

`mypy` and `ruff` are pinned to exact versions in the `dev` extra, so a fresh environment and
CI run the same versions of those two gate tools. Dependabot's `dev-tooling` group moves the
pins in a pull request of their own. The pins do not make the verdict the same: every other
dependency is resolved fresh on every run, and a new release of one can change what the same
`mypy` reports on the same tree. SQLAlchemy 2.1 did: `mypy` 2.3.1 on `main` at `8ab88ad`
reports no errors with SQLAlchemy 2.0.52 and 8 errors with 2.1.0 or 2.1.1 **[measured — n = 3
fresh `uv` environments whose resolved packages differ only in SQLAlchemy; method: `mypy` over
`src/crb` in each, 2026-09-25; apparatus 2.2]**. So CI also runs every day on `main`
with nothing changed: a new upstream release that moves a verdict fails there first, naming
the release, not on the next unrelated pull request.

## The gates

Every PR must pass all of these locally **and** in CI (`.github/workflows/ci.yml`):

```bash
.venv/bin/ruff check src tests
.venv/bin/ruff format --check src tests
.venv/bin/mypy                       # strict, over src/crb
.venv/bin/lint-imports               # crb.core stdlib-only + downward layers
.venv/bin/pytest -q -m "not sandbox_images" --cov=crb --cov-fail-under=70
```

The pytest line is the one CI's `test` job runs. `sandbox_images` is left out because it
builds the reference sandbox images, and CI's `sandbox-images` job runs it on its own.

CI additionally runs `gitleaks` (secrets), `pip-audit` (known vulnerabilities in the
resolved environment) and produces a CycloneDX SBOM.

No test may fail because of the machine it runs on. Running as root, with no docker daemon or
with no network is meant to change which tests run, not their results: builder settings in
tests name a non-root user or pin `os.getuid`, the doctor tests never ask the host's daemon, and a test that needs
a daemon or a network host is skipped with the reason when it is absent (under
`CRB_TEST_STRICT_WARMUP=1` an unreachable host is a failure instead, below). One whole-suite
run under all three conditions still had one failure, from timing rather than the host
**[measured — n = 1 whole-suite run at `b5e2b7f`, `-m "not sandbox_images"`, with uid 0
simulated by patching `os.getuid`, `DOCKER_HOST` pointing at nothing and HTTPS sent to a dead
proxy: 3957 passed, 97 skipped, 1 failed, and that one a wall-clock test that also passed 3
times of 3 alone under the same settings, on a host with a load average near 10; method:
pytest, 2026-09-26; apparatus 2.2]**, so this is a rule the suite is held to, not a guarantee
that it passes on every host. A test that needs something the machine may not have is
marked, and skipped with the reason when it is absent:

- `docker` — a docker daemon that answers `docker info`
- `toolchain(name)` — a language toolchain on PATH (go, node, mvn, cargo)
- `network(*hosts)` — outbound HTTPS to each named host; with no hosts named, the Python
  package index. `tests/conftest.py` asks each host once per session before the test runs
- `live` — model credentials
- `slow` — a long end-to-end test

Set `CRB_TEST_STRICT_WARMUP=1`, as CI does, to turn an unreachable registry or network host,
or a failed toolchain warm-up, into a failure instead of a skip: CI has the network, so there
an unreachable host is a defect. A missing docker daemon is always a skip.
No test may depend on the uid it runs as: name a non-root user when you build builder
container settings, or pin `os.getuid` before you build them (`tests/test_builders_container.py`
refuses a test that does neither).

**Run the full suite, not just your files.** A change to the core can alter a verdict
elsewhere; the negative-controls and census-re-derivation gates (P1) exist to catch that.

### The "never weaken a gate" rule

A PR may not: lower `--cov-fail-under`; add a `# noqa`, `# type: ignore` or
`ignore_imports` to make a failing check pass; mark a failing test `xfail`/`skip` without
a linked issue and a reason in the marker; remove or relax an invariant assertion in
`crb.core` (`FalseQ1Violation`, `SandboxUnavailable`, `LedgerIntegrityError`); or move a
threshold in `RoutingPolicy` to be **less** strict. If a gate is wrong, the fix is a
separate PR that says why, with an ADR when it touches verdict semantics. A reviewer who
sees a weakened gate rejects the PR.

## Layering contract

`crb.core` is **standard-library only** and layers depend **downward only**
([ADR-0008](adr/0008-stdlib-core-and-downward-layers.md)):

```
crb.cli | crb.server  →  crb.factory  →  crb.store  →  crb.builders | crb.observability  →  crb.core
```

Enforced by `[tool.importlinter]` in `pyproject.toml` and the CI `layers` job.

**Optional-layer convention.** A layer whose package does not yet exist is
**parenthesised** in the layers contract — e.g. `"(crb.cli) | (crb.server)"` — so
`lint-imports` passes while the reboot lands package by package. The PR that creates a
package **must remove its parentheses** in the same change; from then on the layer is
mandatory and a missing package fails CI. Never leave a package that exists parenthesised.

`include_external_packages = true` is required in `[tool.importlinter]` so that third-party
imports (`sqlalchemy`, `openai`, …) are visible to the forbidden contract.

## Code style (match the core)

- Frozen dataclasses with `to_dict` / `from_dict`; validation in `__post_init__`.
- Explicit types; `mypy --strict` clean; no `Any` where a type is known.
- Docstrings state the **invariant** a type or function upholds, not what the code does.
- Fail closed: a harness/sandbox/parse error is never a pass; timeouts are failures.
- No secrets in any stored string — pass through `crb.core.redact` (`redact_and_cap`).
- No import-time side effects. No third-party imports in `crb.core`.
- `ruff format` (double quotes, line length 100). Unicode in docstrings is fine.

## How to add a runner

1. Create `src/crb/core/runners/<name>_runner.py` subclassing `BaseRunner`. Implement
   `target_scope`, `belt_scope` (honour `TARGET_ONLY` / `AFFECTED_DIRS` / `BARE` /
   explicit list), `command` (return a `Command`; declare `writable_paths` the toolchain
   needs — build caches, report directories), `parse` (return a `TestRun`; set
   `parse_error` when failures cannot be attributed to test ids), `is_valid_oracle`.
2. Register it in `crb/core/runners/__init__.py` `_REGISTRY` and add the name to
   `crb.core.spec.RUNNERS`.
3. Add a fixture repository under `tests/fixtures/<language>/` with one red→green commit,
   and tests that replay it: RED at parent, gold clean, and each of the negative controls
   (no-op, stub, test-tamper, regression, hard-code, env-poison) gives the expected verdict.
4. Mark toolchain-dependent tests `@pytest.mark.toolchain("<tool>")` and, for the
   sandboxed path, `@pytest.mark.docker`.
5. Runners **never decide verdicts** — they report what the toolchain said.

## How to add a builder (P3+)

1. Create `src/crb/builders/<name>.py` implementing the `Builder` protocol; SDKs go behind an
   optional extra in `pyproject.toml` and a `[[tool.mypy.overrides]]` entry if untyped.
2. The builder receives only what its mode allows ([ADR-0004](adr/0004-builder-registry-sighted-and-blind.md)):
   never the belt scope, baseline, runner command or grader. It must honour the budget and
   return a `BuilderRef` with tokens, cost and latency.
3. Register it in the builder registry; add a hermetic test with an injected fake model
   function, and a `live`-marked smoke test keyed from the environment (skipped in CI).
4. The grader, not the builder, decides: assert on `GradeResult`, never on the builder's
   own report.

## How to add an ADR

1. Copy the format from [`docs/adr/README.md`](adr/README.md); next sequential number;
   file `docs/adr/NNNN-kebab-title.md`; status `Proposed` until merged, then `Accepted`.
2. State the decision so it can be checked against code: name the module/class/function
   that enforces it.
3. Tag evidence `[measured]` / `[hypothesis]` / `[aspiration]`.
4. If the decision changes the meaning of a verdict (belts, size table, class taxonomy,
   routing rule or thresholds), bump `crb.core.version.APPARATUS_VERSION` in the same PR
   and say so in the ADR header.
5. Add the row to the index in `docs/adr/README.md`. Supersede, never edit, an accepted ADR.

## Commit convention

Conventional Commits: `feat(core): …`, `fix(runners): …`, `docs: …`, `ci: …`, `test: …`,
`refactor: …`, `chore: …`. Scope is the package or area. Subject in the imperative, ≤ 72
characters; body explains *why*. Breaking apparatus changes use `!` and reference the ADR.
End commit messages with the attribution line required by the session/tooling that
authored them, when one is in force.

Branches: **`main` is the trunk** (from 2026-09-16; `reboot/v2` was the reboot's
integration branch until then — merged with a merge commit, so its history is on `main`,
and the branch is deleted). A branch exists only while its PR is open: merged and closed
PRs delete theirs. Feature branches
`feat/<area>-<topic>` / `fix/<area>-<topic>` / `docs/<topic>`; one PR per file-disjoint
workstream where possible. **Branch protection on `main` requires the CI jobs green and
the branch up to date before a merge** (lint, types, layers, code-map, dod, both
pytest matrices, PostgreSQL, security, container, walkthrough — the same commands you run
locally:
`pytest -m "not sandbox_images"`, `ruff check`, `ruff format --check`, `mypy --strict src scripts`,
`scripts/code_map.py --check`, `scripts/dod_check.py --check`,
`scripts/claims_check.py --check`, `lint-imports`,
`cd ui && npx tsc -b && npx vitest run`,
`helm lint --strict`); the adversarial verify pass (re-run the full suite on the merged
tree) before each release tag. The repository is public and Actions minutes are free, so
"CI is unavailable" is no longer a reason to merge on local gates (it was, for one day —
DL-035).

## Pull requests and third-party review (CodeRabbit)

From 2026-09-15 every change lands through a pull request into the trunk (`main`; a
release is a tag on `main`). **CodeRabbit** is attached to the repository and
reviews every PR automatically under `.coderabbit.yaml`, which carries per-package
instructions written from this product's own invariants (stdlib-only core, false-Q1 at
write, append-only stores, never-weaken-a-test, the header standard, the claims policy).
Its role is the independent reviewer's: to notice what the tests do not cover and say so on
the PR. Its verdict is **advisory to the humans who merge** — it is never read by the grader,
the routing rule or the sign-off policy (a model's opinion of a model's work is not evidence:
EVIDENCE-AND-CLAIMS §2). Address every finding in the PR (fix, or reply with the reason and
the evidence); `@coderabbitai review` re-runs it after a push, `@coderabbitai resolve` closes
addressed threads. The same reviewer sees the factory's own PRs when a client repository has
it attached — the third-party check on manufactured work that the factory's mechanical
reviewer cannot provide.

## Documentation

- Every number in the docs carries its tag and its method (see EVIDENCE-AND-CLAIMS).
- Cross-link rather than duplicate; ARCHITECTURE is the map, ADRs are the decisions.
- `CHANGELOG.md` follows Keep a Changelog; add an entry under *Unreleased* in the PR.
- Decisions taken by the owner/operator go in `docs/DECISION-LOG.md` (one line, dated).
