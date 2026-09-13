# Contributing to `crb`

This is a private product repository. Contributions follow the rules below; CI enforces
most of them, review enforces the rest. Read [ARCHITECTURE](ARCHITECTURE.md),
[EVIDENCE-AND-CLAIMS](EVIDENCE-AND-CLAIMS.md) and the [ADRs](adr/README.md) first.

## Development setup (uv)

```bash
# Python ≥ 3.12; uv on PATH (https://docs.astral.sh/uv/); git; docker for sandbox tests.
uv venv -q .venv --python 3.12
uv pip install -q -e '.[dev]' --python .venv/bin/python
# optional extras: '.[openai]' '.[claude]' '.[server]' '.[postgres]' or '.[all]'
```

Run tools from the venv (`.venv/bin/…`). Do not commit `.venv/`, `uv.lock` is not yet
committed (see [Known debt](ARCHITECTURE.md#93-known-debt-tracked)).

## The gates

Every PR must pass all of these locally **and** in CI (`.github/workflows/ci.yml`):

```bash
.venv/bin/ruff check src tests
.venv/bin/ruff format --check src tests
.venv/bin/mypy                       # strict, over src/crb
.venv/bin/lint-imports               # crb.core stdlib-only + downward layers
.venv/bin/pytest -q --cov=crb --cov-fail-under=70
```

CI additionally runs `gitleaks` (secrets), `pip-audit` (known vulnerabilities in the
resolved environment) and produces a CycloneDX SBOM. Tests that need infrastructure are
marked and skipped when it is absent: `docker`, `toolchain(name)`, `live` (model
credentials), `slow`.

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

Branches: `reboot/v2` is the integration branch for the reboot; feature branches
`feat/<area>-<topic>`; one PR per file-disjoint workstream where possible. CI green before
merge; the adversarial verify pass (re-run the full suite on the merged tree) before each
release tag.

## Documentation

- Every number in the docs carries its tag and its method (see EVIDENCE-AND-CLAIMS).
- Cross-link rather than duplicate; ARCHITECTURE is the map, ADRs are the decisions.
- `CHANGELOG.md` follows Keep a Changelog; add an entry under *Unreleased* in the PR.
- Decisions taken by the owner/operator go in `docs/DECISION-LOG.md` (one line, dated).
