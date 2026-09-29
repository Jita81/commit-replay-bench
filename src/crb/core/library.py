"""The context library — signed project knowledge in one nomenclature (ADR-0026 item 10).

A repository's library holds what people know about it that a test cannot say: its named
parts, its kinds of change, the decisions in force, its conventions, the designs that
recur and the organisation's quality rules. Every entry is one of six kinds and has the
id ``<kind>/<slug>``. An entry is **proposed with provenance** — a file at a commit, the
graded rows it was learned from, or the person who wrote it — and it is **signed by two
different people**: a *sponsor* who puts it forward and an *approver* who signs it. A
miner or a model may propose an entry (``mined:<version>``, ``drafted:<model>``) but is
never a person: the person who first adopts such a proposal becomes its sponsor.

The record of what happened is an append-only, hash-chained list of **acts**, on the
pattern of the cell sign-off (:mod:`crb.core.signoff`, ADR-0016): ``propose``,
``sponsor``, ``sign``, ``stale``, ``revoke`` and ``retire``. Nothing is edited. A new
version is a new ``propose``; a revocation or a retirement is appended; an entry proposed
from a file reads ``stale`` once that file has changed at the repository's head, and only
a new signature brings it back. The state of an entry is the fold of its acts
(:func:`fold`); every act is checked against that state before it is written
(:func:`apply` raises :class:`LibraryRefused`).

**An entry never reaches a builder's brief from here.** Showing, signing and the page per
work type use an entry as soon as it is signed. A brief uses it only inside a context arm
whose effect was measured (ADR-0026 items 1 and 10, ``+library@<version>``), which is
Wave 5's and off by default. No builder, factory, intake or brief-running core module imports
this module: the import-linter contract "library entries never reach a brief" in
``pyproject.toml`` refuses it. The worker composes a replay's brief and imports the library for
freshness alone — ``tests/test_library.py`` holds it to its freshness read, and
``tests/test_worker.py`` holds the brief a replay builds to none of a signed entry's words.

A ``standard`` entry names the ISO/IEC 25010:2023 characteristic it refines and the
repository's check that evidences it. Without a check the repository runs, it is
*advisory* and counts as no evidence (:func:`evidence_of`) — it counts only when the product's
quality table counts that check for that characteristic. Values that belong in a test, code
and secrets are not entries: a statement that carries a code fence is refused, and so is any
field of an entry or any act that carries a credential shape (:func:`carries_credential`).

Navigation
----------
What it is:   The library's record (``LibraryEntry``, ``Provenance``), its acts
              (``LibraryAct``), the state an entry is in (``EntryState``), the two-person
              rule, staleness, the page per work type as data, and the seams the page reads
              through (the cell's proven standard, the ISO/IEC 25010 table).
What it does: Validates an entry (kind, slug, statement of at most 400 characters, scope,
              provenance, proposer, the characteristic and check of a standard, the parent
              class of a work type); checks each act against the entry's state and refuses
              the ones the rule forbids (the approver is the sponsor or produced the graded
              rows cited, a miner or a model acting as a person, a signature on another
              version, a credential anywhere in the act); chains and verifies the
              acts; folds them into each entry's status; names the entries whose source file
              changed; and builds what ``/library/:repo`` shows for one work type.
How:          Frozen dataclasses; the version is sha256 of the canonical content; each act's
              ``row_hash`` is sha256 of its canonical body with ``prev_hash`` — the grade
              ledger's chain; standard library only (ADR-0008).
Layer:        core — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0026-the-context-standard.md (item 10),
              docs/adr/0016-two-person-rule-is-a-policy-clause-not-an-apparatus-move.md,
              docs/adr/0002-append-only-hash-chained-ledger.md
Works with:   src/crb/core/signoff.py (``is_person_actor`` — the one vocabulary of who is a
              person), src/crb/core/taxonomy.py (a work type's global parent),
              src/crb/store/library.py (the ``library_acts`` table: append under a lock, read),
              src/crb/server/routes/library.py (``/library`` over HTTP),
              ui/src/screens/Library/LibraryPage.tsx (the page per work type)
Tested by:    tests/test_library.py, tests/test_store_library.py,
              tests/test_server_routes_library.py
Touch when:   never for a new repository — a repository's entries are data in the store;
              adding a kind, an act or a status is a change to ADR-0026 item 10 first; a brief
              reads entries only through a measured arm (Wave 5), never from here.
Claims:       A signed entry is two named people's statement about a repository; its effect
              on a builder is ``unmeasured`` until an arm measures it
              (docs/EVIDENCE-AND-CLAIMS.md#7-what-must-never-be-said).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from crb.core.evidence import canonical_json, sha256_text
from crb.core.ledger import GENESIS_HASH, LedgerIntegrityError
from crb.core.redact import redact
from crb.core.signoff import is_person_actor
from crb.core.taxonomy import CLASS_DEFINITIONS, is_known_class

LIBRARY_SCHEMA = "crb.library.v1"

# --- kinds and ids -----------------------------------------------------------------------
KIND_COMPONENT = "component"
KIND_WORK_TYPE = "work-type"
KIND_DECISION = "decision"
KIND_CONVENTION = "convention"
KIND_PATTERN = "pattern"
KIND_STANDARD = "standard"
#: The six kinds, in the order the nomenclature index lists them (ADR-0026 item 10).
KINDS: tuple[str, ...] = (
    KIND_COMPONENT,
    KIND_WORK_TYPE,
    KIND_DECISION,
    KIND_CONVENTION,
    KIND_PATTERN,
    KIND_STANDARD,
)
#: A slug: lower case, digits, ``.``, ``_`` and ``-`` (a global class such as ``bug.fix``
#: is a valid work-type slug), at most 64 characters.
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
STATEMENT_MAX = 400
TITLE_MAX = 120
MAX_SCOPE = 32
MAX_EXAMPLES = 10
MAX_SLOTS = 16
_SHA_RE = re.compile(r"^[0-9a-f]{7,40}$")
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_SLOT_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_CHECK_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$")

# --- status and acts ---------------------------------------------------------------------
STATUS_PROPOSED = "proposed"
STATUS_SIGNED = "signed"
STATUS_STALE = "stale"
STATUS_RETIRED = "retired"
STATUS_REVOKED = "revoked"
STATUSES: tuple[str, ...] = (
    STATUS_PROPOSED,
    STATUS_SIGNED,
    STATUS_STALE,
    STATUS_RETIRED,
    STATUS_REVOKED,
)
#: A status no later act but a new ``propose`` leaves.
FINAL_STATUSES: frozenset[str] = frozenset({STATUS_RETIRED, STATUS_REVOKED})

ACT_PROPOSE = "propose"
ACT_SPONSOR = "sponsor"
ACT_SIGN = "sign"
ACT_STALE = "stale"
ACT_REVOKE = "revoke"
ACT_RETIRE = "retire"
ACTS: tuple[str, ...] = (ACT_PROPOSE, ACT_SPONSOR, ACT_SIGN, ACT_STALE, ACT_REVOKE, ACT_RETIRE)

# --- provenance and proposers ------------------------------------------------------------
PROVENANCE_FILE = "file"
PROVENANCE_ROWS = "rows"
PROVENANCE_PERSON = "person"
PROVENANCE_KINDS: tuple[str, ...] = (PROVENANCE_FILE, PROVENANCE_ROWS, PROVENANCE_PERSON)
#: A proposer that is a process, never a person: a miner at a version, a model that drafted.
PROPOSER_MINED = "mined:"
PROPOSER_DRAFTED = "drafted:"
#: The actor stamped on a retirement the measurement made (Wave 5's arm reader).
ACTOR_MEASUREMENT = "system:library-arm"
#: The actor stamped on a staleness the worker read from the repository's head after a mine.
ACTOR_FRESHNESS = "system:library-freshness"
RETIRED_BY_PERSON = "person"
RETIRED_BY_MEASUREMENT = "measurement"
#: An entry's effect on a builder until an arm measures it (ADR-0026 item 10).
UNMEASURED = "unmeasured"
EVIDENCE_CHECK = "check"
EVIDENCE_ADVISORY = "advisory"

#: The nine product quality characteristics of ISO/IEC 25010:2023, in the standard's order.
#: A ``standard`` entry refines one of them. The characteristic-to-check table itself is
#: ``crb.core.quality_model.QUALITY_MODEL`` (stream C); this vocabulary must equal its names
#: (``tests/test_library.py`` pins it when that module is present).
ISO_25010_CHARACTERISTICS: tuple[str, ...] = (
    "Functional suitability",
    "Performance efficiency",
    "Compatibility",
    "Interaction capability",
    "Reliability",
    "Security",
    "Maintainability",
    "Flexibility",
    "Safety",
)

# --- refusal codes -----------------------------------------------------------------------
REFUSAL_SAME_PERSON = "same_person"
REFUSAL_NOT_A_PERSON = "not_a_person"
REFUSAL_NO_SPONSOR = "no_sponsor"
REFUSAL_ALREADY_SPONSORED = "already_sponsored"
REFUSAL_VERSION_MISMATCH = "version_mismatch"
REFUSAL_NOT_SIGNABLE = "not_signable"
REFUSAL_UNKNOWN_ENTRY = "unknown_entry"
REFUSAL_UNCHANGED = "unchanged"
REFUSAL_FINAL = "already_final"
REFUSAL_NOT_FROM_A_FILE = "not_from_a_file"
REFUSAL_NOT_CHANGED = "file_unchanged"
REFUSAL_REASON_MISSING = "reason_missing"
REFUSAL_READING_MISSING = "reading_missing"
REFUSAL_READING_INVALID = "reading_invalid"
REFUSAL_CREDENTIAL = "credential"
REFUSAL_PRODUCERS_UNRESOLVED = "producers_unresolved"
REFUSAL_ROWS_UNKNOWN = "rows_unknown"
REFUSAL_SAME_ACTOR = "same_actor"


class LibraryRefused(ValueError):
    """An act the rule refuses; ``code`` is one of the ``REFUSAL_*`` codes (HTTP 409)."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


