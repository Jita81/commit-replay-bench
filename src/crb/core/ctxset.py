"""A context set — one frozen, hashed context entry per task, run as its own arm (ADR-0050).

A context set is ONE JSON document, schema ``crb.ctxset.v1``::

    {"schema": "crb.ctxset.v1", "source": "oracle" | "oracle-placebo" | "mech" | "mech-placebo",
     "repo": "<registered repo id>", "method": "<public-safe free text>",
     "matched_to": "<treatment digest>"          (a placebo only),
     "drafter": "<pinned model id>@<sha256 of the drafting prompt>"   (mech* only),
     "entries": [{"task_id", "entry_id", "version", "text", "produced_at", "mechanical",
                  "source_rev" (mech* only: the task's parent commit)}, ...]}

with exactly one entry per task, sorted by ``task_id``.

A **stated-requirement** set (``req`` / ``req-placebo``, ADR-0052) is schema
``crb.ctxset.v2`` — and only those sources are; a v1 ``req*`` document and a v2 document of any
other source are refused::

    {"schema": "crb.ctxset.v2", "source": "req" | "req-placebo", "repo", "method",
     "structure": "prose" | "checklist", "drafter": "human:<id>" | "model:<id>@<sha256>",
     "saw": ["diff", "tests", "ticket"] (a sorted subset), "matched_to" (a placebo only),
     "entries": [{"task_id", "entry_id", "version", "produced_at",
                  "items": [{"item_id", "kind", "statement", "provenance", "discloses"}]}]}

A v2 entry stores no text: its text is rendered BY CODE from its items with the set's
structure (``crb.core.stated.render``), so nothing free-form reaches a brief. Each item's
``discloses`` tokens appear verbatim in its statement (``ctxset_items_undelivered``) and the
fixed limits hold (``ctxset_items_length``). Its **digest** is the sha256 of its
canonical JSON (sorted keys, ``(",", ":")`` separators, UTF-8, no ASCII escaping); its
**name** is ``ctx.<source>.<digest[:12]>`` and is never stored inside the hashed body, so a
changed set is a new digest and a new arm (``A0+library@<name>``). Every check here refuses
with :class:`CtxSetRefused` and a named reason (``ctxset_*``), at store time and again when a
run loads the set.

The **placebo** (ADR-0050 item 7) is its own set over the same tasks, within
``max(16, 2%)`` characters of its treatment per task, sharing no identifier token with the
treatment entry beyond :data:`STOPWORDS`, naming its treatment by digest.

The **gap label** (``anchor.v1``, item 6) is :func:`ctx_gap_anchor`: ``"1"`` when the ticket
names no identifier the parent tree holds. It reads the ticket and the parent tree only — a
pre-treatment covariate, descriptive, never a pooling, routing or primary-test key.

Navigation
----------
What it is:   The context-set record (``CtxSet``, ``CtxEntryRecord``), its parser and digest
              (``parse``, ``canonical_digest``, ``name_of``), the run-time checks
              (``verify_coverage``, ``verify_source_revs``, ``verify_placebo``), the gap rule
              (``ctx_gap_anchor``, ``GAP_RULE``) and the per-task row stamps (``run_stamps``).
What it does: Refuses a malformed set (``ctxset_schema``), a name that disagrees with the
              recomputed digest (``ctxset_digest``), a set whose tasks are not one gold-clean
              task each of one change each (``ctxset_coverage``), a mechanical set without
              its drafter or parent-commit boundary (``ctxset_mechanical``), a placebo that
              is not length-matched or shares identifiers (``ctxset_placebo_*``) and a set of
              another repository (``ctxset_repo``); labels a ticket's gap; stamps rows.
How:          Pure functions over JSON values (stdlib only); the parent tree is reached only
              through the ``tree_has`` callable the worker passes.
Layer:        core — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0050-context-set-arms.md, docs/adr/0052-stated-requirement-arms.md
              (the v2 schema), docs/adr/0026-the-context-standard.md
              (items 1, 7 and 10, which ADR-0050 amends)
Works with:   src/crb/core/context_arm.py (the reserved ``ctx.`` names and the ctx labels),
              src/crb/builders/brief.py (``ContextEntry``, the admission the arm derives; it
              never imports this module), src/crb/server/routes/ctxsets.py (stores a set
              once ``parse`` and the verifiers pass), src/crb/server/worker.py (the run-time
              gap rule and ``run_stamps`` per task), src/crb/core/ctx_compare.py (pairs the
              runs of a parsed ``CtxSet``)
Tested by:    tests/test_ctxset.py
Touch when:   never for a new repository; the schema, a source, the placebo tolerance, the
              stopword list or the gap rule changes (an ADR amending ADR-0050 first; a new
              gap rule is a new ``GAP_RULE`` value, never a silent change).
Claims:       A set's digest says it is unaltered since it was hashed, not that its entries
              are true; a mechanical set's drafting is attested by its record, not produced
              by crb (ADR-0050 Consequences).
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Protocol

from crb.core import context_arm as _arms
from crb.core import stated as _stated

SCHEMA = "crb.ctxset.v1"
#: The stated-requirement schema (ADR-0052): items, a structure and the writer's sight.
SCHEMA_V2 = "crb.ctxset.v2"
SCHEMAS: tuple[str, ...] = (SCHEMA, SCHEMA_V2)

SOURCE_ORACLE = "oracle"
SOURCE_ORACLE_PLACEBO = "oracle-placebo"
SOURCE_MECH = "mech"
SOURCE_MECH_PLACEBO = "mech-placebo"
SOURCE_REQ = "req"
SOURCE_REQ_PLACEBO = "req-placebo"
SOURCES: tuple[str, ...] = _arms.CTX_SOURCES
PLACEBO_SUFFIX = "-placebo"

#: The roles a run plays against one set: ``entries`` (its entries reach the brief) and
#: ``control`` (plain ``A0``, the set's provenance stamped, nothing delivered).
ROLE_ENTRIES = "entries"
ROLE_CONTROL = "control"
ROLES: tuple[str, ...] = (ROLE_ENTRIES, ROLE_CONTROL)

#: The one gap rule (ADR-0050 item 6). A later detector is a new value, never a change here.
GAP_RULE = "anchor.v1"
GAP_YES = "1"
GAP_NO = "0"

#: The refusal reasons, each its own (ADR-0050 item 1 and the design's refusals).
REASON_SCHEMA = "ctxset_schema"
REASON_DIGEST = "ctxset_digest"
REASON_COVERAGE = "ctxset_coverage"
REASON_MECHANICAL = "ctxset_mechanical"
REASON_PLACEBO_UNMATCHED = "ctxset_placebo_unmatched"
REASON_PLACEBO_OVERLAP = "ctxset_placebo_overlap"
REASON_MODE = "ctxset_mode"
REASON_POSTURE = "ctxset_posture"
REASON_REPO = "ctxset_repo"
#: A stated item names a disclosed token its own statement does not carry (ADR-0052 item 3).
REASON_ITEMS_UNDELIVERED = "ctxset_items_undelivered"
#: A stated entry breaks the fixed item, statement or entry-length limits (ADR-0052 item 3.7).
REASON_ITEMS_LENGTH = "ctxset_items_length"
REASONS: tuple[str, ...] = (
    REASON_SCHEMA,
    REASON_DIGEST,
    REASON_COVERAGE,
    REASON_MECHANICAL,
    REASON_PLACEBO_UNMATCHED,
    REASON_PLACEBO_OVERLAP,
    REASON_MODE,
    REASON_POSTURE,
    REASON_REPO,
    REASON_ITEMS_UNDELIVERED,
    REASON_ITEMS_LENGTH,
)

#: A placebo entry's length may differ from its treatment's by at most
#: ``max(PLACEBO_MIN_CHARS, PLACEBO_FRACTION * len(treatment))`` characters.
PLACEBO_MIN_CHARS = 16
PLACEBO_FRACTION = 0.02

#: Identifier tokens a placebo may share with its treatment (compared lower-case): words so
#: common across codebases and prose that sharing one says nothing about the change. Fixed in
#: code; changed only by a reviewed change (ADR-0050 risks).
STOPWORDS: frozenset[str] = frozenset(
    {
        "e.g",
        "i.e",
        "etc",
        "n/a",
        "and/or",
        "self",
        "this",
        "none",
        "null",
        "nil",
        "true",
        "false",
        "__init__",
        "__main__",
        "readme.md",
        "main.go",
        "setup.py",
        "package.json",
        "pyproject.toml",
        "go.mod",
    }
)

_TOP_REQUIRED = ("schema", "source", "repo", "method", "entries")
_TOP_OPTIONAL = ("matched_to", "drafter")
_ENTRY_REQUIRED = ("task_id", "entry_id", "version", "text", "produced_at", "mechanical")
_ENTRY_OPTIONAL = ("source_rev",)
_V2_TOP_REQUIRED = ("schema", "source", "repo", "method", "structure", "drafter", "saw", "entries")
_V2_TOP_OPTIONAL = ("matched_to",)
_V2_ENTRY_REQUIRED = ("task_id", "entry_id", "version", "produced_at", "items")
_ITEM_REQUIRED = ("item_id", "kind", "statement", "provenance", "discloses")
_ITEM_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,31}$")
#: who wrote a stated set's items (ADR-0052): ``stated.REQ_DRAFTER_RE``
_REQ_DRAFTER_RE = _stated.REQ_DRAFTER_RE
_SHA_RE = re.compile(r"^[0-9a-f]{7,64}$")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_DRAFTER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]*@[0-9a-f]{64}$")
_REPO_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_TOKEN_RE = re.compile(r"[A-Za-z0-9_./-]+")
_BACKTICK_RE = re.compile(r"`([^`\n]+)`")
_EDGE_PUNCT = "./-"


class CtxSetRefused(ValueError):
    """A context set failed a check; ``reason`` is one of :data:`REASONS`."""

    def __init__(self, reason: str, detail: str) -> None:
        if reason not in REASONS:
            raise ValueError(f"unknown context-set refusal reason {reason!r}")
        super().__init__(f"{reason}: {detail}")
        self.reason = reason
        self.detail = detail


@dataclass(frozen=True)
class CtxEntryRecord:
    """One task's entry as the set records it. ``source_rev`` is set on a ``mech*`` set only:
    the task's parent commit, the entry's knowledge boundary (ADR-0050 item 4)."""

    task_id: str
    entry_id: str
    version: str
    text: str
    produced_at: str
    mechanical: bool
    source_rev: str = ""
    #: A stated (v2) entry's items, in ``item_id`` order; ``text`` is their rendering.
    items: tuple[_stated.StatedItem, ...] = ()

    def to_doc(self) -> dict[str, Any]:
        if self.items:
            return {
                "task_id": self.task_id,
                "entry_id": self.entry_id,
                "version": self.version,
                "produced_at": self.produced_at,
                "items": [i.to_doc() for i in self.items],
            }
        out: dict[str, Any] = {
            "task_id": self.task_id,
            "entry_id": self.entry_id,
            "version": self.version,
            "text": self.text,
            "produced_at": self.produced_at,
            "mechanical": self.mechanical,
        }
        if self.source_rev:
            out["source_rev"] = self.source_rev
        return out


@dataclass(frozen=True)
class CtxSet:
    """A parsed, digest-checked context set. Build one only through :func:`parse`."""

    source: str
    repo: str
    method: str
    entries: tuple[CtxEntryRecord, ...]
    digest: str
    matched_to: str = ""
    drafter: str = ""
    schema: str = SCHEMA
    #: A stated set's renderer and what its items' writer saw (``crb.ctxset.v2`` only).
    structure: str = ""
    saw: tuple[str, ...] = ()

    @property
    def name(self) -> str:
        """``ctx.<source>.<digest[:12]>`` — the ``+library@`` NAME of the set's arm."""
        return name_of(self.source, self.digest)

    @property
    def arm(self) -> str:
        """The arm a run delivering this set's entries writes: ``A0+library@<name>``."""
        return _arms.ContextArm(_arms.BASE_A0, library=self.name).id

    @property
    def kind(self) -> str:
        """The source's kind, from the one table (``context_arm.CTX_SOURCE_KIND``)."""
        return _arms.ctx_kind(self.source)

    @property
    def hindsight(self) -> bool:
        """``ctx.oracle*`` and ``ctx.req*``: written with hindsight of the answer — a
        measurement-only ceiling (ADR-0050 item 4, ADR-0052 item 1)."""
        return self.kind in (_arms.CTX_KIND_HINDSIGHT, _arms.CTX_KIND_STATED)

    @property
    def mechanical(self) -> bool:
        """``ctx.mech*``: admitted at the task's parent commit under a pinned drafter."""
        return self.kind == _arms.CTX_KIND_MECHANICAL

    @property
    def stated(self) -> bool:
        """``ctx.req*``: entries rendered from declared items (ADR-0052)."""
        return self.kind == _arms.CTX_KIND_STATED

    @property
    def items_digest(self) -> str:
        """A stated set's items digest (``crb.core.stated.items_digest``), ``""`` otherwise.
        Text and structure are outside it: a prose and a checklist set over the same items
        share it."""
        if not self.stated:
            return ""
        return _stated.items_digest({e.task_id: e.items for e in self.entries})

    @property
    def placebo(self) -> bool:
        return self.source.endswith(PLACEBO_SUFFIX)

    @property
    def task_ids(self) -> tuple[str, ...]:
        """The set's tasks in set order (sorted by task id): exactly the tasks a run replays."""
        return tuple(e.task_id for e in self.entries)

    def entry_for(self, task_id: str) -> CtxEntryRecord:
        for e in self.entries:
            if e.task_id == task_id:
                return e
        raise KeyError(task_id)

    def to_doc(self) -> dict[str, Any]:
        """The hashed body, exactly as :func:`canonical_digest` reads it (no name inside)."""
        out: dict[str, Any] = {
            "schema": self.schema,
            "source": self.source,
            "repo": self.repo,
            "method": self.method,
            "entries": [e.to_doc() for e in self.entries],
        }
        if self.matched_to:
            out["matched_to"] = self.matched_to
        if self.drafter:
            out["drafter"] = self.drafter
        if self.schema == SCHEMA_V2:
            out["structure"] = self.structure
            out["saw"] = list(self.saw)
        return out


