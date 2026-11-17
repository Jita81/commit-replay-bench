"""An accepted implementation plan — the structured body a ``ctx.plan*`` entry is rendered from
(ADR-0054).

A plan entry is never free text. Its drafter writes five sections of one-line strings::

    {"summary": ["..."], "files": ["src/pkg/mod.py"], "steps": ["...", "..."],
     "decisions": ["..."], "tests": ["..."]}

and the text the builder reads is rendered BY CODE (:func:`render`): one fixed header, then
``Summary:``, ``Files:``, ``Steps:`` (numbered ``1.``, ``2.``…), ``Settled decisions:`` and
``Tests:``, each line a ``- `` bullet with no indentation (a section with no lines is left
out). ``summary`` and ``steps`` are never empty.

The plan was written BEFORE the build, from the ticket and the parent tree only — never from
the change or its tests — and accepted by the person who asked for the change (or by no one,
``accepted_by: none``). The guard that checks it against the gold change, harness-side, is
:func:`crb.builders.brief.plan_guard`; this module names its reasons (:data:`PLAN_REASONS`)
and holds the fixed limits.

Navigation
----------
What it is:   The accepted-plan vocabulary: the body (``PlanBody``), the sections, what a
              plan's drafter may have seen (``PLAN_SAW_VALUES``), the fixed limits
              (``length_violation``), the shape rule (``shape_violation``), the renderer
              (``render``) and the ``plan_guard`` reason names.
What it does: Renders an entry's text from its plan, deterministically; says why a plan
              breaks its shape or its limits.
How:          Pure functions over a frozen dataclass (stdlib only), so the set parser
              (``crb.core.ctxset``) and the composer's guard (``crb.builders.brief``) read one
              definition.
Layer:        core — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0054-accepted-plan-context-arm.md, docs/adr/0050-context-set-arms.md
Works with:   src/crb/core/ctxset.py (the ``crb.ctxset.v3`` record whose entries carry a plan),
              src/crb/builders/brief.py (``plan_guard``, which re-renders and checks an entry),
              src/crb/core/context_arm.py (the ``ctx.plan*`` source and stamps)
Tested by:    tests/test_plan.py
Touch when:   never for a new repository; a section, the renderer or a limit changes (a new
              ADR first: a renderer change moves every rendered text).
Claims:       A rendered plan says what its drafter planned and who accepted it; the set's
              digest says it is unaltered, not that the plan is right (ADR-0054).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

#: What a plan's drafter saw: the ticket (always) and the parent tree. Never the change or
#: its tests: a plan written with sight of them is not a plan (ADR-0054).
PLAN_SAW_TICKET = "ticket"
PLAN_SAW_TREE = "tree"
PLAN_SAW_VALUES: tuple[str, ...] = (PLAN_SAW_TICKET, PLAN_SAW_TREE)

#: Who accepted a plan: the person who asked for the change (``human:<id>``), or no one
#: (``none``: the plan reached the builder unreviewed, which the row says).
ACCEPTED_NONE = "none"
ACCEPTED_BY_RE = re.compile(r"^(human:[A-Za-z0-9][A-Za-z0-9._-]{0,63}|none)$")

#: The fixed limits (ADR-0054). Changing one is a new ADR.
MAX_PLAN_CHARS = 8000
MAX_LINE_CHARS = 600
MAX_DECISIONS = 24
MAX_LINES = 80
MAX_FILES = 40

#: The one header the renderer opens with.
PLAN_HEADER = (
    "Accepted implementation plan for this change "
    "(written before the build from the ticket and the parent tree):"
)

#: The sections, in render order, with their headings.
SECTIONS: tuple[str, ...] = ("summary", "files", "steps", "decisions", "tests")
SECTION_HEADINGS: dict[str, str] = {
    "summary": "Summary:",
    "files": "Files:",
    "steps": "Steps:",
    "decisions": "Settled decisions:",
    "tests": "Tests:",
}
#: The sections a plan never leaves empty.
REQUIRED_SECTIONS: tuple[str, ...] = ("summary", "steps")

#: The reasons ``crb.builders.brief.plan_guard`` withholds a plan for (ADR-0054).
REASON_RENDER = "plan_render"
REASON_LENGTH = "plan_length"
REASON_CODE_BLOCK = "plan_code_block"
REASON_TEST_NAME = "plan_test_name"
REASON_TEST_PATH = "plan_test_path"
REASON_TEST_SPAN = "plan_test_span"
REASON_GOLD_SPAN = "plan_gold_span"
REASON_ASSERTED_LITERAL = "plan_asserted_literal"
REASON_NO_GOLD = "plan_no_gold"
PLAN_REASONS: tuple[str, ...] = (
    REASON_RENDER,
    REASON_LENGTH,
    REASON_CODE_BLOCK,
    REASON_TEST_NAME,
    REASON_TEST_PATH,
    REASON_TEST_SPAN,
    REASON_GOLD_SPAN,
    REASON_ASSERTED_LITERAL,
    REASON_NO_GOLD,
)


@dataclass(frozen=True)
class PlanBody:
    """One accepted plan: five sections of one-line strings, in the drafter's order."""

    summary: tuple[str, ...]
    files: tuple[str, ...] = ()
    steps: tuple[str, ...] = ()
    decisions: tuple[str, ...] = ()
    tests: tuple[str, ...] = ()

    def section(self, name: str) -> tuple[str, ...]:
        if name not in SECTIONS:
            raise ValueError(f"plan section {name!r} is not one of {SECTIONS}")
        return tuple(getattr(self, name))

    def lines(self) -> tuple[str, ...]:
        """Every line of the plan, section by section in render order."""
        return tuple(line for name in SECTIONS for line in self.section(name))

    def to_doc(self) -> dict[str, Any]:
        return {name: list(self.section(name)) for name in SECTIONS}


