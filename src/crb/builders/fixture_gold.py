"""``fixture_gold`` — a TEST-ONLY builder that replays the commit's own source change.

This is an *instrument check*, not a builder under measurement. It exists so the
whole pipeline — mine → build → grade → evidence pack → ledger → capability map
— can be driven end-to-end hermetically (no model, no network, no credential):
the browser walkthrough (``scripts/walkthrough.sh``) and CI use it to prove
that a run which *should* grade clean does, and that every number on every
screen is derived from real rows.

It does exactly what the ``gold`` negative control does: overlay the commit's
non-test files onto the parent worktree (``Workspace.overlay_sources``). Under
the protocol every real builder is held to (:data:`~crb.builders.base.DEFAULT_RULES`)
that is *git archaeology* — recovering the real patch — so a row it produces
must never be mistaken for a measurement of a builder. Three guards make that
impossible to do by accident:

1. **Registration is opt-in.** :mod:`crb.builders` registers the name only when
   ``CRB_ENABLE_FIXTURE_BUILDER=1`` is set in the worker's environment; without
   it ``get_builder("fixture_gold")`` is an unknown-builder ``ValueError`` exactly
   like any other typo. Production deployments (``deploy/``) never set it.
2. **The identity is unmistakable.** ``name`` is ``fixture_gold``, the model is
   forced to ``gold`` whatever the rung says, ``provider`` is ``fixture`` and
   ``describe()`` / ``BuildOutcome.extra`` carry ``fixture: true`` and a
   ``warning`` string, so every ledger row, evidence pack and capability cell
   names the fixture in its builder/model columns.
3. **It spends nothing and claims nothing.** ``cost_usd`` is ``0`` with
   ``cost_known=True`` (a fixture has a known price: zero), there are no tokens
   and no transcript, and ``done`` is left ``False`` — the grader decides.

The abstract-cell export (``/ledger/export/abstract``) and any federated
learning MUST exclude ``builder == "fixture_gold"`` rows; they measure the
instrument, not a model.

Navigation
----------
What it is:   The test-only ``fixture_gold`` builder — an instrument check that replays the
              commit's own source change so the whole pipeline can be driven with no model.
What it does: Overlays the commit's non-test files onto the parent worktree and returns an
              outcome that names itself unmistakably (builder ``fixture_gold``, model
              ``gold``, provider ``fixture``, ``extra.fixture: true``), spends nothing and
              claims nothing (``done=False``). It is registered only under
              ``CRB_ENABLE_FIXTURE_BUILDER=1``.
How:          ``source_files``: the commit's changed files minus tests and deletions →
              ``Workspace.overlay_sources`` → a zero-cost ``BuildOutcome``.
Layer:        builders — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0004-builder-registry-sighted-and-blind.md
Works with:   src/crb/builders/__init__.py (the opt-in registration), src/crb/core/workspace.py
              (``overlay_sources``), src/crb/core/oracle/controls.py (the ``gold`` control
              does the same overlay — the two must agree), scripts/walkthrough.sh and
              tests/fixtures/builders_repo.py (the hermetic drivers), src/crb/core/federated.py
              (the abstract export that must never carry these rows)
Tested by:    tests/test_builders_fixture_gold.py
Touch when:   never for a new repository and never in production — the switch stays unset
              in deploy/ (docs/DEPLOYMENT.md); a change to what ``gold`` means is a change
              to the negative control first.
Claims:       A ``fixture_gold`` row measures the instrument; it must never be read, summed
              or exported as a builder result (docs/EVIDENCE-AND-CLAIMS.md).
"""

from __future__ import annotations

import os
import time
from collections.abc import Mapping
from typing import Any

from crb.builders.base import (
    STOP_DONE,
    Budget,
    BuildBrief,
    BuildOutcome,
    EventFn,
    emit,
)
from crb.core.workspace import Workspace

#: The environment switch that registers the builder (``1`` only).
ENABLE_ENV = "CRB_ENABLE_FIXTURE_BUILDER"

NAME = "fixture_gold"
MODEL = "gold"
PROVIDER = "fixture"

WARNING = (
    "fixture_gold replays the commit's own source change (git archaeology by design); "
    "it measures the instrument, never a builder — test/dev only"
)


def fixture_builder_enabled(env: Mapping[str, str] | None = None) -> bool:
    """``CRB_ENABLE_FIXTURE_BUILDER=1`` exactly; anything else (unset, ``0``, ``true``)
    keeps the builder unregistered — the switch is deliberately narrow."""
    e = env if env is not None else os.environ
    return e.get(ENABLE_ENV, "").strip() == "1"


class FixtureGoldBuilder:
    """Overlay the commit's non-test files onto the parent worktree (see module doc)."""

    name = NAME

    def __init__(self, *, model: str = MODEL, provider: str = "", **_ignored: Any) -> None:
        # The rung may say anything; the recorded identity is always the fixture's, so a
        # row can never be read back as a model measurement.
        del model, provider
        self.model = MODEL
        self.provider = PROVIDER

    def describe(self) -> dict[str, Any]:
        """The apparatus stamp — carries ``fixture: true`` and the warning on purpose."""
        return {
            "builder": self.name,
            "model": self.model,
            "provider": self.provider,
            "process": "overlay the commit's own source files (gold) — instrument check",
            "fixture": True,
            "warning": WARNING,
        }

    def source_files(self, workspace: Workspace, brief: BuildBrief) -> list[str]:
        """The commit's changed files that the repo layout does not class as tests.

        The brief never carries ``src_files`` (by design); the fixture recovers them from
        the commit itself, which is exactly the archaeology a real builder is forbidden.
        Deleted files are excluded — ``overlay_sources`` checks paths out of the commit,
        and a path absent there would fail the checkout.
        """
        config = brief.repo_config()
        changed = workspace.repo.changed_files(workspace.sha)
        return [
            rel
            for rel in changed
            if not config.is_test(rel) and workspace.repo.show_file(workspace.sha, rel) is not None
        ]

    def build(
        self,
        workspace: Workspace,
        brief: BuildBrief,
        budget: Budget,
        *,
        on_event: EventFn | None = None,
    ) -> BuildOutcome:
        """Overlay the gold sources; the budget is ignored (nothing is spent)."""
        started = time.monotonic()
        files = self.source_files(workspace, brief)
        emit(on_event, "build.attempt", builder=self.name, files=files, fixture=True)
        if files:
            workspace.overlay_sources(files)
        emit(on_event, "build.done", builder=self.name, files=len(files), fixture=True)
        return BuildOutcome(
            builder=self.name,
            model=self.model,
            provider=self.provider,
            mode=brief.mode,
            done=False,  # never a claim: the grader decides
            summary=f"fixture overlay of {len(files)} source file(s)",
            turns=1,
            tool_calls=len(files),
            tokens_in=0,
            tokens_out=0,
            cost_usd=0.0,
            cost_known=True,
            latency_s=time.monotonic() - started,
            attempts=1,
            stop_reason=STOP_DONE,
            budget=budget,
            extra={"fixture": True, "warning": WARNING, "files": files},
        )


__all__ = [
    "ENABLE_ENV",
    "MODEL",
    "NAME",
    "PROVIDER",
    "WARNING",
    "FixtureGoldBuilder",
    "fixture_builder_enabled",
]
