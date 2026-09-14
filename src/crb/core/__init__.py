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
* :mod:`crb.core.signoff`   — human attestations (refused at write on false-Q1).
* :mod:`crb.core.federated` — abstract-cell export (allowlist, k-anonymity). Export only.
* :mod:`crb.core.legacy`    — importers for the census and Athena ledgers.
"""

from crb.core.version import APPARATUS_VERSION, __version__

__all__ = ["APPARATUS_VERSION", "__version__"]