def is_person(actor: str) -> bool:
    """True when ``actor`` names a person: :func:`~crb.core.signoff.is_person_actor`'s rule,
    and never a miner (``mined:…``) or a model (``drafted:…``)."""
    a = actor.strip()
    return is_person_actor(a) and not a.startswith((PROPOSER_MINED, PROPOSER_DRAFTED))


def _is_process_proposer(proposer: str) -> bool:
    for prefix in (PROPOSER_MINED, PROPOSER_DRAFTED):
        if proposer.startswith(prefix) and proposer[len(prefix) :].strip():
            return True
    return False


def carries_credential(value: Any) -> bool:
    """True when any string in ``value`` — nested in mappings, lists and tuples — carries a
    credential shape :func:`~crb.core.redact.redact` would replace. The library's acts are
    append-only and hash-chained, so a credential written once could never be removed:
    every field of an entry and every body of an act is held to this, not only the
    statement (P-383)."""
    if isinstance(value, str):
        return redact(value) != value
    if isinstance(value, Mapping):
        return any(carries_credential(k) or carries_credential(v) for k, v in value.items())
    if isinstance(value, (list, tuple)):
        return any(carries_credential(v) for v in value)
    return False


def entry_id_of(kind: str, slug: str) -> str:
    """The id ``<kind>/<slug>`` — one nomenclature for every kind."""
    return f"{kind}/{slug}"


def split_entry_id(entry_id: str) -> tuple[str, str]:
    """``(kind, slug)`` of ``<kind>/<slug>``; ``ValueError`` for anything else."""
    kind, sep, slug = entry_id.partition("/")
    if not sep or kind not in KINDS or not SLUG_RE.match(slug):
        raise ValueError(f"an entry id is <kind>/<slug> with kind one of {KINDS}: {entry_id!r}")
    return kind, slug