def canonical_json(doc: Any) -> str:
    """The canonical JSON text a digest is taken over."""
    return json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def canonical_digest(doc: Any) -> str:
    """sha256 (hex) of the canonical JSON of ``doc`` — stable across key order."""
    return hashlib.sha256(canonical_json(doc).encode("utf-8")).hexdigest()


def name_of(source: str, digest: str) -> str:
    """``ctx.<source>.<digest[:12]>``; refuses a source or digest outside the grammar."""
    name = f"{_arms.CTX_PREFIX}{source}.{digest[:12]}"
    if not _DIGEST_RE.match(digest) or not _arms.CTX_NAME_RE.match(name):
        raise CtxSetRefused(REASON_SCHEMA, f"no context-set name for {source!r}/{digest!r}")
    return name


def _schema(detail: str) -> CtxSetRefused:
    return CtxSetRefused(REASON_SCHEMA, detail)


def _keys(
    obj: Mapping[str, Any], required: Iterable[str], optional: Iterable[str], where: str
) -> None:
    req = tuple(required)
    missing = [k for k in req if k not in obj]
    if missing:
        raise _schema(f"{where} lacks {missing}")
    extra = sorted(set(obj) - set(req) - set(optional))
    if extra:
        raise _schema(f"{where} carries unknown fields {extra}")


