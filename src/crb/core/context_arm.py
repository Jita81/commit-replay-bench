"""The context arm — which context a builder was given, as one pre-registered id (ADR-0026 item 1).

A row's **context arm** names what the builder's brief carried, in one grammar: a base, then
optional modifiers in this order —

* ``A0`` — the ticket only (the commit message, or the linked ticket as it stood at the
  parent's date); descriptive, never certifies;
* ``S1@<author>`` — the ticket and a failing test the named test author wrote in the sealed
  parent checkout; ``<author>`` is the author's canonical model (ADR-0021's
  ``canonical_model``), so two author models are two arms; certifies retrospectively;
* ``S2`` — the ticket and a failing test a person attached before any build; certifies
  prospectively only;
* ``S3`` — the ticket and the commit's own tests (today's sighted brief); a ceiling, never a
  certificate;
* ``+facts@<drafter>`` — structural facts a pinned model drafted from the ticket and the parent
  tree;
* ``+library@<version>`` — a frozen set of library entries;
* ``+L`` — the repository's loop switch on (ADR-0020): a POLICY, not a snapshot.

The arm is a POOLING key: :func:`crb.core.ledger.cell_stats` refuses rows of two arms
(:class:`ContextArmsPooled`), as it refuses two checks arms (ADR-0024) and two apparatus
versions (ADR-0025). Everything else about the brief is **provenance** (:data:`PROVENANCE_LABELS`)
— shown and filterable, never a reason to split a cell — so the loop adding a playbook line
mid-campaign changes a provenance stamp, never the arm.

Navigation
----------
What it is:   The context-arm vocabulary: the grammar (``parse_arm`` / ``ContextArm``), the
              one helper that decides a row's arm from what its brief carried
              (``context_arm_for``), the provenance label names, the pooling refusal
              (``ContextArmsPooled``) and the read filter (``rows_for_context_arm``).
What it does: Refuses an arm id outside the grammar; names an arm's role (descriptive,
              ceiling, certifies retrospectively or prospectively); decides ``A0`` / ``S3`` /
              ``S1@<author>`` / ``S2`` (with ``+L`` when the brief carried the loop) for a
              replay or factory row; keeps one arm's rows on request.
How:          A regular expression per part; ``context_arm_for`` reads the process step, the
              mode, whether the loop's overlay reached the brief and whose test the builder
              was given; the ledger stamps the result as the hashed ``context_arm`` label on
              every row of apparatus 2.4 or later (``crb.core.ledger.row_labels_at_write``).
Layer:        core — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0026-the-context-standard.md (item 1),
              docs/adr/0025-routing-v2.md (the one bump the stamp rides)
Works with:   src/crb/core/ledger.py (the label, ``GradeRow.context_arm``, the refusal in
              ``cell_stats``), src/crb/core/reading.py (a reading's hierarchy names arms),
              src/crb/core/routing.py (routes one arm), src/crb/core/capability.py (the map
              reads one arm), src/crb/factory/build.py (a factory row's arm),
              src/crb/core/prevention.py (the ``learn`` label ``+L`` reads)
Tested by:    tests/test_context_arm.py, tests/test_routing_v2.py
Touch when:   never for a new repository; an arm base or modifier is added — an ADR amending
              ADR-0026 item 1 first; a new provenance stamp (add it to ``PROVENANCE_LABELS``, never
              to the arm); never for a new repository.
Claims:       An arm names what the brief carried, not what the builder read; ``S3`` never
              certifies and ``A0`` never licenses (docs/EVIDENCE-AND-CLAIMS.md).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Protocol

#: The hashed row label that carries the arm (apparatus 2.4 or later).
LABEL_CONTEXT_ARM = "context_arm"

BASE_A0 = "A0"
BASE_S1 = "S1"
BASE_S2 = "S2"
BASE_S3 = "S3"
BASES: tuple[str, ...] = (BASE_A0, BASE_S1, BASE_S2, BASE_S3)

#: The mode a REPLAY writes each arm's rows in: ``A0`` (the ticket only) and ``S1`` (a test
#: another model wrote, graded on the commit's held-out tests) blind, ``S3`` (the commit's own
#: tests) sighted. The one statement of it: :func:`context_arm_for` derives ``A0``/``S3`` from
#: the mode, the worker's replay ``S1`` arm refuses any other, and the test fixtures stamp
#: their rows from it, so no reader is tested on a row shape the writer never produces
#: (P-338).
REPLAY_MODE: dict[str, str] = {BASE_A0: "blind", BASE_S1: "blind", BASE_S3: "sighted"}

MOD_FACTS = "+facts@"
MOD_LIBRARY = "+library@"
MOD_LOOP = "+L"

#: Provenance stamps (ADR-0026 item 1): shown and filterable, never a pooling key.
LABEL_CTX_TICKET = "ctx_ticket"
LABEL_CTX_BRIEF = "ctx_brief"
LABEL_CTX_HARNESS = "ctx_harness"
LABEL_CTX_RULES = "ctx_rules"
LABEL_CTX_AUTHOR = "ctx_author"
LABEL_CTX_LIBRARY = "ctx_library"
LABEL_CTX_REFUSED = "ctx_refused"
PROVENANCE_LABELS: tuple[str, ...] = (
    LABEL_CTX_TICKET,
    LABEL_CTX_BRIEF,
    LABEL_CTX_HARNESS,
    LABEL_CTX_RULES,
    LABEL_CTX_AUTHOR,
    LABEL_CTX_LIBRARY,
    LABEL_CTX_REFUSED,
    # the existing stamps the loop, the switchboard and spend write (ADR-0020, ADR-0024)
    "learn_playbook",
    "learn_lines",
    "checks",
    "finish_gate",
    "budget_profile",
)

#: The ``learn`` label value that means the loop was off for the run (ADR-0020 §8).
LEARN_OFF = "off"
LABEL_LEARN = "learn"

#: Where a factory build's failing test came from.
TEST_AUTHORED = "authored"
TEST_PERSON = "person"

_NAME = r"[A-Za-z0-9][A-Za-z0-9._:/-]*"
_ARM_RE = re.compile(
    rf"^(?P<base>A0|S1@(?P<author>{_NAME})|S2|S3)"
    rf"(?:\+facts@(?P<facts>{_NAME}))?"
    rf"(?:\+library@(?P<library>{_NAME}))?"
    r"(?P<loop>\+L)?$"
)


class ContextArmsPooled(ValueError):
    """Rows built under two context arms reached one cell (ADR-0026 item 1): a row whose
    builder saw the commit's own tests answers a different question from one whose builder saw
    an authored test or only the ticket, and rows with the loop on and off are two arms — a
    reader chooses one arm (:func:`rows_for_context_arm`) before it reduces a cell."""


@dataclass(frozen=True)
class ContextArm:
    """One parsed arm id. ``author`` is set only on the ``S1`` base."""

    base: str
    author: str = ""
    facts: str = ""
    library: str = ""
    loop: bool = False

    def __post_init__(self) -> None:
        if self.base not in BASES:
            raise ValueError(f"context arm base {self.base!r} not in {BASES}")
        if (self.base == BASE_S1) != bool(self.author):
            raise ValueError("the S1 base names its test author (S1@<author>) and no other does")
        if not _ARM_RE.match(self.id):
            raise ValueError(f"context arm {self.id!r} is outside the grammar (ADR-0026 item 1)")

    @property
    def id(self) -> str:
        """The arm as its one string: base, then ``+facts@``, ``+library@``, ``+L``."""
        out = f"{BASE_S1}@{self.author}" if self.base == BASE_S1 else self.base
        if self.facts:
            out += MOD_FACTS + self.facts
        if self.library:
            out += MOD_LIBRARY + self.library
        if self.loop:
            out += MOD_LOOP
        return out

    @property
    def descriptive(self) -> bool:
        """``A0`` and ``A0+L``: run for the north star and the loop's pair; never certify."""
        return self.base == BASE_A0

    @property
    def ceiling(self) -> bool:
        """``S3``: the commit's own tests were written with the change — a ceiling, never a
        certificate (ADR-0026 item 4)."""
        return self.base == BASE_S3

    @property
    def certifies(self) -> bool:
        """The ``S1`` family (retrospectively) and ``S2`` (prospectively)."""
        return self.base in (BASE_S1, BASE_S2)

    @property
    def prospective_only(self) -> bool:
        """``S2`` certifies only from factory rows graded on held-out acceptance tests."""
        return self.base == BASE_S2

    def with_loop(self, on: bool) -> ContextArm:
        """The same arm with the loop switch on or off."""
        return ContextArm(self.base, self.author, self.facts, self.library, on)

    def __str__(self) -> str:
        return self.id


