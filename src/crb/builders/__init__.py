"""crb.builders — the builders under measurement, behind one contract.

A builder is a (model × process) pair that edits a :class:`~crb.core.workspace.Workspace`
at a commit's parent. The grader (:mod:`crb.core.grade`) — never the builder —
decides whether the edit reproduced the commit. See :mod:`crb.builders.base`
for the contract and the guards every adapter shares.

Adapters
--------
* ``editblock``    — one-shot SEARCH/REPLACE for cheap OpenAI-compatible models.
* ``openai_agent`` — in-process tool loop (read / search / edit / run) over any
  OpenAI-compatible function-calling model (Cerebras, Azure OpenAI, …).
* ``claude_code``  — agentic Claude Code (``claude -p``), the census's measured path.

Third-party SDKs are imported lazily inside the adapters; this package imports
with nothing but the standard library and :mod:`crb.core`.

    >>> from crb.builders import get_builder
    >>> b = get_builder("openai_agent", model="gpt-oss-120b", provider="cerebras")

Test-only
---------
* ``fixture_gold`` — replays the commit's own source (an instrument check for the
  hermetic walkthrough / CI). Registered ONLY when ``CRB_ENABLE_FIXTURE_BUILDER=1``
  is set in the process environment; never in production. See
  :mod:`crb.builders.fixture_gold`.

Navigation
----------
What it is:   The builder registry — name → adapter class — and the package's public
              re-exports (contract, budgets, ladder helpers).
What it does: ``get_builder`` instantiates a registered adapter by name (a typo is a
              ``ValueError`` at construction, never a silent default); ``builder_for_rung``
              turns a ladder rung into an instance, passing the rung's config through minus
              the budget keys; the test-only fixture builder joins the table only under its
              environment switch.
How:          A module-level ``dict``; the third-party SDKs stay lazy inside the adapters so
              importing this package needs nothing beyond the standard library.
Layer:        builders — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0004-builder-registry-sighted-and-blind.md
Works with:   src/crb/builders/base.py (the contract every entry honours),
              src/crb/builders/adapter.py (the caller of ``builder_for_rung``),
              src/crb/builders/claude_code.py, src/crb/builders/openai_agent.py and
              src/crb/builders/editblock.py (the three production adapters),
              src/crb/builders/fixture_gold.py (the opt-in test builder)
Tested by:    tests/test_builders_base.py, tests/test_builders_fixture_gold.py
Touch when:   never for a new repository (pick a rung from ``builder_names()``); adding an
              adapter means one entry here, an ``__all__`` export, a note in docs/OPERATOR.md
              and — if it must run sealed — ``SEALABLE_BUILDERS`` in
              src/crb/builders/container.py.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from crb.builders.base import (
    DEFAULT_RULES,
    STOP_REASONS,
    Budget,
    BuildBrief,
    Builder,
    BuildOutcome,
    EscalationLadder,
    GitArchaeologyGuard,
    GuardRefused,
    Rung,
    TestFileGuard,
)
from crb.builders.budget import (
    BudgetTracker,
    CostMeter,
    Pricing,
    budget_for_rung,
    default_ladder,
    load_pricing,
    parse_ladder,
    price_for,
)
from crb.builders.claude_code import ClaudeCodeBuilder
from crb.builders.editblock import EditBlockBuilder
from crb.builders.fixture_gold import FixtureGoldBuilder, fixture_builder_enabled
from crb.builders.openai_agent import OpenAIAgentBuilder

_REGISTRY: dict[str, Callable[..., Builder]] = {
    "editblock": EditBlockBuilder,
    "openai_agent": OpenAIAgentBuilder,
    "claude_code": ClaudeCodeBuilder,
}

# The test-only fixture builder is registered by an explicit environment switch and
# nothing else: without ``CRB_ENABLE_FIXTURE_BUILDER=1`` the name does not exist.
if fixture_builder_enabled():
    _REGISTRY[FixtureGoldBuilder.name] = FixtureGoldBuilder


def builder_names() -> tuple[str, ...]:
    """Every registered name (the fixture only when its switch is set)."""
    return tuple(_REGISTRY)


def get_builder(name: str, **config: Any) -> Builder:
    """Instantiate a registered builder. ``config`` is the adapter's constructor
    keyword arguments (``model=…`` is required by every adapter but ``claude_code``)."""
    try:
        factory = _REGISTRY[name]
    except KeyError as e:
        raise ValueError(f"unknown builder {name!r}; expected one of {builder_names()}") from e
    return factory(**config)


def builder_for_rung(rung: Rung, **overrides: Any) -> Builder:
    """A ladder rung → a builder instance (``rung.config`` + ``overrides`` as kwargs)."""
    cfg: dict[str, Any] = {
        k: v for k, v in rung.config.items() if k not in Budget.__dataclass_fields__
    }
    cfg["model"] = rung.model
    if rung.provider and rung.builder != "claude_code":
        cfg["provider"] = rung.provider
    cfg.update(overrides)
    return get_builder(rung.builder, **cfg)


__all__ = [
    "DEFAULT_RULES",
    "STOP_REASONS",
    "Budget",
    "BudgetTracker",
    "BuildBrief",
    "BuildOutcome",
    "Builder",
    "ClaudeCodeBuilder",
    "CostMeter",
    "EditBlockBuilder",
    "EscalationLadder",
    "GitArchaeologyGuard",
    "GuardRefused",
    "OpenAIAgentBuilder",
    "Pricing",
    "Rung",
    "TestFileGuard",
    "budget_for_rung",
    "builder_for_rung",
    "builder_names",
    "default_ladder",
    "get_builder",
    "load_pricing",
    "parse_ladder",
    "price_for",
]