def _text(obj: Mapping[str, Any], key: str, where: str, *, empty: bool = False) -> str:
    v = obj.get(key)
    if not isinstance(v, str) or (not empty and not v.strip()):
        raise _schema(f"{where}.{key} is not a non-empty string")
    return v


def _utc(value: str, where: str) -> None:
    try:
        when = datetime.fromisoformat(value)
    except ValueError as e:
        raise _schema(f"{where}.produced_at {value!r} is not ISO-8601") from e
    if when.utcoffset() != timedelta(0):
        raise _schema(f"{where}.produced_at {value!r} is not UTC")


def parse(doc: object, *, name: str | None = None) -> CtxSet:
    """THE parser: a ``crb.ctxset.v1`` document (a mapping, or its JSON text) → :class:`CtxSet`.

    Refuses ``ctxset_schema`` (a missing, unknown or mistyped field, unsorted entries),
    ``ctxset_coverage`` (no entries, or two entries for one task), ``ctxset_mechanical`` (a
    ``mech*`` set without its drafter, or an entry not mechanical or without ``source_rev``;
    a hindsight entry stamped mechanical — a false stamp), ``ctxset_placebo_unmatched`` (a
    placebo naming no treatment digest) and, when ``name`` is given, ``ctxset_digest`` (the
    name disagrees with the recomputed digest)."""
    if isinstance(doc, (str, bytes)):
        try:
            doc = json.loads(doc)
        except ValueError as e:
            raise _schema(f"not JSON: {e}") from e
    if not isinstance(doc, Mapping):
        raise _schema("a context set is a JSON object")
    schema = doc.get("schema")
    if schema not in SCHEMAS:
        raise _schema(f"schema {schema!r} is not one of {SCHEMAS}")
    source = doc.get("source")
    if not isinstance(source, str) or source not in SOURCES:
        raise _schema(f"source {source!r} is not one of {SOURCES}")
    stated = _arms.ctx_kind(source) == _arms.CTX_KIND_STATED
    if stated != (schema == SCHEMA_V2):
        raise _schema(
            f"a {source!r} set is {SCHEMA_V2 if stated else SCHEMA!r}, not {schema!r} "
            "(stated-requirement sources only are v2, ADR-0052)"
        )
    out = _parse_v2(doc, source) if stated else _parse_v1(doc, source)
    if canonical_digest(out.to_doc()) != out.digest:  # pragma: no cover - parse round-trips
        raise _schema("the parsed set does not round-trip to its document")
    if name is not None and name != out.name:
        raise CtxSetRefused(REASON_DIGEST, f"name {name!r} is not the set's {out.name!r}")
    return out


