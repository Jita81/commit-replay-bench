"""crb.factory — forward mode: manufacture NEW work under the replay governance.

The replay bench (:mod:`crb.core`) grades a builder against a repository's own
held-out tests. Forward mode has no held-out test — the work does not exist yet —
so the factory *manufactures* the oracle first and then holds itself to exactly
the same four belts, the same evidence pack, the same ledger row, with
``process_step="factory"``.

The governed loop, per backlog item (the T9 pilot charter):

    register (frozen, hashed backlog)                         backlog.py
      → Definition-of-Ready: structural gaps signed off       readiness.py
      → RED proof: the authored test FAILS on the base        testfirst.py
      → build under the four belts, pack + ledger row         build.py
      → deliver as BRANCH + PR, never the default branch      delivery.py
      → independent review, verdict BEFORE any edit           review.py
      → every step appended to a hash-chained evidence file   evidence.py
    orchestrated, with events, by                              loop.py

Layering: this package imports ``crb.core``, ``crb.builders`` and
``crb.observability`` only. Store integration (``crb.store``) is a later
workstream; persistence here is JSONL behind the :class:`FactoryStore` protocol.

Navigation
----------
What it is:   The ``crb.factory`` package — forward mode's public surface and the map of its
              governed loop.
What it does: Re-exports the types and functions of each step (backlog, readiness, RED
              proof, build, delivery, review, evidence, loop) so a caller wires the loop
              from one import; the docstring above is the step order and the layering rule
              (core + builders + observability only, JSONL persistence).
How:          Plain re-exports; ``review()`` is deliberately not re-exported (it would
              shadow the submodule).
Layer:        factory — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0008-stdlib-core-and-downward-layers.md,
              docs/adr/0001-four-belts-and-false-q1-at-write.md
Works with:   src/crb/factory/loop.py (the orchestrator), src/crb/factory/backlog.py (step
              1), src/crb/factory/readiness.py (step 2), src/crb/factory/testfirst.py (step
              3), src/crb/factory/build.py (step 4), src/crb/factory/delivery.py (step 5),
              src/crb/factory/review.py (step 6), src/crb/factory/evidence.py (the ledger
              every step appends to), docs/API.md#factory-phase-p6
Tested by:    tests/test_factory_loop.py
Touch when:   never for a new repository; only when a new step type becomes part of the
              public surface (re-export it and extend the docstring's table).
"""

from __future__ import annotations

from crb.factory.backlog import Backlog, BacklogError, BacklogFrozen, BacklogItem
from crb.factory.build import BuildResult, OracleCommit, OracleTampered, build_item, build_ladder
from crb.factory.delivery import (
    DefaultBranchProtectionError,
    DeliveryError,
    DeliveryResult,
    GitCredentials,
    GitCredentialsProvider,
    NoGitCredentialsError,
    NullProvider,
    StaticProvider,
    assert_not_default_branch,
    deliver,
)
from crb.factory.evidence import FactoryEvent, FactoryEvidence, FactoryStore, JsonlFactoryStore
from crb.factory.loop import FactoryLoop, FactorySpec, ItemOutcome
from crb.factory.readiness import (
    Gap,
    GapSignoff,
    JsonlGapSignoffLedger,
    NotReady,
    Readiness,
    assess,
    require_ready,
)
from crb.factory.review import (  # ``review()`` itself is NOT re-exported: it would shadow the submodule
    EditBeforeVerdict,
    ReviewFinding,
    ReviewVerdict,
    SameIdentityError,
)
from crb.factory.testfirst import AuthoredTest, NotRed, RedProof, prove_red

__all__ = [
    "AuthoredTest",
    "Backlog",
    "BacklogError",
    "BacklogFrozen",
    "BacklogItem",
    "BuildResult",
    "DefaultBranchProtectionError",
    "DeliveryError",
    "DeliveryResult",
    "EditBeforeVerdict",
    "FactoryEvent",
    "FactoryEvidence",
    "FactoryLoop",
    "FactorySpec",
    "FactoryStore",
    "Gap",
    "GapSignoff",
    "GitCredentials",
    "GitCredentialsProvider",
    "ItemOutcome",
    "JsonlFactoryStore",
    "JsonlGapSignoffLedger",
    "NoGitCredentialsError",
    "NotReady",
    "NotRed",
    "NullProvider",
    "OracleCommit",
    "OracleTampered",
    "Readiness",
    "RedProof",
    "ReviewFinding",
    "ReviewVerdict",
    "SameIdentityError",
    "StaticProvider",
    "assert_not_default_branch",
    "assess",
    "build_item",
    "build_ladder",
    "deliver",
    "prove_red",
    "require_ready",
]