def parse_arm(arm: str) -> ContextArm:
    """``"S1@claude-opus-5+L"`` → :class:`ContextArm`; refuses anything outside the grammar."""
    m = _ARM_RE.match((arm or "").strip())
    if not m:
        raise ValueError(
            f"context arm {arm!r} is outside the grammar: a base (A0, S1@<author>, S2, S3), "
            "then optional +facts@<drafter>, +library@<version>, +L in that order"
        )
    base = m.group("base")
    return ContextArm(
        base=BASE_S1 if base.startswith(BASE_S1) else base,
        author=m.group("author") or "",
        facts=m.group("facts") or "",
        library=m.group("library") or "",
        loop=bool(m.group("loop")),
    )


def mode_admits(row_mode: str, row_arm: str, mode: str) -> bool:
    """Whether a reader asking for ``mode`` (``sighted``, ``blind`` or ``all``) keeps a row
    written in ``row_mode`` on ``row_arm`` — THE rule every map, route and sign-off reader
    applies (P-338). ``mode`` splits the descriptive and ceiling arms and the rows from
    before 2.4 that carry no arm; a CERTIFYING arm (``S1@<author>``, ``S2``) is kept whatever
    the mode, because a reading proves it on the mode its writer runs it in (the replay
    ``S1`` arm is blind, :data:`REPLAY_MODE`) and a map reads one arm per cell — dropping it
    by mode left the standard a reading proved unrouted and unsignable."""
    if mode in ("all", row_mode):
        return True
    try:
        return bool(row_arm) and parse_arm(row_arm).certifies
    except ValueError:
        return False


