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
              (``ContextArmsPooled``), the read filter (``rows_for_context_arm``) and the
              context-set predicates (``ctx_set_name``, ``hindsight_arm``,
              ``stated_arm``, ``plan_arm``, ``audited_plan_arm``, ``measurement_only``,
              ADR-0050, ADR-0052, ADR-0054 and ADR-0055) over one source-to-kind table
              (``CTX_SOURCE_KIND``).
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
              docs/adr/0025-routing-v2.md (the one bump the stamp rides),
              docs/adr/0050-context-set-arms.md (the reserved ``ctx.`` library names),
              docs/adr/0052-stated-requirement-arms.md (the ``req`` sources and their stamps),
              docs/adr/0054-accepted-plan-context-arm.md (the ``plan`` source and its stamps),
              docs/adr/0055-audited-bypass-plan-arm.md (the ``plan-audited`` source)
Works with:   src/crb/core/ledger.py (the label, ``GradeRow.context_arm``, the refusal in
              ``cell_stats``), src/crb/core/reading.py (a reading's hierarchy names arms),
              src/crb/core/routing.py (routes one arm), src/crb/core/capability.py (the map
              reads one arm), src/crb/factory/build.py (a factory row's arm),
              src/crb/core/prevention.py (the ``learn`` label ``+L`` reads)
Tested by:    tests/test_context_arm.py, tests/test_routing_v2.py
Touch when:   never for a new repository; an arm base or modifier is added — an ADR amending
              ADR-0026 item 1 first; a new provenance stamp (add it to ``PROVENANCE_LABELS``, never
              to the arm); a context-set source or name rule changes (ADR-0050 first); never for
              a new repository.
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

#: A ``+library@`` NAME that starts with this prefix is reserved for a context set (ADR-0050
#: item 2): ``ctx.<source>.<digest[:12]>``, and only on base ``A0`` without ``+facts`` or ``+L``.
CTX_PREFIX = "ctx."
#: The kind of each context-set source: ``hindsight`` (written with sight of the answer, read
#: as a ceiling, under the novel-token guard), ``mechanical`` (drafted at the parent commit by a
#: pinned drafter) and ``stated`` (ADR-0052: stated requirements, written with hindsight, whose
#: new names are declared item by item and checked by ``req_guard``) and ``planned``
#: (ADR-0054: an accepted implementation plan, written before the build from the ticket and the
#: parent tree, checked by ``plan_guard``; it has no placebo source yet). ``plan-audited``
#: (ADR-0055) is a ``planned`` source whose set carries an attestation that its plans were
#: drafted blind; its arm skips only the guard's lookalike reasons. THE one table every
#: predicate below and ``crb.core.ctxset`` derives a source's kind from (ADR-0052 item 4).
CTX_KIND_HINDSIGHT = "hindsight"
CTX_KIND_MECHANICAL = "mechanical"
CTX_KIND_STATED = "stated"
CTX_KIND_PLANNED = "planned"
CTX_KINDS: tuple[str, ...] = (
    CTX_KIND_HINDSIGHT,
    CTX_KIND_MECHANICAL,
    CTX_KIND_STATED,
    CTX_KIND_PLANNED,
)
CTX_SOURCE_KIND: dict[str, str] = {
    "oracle": CTX_KIND_HINDSIGHT,
    "oracle-placebo": CTX_KIND_HINDSIGHT,
    "mech": CTX_KIND_MECHANICAL,
    "mech-placebo": CTX_KIND_MECHANICAL,
    "req": CTX_KIND_STATED,
    "req-placebo": CTX_KIND_STATED,
    "plan": CTX_KIND_PLANNED,
    "plan-audited": CTX_KIND_PLANNED,
}
#: The context-set sources, in table order.
CTX_SOURCES: tuple[str, ...] = tuple(CTX_SOURCE_KIND)
CTX_HINDSIGHT_PREFIX = "ctx.oracle"
CTX_NAME_RE = re.compile(
    r"^ctx\.(" + "|".join(re.escape(s) for s in CTX_SOURCES) + r")\.[0-9a-f]{12}$"
)

#: Provenance stamps (ADR-0026 item 1): shown and filterable, never a pooling key.
LABEL_CTX_TICKET = "ctx_ticket"
LABEL_CTX_BRIEF = "ctx_brief"
LABEL_CTX_HARNESS = "ctx_harness"
LABEL_CTX_RULES = "ctx_rules"
LABEL_CTX_AUTHOR = "ctx_author"
LABEL_CTX_LIBRARY = "ctx_library"
LABEL_CTX_REFUSED = "ctx_refused"
#: Context-set stamps (ADR-0050 item 5): provenance, never the arm. ``ctx_set`` is the set's
#: full digest; ``ctx_source`` its source, or ``control`` on a plain ``A0`` control row.
LABEL_CTX_SET = "ctx_set"
LABEL_CTX_SOURCE = "ctx_source"
LABEL_CTX_GAP = "ctx_gap"
LABEL_CTX_GAP_RULE = "ctx_gap_rule"
LABEL_CTX_DELIVERED = "ctx_delivered"
LABEL_CTX_CHARS = "ctx_chars"
LABEL_CTX_CEILING = "ctx_ceiling"
LABEL_CTX_DRAFTER = "ctx_drafter"
#: Stated-requirement stamps (ADR-0052 item 2), on an entries row of a ``ctx.req*`` arm only:
#: ``ctx_stated`` = ``1``; ``ctx_items`` the set's items digest; ``ctx_structure`` the
#: renderer; ``ctx_author_saw`` what the items' writer saw; ``ctx_prov`` the task's declared
#: item provenance counts; ``ctx_req_drafter`` who wrote the items (never ``ctx_drafter``,
#: which means a mechanical drafter); ``ctx_req_refused`` the guard's reasons when it withheld
#: the entry.
LABEL_CTX_STATED = "ctx_stated"
LABEL_CTX_ITEMS = "ctx_items"
LABEL_CTX_STRUCTURE = "ctx_structure"
LABEL_CTX_AUTHOR_SAW = "ctx_author_saw"
LABEL_CTX_PROV = "ctx_prov"
LABEL_CTX_REQ_DRAFTER = "ctx_req_drafter"
LABEL_CTX_REQ_REFUSED = "ctx_req_refused"
#: ADR-0053: on an entries row of a ``ctx.req*`` arm whose run opted in to
#: ``measure_open_gaps``, the count of the task's open requirement gaps (absent otherwise):
#: the row was measured with a requirement the requester had not yet stated.
LABEL_CTX_OPEN_GAPS = "ctx_open_gaps"
#: Accepted-plan stamps (ADR-0054), on an entries row of a ``ctx.plan*`` arm only:
#: ``ctx_plan_drafter`` who wrote the plan (``human:<id>`` or ``model:<id>@<sha256>``; never
#: ``ctx_drafter``, which means a mechanical drafter); ``ctx_plan_saw`` what the drafter saw
#: (``ticket`` or ``ticket,tree``); ``ctx_plan_accepted`` who accepted it (``human:<id>`` or
#: ``none``); ``ctx_plan_refused`` the guard's reasons when it withheld the plan;
#: ``ctx_plan_novel`` how many tokens the change introduced the delivered plan names
#: (counted, never refused).
LABEL_CTX_PLAN_DRAFTER = "ctx_plan_drafter"
LABEL_CTX_PLAN_SAW = "ctx_plan_saw"
LABEL_CTX_PLAN_ACCEPTED = "ctx_plan_accepted"
LABEL_CTX_PLAN_REFUSED = "ctx_plan_refused"
LABEL_CTX_PLAN_NOVEL = "ctx_plan_novel"
#: Audited-bypass stamps (ADR-0055), on an entries row of a ``ctx.plan-audited*`` arm only:
#: ``ctx_plan_guard`` = ``audited_bypass`` (the guard's lookalike reasons were not applied);
#: ``ctx_plan_would_refuse`` the lookalike reasons the full guard would have withheld the plan
#: for; ``ctx_plan_audit`` the audit record's sha256; ``ctx_plan_auditor`` who attested it.
#: The attestation is the storing operator's claim: the product does not verify it.
LABEL_CTX_PLAN_GUARD = "ctx_plan_guard"
LABEL_CTX_PLAN_WOULD_REFUSE = "ctx_plan_would_refuse"
LABEL_CTX_PLAN_AUDIT = "ctx_plan_audit"
LABEL_CTX_PLAN_AUDITOR = "ctx_plan_auditor"
#: The one value of ``ctx_plan_guard`` (ADR-0055).
PLAN_GUARD_AUDITED_BYPASS = "audited_bypass"
#: The builder's turns on a row of a context-set run (ADR-0052 item 5). Deliberately NOT in
#: :data:`PROVENANCE_LABELS`: a per-row count is not a stamp to list or filter by, and the
#: control rows that carry it are plain ``A0`` rows (ADR-0052 review note 13).
LABEL_CTX_TURNS = "ctx_turns"
#: ``ctx_source`` on a plain ``A0`` row of a context-set control run.
CTX_SOURCE_CONTROL = "control"
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
    # the context-set stamps (ADR-0050 item 5)
    LABEL_CTX_SET,
    LABEL_CTX_SOURCE,
    LABEL_CTX_GAP,
    LABEL_CTX_GAP_RULE,
    LABEL_CTX_DELIVERED,
    LABEL_CTX_CHARS,
    LABEL_CTX_CEILING,
    LABEL_CTX_DRAFTER,
    # the stated-requirement stamps (ADR-0052 item 2)
    LABEL_CTX_STATED,
    LABEL_CTX_ITEMS,
    LABEL_CTX_STRUCTURE,
    LABEL_CTX_AUTHOR_SAW,
    LABEL_CTX_PROV,
    LABEL_CTX_REQ_DRAFTER,
    LABEL_CTX_REQ_REFUSED,
    LABEL_CTX_OPEN_GAPS,
    # the accepted-plan stamps (ADR-0054)
    LABEL_CTX_PLAN_DRAFTER,
    LABEL_CTX_PLAN_SAW,
    LABEL_CTX_PLAN_ACCEPTED,
    LABEL_CTX_PLAN_REFUSED,
    LABEL_CTX_PLAN_NOVEL,
    # the audited-bypass stamps (ADR-0055)
    LABEL_CTX_PLAN_GUARD,
    LABEL_CTX_PLAN_WOULD_REFUSE,
    LABEL_CTX_PLAN_AUDIT,
    LABEL_CTX_PLAN_AUDITOR,
)

#: The ``learn`` label value that means the loop was off for the run (ADR-0020 §8).
LEARN_OFF = "off"
LABEL_LEARN = "learn"

#: Where a factory build's failing test came from.
TEST_AUTHORED = "authored"
TEST_PERSON = "person"

_NAME = r"[A-Za-z0-9][A-Za-z0-9._:/-]*"
#: A ``+library@`` NAME: any ordinary name outside the reserved ``ctx.`` namespace, or a
#: well-formed context-set name (``CTX_NAME_RE``). A malformed ``ctx.`` name is outside the
#: grammar, so it can never parse as an ordinary, certifying library arm (ADR-0050 item 2).
_LIBRARY_NAME = (
    rf"(?!{re.escape(CTX_PREFIX)}){_NAME}"
    rf"|{CTX_NAME_RE.pattern.removeprefix('^').removesuffix('$')}"
)
_ARM_RE = re.compile(
    rf"^(?P<base>A0|S1@(?P<author>{_NAME})|S2|S3)"
    rf"(?:\+facts@(?P<facts>{_NAME}))?"
    rf"(?:\+library@(?P<library>{_LIBRARY_NAME}))?"
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


def ctx_set_name(arm: str) -> str:
    """The context-set NAME an arm's ``+library@`` modifier carries (ADR-0050 item 2), or
    ``""`` when the arm names no context set (or is outside the grammar). Derived from the arm
    id alone, so no run parameter can disagree with it."""
    m = _ARM_RE.match((arm or "").strip())
    if not m:
        return ""
    name = m.group("library") or ""
    return name if CTX_NAME_RE.match(name) else ""


def ctx_source_of(arm: str) -> str:
    """The context-set source an arm names (``oracle``, ``req-placebo`` ...), or ``""``."""
    name = ctx_set_name(arm)
    return name.split(".")[1] if name else ""


def ctx_kind(source: str) -> str:
    """A context-set source's kind from :data:`CTX_SOURCE_KIND`; refuses an unknown source."""
    try:
        return CTX_SOURCE_KIND[source]
    except KeyError:
        raise ValueError(f"context-set source {source!r} is not one of {CTX_SOURCES}") from None


def hindsight_arm(arm: str) -> bool:
    """``True`` for a context-set arm written with hindsight of the answer: the ``hindsight``
    kind (``ctx.oracle*``, ADR-0050 items 2 and 4) and the ``stated`` kind (``ctx.req*``,
    ADR-0052). Both skip the retrospective time rule and are read as a ceiling."""
    source = ctx_source_of(arm)
    return bool(source) and ctx_kind(source) in (CTX_KIND_HINDSIGHT, CTX_KIND_STATED)


def stated_arm(arm: str) -> bool:
    """``True`` for a stated-requirement arm (``ctx.req*``, ADR-0052): its entries are
    rendered from declared items and checked by ``req_guard`` instead of the novel-token
    guard; every other line of its brief keeps the novel-token guard."""
    source = ctx_source_of(arm)
    return bool(source) and ctx_kind(source) == CTX_KIND_STATED


def plan_arm(arm: str) -> bool:
    """``True`` for an accepted-plan arm (``ctx.plan*``, ADR-0054): its entries are rendered
    from a plan and checked by ``plan_guard``; they are admitted at the task's parent commit
    without the mechanical stamp, and the text reaches the brief's own plan block."""
    source = ctx_source_of(arm)
    return bool(source) and ctx_kind(source) == CTX_KIND_PLANNED


def audited_plan_arm(arm: str) -> bool:
    """``True`` for an audited-bypass plan arm (``ctx.plan-audited*``, ADR-0055): a plan arm
    whose set attests blind drafting, so ``plan_guard``'s lookalike reasons are stamped, not
    applied. Its rows never pool or pair with a ``ctx.plan.<hex>`` arm's."""
    return ctx_source_of(arm) == "plan-audited"


def measurement_only(arm: str) -> bool:
    """``True`` for any context-set arm: no reading accepts it and it never certifies,
    licenses, routes or enters the value scorecard (ADR-0050 item 9)."""
    return ctx_set_name(arm) != ""


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
    "CTX_HINDSIGHT_PREFIX",
    "CTX_KINDS",
    "CTX_KIND_HINDSIGHT",
    "CTX_KIND_MECHANICAL",
    "CTX_KIND_PLANNED",
    "CTX_KIND_STATED",
    "CTX_NAME_RE",
    "CTX_PREFIX",
    "CTX_SOURCES",
    "CTX_SOURCE_CONTROL",
    "CTX_SOURCE_KIND",
    "LABEL_CONTEXT_ARM",
    "LABEL_CTX_AUTHOR_SAW",
    "LABEL_CTX_CEILING",
    "LABEL_CTX_CHARS",
    "LABEL_CTX_DELIVERED",
    "LABEL_CTX_DRAFTER",
    "LABEL_CTX_GAP",
    "LABEL_CTX_GAP_RULE",
    "LABEL_CTX_ITEMS",
    "LABEL_CTX_OPEN_GAPS",
    "LABEL_CTX_PLAN_ACCEPTED",
    "LABEL_CTX_PLAN_AUDIT",
    "LABEL_CTX_PLAN_AUDITOR",
    "LABEL_CTX_PLAN_DRAFTER",
    "LABEL_CTX_PLAN_GUARD",
    "LABEL_CTX_PLAN_NOVEL",
    "LABEL_CTX_PLAN_REFUSED",
    "LABEL_CTX_PLAN_SAW",
    "LABEL_CTX_PLAN_WOULD_REFUSE",
    "LABEL_CTX_PROV",
    "LABEL_CTX_REQ_DRAFTER",
    "LABEL_CTX_REQ_REFUSED",
    "LABEL_CTX_SET",
    "LABEL_CTX_SOURCE",
    "LABEL_CTX_STATED",
    "LABEL_CTX_STRUCTURE",
    "LABEL_CTX_TURNS",
    "PLAN_GUARD_AUDITED_BYPASS",
    "PROVENANCE_LABELS",
    "REPLAY_MODE",
    "TEST_AUTHORED",
    "TEST_PERSON",
    "ContextArm",
    "ContextArmsPooled",
    "arms_present",
    "audited_plan_arm",
    "context_arm_for",
    "ctx_kind",
    "ctx_set_name",
    "ctx_source_of",
    "hindsight_arm",
    "is_arm",
    "loop_on",
    "measurement_only",
    "mode_admits",
    "parse_arm",
    "plan_arm",
    "rows_for_context_arm",
    "stated_arm",
]
