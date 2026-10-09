"""Request shapes of ``/classes`` — an organisation's class sets over HTTP.

Navigation
----------
What it is:   The Pydantic models ``/classes`` reads: a proposal (the classes and their
              rules), a proposal of version N+1 from the library's work-type entries, a
              signature (the digest read), a revocation (the reason) and a person's label.
What it does: Bounds every field at the edge (a slug, a definition of at most 400 characters, at
              most 64 classes, at most 32 terms per rule group, a digest) so the core's own
              validation is the second line; a rule has only ticket-time fields — there is no
              field for a path, a line count or churn.
How:          ``BaseModel`` with ``extra="forbid"``; the class set's own rules stay in
              ``crb.core.class_sets`` (a proposal the core refuses is a 422).
Layer:        server — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0026-the-context-standard.md (item 9)
Works with:   src/crb/server/routes/classes.py (the routes), src/crb/core/class_sets.py (the
              record), ui/src/api/types.ts (``ClassSetProposal``), docs/API.md#classes (the
              field list these models carry)
Tested by:    tests/test_server_routes_classes.py
Touch when:   never for a new repository; a field of the record changes in
              src/crb/core/class_sets.py first, then here, then the UI type and docs/API.md.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from crb.core.library import STATEMENT_MAX, TITLE_MAX

_SHORT = 64
_TERMS = 32


class RuleIn(BaseModel):
    """What puts a ticket in the class — ticket-time fields only (ADR-0026 item 9)."""

    model_config = ConfigDict(extra="forbid")

    words: list[str] = Field(default_factory=list, max_length=_TERMS)
    work_item_types: list[str] = Field(default_factory=list, max_length=_TERMS)
    components: list[str] = Field(default_factory=list, max_length=_TERMS)
    labels: list[str] = Field(default_factory=list, max_length=_TERMS)


class ClassIn(BaseModel):
    """One class: its slug, title, definition in the user's words, global parent and rule —
    or a signed library work-type entry (``entry_repo`` and ``entry_slug``) whose title,
    statement and parent it takes when those are left empty."""

    model_config = ConfigDict(extra="forbid")

    slug: str = Field(default="", max_length=_SHORT)
    title: str = Field(default="", max_length=TITLE_MAX)
    definition: str = Field(default="", max_length=STATEMENT_MAX)
    parent: str = Field(default="", max_length=_SHORT)
    rule: RuleIn
    entry_repo: str = Field(default="", max_length=_SHORT)
    entry_slug: str = Field(default="", max_length=_SHORT)


class ProposeIn(BaseModel):
    """``POST /classes/{org}/versions``: the caller proposes, and so sponsors, the
    organisation's next version over ``repos``."""

    model_config = ConfigDict(extra="forbid")

    repos: list[str] = Field(min_length=1, max_length=64)
    classes: list[ClassIn] = Field(min_length=1, max_length=64)


class FromLibraryIn(BaseModel):
    """``POST /classes/{org}/versions/from-library`` — the DL-044 seam: version N+1 is the
    latest version's classes plus every signed work-type entry of ``repos`` that is not yet a
    class; ``rules`` names each new class's rule by the entry's slug."""

    model_config = ConfigDict(extra="forbid")

    repos: list[str] = Field(min_length=1, max_length=64)
    rules: dict[str, RuleIn] = Field(default_factory=dict)


class DigestIn(BaseModel):
    """``sign``: the digest of the version the approver read — a signature on any other is 409."""

    model_config = ConfigDict(extra="forbid")

    digest: str = Field(min_length=64, max_length=64)


class ReasonIn(BaseModel):
    """``revoke``: why, in the person's own words (required)."""

    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=1000)


class LabelIn(BaseModel):
    """A person's label of one derivation commit: the class they read it as, or
    ``(unclassified)`` when it is none of them."""

    model_config = ConfigDict(extra="forbid")

    repo: str = Field(min_length=1, max_length=_SHORT)
    task_id: str = Field(min_length=7, max_length=_SHORT)
    capability_class: str = Field(min_length=1, max_length=_SHORT, alias="class")


__all__ = ["ClassIn", "DigestIn", "FromLibraryIn", "LabelIn", "ProposeIn", "ReasonIn", "RuleIn"]