def _matched_to(doc: Mapping[str, Any], source: str) -> str:
    placebo = source.endswith(PLACEBO_SUFFIX)
    if "matched_to" in doc:
        if not placebo:
            raise _schema(f"matched_to is a placebo's field; source is {source!r}")
        matched_to = doc["matched_to"]
        if not isinstance(matched_to, str) or not _DIGEST_RE.match(matched_to):
            raise _schema("matched_to is not a full sha256 digest")
        return matched_to
    if placebo:
        raise CtxSetRefused(REASON_PLACEBO_UNMATCHED, "a placebo names its treatment's digest")
    return ""


def _check_entry_order(entries: list[CtxEntryRecord]) -> None:
    ids = [e.task_id for e in entries]
    dupes = sorted({t for t in ids if ids.count(t) > 1})
    if dupes:
        raise CtxSetRefused(REASON_COVERAGE, f"tasks with several entries: {dupes}")
    if ids != sorted(ids):
        raise _schema("entries are not sorted by task_id")


def _parse_v1(doc: Mapping[str, Any], source: str) -> CtxSet:
    _keys(doc, _TOP_REQUIRED, _TOP_OPTIONAL, "set")
    repo = _text(doc, "repo", "set")
    if not _REPO_RE.match(repo):
        raise _schema(f"repo {repo!r} is not a repository id")
    method = _text(doc, "method", "set")
    hindsight = _arms.ctx_kind(source) == _arms.CTX_KIND_HINDSIGHT
    mech = _arms.ctx_kind(source) == _arms.CTX_KIND_MECHANICAL
    matched_to = _matched_to(doc, source)

    drafter = ""
    if "drafter" in doc:
        if hindsight:
            raise _schema(f"drafter is a mechanical set's field; source is {source!r}")
        drafter = doc["drafter"]
        if not isinstance(drafter, str) or not _DRAFTER_RE.match(drafter):
            raise _schema("drafter is not '<pinned model id>@<sha256 of the drafting prompt>'")
    elif mech:
        raise CtxSetRefused(REASON_MECHANICAL, "a mechanical set names its pinned drafter")

    raw = doc["entries"]
    if not isinstance(raw, list):
        raise _schema("entries is not a list")
    if not raw:
        raise CtxSetRefused(REASON_COVERAGE, "a context set covers at least one task")
    entries: list[CtxEntryRecord] = []
    for i, item in enumerate(raw):
        where = f"entries[{i}]"
        if not isinstance(item, Mapping):
            raise _schema(f"{where} is not an object")
        _keys(item, _ENTRY_REQUIRED, _ENTRY_OPTIONAL, where)
        task_id = _text(item, "task_id", where)
        if not _SHA_RE.match(task_id):
            raise _schema(f"{where}.task_id {task_id!r} is not a git sha")
        produced_at = _text(item, "produced_at", where)
        _utc(produced_at, where)
        mechanical = item["mechanical"]
        if not isinstance(mechanical, bool):
            raise _schema(f"{where}.mechanical is not a boolean")
        source_rev = ""
        if "source_rev" in item:
            if hindsight:
                raise _schema(f"{where}.source_rev is a mechanical set's field")
            source_rev = item["source_rev"]
            if not isinstance(source_rev, str) or (source_rev and not _SHA_RE.match(source_rev)):
                raise _schema(f"{where}.source_rev is not a git sha")
        if hindsight and mechanical:
            raise CtxSetRefused(
                REASON_MECHANICAL,
                f"{where}: a hindsight entry is never stamped mechanical (a false stamp)",
            )
        if mech and (not mechanical or not source_rev):
            raise CtxSetRefused(
                REASON_MECHANICAL,
                f"{where}: a mechanical set's entry is mechanical and records its source_rev",
            )
        entries.append(
            CtxEntryRecord(
                task_id=task_id,
                entry_id=_text(item, "entry_id", where),
                version=_text(item, "version", where),
                text=_text(item, "text", where),
                produced_at=produced_at,
                mechanical=mechanical,
                source_rev=source_rev,
            )
        )
    _check_entry_order(entries)
    return CtxSet(
        source=source,
        repo=repo,
        method=method,
        entries=tuple(entries),
        digest=canonical_digest(doc),
        matched_to=matched_to,
        drafter=drafter,
    )