def _tuple(
    values: Iterable[str], what: str, pattern: re.Pattern[str], limit: int
) -> tuple[str, ...]:
    out = tuple(str(v).strip() for v in values)
    if len(out) > limit:
        raise ValueError(f"{what}: at most {limit}, got {len(out)}")
    for v in out:
        if not pattern.match(v):
            raise ValueError(f"{what}: {v!r} is not a valid name")
    if len(set(out)) != len(out):
        raise ValueError(f"{what}: a name is listed twice")
    return out


# ---------------------------------------------------------------------------
# The record
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Provenance:
    """Where an entry came from: a file at a commit (``path``, ``commit`` and ``digest`` —
    sha256 of the file's bytes at that commit, which staleness compares), the graded rows
    it was learned from (their row hashes), or the person who wrote it."""

    kind: str
    path: str = ""
    commit: str = ""
    digest: str = ""
    rows: tuple[str, ...] = ()
    person: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "rows", tuple(self.rows))
        if self.kind not in PROVENANCE_KINDS:
            raise ValueError(f"provenance is one of {PROVENANCE_KINDS}, got {self.kind!r}")
        if self.kind == PROVENANCE_FILE:
            if not self.path.strip() or self.path.startswith("/") or ".." in self.path.split("/"):
                raise ValueError("a file provenance names a path inside the repository")
            if not _SHA_RE.match(self.commit):
                raise ValueError("a file provenance names the commit it was read at")
            if not _HASH_RE.match(self.digest):
                raise ValueError(
                    "a file provenance carries the sha256 of the file it was read from"
                )
        elif self.path or self.commit or self.digest:
            raise ValueError(f"a {self.kind} provenance names no file")
        if self.kind == PROVENANCE_ROWS:
            if not self.rows or not all(_HASH_RE.match(r) for r in self.rows):
                raise ValueError("a rows provenance names the graded rows (their row hashes)")
        elif self.rows:
            raise ValueError(f"a {self.kind} provenance names no graded rows")
        if self.kind == PROVENANCE_PERSON:
            if not is_person(self.person):
                raise ValueError("a person provenance names the person who wrote the entry")
        elif self.person:
            raise ValueError(f"a {self.kind} provenance names no person")

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "path": self.path,
            "commit": self.commit,
            "digest": self.digest,
            "rows": list(self.rows),
            "person": self.person,
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> Provenance:
        return cls(
            kind=str(d.get("kind", "")),
            path=str(d.get("path", "")),
            commit=str(d.get("commit", "")),
            digest=str(d.get("digest", "")),
            rows=tuple(str(r) for r in d.get("rows") or ()),
            person=str(d.get("person", "")),
        )

    def label(self) -> str:
        """The provenance as a person reads it."""
        if self.kind == PROVENANCE_FILE:
            # the proposer's path, commit and digest: the product reads the file only at the
            # repository's head, after each mine (G-735)
            return f"{self.path} at {self.commit[:12]}, as proposed"
        if self.kind == PROVENANCE_ROWS:
            return f"{len(self.rows)} graded row{'s' if len(self.rows) != 1 else ''}"
        return "written by a person"


@dataclass(frozen=True)
class LibraryEntry:
    """One version of one entry. Its ``version`` is sha256 of its content, so any change —
    a word of the statement, a scope, the provenance — is a new version that needs a new
    signature. ``characteristic`` and ``check`` belong to a ``standard`` (the characteristic
    is required) or a ``convention`` (both optional); ``parent_class``, ``examples`` and
    ``slots`` to a ``work-type`` (the parent is required)."""

    repo: str
    kind: str
    slug: str
    title: str
    statement: str
    provenance: Provenance
    proposed_by: str
    components: tuple[str, ...] = ()
    work_types: tuple[str, ...] = ()
    characteristic: str = ""
    check: str = ""
    parent_class: str = ""
    examples: tuple[str, ...] = ()
    slots: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.repo.strip():
            raise ValueError("an entry belongs to a repository")
        if self.kind not in KINDS:
            raise ValueError(f"kind is one of {KINDS}, got {self.kind!r}")
        if not SLUG_RE.match(self.slug):
            raise ValueError(
                "a slug is lower case letters, digits, '.', '_' or '-', at most 64 characters"
            )
        title = self.title.strip()
        if not title or len(title) > TITLE_MAX:
            raise ValueError(f"a title is 1 to {TITLE_MAX} characters")
        object.__setattr__(self, "title", title)
        statement = self.statement.strip()
        if not statement:
            raise ValueError("an entry states what it knows")
        if len(statement) > STATEMENT_MAX:
            raise ValueError(
                f"a statement is at most {STATEMENT_MAX} characters, got {len(statement)}"
            )
        if "```" in statement:
            raise ValueError("a statement carries no code: code belongs in the repository")
        if redact(statement) != statement or redact(title) != title:
            raise ValueError("a statement carries no credential: secrets are never entries")
        object.__setattr__(self, "statement", statement)
        proposer = self.proposed_by.strip()
        if not (is_person(proposer) or _is_process_proposer(proposer)):
            raise ValueError("an entry is proposed by a person, mined:<version> or drafted:<model>")
        object.__setattr__(self, "proposed_by", proposer)
        if self.provenance.kind == PROVENANCE_PERSON and not is_person(proposer):
            raise ValueError("an entry a person wrote is proposed by that person")
        object.__setattr__(
            self, "components", _tuple(self.components, "components", SLUG_RE, MAX_SCOPE)
        )
        object.__setattr__(
            self, "work_types", _tuple(self.work_types, "work types", SLUG_RE, MAX_SCOPE)
        )
        object.__setattr__(
            self, "examples", _tuple(self.examples, "examples", _SHA_RE, MAX_EXAMPLES)
        )
        object.__setattr__(self, "slots", _tuple(self.slots, "slots", _SLOT_RE, MAX_SLOTS))
        self._validate_kind_fields()
        for name, value in self.content().items():
            if carries_credential(value):
                raise ValueError(
                    f"an entry carries no credential ({name}): secrets are never entries"
                )

    def _validate_kind_fields(self) -> None:
        if self.kind in (KIND_STANDARD, KIND_CONVENTION):
            if self.characteristic and self.characteristic not in ISO_25010_CHARACTERISTICS:
                raise ValueError(
                    f"a characteristic is one of ISO/IEC 25010:2023's nine: "
                    f"{', '.join(ISO_25010_CHARACTERISTICS)}"
                )
            if self.kind == KIND_STANDARD and not self.characteristic:
                raise ValueError(
                    "a standard names the ISO/IEC 25010:2023 characteristic it refines"
                )
            if self.check and not _CHECK_RE.match(self.check):
                raise ValueError("a check is named as the repository runs it")
        elif self.characteristic or self.check:
            raise ValueError("only a standard or a convention names a characteristic or a check")
        if self.kind == KIND_WORK_TYPE:
            if not is_known_class(self.parent_class):
                raise ValueError("a work type names its global parent class")
            if is_known_class(self.slug) or self.slug in CLASS_DEFINITIONS:
                raise ValueError(
                    f"a work type is named apart from the global classes: {self.slug} is a "
                    "global class and already has its page"
                )
        elif self.parent_class or self.examples or self.slots:
            raise ValueError("only a work type names a parent class, example commits or slots")

    @property
    def entry_id(self) -> str:
        return entry_id_of(self.kind, self.slug)

    def content(self) -> dict[str, Any]:
        """The versioned content (everything a signature vouches for)."""
        return {
            "repo": self.repo,
            "kind": self.kind,
            "slug": self.slug,
            "title": self.title,
            "statement": self.statement,
            "provenance": self.provenance.to_dict(),
            "proposed_by": self.proposed_by,
            "components": list(self.components),
            "work_types": list(self.work_types),
            "characteristic": self.characteristic,
            "check": self.check,
            "parent_class": self.parent_class,
            "examples": list(self.examples),
            "slots": list(self.slots),
        }

    @property
    def version(self) -> str:
        return sha256_text(canonical_json(self.content()))

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> LibraryEntry:
        return cls(
            repo=str(d.get("repo", "")),
            kind=str(d.get("kind", "")),
            slug=str(d.get("slug", "")),
            title=str(d.get("title", "")),
            statement=str(d.get("statement", "")),
            provenance=Provenance.from_dict(d.get("provenance") or {}),
            proposed_by=str(d.get("proposed_by", "")),
            components=tuple(str(x) for x in d.get("components") or ()),
            work_types=tuple(str(x) for x in d.get("work_types") or ()),
            characteristic=str(d.get("characteristic", "")),
            check=str(d.get("check", "")),
            parent_class=str(d.get("parent_class", "")),
            examples=tuple(str(x) for x in d.get("examples") or ()),
            slots=tuple(str(x) for x in d.get("slots") or ()),
        )


