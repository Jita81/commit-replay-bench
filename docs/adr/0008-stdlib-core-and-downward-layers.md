# ADR-0008 — Standard-library core and downward-only layers

**Status:** Accepted
**Date:** 2026-09-13
**Apparatus impact:** none

## Context

Upstream, importing the benchmark ledger module instantiated an ORM engine through a
package `__init__` chain; the grader was coupled to a web application; three copies of the
grading logic drifted `[observed by inspection of AthenaClaude `origin/main` on 2026-09-13
(the three: `commit_replay.grade`, `scripts/factorial/grade.py`,
`~/.expansion-bench/bench.py:grade`) — an inventory, not a measurement, and pre-`crb`
apparatus]`. An instrument that an NHS organisation must be able to audit — and
that a second team must be able to re-run to check our numbers — has to be small, have no
hidden side effects on import, and depend on nothing whose behaviour changes under it.
Python 3.12 ships `subprocess`, `hashlib`, `json`, `dataclasses`, `pathlib`, `re` and
`math`; that is everything the engine needs.

## Decision

1. **`crb.core` is standard-library only.** It must import cleanly with nothing but a
   Python ≥ 3.12 interpreter; `git` and (optionally) `docker` are the only executables it
   invokes. `pyproject.toml` declares `dependencies = []`; model SDKs, the ORM, the web
   framework and metrics clients are optional extras used only by outer layers.
2. **Layers depend downward only:**

   ```
   crb.cli | crb.server
        ↓
   crb.factory
        ↓
   crb.store
        ↓
   crb.builders | crb.observability
        ↓
   crb.core
   ```

   A layer may import the layers below it, never above; siblings (`cli`/`server`,
   `builders`/`observability`) may not import each other.
3. **Enforced, not advised.** `[tool.importlinter]` in `pyproject.toml` declares two
   contracts — `crb.core is standard-library only` (a `forbidden` contract listing every
   outer package and every third-party module we could plausibly reach for) and
   `layers depend downward only` (a `layers` contract). `include_external_packages = true`
   makes third-party imports visible to the checker. The CI `layers` job runs
   `lint-imports`; a broken contract fails the build.
4. **Optional-layer convention.** Until a package exists it is parenthesised in the layers
   list — `"(crb.cli) | (crb.server)"` — so the contract passes while the reboot lands
   package by package. The PR that creates a package **removes its parentheses** in the
   same change, making the layer mandatory from then on.
5. **Core style**: frozen dataclasses with `to_dict`/`from_dict`, explicit types
   (`mypy --strict` over `src/crb`), docstrings that state the *invariant* a type or
   function upholds, no import-time side effects, and fail-closed behaviour everywhere
   (a harness error is never a pass).
6. Extension points the core defines and outer layers implement: `Executor` (execution),
   `TestRunner` (runners), the `on_event` callback (`EventFn`) that observability adapts,
   and — in P3 — the `Builder` protocol.

## Consequences

- The grader can be embedded (in a CI job, a notebook, a second team's harness) without a
  database, a model SDK or a network; `docs/REPRODUCING-THE-CENSUS.md` (P7) relies on this.
- Anything the core needs that would normally come from a library must be written in the
  core (Wilson intervals, canonical JSON, redaction regexes) and tested there.
- The server cannot reach into the grader to "adjust" a verdict; the only way in is the
  public functions the core exposes, which enforce their invariants.
- Adding a new runner or executor does not require a new dependency; adding a new builder
  does, and it lives in `crb.builders` behind an extra.
- A contributor who forgets the layering finds out in CI, not in review.

## Alternatives considered

- **One package with "please keep it clean" guidance.** Rejected: upstream shows the
  outcome.
- **Allow a small set of vetted third-party packages in the core (e.g. `pydantic`).**
  Rejected: every dependency is a behaviour we do not control in the path that produces
  verdicts; validation is done by hand in `__post_init__`.
- **Separate repositories per layer.** Rejected for now: one repository, one CI, one
  version; import-linter gives the isolation without the release overhead.
- **Enforce layering with tests instead of import-linter.** Rejected: import-linter
  builds the full import graph (including external packages) and reports the violating
  chain; hand-written tests would only sample.