def _sorted_unique(values: list[str], where: str) -> None:
    if values != sorted(set(values)):
        raise _schema(f"{where} is not sorted and unique")


def _parse_item(raw: object, where: str) -> _stated.StatedItem:
    if not isinstance(raw, Mapping):
        raise _schema(f"{where} is not an object")
    _keys(raw, _ITEM_REQUIRED, (), where)
    item_id = _text(raw, "item_id", where)
    if not _ITEM_ID_RE.match(item_id):
        raise _schema(f"{where}.item_id {item_id!r} is not a short id")
    kind = _text(raw, "kind", where)
    if kind not in _stated.KINDS:
        raise _schema(f"{where}.kind {kind!r} is not one of {_stated.KINDS}")
    provenance = _text(raw, "provenance", where)
    if provenance not in _stated.PROVENANCES:
        raise _schema(f"{where}.provenance {provenance!r} is not one of {_stated.PROVENANCES}")
    statement = _text(raw, "statement", where)
    if "\n" in statement or "\r" in statement:
        raise _schema(f"{where}.statement spans several lines")
    discloses = raw["discloses"]
    if not isinstance(discloses, list) or not all(
        isinstance(t, str) and t.strip() == t and t for t in discloses
    ):
        raise _schema(f"{where}.discloses is not a list of non-empty trimmed strings")
    _sorted_unique(discloses, f"{where}.discloses")
    missing = [t for t in discloses if t not in statement]
    if missing:
        raise CtxSetRefused(
            REASON_ITEMS_UNDELIVERED, f"{where}: discloses {missing}, its statement does not"
        )
    return _stated.StatedItem(
        item_id=item_id,
        kind=kind,
        statement=statement,
        provenance=provenance,
        discloses=tuple(discloses),
    )