def is_arm(arm: str) -> bool:
    """``True`` for a string inside the grammar."""
    return bool(_ARM_RE.match((arm or "").strip()))


def loop_on(labels: Mapping[str, str]) -> bool:
    """Did the run's loop switch reach this brief? The ``learn`` label every row of a run
    carries (ADR-0020 §8): absent or ``off`` means the loop was off."""
    return labels.get(LABEL_LEARN, LEARN_OFF) not in ("", LEARN_OFF)


def context_arm_for(
    *,
    process_step: str,
    mode: str,
    loop: bool = False,
    test_source: str = "",
    test_author: str = "",
    facts_drafter: str = "",
    library_version: str = "",
) -> str:
    """THE decision of a row's arm from what its brief carried (ADR-0026 item 1).

    * a replay the builder ran blind (the ticket only) → ``A0``;
    * a replay the builder ran sighted on the commit's own tests → ``S3``;
    * a build on a test a model authored (a factory build, or the replay ``S1`` arm) →
      ``S1@<test_author>`` — ``test_author`` must already be the canonical model
      (``crb.factory.testfirst.canonical_model``), so a provider label never makes one model
      two authors;
    * a factory build on a test a person attached → ``S2``;

    then ``+facts@<drafter>``, ``+library@<version>`` and ``+L`` when the brief carried them.
    ``loop`` is whether the loop's overlay and lines reached THIS brief (a factory brief carries
    them only when its standard arm does — stream F's composer decides and passes it here).
    """
    if test_source == TEST_PERSON:
        base = ContextArm(BASE_S2)
    elif test_source == TEST_AUTHORED:
        if not test_author:
            raise ValueError("an authored-test build names its test author's canonical model")
        base = ContextArm(BASE_S1, author=test_author)
    elif test_source:
        raise ValueError(f"test_source {test_source!r} is not {TEST_AUTHORED!r} or {TEST_PERSON!r}")
    elif process_step == "factory":
        raise ValueError("a factory build's arm names whose failing test it was given")
    elif mode == REPLAY_MODE[BASE_A0]:
        base = ContextArm(BASE_A0)
    elif mode == REPLAY_MODE[BASE_S3]:
        base = ContextArm(BASE_S3)
    else:
        raise ValueError(f"mode {mode!r} is neither 'sighted' nor 'blind'")
    arm = ContextArm(
        base.base,
        author=base.author,
        facts=facts_drafter,
        library=library_version,
        loop=loop,
    )
    return arm.id


class _HasArm(Protocol):
    @property
    def context_arm(self) -> str: ...


def rows_for_context_arm[R: _HasArm](rows: Iterable[R], arm: str) -> list[R]:
    """The rows built under ONE context arm — the read filter every reader that reduces cells
    applies, as it applies the checks arm and the apparatus. There is no pooled view."""
    parse_arm(arm)
    return [r for r in rows if r.context_arm == arm]


def arms_present(rows: Iterable[_HasArm]) -> list[str]:
    """The distinct arms of ``rows`` in a stable order (``""`` — an unstamped row from
    before 2.4 — sorts first)."""
    return sorted({r.context_arm for r in rows})


__all__ = [
    "BASES",
    "BASE_A0",
    "BASE_S1",
    "BASE_S2",
    "BASE_S3",
    "LABEL_CONTEXT_ARM",
    "PROVENANCE_LABELS",
    "REPLAY_MODE",
    "TEST_AUTHORED",
    "TEST_PERSON",
    "ContextArm",
    "ContextArmsPooled",
    "arms_present",
    "context_arm_for",
    "is_arm",
    "loop_on",
    "mode_admits",
    "parse_arm",
    "rows_for_context_arm",
]
