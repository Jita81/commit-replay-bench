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
from crb.builders.openai_agent import OpenAIAgentBuilder

_REGISTRY: dict[str, Callable[..., Builder]] = {
    "editblock": EditBlockBuilder,
    "openai_agent": OpenAIAgentBuilder,
    "claude_code": ClaudeCodeBuilder,
}


def builder_names() -> tuple[str, ...]:
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