def _parse_v2(doc: Mapping[str, Any], source: str) -> CtxSet:
    _keys(doc, _V2_TOP_REQUIRED, _V2_TOP_OPTIONAL, "set")
    repo = _text(doc, "repo", "set")
    if not _REPO_RE.match(repo):
        raise _schema(f"repo {repo!r} is not a repository id")
    method = _text(doc, "method", "set")
    structure = _text(doc, "structure", "set")
    if structure not in _stated.STRUCTURES:
        raise _schema(f"structure {structure!r} is not one of {_stated.STRUCTURES}")
    drafter = _text(doc, "drafter", "set")
    if not _REQ_DRAFTER_RE.match(drafter):
        raise _schema("drafter is not 'human:<id>' or 'model:<pinned id>@<sha256 of the prompt>'")
    saw = doc["saw"]
    if not isinstance(saw, list) or not saw or not all(s in _stated.SAW_VALUES for s in saw):
        raise _schema(f"saw is not a non-empty list of {_stated.SAW_VALUES}")
    _sorted_unique(saw, "set.saw")
    matched_to = _matched_to(doc, source)

    raw = doc["entries"]
    if not isinstance(raw, list):
        raise _schema("entries is not a list")
    if not raw:
        raise CtxSetRefused(REASON_COVERAGE, "a context set covers at least one task")
    entries: list[CtxEntryRecord] = []
    for i, entry in enumerate(raw):
        where = f"entries[{i}]"
        if not isinstance(entry, Mapping):
            raise _schema(f"{where} is not an object")
        _keys(entry, _V2_ENTRY_REQUIRED, (), where)
        task_id = _text(entry, "task_id", where)
        if not _SHA_RE.match(task_id):
            raise _schema(f"{where}.task_id {task_id!r} is not a git sha")
        produced_at = _text(entry, "produced_at", where)
        _utc(produced_at, where)
        raw_items = entry["items"]
        if not isinstance(raw_items, list) or not raw_items:
            raise _schema(f"{where}.items is not a non-empty list")
        items = [_parse_item(it, f"{where}.items[{j}]") for j, it in enumerate(raw_items)]
        _sorted_unique([it.item_id for it in items], f"{where}.items item_id")
        text = _stated.render(structure, items)
        over = _stated.length_violation(items, text)
        if over:
            raise CtxSetRefused(REASON_ITEMS_LENGTH, f"{where}: {over}")
        entries.append(
            CtxEntryRecord(
                task_id=task_id,
                entry_id=_text(entry, "entry_id", where),
                version=_text(entry, "version", where),
                text=text,
                produced_at=produced_at,
                mechanical=False,
                items=tuple(items),
            )
        )
    _check_entry_order(entries)
    return CtxSet(
        source=source,
        repo=repo,
        method=method,
        entries=tuple(entries),
        digest=canonical_digest(doc),
        matched_to=matched_to,
        drafter=drafter,
        schema=SCHEMA_V2,
        structure=structure,
        saw=tuple(saw),
    )


class TaskLike(Protocol):
    """What :func:`verify_coverage` reads of a task (``crb.core.spec.TaskSpec`` fits)."""

    @property
    def task_id(self) -> str: ...

    @property
    def repo(self) -> str: ...

    @property
    def gold_clean(self) -> bool | None: ...

    @property
    def labels(self) -> Mapping[str, str]: ...


def verify_coverage(ctxset: CtxSet, tasks: Iterable[TaskLike], *, repo: str | None = None) -> None:
    """The set's tasks are gold-clean tasks of its repository, one change each.

    ``tasks`` are the repository's registered tasks; ``repo`` the run's repository.
    Refuses ``ctxset_repo`` (the set is another repository's) and ``ctxset_coverage`` (a
    task id that is not a gold-clean task of the repository, or two set tasks sharing one
    ``change_id`` — so pairing by task id equals pairing by change)."""
    if repo is not None and ctxset.repo != repo:
        raise CtxSetRefused(REASON_REPO, f"the set is {ctxset.repo!r}'s, the run is {repo!r}'s")
    by_id = {t.task_id: t for t in tasks if t.repo == ctxset.repo}
    unknown = [tid for tid in ctxset.task_ids if tid not in by_id]
    if unknown:
        raise CtxSetRefused(REASON_COVERAGE, f"not tasks of {ctxset.repo!r}: {unknown}")
    unproven = [tid for tid in ctxset.task_ids if by_id[tid].gold_clean is not True]
    if unproven:
        raise CtxSetRefused(REASON_COVERAGE, f"not gold-clean: {unproven}")
    seen: dict[str, str] = {}
    for tid in ctxset.task_ids:
        change = by_id[tid].labels.get("change_id") or tid
        if change in seen:
            raise CtxSetRefused(
                REASON_COVERAGE, f"tasks {seen[change]} and {tid} share change {change}"
            )
        seen[change] = tid


