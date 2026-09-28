"""Request and response shapes of ``/library`` — the context library over HTTP.

Navigation
----------
What it is:   The Pydantic models ``/library`` reads and serves: a proposal, the act bodies
              (sponsor, sign, revoke, retire, freshness), a miner run (``MineRequest``,
              ``MineOut``), the registry (``MinersOut``) and the entry, index and page shapes.
What it does: Bounds every field at the edge (a statement of at most 400 characters, a slug,
              a version hash, a reason) so the core's own validation is the second line, and
              names each field the UI reads (ui/src/api/types.ts mirrors them).
How:          ``BaseModel`` with ``extra="forbid"``; the entry's own rules stay in
              ``crb.core.library`` (a proposal the core refuses is a 422).
Layer:        server — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0026-the-context-standard.md (item 10)
Works with:   src/crb/server/routes/library.py (the routes), src/crb/core/library.py (the
              record), src/crb/core/miners.py (the run ``MineOut`` serves), ui/src/api/types.ts (``LibraryEntry``, ``LibraryIndex``,
              ``WorkTypePage``), docs/API.md#library (the field list these models carry)
Tested by:    tests/test_server_routes_library.py, tests/test_server_routes_library_mine.py
Touch when:   never for a new repository; a field of the record changes in
              src/crb/core/library.py first, then here, then the UI type and docs/API.md.
"""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field

from crb.core.library import STATEMENT_MAX, TITLE_MAX

_SHORT = 64


class ProvenanceIn(BaseModel):
    """Where the entry comes from: ``person`` (the proposer — the default), ``file`` (a path
    at a commit with the sha256 of its bytes there) or ``rows`` (graded row hashes)."""

    model_config = ConfigDict(extra="forbid")

    kind: str = Field(default="person", max_length=16)
    path: str = Field(default="", max_length=512)
    commit: str = Field(default="", max_length=40)
    digest: str = Field(default="", max_length=64)
    rows: list[str] = Field(default_factory=list, max_length=200)


class EntryProposeRequest(BaseModel):
    """``POST /library/{repo}/entries``: the caller proposes, and so sponsors, the entry."""

    model_config = ConfigDict(extra="forbid")

    kind: str = Field(max_length=16)
    slug: str = Field(min_length=1, max_length=_SHORT)
    title: str = Field(min_length=1, max_length=TITLE_MAX)
    statement: str = Field(min_length=1, max_length=STATEMENT_MAX)
    components: list[str] = Field(default_factory=list, max_length=32)
    work_types: list[str] = Field(default_factory=list, max_length=32)
    characteristic: str = Field(default="", max_length=_SHORT)
    check: str = Field(default="", max_length=_SHORT)
    parent_class: str = Field(default="", max_length=_SHORT)
    examples: list[str] = Field(default_factory=list, max_length=10)
    slots: list[str] = Field(default_factory=list, max_length=16)
    provenance: ProvenanceIn = Field(default_factory=ProvenanceIn)


class VersionRequest(BaseModel):
    """``sponsor`` / ``sign``: the version the person read — an act on any other is 409."""

    model_config = ConfigDict(extra="forbid")

    version: str = Field(min_length=64, max_length=64)


class ReasonRequest(BaseModel):
    """``revoke`` / ``retire``: why, in the person's own words (required)."""

    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=1000)


class FreshnessRequest(BaseModel):
    """``POST /library/{repo}/freshness``: the repository's head as the caller read it —
    the commit and, per path, the sha256 of the file's bytes there (``""`` when absent)."""

    model_config = ConfigDict(extra="forbid")

    head_commit: str = Field(min_length=7, max_length=40, pattern=r"^[0-9a-fA-F]{7,40}$")
    digests: dict[str, Annotated[str, Field(pattern=r"^([0-9a-fA-F]{64})?$")]] = Field(
        default_factory=dict, max_length=500
    )


class EntryOut(BaseModel):
    """One entry as it stands: the record, its status and the people behind it."""

    entry_id: str
    version: str
    entry: dict[str, Any]
    status: str
    proposed_at: str
    sponsor: str
    sponsor_name: str = ""
    sponsored_at: str
    approver: str
    approver_name: str = ""
    signed_at: str
    stale: dict[str, str] | None = None
    retired: dict[str, str] | None = None
    revoked: dict[str, str] | None = None
    effect: str
    evidence: str = ""
    acts: int


class WorkTypeOut(BaseModel):
    """A work type the repository has a page for."""

    slug: str
    title: str
    parent_class: str
    status: str
    tasks: int


class LibraryIndexOut(BaseModel):
    """``GET /library/{repo}``: the nomenclature index and the work types."""

    repo: str
    entries: list[EntryOut]
    work_types: list[WorkTypeOut]
    kinds: list[str]
    characteristics: list[str]
    statement_max: int
    reaches_briefs: bool = False


class WorkTypePageOut(BaseModel):
    """``GET /library/{repo}/work-types/{slug}``: the page per work type."""

    repo: str
    slug: str
    title: str
    definition: str
    definition_source: str
    parent_class: str
    examples: list[dict[str, str]]
    ticket_slots: list[dict[str, str]]
    signed_slots: list[str]
    context: list[dict[str, Any]]
    sizes: list[dict[str, Any]]
    quality: dict[str, Any]
    reaches_briefs: bool = False


class FreshnessOut(BaseModel):
    """The entries this reading of the head made stale."""

    repo: str
    head_commit: str
    stale: list[str]


class LibraryVerifyOut(BaseModel):
    """``GET /library/verify``: the whole chain walked from genesis."""

    ok: bool
    acts: int
    error: str = ""


class MineRequest(BaseModel):
    """``POST /library/{repo}/mine``: the commit to pin (a sha, a branch or a tag of the
    clone; empty = its ``HEAD``) and the miners to run (empty = every registered one)."""

    model_config = ConfigDict(extra="forbid")

    commit: str = Field(default="", max_length=100, pattern=r"^([A-Za-z0-9_.][A-Za-z0-9_./-]*)?$")
    miners: list[Annotated[str, Field(max_length=32)]] = Field(default_factory=list, max_length=32)


class MineOutcomeOut(BaseModel):
    """What the run did with one draft or note of one miner."""

    miner: str
    subject: str
    outcome: str
    reason: str = ""
    version: str = ""
    counts: dict[str, int] = Field(default_factory=dict)


class MineOut(BaseModel):
    """``POST /library/{repo}/mine``: the pinned commit, the miners applied
    (``name@version``), the count per outcome, the entries proposed (each ``proposed`` with
    no sponsor — a person adopts it, a different person signs it) and every outcome."""

    repo: str
    commit: str
    miners: list[str]
    counts: dict[str, int]
    proposed: list[EntryOut]
    outcomes: list[MineOutcomeOut]
    files_read: int
    reaches_briefs: bool = False


class MinerOut(BaseModel):
    """One registered miner."""

    name: str
    version: str
    proposer: str
    kinds: list[str]
    reads: str


class MinersOut(BaseModel):
    """``GET /library/{repo}/miners``: the registry a run applies, in its order."""

    repo: str
    miners: list[MinerOut]
