"""Stated requirements — the structured items a ``ctx.req*`` entry is rendered from (ADR-0052).

A stated-requirement entry is never free text. Its author writes ITEMS, each one requirement a
reviewer would sign off against::

    {"item_id": "i01", "kind": "error_text", "statement": "...", "provenance": "tests_only",
     "discloses": ["token the change introduces", ...]}

and the text the builder reads is rendered BY CODE from the items with the set's fixed
renderer (:data:`STRUCTURES`): ``prose`` (one paragraph) or ``checklist`` (one ``- `` line per
item). Both renderers state every item's statement verbatim, in ``item_id`` order, under one
fixed header and with no kind or provenance tag, so two structures over the same items carry
the same information and differ only in form (ADR-0052 item 4; review must-fix 2).

The **item hash** is the sha256 of the canonical JSON of ``{task_id, item_id, kind,
statement, provenance, discloses}``; the **items digest** of a set is the sha256 of the
sorted list of its item hashes. Text and structure are outside it, so a prose set and a
checklist set over the same items share one items digest — and one control run.

**Provenance** says where an item's disclosed tokens live: ``product`` (the parent tree),
``change_detail`` (the change's source post-image, with or without its tests), ``tests_only``
(only the held-out tests' post-image) or ``nowhere``. They rank ``nowhere < product <
change_detail < tests_only`` and an item takes the most answer-side of its tokens. An item
that discloses no token cannot be checked mechanically: it is counted ``attested``.

Navigation
----------
What it is:   The stated-requirement vocabulary: item kinds, provenance values and their
              rank, the structures and their renderers (``render``), the item and items
              digests (``item_hash``, ``items_digest``), the fixed length limits and the
              ``ctx_prov`` stamp (``prov_label``), and the ``req_guard`` reason names.
What it does: Renders an entry's text from its items, deterministically; hashes items;
              names the reasons ``crb.builders.brief.req_guard`` refuses with.
How:          Pure functions over frozen dataclasses (stdlib only), so the set parser
              (``crb.core.ctxset``), the composer's guard (``crb.builders.brief``) and the
              pair reader (``crb.core.ctx_compare``) read one definition.
Layer:        core — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0052-stated-requirement-arms.md, docs/adr/0050-context-set-arms.md
Works with:   src/crb/core/ctxset.py (the ``crb.ctxset.v2`` record whose entries carry items),
              src/crb/builders/brief.py (``req_guard``, which re-renders and checks an entry),
              src/crb/core/ctx_compare.py (items-digest pairing, provenance strata),
              src/crb/core/context_arm.py (the ``ctx.req*`` sources and stamps)
Tested by:    tests/test_stated.py
Touch when:   never for a new repository; a kind, provenance value, structure, renderer or
              length limit changes (a new ADR first: a renderer change moves every digest
              of a rendered text).
Claims:       A rendered entry says what its writer stated, with sight of the change and its
              tests; the items digest says the items are unaltered, not that they are true or
              complete (ADR-0052 Consequences).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

KIND_NAME = "name"
KIND_SIGNATURE = "signature"
KIND_ERROR_TEXT = "error_text"
KIND_FORMAT = "format"
KIND_RULE = "rule"
KIND_VALUE = "value"
KINDS: tuple[str, ...] = (
    KIND_NAME,
    KIND_SIGNATURE,
    KIND_ERROR_TEXT,
    KIND_FORMAT,
    KIND_RULE,
    KIND_VALUE,
)

PROV_PRODUCT = "product"
PROV_CHANGE_DETAIL = "change_detail"
PROV_TESTS_ONLY = "tests_only"
PROV_NOWHERE = "nowhere"
PROVENANCES: tuple[str, ...] = (PROV_PRODUCT, PROV_CHANGE_DETAIL, PROV_TESTS_ONLY, PROV_NOWHERE)
#: The order "most answer-side" is read in (review item 5): an item takes its tokens' maximum.
PROV_RANK: Mapping[str, int] = {
    PROV_NOWHERE: 0,
    PROV_PRODUCT: 1,
    PROV_CHANGE_DETAIL: 2,
    PROV_TESTS_ONLY: 3,
}
#: The ``ctx_prov`` count of items that disclose no token: stated, not mechanically checked.
PROV_ATTESTED = "attested"

STRUCTURE_PROSE = "prose"
STRUCTURE_CHECKLIST = "checklist"
STRUCTURES: tuple[str, ...] = (STRUCTURE_PROSE, STRUCTURE_CHECKLIST)

#: What a set records its items' writer saw (``saw``, stamped as ``ctx_author_saw``).
SAW_DIFF = "diff"
SAW_TESTS = "tests"
SAW_TICKET = "ticket"
SAW_VALUES: tuple[str, ...] = (SAW_DIFF, SAW_TESTS, SAW_TICKET)

#: The fixed limits (ADR-0052 item 3.7). Changing one is a new ADR.
MAX_ITEMS = 12
MAX_STATEMENT_CHARS = 240
MAX_ENTRY_CHARS = 1600
#: The shared-span length the copy rule refuses (ADR-0052 item 3.6), in code tokens.
SPAN_TOKENS = 8

#: The one header both renderers open with.
HEADER = "Stated requirements for this change:"

#: The reasons ``crb.builders.brief.req_guard`` withholds an entry for (ADR-0052 item 3).
REASON_RENDER = "req_render"
REASON_LENGTH = "req_length"
REASON_CODE_BLOCK = "req_code_block"
REASON_UNDECLARED_NOVEL = "req_undeclared_novel"
REASON_PROVENANCE = "req_provenance"
REASON_TEST_NAME = "req_test_name"
REASON_TEST_PATH = "req_test_path"
REASON_TEST_SPAN = "req_test_span"
REASON_SIGNATURE = "req_signature"
REASON_NO_GOLD = "req_no_gold"
REASONS: tuple[str, ...] = (
    REASON_RENDER,
    REASON_LENGTH,
    REASON_CODE_BLOCK,
    REASON_UNDECLARED_NOVEL,
    REASON_PROVENANCE,
    REASON_TEST_NAME,
    REASON_TEST_PATH,
    REASON_TEST_SPAN,
    REASON_SIGNATURE,
    REASON_NO_GOLD,
)


@dataclass(frozen=True)
class StatedItem:
    """One stated requirement. ``discloses`` holds the tokens the statement names that the
    change may have introduced, each a substring of ``statement``, sorted and unique."""

    item_id: str
    kind: str
    statement: str
    provenance: str
    discloses: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ValueError(f"item kind {self.kind!r} is not one of {KINDS}")
        if self.provenance not in PROVENANCES:
            raise ValueError(f"item provenance {self.provenance!r} is not one of {PROVENANCES}")

    @property
    def attested(self) -> bool:
        """An item that discloses no token: its provenance is stated, never checked."""
        return not self.discloses

    def to_doc(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "kind": self.kind,
            "statement": self.statement,
            "provenance": self.provenance,
            "discloses": list(self.discloses),
        }


def _sentence(statement: str) -> str:
    s = statement.strip()
    return s if s.endswith((".", "!", "?")) else s + "."


def _ordered(items: Iterable[StatedItem]) -> list[StatedItem]:
    return sorted(items, key=lambda i: i.item_id)


def render_prose(items: Sequence[StatedItem]) -> str:
    """The ``prose`` renderer: the header and one paragraph, each statement a sentence."""
    return HEADER + " " + " ".join(_sentence(i.statement) for i in _ordered(items))


def render_checklist(items: Sequence[StatedItem]) -> str:
    """The ``checklist`` renderer: the header, then one ``- <statement>`` line per item."""
    return "\n".join([HEADER, *(f"- {i.statement.strip()}" for i in _ordered(items))])


_RENDERERS = {STRUCTURE_PROSE: render_prose, STRUCTURE_CHECKLIST: render_checklist}


def render(structure: str, items: Sequence[StatedItem]) -> str:
    """THE text of a stated entry: ``structure``'s fixed renderer over ``items``. Nothing
    else produces the text a ``ctx.req*`` arm delivers (ADR-0052 item 4)."""
    try:
        fn = _RENDERERS[structure]
    except KeyError:
        raise ValueError(f"structure {structure!r} is not one of {STRUCTURES}") from None
    if not items:
        raise ValueError("a stated entry renders at least one item")
    return fn(items)


def _canonical(doc: Any) -> str:
    return json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def item_hash(task_id: str, item: StatedItem) -> str:
    """sha256 of ``{task_id, item_id, kind, statement, provenance, discloses (sorted)}``."""
    body = {**item.to_doc(), "task_id": task_id, "discloses": sorted(item.discloses)}
    return hashlib.sha256(_canonical(body).encode("utf-8")).hexdigest()


def items_digest(per_task: Mapping[str, Sequence[StatedItem]]) -> str:
    """The items digest of a set: sha256 of the sorted list of every task's item hashes.
    The rendered text and the structure are outside it."""
    hashes = sorted(item_hash(tid, i) for tid, items in per_task.items() for i in items)
    return hashlib.sha256(_canonical(hashes).encode("utf-8")).hexdigest()


def length_violation(items: Sequence[StatedItem], text: str) -> str:
    """Why an entry breaks the fixed limits (``""`` when it does not)."""
    if len(items) > MAX_ITEMS:
        return f"{len(items)} items (at most {MAX_ITEMS})"
    for i in items:
        if len(i.statement) > MAX_STATEMENT_CHARS:
            return (
                f"item {i.item_id}: {len(i.statement)} characters (at most {MAX_STATEMENT_CHARS})"
            )
    if len(text) > MAX_ENTRY_CHARS:
        return f"{len(text)} entry characters (at most {MAX_ENTRY_CHARS})"
    return ""


def prov_counts(items: Iterable[StatedItem]) -> dict[str, int]:
    """Declared provenance per item, in :data:`PROVENANCES` order, plus ``attested``."""
    items = list(items)
    out = {p: sum(1 for i in items if i.provenance == p) for p in PROVENANCES}
    out[PROV_ATTESTED] = sum(1 for i in items if i.attested)
    return out


def prov_label(items: Iterable[StatedItem]) -> str:
    """The ``ctx_prov`` stamp: ``product:N,change_detail:N,tests_only:N,nowhere:N;attested:N``."""
    c = prov_counts(items)
    head = ",".join(f"{p}:{c[p]}" for p in PROVENANCES)
    return f"{head};{PROV_ATTESTED}:{c[PROV_ATTESTED]}"


def any_tests_only(items: Iterable[StatedItem]) -> bool:
    """Whether any item states something only the held-out tests hold (the required
    provenance split a comparison reports, ADR-0052 review note 8)."""
    return any(i.provenance == PROV_TESTS_ONLY for i in items)


__all__ = [
    "HEADER",
    "KINDS",
    "KIND_ERROR_TEXT",
    "KIND_FORMAT",
    "KIND_NAME",
    "KIND_RULE",
    "KIND_SIGNATURE",
    "KIND_VALUE",
    "MAX_ENTRY_CHARS",
    "MAX_ITEMS",
    "MAX_STATEMENT_CHARS",
    "PROVENANCES",
    "PROV_ATTESTED",
    "PROV_CHANGE_DETAIL",
    "PROV_NOWHERE",
    "PROV_PRODUCT",
    "PROV_RANK",
    "PROV_TESTS_ONLY",
    "REASONS",
    "REASON_CODE_BLOCK",
    "REASON_LENGTH",
    "REASON_NO_GOLD",
    "REASON_PROVENANCE",
    "REASON_RENDER",
    "REASON_SIGNATURE",
    "REASON_TEST_NAME",
    "REASON_TEST_PATH",
    "REASON_TEST_SPAN",
    "REASON_UNDECLARED_NOVEL",
    "SAW_DIFF",
    "SAW_TESTS",
    "SAW_TICKET",
    "SAW_VALUES",
    "SPAN_TOKENS",
    "STRUCTURES",
    "STRUCTURE_CHECKLIST",
    "STRUCTURE_PROSE",
    "StatedItem",
    "any_tests_only",
    "item_hash",
    "items_digest",
    "length_violation",
    "prov_counts",
    "prov_label",
    "render",
    "render_checklist",
    "render_prose",
]