def verify_source_revs(ctxset: CtxSet, parents: Mapping[str, str]) -> None:
    """A ``mech*`` set's entries were drafted at their task's parent commit: refuses
    ``ctxset_mechanical`` when an entry's ``source_rev`` is not ``parents[task_id]``. A
    hindsight set records no ``source_rev`` and passes."""
    if not ctxset.mechanical:
        return
    for e in ctxset.entries:
        parent = parents.get(e.task_id, "")
        if not parent or e.source_rev != parent:
            raise CtxSetRefused(
                REASON_MECHANICAL,
                f"{e.task_id}: source_rev {e.source_rev!r} is not the task's parent {parent!r}",
            )


def _strip_token(tok: str) -> str:
    return tok.strip(_EDGE_PUNCT)


def _looks_like_identifier(tok: str) -> bool:
    return len(tok) >= 3 and (any(c in tok for c in "_./") or any(c.isupper() for c in tok[1:]))


def identifier_tokens(text: str) -> frozenset[str]:
    """The identifier tokens of a text, the one extraction the gap rule and the placebo
    check share: every backticked span (stripped, a trailing ``()`` dropped) and every token
    of at least three characters that contains ``_``, ``.`` or ``/`` or an inner capital."""
    out: set[str] = set()
    for m in _BACKTICK_RE.finditer(text):
        span = m.group(1).strip()
        if span.endswith("()"):
            span = span[:-2]
        if span:
            out.add(span)
    for m in _TOKEN_RE.finditer(text):
        tok = _strip_token(m.group(0))
        if _looks_like_identifier(tok):
            out.add(tok)
    return frozenset(out)


def placebo_tolerance(treatment_chars: int) -> int:
    """How many characters a placebo entry may differ from its treatment entry by."""
    return max(PLACEBO_MIN_CHARS, int(PLACEBO_FRACTION * treatment_chars))


def verify_placebo(treatment: CtxSet, placebo: CtxSet) -> None:
    """A placebo is matched to its treatment (ADR-0050 item 7): it names the treatment's
    digest, is the treatment source's placebo, covers the identical tasks of the same
    repository, is within :func:`placebo_tolerance` characters per task
    (``ctxset_placebo_unmatched``), and shares no identifier token with the treatment entry
    beyond :data:`STOPWORDS` (``ctxset_placebo_overlap``)."""

    def unmatched(detail: str) -> CtxSetRefused:
        return CtxSetRefused(REASON_PLACEBO_UNMATCHED, detail)

    if not placebo.placebo or treatment.placebo:
        raise unmatched(f"{placebo.name} is not a placebo of the treatment {treatment.name}")
    if placebo.source != treatment.source + PLACEBO_SUFFIX:
        raise unmatched(f"{placebo.source!r} is not the placebo of {treatment.source!r}")
    if placebo.matched_to != treatment.digest:
        raise unmatched(f"{placebo.name} names {placebo.matched_to[:12]}, not {treatment.name}")
    if placebo.repo != treatment.repo:
        raise unmatched(f"the placebo is {placebo.repo!r}'s, the treatment {treatment.repo!r}'s")
    if set(placebo.task_ids) != set(treatment.task_ids):
        raise unmatched("the placebo and its treatment cover different tasks")
    if placebo.structure != treatment.structure:
        raise unmatched(
            f"the placebo is {placebo.structure!r}, its treatment {treatment.structure!r}"
        )
    for t in treatment.entries:
        p = placebo.entry_for(t.task_id)
        if abs(len(p.text) - len(t.text)) > placebo_tolerance(len(t.text)):
            raise unmatched(
                f"{t.task_id}: {len(p.text)} placebo characters against {len(t.text)} "
                f"(tolerance {placebo_tolerance(len(t.text))})"
            )
        shared = sorted(
            (
                {x.lower() for x in identifier_tokens(p.text)}
                & {x.lower() for x in identifier_tokens(t.text)}
            )
            - STOPWORDS
        )
        if shared:
            raise CtxSetRefused(REASON_PLACEBO_OVERLAP, f"{t.task_id}: shares identifiers {shared}")


def ctx_gap_anchor(ticket_text: str, tree_has: Callable[[str], bool]) -> str:
    """Rule ``anchor.v1`` (ADR-0050 item 6): ``"1"`` when the ticket names no identifier the
    parent tree holds, else ``"0"``. ``tree_has(token)`` answers whether the parent tree
    contains the token (the worker: ``git grep -q -F`` at the parent); it is the rule's ONLY
    reach outside the ticket, so the label never reads the gold diff, the held-out tests or
    any entry. Tokens are asked in sorted order and the first hit decides."""
    for tok in sorted(identifier_tokens(ticket_text)):
        if tree_has(tok):
            return GAP_NO
    return GAP_YES


