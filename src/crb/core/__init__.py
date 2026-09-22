"""crb.core — the commit-replay engine.

STANDARD LIBRARY ONLY. This package must stay importable with nothing but a
Python 3.12 interpreter, git, and (optionally) docker on the host. The contract
is enforced by import-linter in CI (see ``[tool.importlinter]`` in
``pyproject.toml``).

The engine is deliberately small and mechanical:

* :mod:`crb.core.taxonomy`  — the closed change-class vocabulary (path + intent) as data.
* :mod:`crb.core.classify`  — the intent label, its evidence hash, and the one
  resolution rule (human > confident intent > path).
* :mod:`crb.core.spec`      — the vocabulary: languages, size tiers, path
  classifier, repo config, task spec (two class axes → one resolved class).
* :mod:`crb.core.git`       — a thin, argv-only git wrapper.
* :mod:`crb.core.execution` — where commands run: on the host, or inside a
  hardened, network-less container (fail-closed).
* :mod:`crb.core.runners`   — per-language test runners on ONE contract:
  ``(returncode, failing_test_ids, tail)``.
* :mod:`crb.core.workspace` — parent checkout + test overlay + gold overlay.
* :mod:`crb.core.mine`      — find replayable commits; RED-check; baseline; gold.
* :mod:`crb.core.grade`     — THE four-belt grader. false-Q1 = 0 by construction.
* :mod:`crb.core.evidence`  — the per-task evidence pack ("no pack ⇒ no Q1").
* :mod:`crb.core.ledger`    — append-only, hash-chained grade rows + cell stats.
* :mod:`crb.core.stats`     — Wilson intervals and friends.
* :mod:`crb.core.routing`   — the ONE published routing rule.
* :mod:`crb.core.oracle`    — oracle adequacy: mutation strength, negative controls.
* :mod:`crb.core.run`       — the run orchestrator (prep → build → grade → ledger).
* :mod:`crb.core.capability`— capability map, change profile, trusted autonomy coverage.
* :mod:`crb.core.forecast`  — ex-ante build forecast and readiness punch-list.
* :mod:`crb.core.signoff`   — human attestations (a policy decision, refused at write: false-Q1, thin cell, controls, oracle, route, attestation, the two-person rule).
* :mod:`crb.core.federated` — abstract-cell export (allowlist, k-anonymity). Export only.
* :mod:`crb.core.legacy`    — importers for the census and Athena ledgers.
* :mod:`crb.core.secrets_file` — owner-only secrets at rest (0700 dir / 0600 files,
  atomic writes, fingerprint-only status); shared by the builders and the server.
* :mod:`crb.core.lint`      — belt 5: the repository's own formatter/linter.
* :mod:`crb.core.test_infra`— belt 1b: which files are the oracle's execution environment.
* :mod:`crb.core.services`  — services the oracle needs (era-selected, fail-closed).
* :mod:`crb.core.review`    — human review ledger, anchored to the patch hash.
* :mod:`crb.core.learn`     — refusal triage, strengthening backlog, re-measurement plan.
* :mod:`crb.core.redact`    — credential redaction for everything that leaves the sandbox.
* :mod:`crb.core.version`   — ``__version__`` and ``APPARATUS_VERSION``.

Navigation
----------
What it is:   The package marker and index of the engine — the module list above is the
              map a reader walks.
What it does: Re-exports the two version constants; imports nothing else, so importing
              ``crb.core`` never pulls in a subsystem (the layering is enforced by
              import-linter, not by this file).
How:          One import from ``crb.core.version``; ``__all__`` names the two constants.
Layer:        core — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0008-stdlib-core-and-downward-layers.md
Works with:   src/crb/core/version.py (the only import), src/crb/core/grade.py (the module
              the package exists for), src/crb/core/ledger.py, src/crb/core/run.py
              (the orchestrator that ties the engine together), pyproject.toml (the
              import-linter contract)
Tested by:    tests/test_version_consistency.py (the re-export), tests/test_grade.py and the
              rest of tests/ through the modules listed above
Touch when:   a module is added to or removed from ``crb.core`` — keep the list above in
              step (docs/CODE-MAP.md is generated; this list is hand-kept); never add an
              import here.
"""

from crb.core.version import APPARATUS_VERSION, __version__

__all__ = ["APPARATUS_VERSION", "__version__"]