#: ``(characteristic, check)`` pairs: the product's quality table counts the check as
#: evidence of part of the characteristic, and the repository switches the check on.
EvidencePairs = frozenset[tuple[str, str]]


def evidence_pairs(quality: Sequence[Mapping[str, Any]] | None) -> EvidencePairs:
    """The pairs :func:`quality_rows` counts and the repository runs; empty when the
    product's ISO/IEC 25010 table is not on the build — then no entry is evidenced."""
    return frozenset(
        (str(row["characteristic"]), str(c["check"]))
        for row in quality or ()
        for c in row.get("checks") or ()
        if c.get("on")
    )


def evidence_of(entry: LibraryEntry, counted: Iterable[tuple[str, str]]) -> str:
    """``check`` when a standard or convention names a characteristic and a check that the
    product's quality table counts as evidence of that characteristic and the repository
    runs (``counted``, from :func:`evidence_pairs`); else ``advisory`` — shown and signed,
    counted as no evidence (ADR-0026 item 10). A check that evidences another
    characteristic is no evidence of this one: ``target_green`` says nothing of Security."""
    if entry.kind not in (KIND_STANDARD, KIND_CONVENTION):
        return ""
    pair = (entry.characteristic, entry.check)
    return (
        EVIDENCE_CHECK
        if entry.characteristic and entry.check and pair in set(counted)
        else EVIDENCE_ADVISORY
    )


# ---------------------------------------------------------------------------
# Acts and the chain
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LibraryAct:
    """One append to the library's ledger. ``body`` holds what the act needs: the entry's
    content for a ``propose``; the reason for a ``revoke``; ``by``, the reason and the
    reading for a ``retire``; the head commit and the file's new digest for a ``stale``;
    nothing for a ``sponsor`` or a ``sign``."""

    act_id: str
    repo: str
    entry_id: str
    version: str
    act: str
    actor: str
    created: str
    body: Mapping[str, Any] = field(default_factory=dict)
    schema: str = LIBRARY_SCHEMA
    prev_hash: str = ""
    row_hash: str = ""

    def __post_init__(self) -> None:
        if self.act not in ACTS:
            raise ValueError(f"an act is one of {ACTS}, got {self.act!r}")
        split_entry_id(self.entry_id)
        object.__setattr__(self, "body", dict(self.body))

    def hashed(self) -> dict[str, Any]:
        """Every field but ``row_hash`` — the body the chain hashes."""
        return {
            "act_id": self.act_id,
            "schema": self.schema,
            "repo": self.repo,
            "entry_id": self.entry_id,
            "version": self.version,
            "act": self.act,
            "actor": self.actor,
            "created": self.created,
            "body": dict(self.body),
            "prev_hash": self.prev_hash,
        }

    def compute_hash(self) -> str:
        return sha256_text(canonical_json(self.hashed()))

    def chained(self, prev_hash: str) -> LibraryAct:
        linked = replace(self, prev_hash=prev_hash, row_hash="")
        return replace(linked, row_hash=linked.compute_hash())

    def verify_hash(self) -> bool:
        return bool(self.row_hash) and self.row_hash == self.compute_hash()

    def to_dict(self) -> dict[str, Any]:
        return {**self.hashed(), "row_hash": self.row_hash}

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> LibraryAct:
        return cls(
            act_id=str(d.get("act_id", "")),
            repo=str(d.get("repo", "")),
            entry_id=str(d.get("entry_id", "")),
            version=str(d.get("version", "")),
            act=str(d.get("act", "")),
            actor=str(d.get("actor", "")),
            created=str(d.get("created", "")),
            body=dict(d.get("body") or {}),
            schema=str(d.get("schema", LIBRARY_SCHEMA)),
            prev_hash=str(d.get("prev_hash", "")),
            row_hash=str(d.get("row_hash", "")),
        )


