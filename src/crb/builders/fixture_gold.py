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

1. **Registration is opt-in, and never in production.** :mod:`crb.builders`
   registers the name only when ``CRB_ENABLE_FIXTURE_BUILDER=1`` is set in the
   worker's environment AND ``CRB_ENV`` names a non-production environment
   (``dev``); production is the default posture — ``CRB_ENV`` unset or empty is
   ``prod`` to ``crb.server.settings`` and to this belt alike, and ``prod`` /
   ``production`` by name deny the switch (:mod:`crb.core.fixture_builder_switch`).
   Without that ``get_builder("fixture_gold")`` is an unknown-builder ``ValueError``
   exactly like any other typo. Production deployments (``deploy/``) never set the
   switch, and the belt holds even if one did, on the documented single-host path
   too. The ``builders`` health probe reports ``fixture_gold`` through the same
   function, so ``/health`` and the worker agree.
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
              ``CRB_ENABLE_FIXTURE_BUILDER=1`` with ``CRB_ENV`` naming a non-production
              environment — unset is production (the switch is
              ``crb.core.fixture_builder_switch``, which the ``builders`` health probe reads
              too). With ``builder_config {"attempt": cmd}`` it
              first asks the real shell guard about ``cmd`` (never running it); a refusal is
              recorded as a protocol violation and the attempt stops with no patch — how
              the Learn walkthrough gets a real refusal row on a hermetic stack.
How:          ``source_files``: the commit's changed files minus tests and deletions →
              ``Workspace.overlay_sources`` → a zero-cost ``BuildOutcome``.
Layer:        builders — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0004-builder-registry-sighted-and-blind.md
Works with:   src/crb/builders/__init__.py (the opt-in registration),
              src/crb/core/fixture_builder_switch.py (the switch and its production belt, shared
              with src/crb/observability/probes.py), src/crb/core/workspace.py
              (``overlay_sources``), src/crb/core/oracle/controls.py (the ``gold`` control
              does the same overlay — the two must agree), scripts/walkthrough.sh and
              tests/fixtures/builders_repo.py (the hermetic drivers), src/crb/core/federated.py
              (the abstract export never carries these rows: ``export_abstract`` keeps every
              row whose provider is ``PROVIDER`` inside the tenant, P-665)
Tested by:    tests/test_builders_fixture_gold.py, tests/test_probe_fixture_builder.py
Touch when:   never for a new repository and never in production — the switch stays unset
              in deploy/ (docs/DEPLOYMENT.md); a change to what ``gold`` means is a change
              to the negative control first.
Claims:       A ``fixture_gold`` row measures the instrument; it must never be read, summed
              or exported as a builder result (docs/EVIDENCE-AND-CLAIMS.md).
"""

from __future__ import annotations

import time
from typing import Any

from crb.builders.base import (
    STOP_DONE,
    Budget,
    BuildBrief,
    BuildOutcome,
    EventFn,
    GitArchaeologyGuard,
    emit,
)
from crb.core.fixture_builder_switch import (
    ENABLE_ENV,
    ENV_ENV,
    PRODUCTION_ENVS,
    fixture_builder_enabled,
)
from crb.core.workspace import Workspace

# ``ENABLE_ENV`` and ``fixture_builder_enabled`` live in crb.core.fixture_builder_switch so
# the ``builders`` health probe (crb.observability, a sibling layer) reads the SAME switch
# and the same production belt; they are re-exported here as the builder's own names.
__all__ = [
    "ENABLE_ENV",
    "ENV_ENV",
    "MODEL",
    "NAME",
    "PRODUCTION_ENVS",
    "PROVIDER",
    "WARNING",
    "FixtureGoldBuilder",
    "fixture_builder_enabled",
]

NAME = "fixture_gold"
MODEL = "gold"
PROVIDER = "fixture"

WARNING = (
    "fixture_gold replays the commit's own source change (git archaeology by design); "
    "it measures the instrument, never a builder — test/dev only"
)


class FixtureGoldBuilder:
    """Overlay the commit's non-test files onto the parent worktree (see module doc)."""

    name = NAME

    def __init__(
        self, *, model: str = MODEL, provider: str = "", attempt: str = "", **_ignored: Any
    ) -> None:
        # The rung may say anything; the recorded identity is always the fixture's, so a
        # row can never be read back as a model measurement.
        del model, provider
        self.model = MODEL
        self.provider = PROVIDER
        #: ``builder_config {"attempt": "<shell command>"}`` — one command put to the REAL
        #: shell guard as a builder's tool call would be. The fixture never runs it; a
        #: refusal is recorded the way the agentic builders record one, so a hermetic stack
        #: can produce a genuine ``protocol`` row for the Learn walkthrough (G-913).
        self.attempt = str(attempt or "").strip()

    def describe(self) -> dict[str, Any]:
        """The apparatus stamp — carries ``fixture: true`` and the warning on purpose."""
        return {
            "builder": self.name,
            "model": self.model,
            "provider": self.provider,
            "process": "overlay the commit's own source files (gold) — instrument check",
            "fixture": True,
            "warning": WARNING,
            **({"attempt": self.attempt} if self.attempt else {}),
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
        errors: list[str] = []
        if self.attempt:
            # asked of the guard, never executed: the fixture has no shell tool
            reason = GitArchaeologyGuard(cwd=workspace.root).check_shell(self.attempt)
            if reason:
                errors.append(f"{reason} (attempted: {self.attempt[:120]})")
            emit(on_event, "build.tool", name="shell", ok=not reason, fixture=True)
        # a refused attempt stops there, as a builder whose one move was refused would: no
        # patch, so the grade is not clean and the row is `protocol` (a clean grade would
        # outrank the refusal, and the gold overlay is harness-written, so it is not undone)
        files = [] if errors else self.source_files(workspace, brief)
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
            # one per overlaid file, plus the attempted shell call its ``build.tool`` event
            # records — refused or not (P-425)
            tool_calls=len(files) + (1 if self.attempt else 0),
            tokens_in=0,
            tokens_out=0,
            cost_usd=0.0,
            cost_known=True,
            latency_s=time.monotonic() - started,
            attempts=1,
            stop_reason=STOP_DONE,
            errors=tuple(errors),
            budget=budget,
            extra={
                "fixture": True,
                "warning": WARNING,
                "files": files,
                **({"attempt": self.attempt} if self.attempt else {}),
            },
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