def shape_violation(plan: PlanBody) -> str:
    """Why a plan breaks its shape (``""`` when it does not): a line that is not one trimmed,
    non-empty line, a line carrying a code fence, or an empty ``summary`` or ``steps``."""
    for name in SECTIONS:
        for j, line in enumerate(plan.section(name)):
            if not isinstance(line, str) or not line or line.strip() != line:
                return f"{name}[{j}] is not a trimmed, non-empty string"
            if "\n" in line or "\r" in line:
                return f"{name}[{j}] spans several lines"
            if "```" in line or "~~~" in line:
                return f"{name}[{j}] carries a code fence"
    for name in REQUIRED_SECTIONS:
        if not plan.section(name):
            return f"{name} is empty (a plan always states its {name})"
    return ""


def render(plan: PlanBody) -> str:
    """THE text of a plan entry: the header, then each non-empty section under its heading,
    ``- `` bullets (``Steps:`` numbered ``1.``, ``2.``…), no indentation. Nothing else
    produces the text a ``ctx.plan*`` arm delivers (ADR-0054)."""
    if shape_violation(plan):
        raise ValueError(f"a plan that breaks its shape is not rendered: {shape_violation(plan)}")
    out = [PLAN_HEADER]
    for name in SECTIONS:
        lines = plan.section(name)
        if not lines:
            continue
        out.append(SECTION_HEADINGS[name])
        if name == "steps":
            out.extend(f"{n}. {line}" for n, line in enumerate(lines, 1))
        else:
            out.extend(f"- {line}" for line in lines)
    return "\n".join(out)


def length_violation(plan: PlanBody, text: str | None = None) -> str:
    """Why a plan breaks the fixed limits (``""`` when it does not); ``text`` is its rendering
    (rendered here when not given)."""
    lines = plan.lines()
    if len(lines) > MAX_LINES:
        return f"{len(lines)} lines (at most {MAX_LINES})"
    if len(plan.files) > MAX_FILES:
        return f"{len(plan.files)} files (at most {MAX_FILES})"
    if len(plan.decisions) > MAX_DECISIONS:
        return f"{len(plan.decisions)} decisions (at most {MAX_DECISIONS})"
    for name in SECTIONS:
        for j, line in enumerate(plan.section(name)):
            if len(line) > MAX_LINE_CHARS:
                return f"{name}[{j}]: {len(line)} characters (at most {MAX_LINE_CHARS})"
    rendered = render(plan) if text is None else text
    if len(rendered) > MAX_PLAN_CHARS:
        return f"{len(rendered)} plan characters (at most {MAX_PLAN_CHARS})"
    return ""


def plan_from_doc(doc: Any) -> PlanBody:
    """A :class:`PlanBody` from its document (the five sections, each a list of strings);
    raises ``ValueError`` on a missing or unknown section or a non-string line. Shape and
    limits are the caller's checks (:func:`shape_violation`, :func:`length_violation`)."""
    if not isinstance(doc, dict):
        raise ValueError("a plan is an object of five sections")
    missing = [s for s in SECTIONS if s not in doc]
    extra = sorted(set(doc) - set(SECTIONS))
    if missing or extra:
        raise ValueError(f"a plan holds exactly the sections {SECTIONS}")
    parts: dict[str, tuple[str, ...]] = {}
    for name in SECTIONS:
        raw = doc[name]
        if not isinstance(raw, list) or not all(isinstance(x, str) for x in raw):
            raise ValueError(f"plan.{name} is not a list of strings")
        parts[name] = tuple(raw)
    return PlanBody(**parts)


__all__ = [
    "ACCEPTED_BY_RE",
    "ACCEPTED_NONE",
    "MAX_DECISIONS",
    "MAX_FILES",
    "MAX_LINES",
    "MAX_LINE_CHARS",
    "MAX_PLAN_CHARS",
    "PLAN_HEADER",
    "PLAN_REASONS",
    "PLAN_SAW_TICKET",
    "PLAN_SAW_TREE",
    "PLAN_SAW_VALUES",
    "REASON_ASSERTED_LITERAL",
    "REASON_CODE_BLOCK",
    "REASON_GOLD_SPAN",
    "REASON_LENGTH",
    "REASON_NO_GOLD",
    "REASON_RENDER",
    "REASON_TEST_NAME",
    "REASON_TEST_PATH",
    "REASON_TEST_SPAN",
    "REQUIRED_SECTIONS",
    "SECTIONS",
    "SECTION_HEADINGS",
    "PlanBody",
    "length_violation",
    "plan_from_doc",
    "render",
    "shape_violation",
]