def verify_library_chain(acts: Iterable[LibraryAct]) -> int:
    """Prove ``acts`` (in append order) is an unbroken chain from genesis; returns the count
    and raises :class:`~crb.core.ledger.LedgerIntegrityError` at the first break."""
    prev = GENESIS_HASH
    n = 0
    for a in acts:
        n += 1
        if a.prev_hash != prev:
            raise LedgerIntegrityError(f"library act {n} ({a.act_id[:8]}) prev_hash mismatch")
        if not a.verify_hash():
            raise LedgerIntegrityError(f"library act {n} ({a.act_id[:8]}) row_hash mismatch")
        prev = a.row_hash
    return n


# ---------------------------------------------------------------------------
# State: the fold of an entry's acts, and the rule each act is checked against
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EntryState:
    """Where one entry stands: its current version, status, who sponsored and who signed
    it and when, and — when it applies — why it is stale, retired or revoked. ``effect`` is
    ``unmeasured`` until a measured arm serves one (Wave 5, G-675)."""

    entry: LibraryEntry
    status: str
    proposed_at: str = ""
    sponsor: str = ""
    sponsored_at: str = ""
    approver: str = ""
    signed_at: str = ""
    acknowledged_digest: str = ""
    stale: Mapping[str, str] | None = None
    retired: Mapping[str, str] | None = None
    revoked: Mapping[str, str] | None = None
    effect: str = UNMEASURED
    acts: int = 0

    @property
    def entry_id(self) -> str:
        return self.entry.entry_id

    @property
    def usable(self) -> bool:
        """Signed and fresh — the only state in which an entry may be shown as signed
        context. Even then it reaches no brief outside a measured arm (ADR-0026 item 10)."""
        return self.status == STATUS_SIGNED

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "version": self.entry.version,
            "entry": self.entry.content(),
            "status": self.status,
            "proposed_at": self.proposed_at,
            "sponsor": self.sponsor,
            "sponsored_at": self.sponsored_at,
            "approver": self.approver,
            "signed_at": self.signed_at,
            "stale": dict(self.stale) if self.stale else None,
            "retired": dict(self.retired) if self.retired else None,
            "revoked": dict(self.revoked) if self.revoked else None,
            "effect": self.effect,
            "acts": self.acts,
        }


def _signed_against(state: EntryState) -> frozenset[str]:
    """The file digests an entry read from a file vouches for: the one it was proposed
    against and, once re-signed while stale, the one the approver acknowledged. Never the
    empty digest — that is a file gone at head, which is always a change (P-382)."""
    return frozenset(d for d in (state.entry.provenance.digest, state.acknowledged_digest) if d)


def _need_person(actor: str, what: str) -> None:
    if not is_person(actor):
        raise LibraryRefused(
            f"{what} is a person's act: {actor!r} is a miner, a model, the system or nobody",
            code=REFUSAL_NOT_A_PERSON,
        )


def refuse_same_person(thing: str, *, sponsor: str, approver: str) -> None:
    """THE two-person rule (ADR-0026 item 10, DESIGN §9.3), for every library entry and every
    class-set version (``crb.core.class_sets``): the approver can never be the sponsor.
    Raises :class:`LibraryRefused` ``same_person``."""
    if approver == sponsor:
        raise LibraryRefused(
            f"the sponsor cannot sign their own {thing} — a second person must sign it "
            "(the two-person rule, ADR-0026 item 10; cannot be relaxed)",
            code=REFUSAL_SAME_PERSON,
        )


def _need_version(state: EntryState, act: LibraryAct) -> None:
    if act.version != state.entry.version:
        raise LibraryRefused(
            f"{state.entry_id} is at version {state.entry.version[:12]}; the act names "
            f"{act.version[:12] or 'none'} — read the entry again and act on what it now says",
            code=REFUSAL_VERSION_MISMATCH,
        )


def _need_independent_of_rows(state: EntryState, act: LibraryAct) -> None:
    """Ground 1 of the cell sign-off's two-person rule (``same_actor_refusal``, DESIGN
    §9.3), for an entry learned from graded rows: the caller resolves the cited rows in the
    grade ledger and names, in the sign act, the ones it did not find (``rows_missing``)
    and the actors of the rows and of the runs that produced them (``row_actors``). The
    signature is refused when the caller resolved nothing, when a cited row does not
    exist, or when the approver produced one of them."""
    actors = act.body.get("row_actors")
    missing = act.body.get("rows_missing")
    if not isinstance(actors, list) or not isinstance(missing, list):
        raise LibraryRefused(
            f"{state.entry_id} was learned from graded rows: a signature names who produced "
            "them, read from the grade ledger",
            code=REFUSAL_PRODUCERS_UNRESOLVED,
        )
    if missing:
        raise LibraryRefused(
            f"{state.entry_id} cites {len(missing)} graded row"
            f"{'s' if len(missing) != 1 else ''} this repository does not hold",
            code=REFUSAL_ROWS_UNKNOWN,
        )
    if act.actor in {str(a) for a in actors if is_person(str(a))}:
        raise LibraryRefused(
            f"{act.actor} produced graded rows {state.entry_id} was learned from: the person "
            "who produced the evidence cannot sign it — a second approver must sign "
            "(cannot be relaxed)",
            code=REFUSAL_SAME_ACTOR,
        )