def run_stamps(ctxset: CtxSet, role: str, gaps: Mapping[str, str]) -> dict[str, dict[str, str]]:
    """Each set task → the ctx labels every row of that task carries (ADR-0050 item 5), set
    before any step that can fail. ``entries``: ``ctx_set`` (the full digest), ``ctx_source``,
    ``ctx_gap``, ``ctx_gap_rule``, ``ctx_delivered`` = ``ctx_chars`` = ``"0"`` (the composer's
    own counts replace them when it runs), ``ctx_drafter`` on a ``mech*`` set and
    ``ctx_ceiling`` = ``"1"`` on a hindsight set, and on a stated set (ADR-0052 item 2)
    ``ctx_stated`` = ``"1"``, ``ctx_items``, ``ctx_structure``, ``ctx_author_saw``, the task's
    ``ctx_prov`` and ``ctx_req_drafter``. ``control``: ``ctx_set``, ``ctx_source`` =
    ``control``, ``ctx_gap`` and ``ctx_gap_rule``. ``gaps`` holds every task's
    :func:`ctx_gap_anchor` value."""
    if role not in ROLES:
        raise ValueError(f"role {role!r} is not one of {ROLES}")
    out: dict[str, dict[str, str]] = {}
    for tid in ctxset.task_ids:
        gap = gaps.get(tid)
        if gap not in (GAP_NO, GAP_YES):
            raise ValueError(f"task {tid}: ctx_gap {gap!r} is not '0' or '1'")
        stamps = {
            _arms.LABEL_CTX_SET: ctxset.digest,
            _arms.LABEL_CTX_GAP: gap,
            _arms.LABEL_CTX_GAP_RULE: GAP_RULE,
        }
        if role == ROLE_CONTROL:
            stamps[_arms.LABEL_CTX_SOURCE] = _arms.CTX_SOURCE_CONTROL
        else:
            stamps[_arms.LABEL_CTX_SOURCE] = ctxset.source
            stamps[_arms.LABEL_CTX_DELIVERED] = "0"
            stamps[_arms.LABEL_CTX_CHARS] = "0"
            if ctxset.mechanical:
                stamps[_arms.LABEL_CTX_DRAFTER] = ctxset.drafter
            if ctxset.hindsight:
                stamps[_arms.LABEL_CTX_CEILING] = "1"
            if ctxset.stated:
                entry = ctxset.entry_for(tid)
                stamps[_arms.LABEL_CTX_STATED] = "1"
                stamps[_arms.LABEL_CTX_ITEMS] = ctxset.items_digest
                stamps[_arms.LABEL_CTX_STRUCTURE] = ctxset.structure
                stamps[_arms.LABEL_CTX_AUTHOR_SAW] = ",".join(ctxset.saw)
                stamps[_arms.LABEL_CTX_PROV] = _stated.prov_label(entry.items)
                stamps[_arms.LABEL_CTX_REQ_DRAFTER] = ctxset.drafter
        out[tid] = stamps
    return out


__all__ = [
    "GAP_NO",
    "GAP_RULE",
    "GAP_YES",
    "PLACEBO_FRACTION",
    "PLACEBO_MIN_CHARS",
    "PLACEBO_SUFFIX",
    "REASONS",
    "REASON_COVERAGE",
    "REASON_DIGEST",
    "REASON_ITEMS_LENGTH",
    "REASON_ITEMS_UNDELIVERED",
    "REASON_MECHANICAL",
    "REASON_MODE",
    "REASON_PLACEBO_OVERLAP",
    "REASON_PLACEBO_UNMATCHED",
    "REASON_POSTURE",
    "REASON_REPO",
    "REASON_SCHEMA",
    "ROLES",
    "ROLE_CONTROL",
    "ROLE_ENTRIES",
    "SCHEMA",
    "SCHEMAS",
    "SCHEMA_V2",
    "SOURCES",
    "SOURCE_MECH",
    "SOURCE_MECH_PLACEBO",
    "SOURCE_ORACLE",
    "SOURCE_ORACLE_PLACEBO",
    "SOURCE_REQ",
    "SOURCE_REQ_PLACEBO",
    "STOPWORDS",
    "CtxEntryRecord",
    "CtxSet",
    "CtxSetRefused",
    "TaskLike",
    "canonical_digest",
    "canonical_json",
    "ctx_gap_anchor",
    "identifier_tokens",
    "name_of",
    "parse",
    "placebo_tolerance",
    "run_stamps",
    "verify_coverage",
    "verify_placebo",
    "verify_source_revs",
]