def _apply_propose(state: EntryState | None, act: LibraryAct) -> EntryState:
    entry = LibraryEntry.from_dict(act.body.get("entry") or {})
    if entry.entry_id != act.entry_id or entry.repo != act.repo or entry.version != act.version:
        raise LedgerIntegrityError(f"library act {act.act_id[:8]}: the proposal is not its entry")
    if act.actor != entry.proposed_by:
        raise LibraryRefused(
            "a proposal is recorded under the proposer it names", code=REFUSAL_NOT_A_PERSON
        )
    if (
        state is not None
        and state.status not in FINAL_STATUSES
        and state.entry.version == entry.version
    ):
        raise LibraryRefused(
            f"{entry.entry_id} already stands at this version ({state.status}): nothing changed",
            code=REFUSAL_UNCHANGED,
        )
    sponsor = entry.proposed_by if is_person(entry.proposed_by) else ""
    return EntryState(
        entry=entry,
        status=STATUS_PROPOSED,
        proposed_at=act.created,
        sponsor=sponsor,
        sponsored_at=act.created if sponsor else "",
        acts=(state.acts if state else 0) + 1,
    )


def apply(state: EntryState | None, act: LibraryAct) -> EntryState:
    """The entry's state after ``act``, or :class:`LibraryRefused` when the rule forbids it.

    **The two-person rule** (ADR-0026 item 10, DESIGN §9.3): a signature needs a sponsor —
    the person who proposed the entry, or who adopted a miner's or a model's proposal — and
    an approver who is a different person. A miner or a model is never a person. A
    signature names the version it read; a later proposal of the entry is a new version
    and needs a new signature. ``stale`` applies only to an entry proposed from a file and
    only for a digest it has not already been signed against. A ``retire`` is a person's
    (with a reason) or the measurement's (``by: measurement``, with the reading's id); a
    ``revoke`` is a person's, with a reason. Revoked and retired entries take no act but a
    new proposal.
    """
    if carries_credential(act.hashed()):
        raise LibraryRefused(
            "an act carries no credential: the library is append-only, and a secret written "
            "to it could never be removed",
            code=REFUSAL_CREDENTIAL,
        )
    if act.act == ACT_PROPOSE:
        return _apply_propose(state, act)
    if state is None:
        raise LibraryRefused(
            f"no entry {act.entry_id} in {act.repo}'s library", code=REFUSAL_UNKNOWN_ENTRY
        )
    if state.status in FINAL_STATUSES:
        raise LibraryRefused(
            f"{state.entry_id} is {state.status}; only a new proposal brings it back",
            code=REFUSAL_FINAL,
        )
    n = state.acts + 1
    if act.act == ACT_SPONSOR:
        _need_person(act.actor, "sponsoring an entry")
        _need_version(state, act)
        if state.sponsor:
            raise LibraryRefused(
                f"{state.entry_id} already has a sponsor; the next person to act on it signs it",
                code=REFUSAL_ALREADY_SPONSORED,
            )
        return replace(state, sponsor=act.actor, sponsored_at=act.created, acts=n)
    if act.act == ACT_SIGN:
        _need_person(act.actor, "signing an entry")
        _need_version(state, act)
        if state.status not in (STATUS_PROPOSED, STATUS_STALE):
            raise LibraryRefused(
                f"{state.entry_id} is {state.status}: there is nothing to sign",
                code=REFUSAL_NOT_SIGNABLE,
            )
        if not state.sponsor:
            raise LibraryRefused(
                f"{state.entry_id} was proposed by {state.entry.proposed_by}, which is not a "
                "person: a person must sponsor it before another person signs it",
                code=REFUSAL_NO_SPONSOR,
            )
        refuse_same_person("entry", sponsor=state.sponsor, approver=act.actor)
        if state.entry.provenance.kind == PROVENANCE_ROWS:
            _need_independent_of_rows(state, act)
        # a re-signature of a stale entry acknowledges the file as it now reads at head
        ack = (state.stale or {}).get("digest", "") or state.acknowledged_digest
        return replace(
            state,
            status=STATUS_SIGNED,
            approver=act.actor,
            signed_at=act.created,
            acknowledged_digest=ack,
            stale=None,
            acts=n,
        )
    if act.act == ACT_STALE:
        prov = state.entry.provenance
        if prov.kind != PROVENANCE_FILE:
            raise LibraryRefused(
                f"{state.entry_id} was not read from a file", code=REFUSAL_NOT_FROM_A_FILE
            )
        digest = str(act.body.get("digest", ""))
        head = str(act.body.get("head_commit", ""))
        if (digest and not _HASH_RE.match(digest)) or (head and not _SHA_RE.match(head)):
            raise LibraryRefused(
                "a staleness names the head commit and the sha256 of the file there",
                code=REFUSAL_READING_INVALID,
            )
        if digest in _signed_against(state) or (
            state.status == STATUS_STALE and state.stale and state.stale.get("digest") == digest
        ):
            raise LibraryRefused(
                f"{prov.path} has not changed since {state.entry_id} was signed against it",
                code=REFUSAL_NOT_CHANGED,
            )
        return replace(
            state,
            status=STATUS_STALE,
            stale={
                "head_commit": str(act.body.get("head_commit", "")),
                "path": prov.path,
                "digest": digest,
                "at": act.created,
            },
            acts=n,
        )
    reason = str(act.body.get("reason", "")).strip()
    if act.act == ACT_REVOKE:
        _need_person(act.actor, "revoking an entry")
        if not reason:
            raise LibraryRefused("a revocation says why", code=REFUSAL_REASON_MISSING)
        return replace(
            state,
            status=STATUS_REVOKED,
            revoked={"actor": act.actor, "reason": reason, "at": act.created},
            acts=n,
        )
    # ACT_RETIRE
    by = str(act.body.get("by", RETIRED_BY_PERSON))
    reading = str(act.body.get("reading_id", "")).strip()
    if by == RETIRED_BY_MEASUREMENT:
        if act.actor != ACTOR_MEASUREMENT or not reading:
            raise LibraryRefused(
                "a retirement by measurement is the arm reader's, and names the reading",
                code=REFUSAL_READING_MISSING,
            )
    else:
        _need_person(act.actor, "retiring an entry")
        by = RETIRED_BY_PERSON
    if not reason:
        raise LibraryRefused("a retirement says why", code=REFUSAL_REASON_MISSING)
    return replace(
        state,
        status=STATUS_RETIRED,
        retired={
            "actor": act.actor,
            "by": by,
            "reason": reason,
            "reading_id": reading,
            "at": act.created,
        },
        acts=n,
    )


def fold(acts: Iterable[LibraryAct]) -> dict[str, EntryState]:
    """entry id → its state, over ``acts`` in append order (one repository's). Every act
    was checked when it was written; one that no longer applies means the store was
    changed outside this module, and is raised as a
    :class:`~crb.core.ledger.LedgerIntegrityError`, never skipped."""
    states: dict[str, EntryState] = {}
    for a in acts:
        try:
            states[a.entry_id] = apply(states.get(a.entry_id), a)
        except LibraryRefused as e:
            raise LedgerIntegrityError(
                f"library act {a.act_id[:8]} ({a.act} on {a.entry_id}) no longer applies: {e}"
            ) from e
    return states


def signed_context(states: Iterable[EntryState]) -> list[EntryState]:
    """The entries that are signed and fresh. An unsigned, stale, retired or revoked entry
    is never among them. This is what a page shows as signed context — it is NOT a brief:
    nothing here reaches a builder outside a measured arm (ADR-0026 item 10)."""
    return [s for s in states if s.usable]


def _judged(state: EntryState) -> bool:
    return state.entry.provenance.kind == PROVENANCE_FILE and state.status in (
        STATUS_PROPOSED,
        STATUS_SIGNED,
    )


def files_cited(states: Iterable[EntryState]) -> list[str]:
    """The paths a reader of the repository's head must hash: every file a proposed or
    signed entry was read from, sorted and each once."""
    return sorted({s.entry.provenance.path for s in states if _judged(s)})


def stale_candidates(
    states: Iterable[EntryState], digests_at_head: Mapping[str, str | None]
) -> list[tuple[EntryState, str]]:
    """``(state, digest at head)`` for each proposed or signed entry read from a file whose
    bytes at the repository's head differ from the ones it was proposed (or last re-signed)
    against. A file absent at head reads as the empty digest. A path the caller did not
    read is skipped — not reading a file is not evidence that it changed."""
    out: list[tuple[EntryState, str]] = []
    for s in states:
        prov = s.entry.provenance
        if not _judged(s):
            continue
        if prov.path not in digests_at_head:
            continue
        now = digests_at_head[prov.path] or ""
        if now not in _signed_against(s):
            out.append((s, now))
    return out


# ---------------------------------------------------------------------------
# The page per work type, as data
# ---------------------------------------------------------------------------

SIZES: tuple[str, ...] = ("XS", "S", "M", "L", "XL")
#: Distinct commits the look rule's first look needs (ADR-0026 item 3).
FIRST_LOOK = 20


@dataclass(frozen=True)
class ProvenStandard:
    """A cell's proven context standard as stream R's registered reading serves it: the
    arm, its distinct commits and clean ones, the 95 % Wilson interval, the apparatus, the
    look state and whether the arm is a ceiling (``S3`` alone)."""

    arm: str
    n: int
    clean: int
    ci_low: float
    ci_high: float
    apparatus: str
    state: str = "deliver"
    ceiling: bool = False
    reading_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "arm": self.arm,
            "n": self.n,
            "clean": self.clean,
            "ci_low": self.ci_low,
            "ci_high": self.ci_high,
            "apparatus": self.apparatus,
            "state": self.state,
            "ceiling": self.ceiling,
            "reading_id": self.reading_id,
        }


#: ``(repo, work type's global class, size) → ProvenStandard | None`` — the reader the page
#: is given.
StandardReader = Callable[[str, str, str], "ProvenStandard | None"]


def standard_for(repo: str, capability_class: str, size: str) -> ProvenStandard | None:
    """The pure core's reader of a cell's proven standard: it holds no store, so it answers
    ``None`` — no proven standard — for every cell. The server's page binds stream R's
    registered readings in its place (``crb.server.routes.library.store_standard_reader``,
    through the same store-bound readers as the factory's entry gate)."""
    del repo, capability_class, size
    return None


def next_measurement(tasks_in_cell: int) -> str:
    """What would prove the cell, in words: a registered reading and how far its pool is."""
    have = f"{tasks_in_cell} commit{'s' if tasks_in_cell != 1 else ''} of this kind and size mined"
    return (
        f"Register a reading of this cell (S3, then S1, under the look rule). A first look "
        f"needs {FIRST_LOOK} distinct commits; {have} so far."
    )


def quality_rows(
    model: Sequence[Any] | None, switched_on: Iterable[str]
) -> list[dict[str, Any]] | None:
    """Each ISO/IEC 25010:2023 characteristic with the repository's switched-on checks
    counted as evidence of part of it, read from stream C's table
    (``crb.core.quality_model.QUALITY_MODEL``: ``name``, ``counted`` with ``check``,
    ``label``, ``sub`` and ``runs``, and ``note``). ``None`` when the table is not on this
    build — the page then says so, and never supplies a table of its own."""
    if model is None:
        return None
    on = set(switched_on)
    rows: list[dict[str, Any]] = []
    for c in model:
        counted = [
            {
                "check": str(e.check),
                "label": str(e.label),
                "sub": str(e.sub),
                "runs": str(e.runs),
                "on": str(e.check) in on,
            }
            for e in getattr(c, "counted", ())
        ]
        rows.append(
            {
                "characteristic": str(c.name),
                "checks": counted,
                "evidenced": any(x["on"] for x in counted),
                "note": str(getattr(c, "note", "")),
            }
        )
    return rows


def _in_scope(state: EntryState, work_type: str, parent: str) -> bool:
    e = state.entry
    if e.kind == KIND_WORK_TYPE:
        return False
    return work_type in e.work_types or (bool(parent) and parent in e.work_types)


def _context_row(state: EntryState, counted: EvidencePairs) -> dict[str, Any]:
    e = state.entry
    return {
        "entry_id": state.entry_id,
        "kind": e.kind,
        "title": e.title,
        "statement": e.statement,
        "sponsor": state.sponsor,
        "approver": state.approver,
        "signed_at": state.signed_at,
        "provenance": e.provenance.to_dict(),
        "provenance_label": e.provenance.label(),
        "proposed_by": e.proposed_by,
        "effect": state.effect,
        "characteristic": e.characteristic,
        "check": e.check,
        "evidence": evidence_of(e, counted),
    }


def work_type_page(
    repo: str,
    slug: str,
    states: Mapping[str, EntryState],
    *,
    tasks: Sequence[Mapping[str, Any]],
    catalogue: Sequence[Mapping[str, str]],
    runnable_checks: Iterable[str],
    quality: list[dict[str, Any]] | None,
    reader: StandardReader = standard_for,
) -> dict[str, Any]:
    """What ``/library/:repo`` shows for one work type (``product.explanation.211``).

    ``slug`` is a global class (``bug.fix``) or a work-type entry's slug. ``tasks`` are the
    repository's mined tasks (``task_id``, ``capability_class``, ``size``, ``subject``);
    ``catalogue`` the slots readiness asks a ticket of this class for today (the readiness
    catalogue — version 1 of a work type's slots); ``quality`` the rows of
    :func:`quality_rows`. The signed context lists only signed, fresh entries scoped to
    the work type (or its parent class), each with its sponsor, signer, date, provenance
    and effect — ``unmeasured`` here, because no arm has measured one. Nothing on the page
    reaches a builder's brief."""
    wt_state = states.get(entry_id_of(KIND_WORK_TYPE, slug))
    signed_wt = wt_state if wt_state is not None and wt_state.usable else None
    if signed_wt is not None:
        parent = signed_wt.entry.parent_class
        title = signed_wt.entry.title
        definition = signed_wt.entry.statement
        source = signed_wt.entry_id
    elif is_known_class(slug) and slug in CLASS_DEFINITIONS:
        parent, title, definition, source = slug, slug, CLASS_DEFINITIONS[slug], "global"
    else:
        raise KeyError(slug)
    runnable = set(runnable_checks)
    mine = [t for t in tasks if str(t.get("capability_class", "")) == parent]
    examples = [
        {
            "sha": str(t.get("task_id", "")),
            "subject": str(t.get("subject", "")),
            "size": str(t.get("size", "")),
        }
        for t in mine[:5]
    ]
    if signed_wt is not None:
        known = {x["sha"] for x in examples}
        examples = [
            {"sha": sha, "subject": "", "size": ""}
            for sha in signed_wt.entry.examples
            if sha not in known
        ] + examples
    sizes = []
    for size in SIZES:
        n_tasks = sum(1 for t in mine if str(t.get("size", "")) == size)
        std = reader(repo, parent, size)
        sizes.append(
            {
                "size": size,
                "tasks": n_tasks,
                "standard": std.to_dict() if std is not None else None,
                "next": "" if std is not None else next_measurement(n_tasks),
            }
        )
    counted = evidence_pairs(quality)
    context = [
        _context_row(s, counted)
        for s in signed_context(states.values())
        if _in_scope(s, slug, parent)
    ]
    standards = [c for c in context if c["kind"] in (KIND_STANDARD, KIND_CONVENTION)]
    return {
        "repo": repo,
        "slug": slug,
        "title": title,
        "definition": definition,
        "definition_source": source,
        "parent_class": parent,
        "examples": examples,
        "ticket_slots": [dict(s) for s in catalogue],
        "signed_slots": list(signed_wt.entry.slots) if signed_wt is not None else [],
        "context": context,
        "sizes": sizes,
        "quality": {
            "served": quality is not None,
            "rows": quality or [],
            "switched_on": sorted(runnable),
            "standards": standards,
        },
    }


def work_types_of(
    states: Mapping[str, EntryState], tasks: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """The work types a repository has a page for: every global class its mined tasks carry,
    and every work-type entry — signed or not — with its status, parent and task count."""
    counts: dict[str, int] = {}
    for t in tasks:
        cls = str(t.get("capability_class", ""))
        if is_known_class(cls) and cls in CLASS_DEFINITIONS:
            counts[cls] = counts.get(cls, 0) + 1
    out: dict[str, dict[str, Any]] = {
        cls: {"slug": cls, "title": cls, "parent_class": cls, "status": "global", "tasks": n}
        for cls, n in counts.items()
    }
    for s in states.values():
        e = s.entry
        if e.kind != KIND_WORK_TYPE:
            continue
        out[e.slug] = {
            "slug": e.slug,
            "title": e.title,
            "parent_class": e.parent_class,
            "status": s.status,
            "tasks": counts.get(e.parent_class, 0),
        }
    return sorted(out.values(), key=lambda w: (-int(w["tasks"]), str(w["slug"])))


__all__ = [
    "ACTOR_FRESHNESS",
    "ACTOR_MEASUREMENT",
    "ACTS",
    "EVIDENCE_ADVISORY",
    "EVIDENCE_CHECK",
    "FINAL_STATUSES",
    "FIRST_LOOK",
    "ISO_25010_CHARACTERISTICS",
    "KINDS",
    "LIBRARY_SCHEMA",
    "PROVENANCE_KINDS",
    "SIZES",
    "STATEMENT_MAX",
    "STATUSES",
    "UNMEASURED",
    "EntryState",
    "EvidencePairs",
    "LibraryAct",
    "LibraryEntry",
    "LibraryRefused",
    "ProvenStandard",
    "Provenance",
    "StandardReader",
    "apply",
    "carries_credential",
    "entry_id_of",
    "evidence_of",
    "evidence_pairs",
    "files_cited",
    "fold",
    "is_person",
    "next_measurement",
    "quality_rows",
    "refuse_same_person",
    "signed_context",
    "split_entry_id",
    "stale_candidates",
    "standard_for",
    "verify_library_chain",
    "work_type_page",
    "work_types_of",
]
