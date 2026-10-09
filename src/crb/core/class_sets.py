"""An organisation's own classes of work — class-set versions, held out by commit (ADR-0026 item 9).

The global vocabulary (:mod:`crb.core.taxonomy`, ``global/classes@v1``) is one set of classes
for every repository. An organisation's work is not shaped like everyone else's, so it may
propose its own set: ``<org>/classes@vN``. Each of its classes is a **child of one global
class** (its *parent*), so ``capability_class`` in the cell key stays the global parent and
the federated key never moves; the organisation's class splits a global cell into its own
cells, read on their own axis (``labels.taxonomy`` and the reading's ``org_class``).

Four rules keep such a set honest:

* **Held out by commit.** Before any class is proposed, each repository's replayable commits
  are split by ``sha256("crb.split.v1|" + repo + "|" + commit)`` into a **derivation set**
  (:data:`DERIVATION_SHARE`, one third — an ADR-0026 [operator] value) and a **confirmation
  set** (two thirds). Proposing and labelling read derivation commits only (a class's example
  commits, :func:`examples_of`, are derivation commits set aside from the labelled sample); a
  version licenses only on confirmation commits, through a reading registered after it was
  signed (:func:`refuse_reading_pool`). There is no merge, split or separation-test tool yet
  (G-764): a version is changed by proposing the next one.
* **One rule on both sides.** A version's rule reads only what a ticket carries —
  :class:`TicketFields`: its text, work-item type, component or area, labels and points, and
  the organisation's component names from the library. At intake it reads the ticket; at
  replay the commit's linked ticket as it stood at the parent's date, or else the commit
  message, marked as a proxy. Changed paths, line counts and churn are never an input: the
  dataclass has no field for them. A person's ``crb:class=`` override on a ticket is honoured
  and counted, and a high override rate fails the rule.
* **The validity report** (:func:`validity_report`) — coverage, agreement with a
  person-labelled sample (Cohen's κ, never reading the sponsor's labels: the rule is theirs),
  stability, ticket consistency, points-to-churn size agreement, measurability (only commits a
  reading of the class can pool: mined under its parent) and the override rate — runs before a
  version may route.
* **Two people.** A version is proposed by a sponsor and signed by a different approver,
  through the library's one two-person rule (:func:`crb.core.library.refuse_same_person`).
  A version routes nothing until its report passes and it is signed (:func:`routes`).

Navigation
----------
What it is:   The class-set record (``OrgClass``, ``ClassRule``, ``ClassSetVersion``), the
              ticket-time fields a rule reads (``TicketFields``), the per-commit split, the one
              classifier, the version's acts and their fold (``ClassSetAct``, ``VersionState``),
              the validity report and the routing and reading-pool guards.
What it does: Splits commits into derivation and confirmation sets by a seeded hash; picks each
              class's example commits (set aside from the labelled sample); classifies
              a ticket or a commit's message by the version's rule (override first, then the
              first matching class, else unclassified); checks each act against the version's
              state (a proposal is the org's next number; a signature needs a person who is not
              the sponsor and names the digest it read); computes the six measures and the
              override rate against ADR-0026's thresholds; says whether a version routes and
              refuses a reading pool that holds a derivation commit or reads a version that
              does not route.
How:          Frozen dataclasses; a version's digest is sha256 of its canonical content; each
              act's ``row_hash`` is sha256 of its canonical body with ``prev_hash`` (the grade
              ledger's chain); κ is Cohen's over the rule's and the person's labels; standard
              library only (ADR-0008).
Layer:        core — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0026-the-context-standard.md (item 9),
              docs/adr/0016-two-person-rule-is-a-policy-clause-not-an-apparatus-move.md
Works with:   src/crb/core/library.py (``is_person``, ``refuse_same_person`` — the one
              two-person rule; the work-type entries a version's classes cite),
              src/crb/core/taxonomy.py (the global parents; ``parse_class_set``),
              src/crb/core/reading.py (``ReadingRefused`` — the pool guard's refusal),
              src/crb/store/class_sets.py (the ``class_set_acts`` and ``class_labels`` tables),
              src/crb/server/routes/classes.py (``/classes`` over HTTP),
              ui/src/screens/Classes/ClassesPage.tsx (the class set, a page per class, the
              labelling screen)
Tested by:    tests/test_class_sets.py, tests/test_server_routes_classes.py
Touch when:   onboarding a client repository never needs it — an organisation's classes are
              data in the store (a class-set version), never a code edit; a threshold of the
              validity report changes (an ADR amending ADR-0026 item 9 first); a ticket-time
              field is added to the rule (ADR-0026 item 9 first — never a path, a line count or
              churn).
Claims:       A signed version whose report passes says two named people agree the classes
              describe the organisation's work and that the rule reproduces a person's labels;
              it proves no class can be built
              (docs/EVIDENCE-AND-CLAIMS.md#7-what-must-never-be-said).
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, fields, replace
from typing import Any

from crb.core.evidence import canonical_json, sha256_text
from crb.core.ledger import GENESIS_HASH, LedgerIntegrityError
from crb.core.library import (
    REFUSAL_CREDENTIAL,
    REFUSAL_NOT_A_PERSON,
    REFUSAL_REASON_MISSING,
    REFUSAL_UNKNOWN_ENTRY,
    REFUSAL_VERSION_MISMATCH,
    SLUG_RE,
    STATEMENT_MAX,
    TITLE_MAX,
    LibraryRefused,
    carries_credential,
    is_person,
    refuse_same_person,
)
from crb.core.reading import ReadingRefused
from crb.core.taxonomy import (
    CLASS_DEFINITIONS,
    GLOBAL_CLASS_SET,
    UNCLASSIFIED,
    is_known_class,
    parse_class_set,
)

CLASS_SET_SCHEMA = "crb.class_set.v1"

# --- the split (ADR-0026 item 9) ---------------------------------------------------------
#: The preimage prefix of the per-commit split.
SPLIT_SEED = "crb.split.v1"
#: The derivation set's share of each repository's replayable commits — an ADR-0026
#: [operator] value (`one third`), used as proposed until the operator fixes it.
DERIVATION_SHARE = 1 / 3
DERIVATION = "derivation"
CONFIRMATION = "confirmation"

# --- the validity report's thresholds (ADR-0026 item 9, [operator]) ----------------------
COVERAGE_MIN = 0.90
KAPPA_MIN = 0.6
SAMPLE_MIN = 50
PER_CLASS_MIN = 5
STABILITY_MIN = 0.90
TICKETS_MIN = 20
TICKET_CONSISTENCY_MIN = 0.80
SIZE_TICKETS_MIN = 20
SIZE_EQUAL_MIN = 0.80
SIZE_SMALLER_MAX = 0.10
MEASURABLE_MIN = 20
#: The most overrides a rule may need before it fails — ADR-0026 names the clause ("a high
#: override rate fails the rule") without a number; this is the product's proposal (DL-331),
#: pending the operator's value.
OVERRIDE_RATE_MAX = 0.20

# --- sources of the fields a rule reads ----------------------------------------------------
SOURCE_MESSAGE = "message"
SOURCE_TICKET_PREFIX = "ticket@"
TAG_CLASS = "crb:class="

# --- a classification's source -------------------------------------------------------------
BY_OVERRIDE = "override"
BY_RULE = "rule"
BY_NONE = "none"

# --- acts and statuses --------------------------------------------------------------------
ACT_PROPOSE = "propose"
ACT_SIGN = "sign"
ACT_REVOKE = "revoke"
ACTS: tuple[str, ...] = (ACT_PROPOSE, ACT_SIGN, ACT_REVOKE)
STATUS_PROPOSED = "proposed"
STATUS_SIGNED = "signed"
STATUS_REVOKED = "revoked"

# --- refusal codes (reused from the library where the rule is the same) -------------------
REFUSAL_OUT_OF_ORDER = "version_out_of_order"
REFUSAL_NOT_SIGNABLE = "not_signable"
REFUSAL_DERIVATION_COMMIT = "derivation_commit"
REFUSAL_NOT_ROUTING = "class_set_not_routing"
REFUSAL_CONFIRMATION_LABEL = "confirmation_commit"
REFUSAL_EXAMPLE_LABEL = "example_commit"
REFUSAL_SPONSOR_LABEL = "sponsor_label"
REFUSAL_REPO_TAKEN = "repository_has_a_class_set"

# --- why a version does not route ---------------------------------------------------------
ROUTE_OK = "routes"
ROUTE_UNKNOWN = "class_set_unknown"
ROUTE_UNSIGNED = "class_set_unsigned"
ROUTE_REVOKED = "class_set_revoked"
ROUTE_REPORT_FAILED = "class_set_report_failed"

#: Example commits a class's page shows at most — drawn from the derivation commits set aside
#: from the labelled sample, so no person labels a commit they were shown as the rule's example
#: (P-686).
EXAMPLES_PER_CLASS = 5
#: The share of derivation commits set aside as examples, and the seed of that draw: a property
#: of each commit alone (like the split), so mining more history never turns an example into a
#: commit to label, nor the reverse.
EXAMPLE_SHARE = 1 / 8
EXAMPLE_SEED = "crb.example.v1"

#: The report's measures that never stop a version routing: size agreement decides only
#: whether story points size a ticket (ADR-0026 item 8; DL-331).
NOT_ROUTING_CONDITIONS: frozenset[str] = frozenset({"size_agreement"})

MAX_CLASSES = 64
MAX_TERMS = 32
_ORG_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,47}$")
_TERM_RE = re.compile(r"^[^\s].{0,63}$")


class ClassSetRefused(LibraryRefused):
    """An act on a class set the rule refuses; ``code`` is a ``REFUSAL_*`` code (HTTP 409).
    A subclass of the library's refusal, because the two-person rule is the library's."""


# ---------------------------------------------------------------------------
# The split
# ---------------------------------------------------------------------------


def split_of(
    repo: str, commit: str, *, share: float = DERIVATION_SHARE, seed: str = SPLIT_SEED
) -> str:
    """``derivation`` or ``confirmation`` for one commit — a seeded hash, blind to every
    outcome, fixed before any class is proposed. The first 16 hex digits of
    ``sha256(seed + "|" + repo + "|" + commit)`` read as a fraction of 16^16 fall below
    ``share`` for a derivation commit."""
    if not 0.0 < share < 1.0:
        raise ValueError(f"a derivation share lies strictly between 0 and 1, got {share}")
    digest = hashlib.sha256(f"{seed}|{repo}|{commit}".encode()).hexdigest()
    return DERIVATION if int(digest[:16], 16) / 16**16 < share else CONFIRMATION


# ---------------------------------------------------------------------------
# What a rule may read
# ---------------------------------------------------------------------------


def _terms(values: Iterable[str], what: str) -> tuple[str, ...]:
    out = tuple(dict.fromkeys(str(v).strip().casefold() for v in values if str(v).strip()))
    if len(out) > MAX_TERMS:
        raise ValueError(f"{what}: at most {MAX_TERMS}, got {len(out)}")
    for v in out:
        if not _TERM_RE.match(v):
            raise ValueError(f"{what}: {v!r} is not a term a ticket carries")
    return out


@dataclass(frozen=True)
class TicketFields:
    """The ticket-time fields a class rule may read, and nothing else (ADR-0026 item 9):
    the ticket's text, its work-item type, its component or area, its labels and its points,
    and where they came from — ``ticket@<date>`` (the linked ticket as it stood at that date)
    or ``message`` (the commit message standing in for a ticket: a proxy). There is no field
    for a changed path, a line count or churn: they are diagnostics, never an input."""

    text: str
    work_item_type: str = ""
    component: str = ""
    labels: tuple[str, ...] = ()
    points: float | None = None
    source: str = SOURCE_MESSAGE

    def __post_init__(self) -> None:
        object.__setattr__(self, "labels", tuple(str(x).strip() for x in self.labels if x))
        src = self.source.strip()
        if src != SOURCE_MESSAGE and not (
            src.startswith(SOURCE_TICKET_PREFIX) and len(src) > len(SOURCE_TICKET_PREFIX)
        ):
            raise ValueError("fields come from the message, or a ticket at a date (ticket@<date>)")
        object.__setattr__(self, "source", src)

    @property
    def proxy(self) -> bool:
        """``True`` when the commit message stood in for a ticket."""
        return self.source == SOURCE_MESSAGE

    @property
    def override(self) -> str:
        """The class a person named with a ``crb:class=`` label, or ``""``."""
        for label in self.labels:
            if label.casefold().startswith(TAG_CLASS):
                return label[len(TAG_CLASS) :].strip().casefold()
        return ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "work_item_type": self.work_item_type,
            "component": self.component,
            "labels": list(self.labels),
            "points": self.points,
            "source": self.source,
        }


#: The names of every field a rule may read — pinned by a test so a path, a line count or a
#: churn figure can never be added to the rule's input without the test and an ADR.
TICKET_TIME_FIELDS: tuple[str, ...] = tuple(f.name for f in fields(TicketFields))


def from_message(message: str) -> TicketFields:
    """A replayed commit with no linked ticket: its message, marked as a proxy."""
    return TicketFields(text=message or "", source=SOURCE_MESSAGE)


def _word_in(term: str, text: str) -> bool:
    return re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", text) is not None


@dataclass(frozen=True)
class ClassRule:
    """What puts a ticket in a class, over ticket-time fields only. Each non-empty group must
    match (AND); within a group any term does (OR). ``words`` are whole words or phrases of the
    text; ``components`` are the organisation's component names, matched against the ticket's
    component or area, or named as a word in its text; ``work_item_types`` and ``labels``
    match the ticket's own."""

    words: tuple[str, ...] = ()
    work_item_types: tuple[str, ...] = ()
    components: tuple[str, ...] = ()
    labels: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("words", "work_item_types", "components", "labels"):
            object.__setattr__(self, name, _terms(getattr(self, name), name))
        if not (self.words or self.work_item_types or self.components or self.labels):
            raise ValueError("a rule names at least one word, work-item type, component or label")
        if any(t.startswith(TAG_CLASS) for t in self.labels):
            raise ValueError("a rule never matches the crb:class= override: that is a person's")

    def matches(self, f: TicketFields) -> bool:
        text = f.text.casefold()
        if self.words and not any(_word_in(w, text) for w in self.words):
            return False
        if self.work_item_types and f.work_item_type.strip().casefold() not in self.work_item_types:
            return False
        if self.components:
            comp = f.component.strip().casefold()
            if not any(c == comp or _word_in(c, text) for c in self.components):
                return False
        if self.labels:
            have = {x.casefold() for x in f.labels}
            if not any(x in have for x in self.labels):
                return False
        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "words": list(self.words),
            "work_item_types": list(self.work_item_types),
            "components": list(self.components),
            "labels": list(self.labels),
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> ClassRule:
        return cls(
            words=tuple(d.get("words") or ()),
            work_item_types=tuple(d.get("work_item_types") or ()),
            components=tuple(d.get("components") or ()),
            labels=tuple(d.get("labels") or ()),
        )


# ---------------------------------------------------------------------------
# The record
# ---------------------------------------------------------------------------


def global_parents() -> tuple[str, ...]:
    """The global classes an organisation's class may be a child of, in the vocabulary's
    order (every global class but ``(unclassified)``)."""
    return tuple(k for k in CLASS_DEFINITIONS if k != UNCLASSIFIED)


@dataclass(frozen=True)
class OrgClass:
    """One class of an organisation's set: a slug apart from the global classes, a title, a
    definition in the user's words (at most 400 characters), its global parent, its rule, and
    — when a using team proposed it as a library work-type entry — that entry's id and
    repository (the DL-044 seam)."""

    slug: str
    title: str
    definition: str
    parent: str
    rule: ClassRule
    entry_id: str = ""
    entry_repo: str = ""

    def __post_init__(self) -> None:
        if not SLUG_RE.match(self.slug):
            raise ValueError(
                "a class slug is lower case letters, digits, '.', '_' or '-', at most 64 characters"
            )
        if is_known_class(self.slug) or self.slug in CLASS_DEFINITIONS:
            raise ValueError(
                f"{self.slug} is a global class: an organisation's class is named apart from them"
            )
        if self.parent == UNCLASSIFIED or self.parent not in CLASS_DEFINITIONS:
            raise ValueError(
                f"{self.slug}: its parent {self.parent!r} is not a global class; it is one of "
                + ", ".join(global_parents())
            )
        title = self.title.strip()
        if not title or len(title) > TITLE_MAX:
            raise ValueError(f"a class title is 1 to {TITLE_MAX} characters")
        object.__setattr__(self, "title", title)
        definition = self.definition.strip()
        if not definition or len(definition) > STATEMENT_MAX:
            raise ValueError(f"a class's definition is 1 to {STATEMENT_MAX} characters")
        object.__setattr__(self, "definition", definition)
        if bool(self.entry_id) != bool(self.entry_repo):
            raise ValueError("a class cites a work-type entry and its repository together")
        if self.entry_id and not self.entry_id.startswith("work-type/"):
            raise ValueError("a class cites a work-type entry of the library")

    def to_dict(self) -> dict[str, Any]:
        return {
            "slug": self.slug,
            "title": self.title,
            "definition": self.definition,
            "parent": self.parent,
            "rule": self.rule.to_dict(),
            "entry_id": self.entry_id,
            "entry_repo": self.entry_repo,
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> OrgClass:
        return cls(
            slug=str(d.get("slug", "")),
            title=str(d.get("title", "")),
            definition=str(d.get("definition", "")),
            parent=str(d.get("parent", "")),
            rule=ClassRule.from_dict(d.get("rule") or {}),
            entry_id=str(d.get("entry_id", "") or ""),
            entry_repo=str(d.get("entry_repo", "") or ""),
        )


@dataclass(frozen=True)
class ClassSetVersion:
    """One version of an organisation's class set: ``<org>/classes@v<n>``. ``classes`` are in
    priority order (the first whose rule matches wins); ``repos`` are the repositories it
    covers; the split's share and seed are recorded on it; ``based_on`` names the version it
    grew from. Its ``digest`` is sha256 of its content, so any change is a new version."""

    org: str
    n: int
    classes: tuple[OrgClass, ...]
    repos: tuple[str, ...]
    proposed_by: str
    derivation_share: float = DERIVATION_SHARE
    split_seed: str = SPLIT_SEED
    based_on: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "classes", tuple(self.classes))
        object.__setattr__(self, "repos", tuple(dict.fromkeys(r.strip() for r in self.repos)))
        if not _ORG_RE.match(self.org) or self.org == "global":
            raise ValueError(
                "an organisation is named in lower case letters, digits, '.', '_' or '-' "
                "(and never 'global', the global vocabulary's owner)"
            )
        if self.n < 1:
            raise ValueError("a version number starts at 1")
        parse_class_set(self.version_id)
        if not self.classes or len(self.classes) > MAX_CLASSES:
            raise ValueError(f"a class set holds 1 to {MAX_CLASSES} classes")
        slugs = [c.slug for c in self.classes]
        if len(set(slugs)) != len(slugs):
            raise ValueError("a class is named twice")
        if not self.repos or not all(self.repos):
            raise ValueError("a class set names the repositories whose commits it describes")
        if not 0.0 < self.derivation_share < 1.0:
            raise ValueError("the derivation share lies strictly between 0 and 1")
        if not is_person(self.proposed_by):
            raise ValueError("a class set is proposed by a person, its sponsor")
        if self.based_on:
            parse_class_set(self.based_on)
        if carries_credential(self.content()):
            raise ValueError("a class set carries no credential")

    @property
    def version_id(self) -> str:
        return f"{self.org}/classes@v{self.n}"

    def content(self) -> dict[str, Any]:
        return {
            "schema": CLASS_SET_SCHEMA,
            "org": self.org,
            "n": self.n,
            "classes": [c.to_dict() for c in self.classes],
            "repos": list(self.repos),
            "proposed_by": self.proposed_by,
            "derivation_share": self.derivation_share,
            "split_seed": self.split_seed,
            "based_on": self.based_on,
        }

    @property
    def digest(self) -> str:
        return sha256_text(canonical_json(self.content()))

    def class_of(self, slug: str) -> OrgClass | None:
        return next((c for c in self.classes if c.slug == slug), None)

    def split(self, repo: str, commit: str) -> str:
        return split_of(repo, commit, share=self.derivation_share, seed=self.split_seed)

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> ClassSetVersion:
        return cls(
            org=str(d.get("org", "")),
            n=int(d.get("n", 0) or 0),
            classes=tuple(OrgClass.from_dict(c) for c in d.get("classes") or ()),
            repos=tuple(str(r) for r in d.get("repos") or ()),
            proposed_by=str(d.get("proposed_by", "")),
            derivation_share=float(d.get("derivation_share", DERIVATION_SHARE)),
            split_seed=str(d.get("split_seed", SPLIT_SEED) or SPLIT_SEED),
            based_on=str(d.get("based_on", "") or ""),
        )


# ---------------------------------------------------------------------------
# The one classifier
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Decision:
    """A ticket's class under one version: the class (or ``(unclassified)``), its global
    parent, how it was decided (``override``, ``rule`` or ``none``) and whether the fields were
    the message standing in for a ticket."""

    slug: str
    parent: str
    by: str
    proxy: bool

    @property
    def classified(self) -> bool:
        return self.slug != UNCLASSIFIED

    def to_dict(self) -> dict[str, Any]:
        return {"class": self.slug, "parent": self.parent, "by": self.by, "proxy": self.proxy}


def classify(version: ClassSetVersion, f: TicketFields) -> Decision:
    """THE rule of a version, the same at intake and at replay: a person's ``crb:class=``
    override naming one of the version's classes wins; else the first class whose rule
    matches; else ``(unclassified)``."""
    named = f.override
    if named:
        hit = version.class_of(named)
        if hit is not None:
            return Decision(hit.slug, hit.parent, BY_OVERRIDE, f.proxy)
    for c in version.classes:
        if c.rule.matches(f):
            return Decision(c.slug, c.parent, BY_RULE, f.proxy)
    return Decision(UNCLASSIFIED, "", BY_NONE, f.proxy)


# ---------------------------------------------------------------------------
# Acts and the chain
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ClassSetAct:
    """One append to the class sets' ledger: the version's content for a ``propose``; the
    digest the approver read for a ``sign``; the reason for a ``revoke``."""

    act_id: str
    org: str
    version_id: str
    digest: str
    act: str
    actor: str
    created: str
    body: Mapping[str, Any] = field(default_factory=dict)
    schema: str = CLASS_SET_SCHEMA
    prev_hash: str = ""
    row_hash: str = ""

    def __post_init__(self) -> None:
        if self.act not in ACTS:
            raise ValueError(f"an act is one of {ACTS}, got {self.act!r}")
        owner, _n = parse_class_set(self.version_id)
        if owner != self.org:
            raise ValueError(f"{self.version_id} is not {self.org}'s")
        object.__setattr__(self, "body", dict(self.body))

    def hashed(self) -> dict[str, Any]:
        return {
            "act_id": self.act_id,
            "schema": self.schema,
            "org": self.org,
            "version_id": self.version_id,
            "digest": self.digest,
            "act": self.act,
            "actor": self.actor,
            "created": self.created,
            "body": dict(self.body),
            "prev_hash": self.prev_hash,
        }

    def compute_hash(self) -> str:
        return sha256_text(canonical_json(self.hashed()))

    def chained(self, prev_hash: str) -> ClassSetAct:
        linked = replace(self, prev_hash=prev_hash, row_hash="")
        return replace(linked, row_hash=linked.compute_hash())

    def verify_hash(self) -> bool:
        return bool(self.row_hash) and self.row_hash == self.compute_hash()

    def to_dict(self) -> dict[str, Any]:
        return {**self.hashed(), "row_hash": self.row_hash}


def verify_chain(acts: Iterable[ClassSetAct]) -> int:
    """Prove ``acts`` (append order) is an unbroken chain from genesis; the count, or
    :class:`~crb.core.ledger.LedgerIntegrityError` at the first break."""
    prev = GENESIS_HASH
    n = 0
    for a in acts:
        n += 1
        if a.prev_hash != prev:
            raise LedgerIntegrityError(f"class-set act {n} ({a.act_id[:8]}) prev_hash mismatch")
        if not a.verify_hash():
            raise LedgerIntegrityError(f"class-set act {n} ({a.act_id[:8]}) row_hash mismatch")
        prev = a.row_hash
    return n


@dataclass(frozen=True)
class VersionState:
    """Where one version stands: proposed, signed or revoked; its sponsor (the person who
    proposed it) and approver, and when each acted."""

    version: ClassSetVersion
    status: str
    sponsor: str
    proposed_at: str
    approver: str = ""
    signed_at: str = ""
    revoked: Mapping[str, str] | None = None

    @property
    def version_id(self) -> str:
        return self.version.version_id

    @property
    def signed(self) -> bool:
        return self.status == STATUS_SIGNED

    def to_dict(self) -> dict[str, Any]:
        return {
            "version_id": self.version_id,
            "digest": self.version.digest,
            "version": self.version.content(),
            "status": self.status,
            "sponsor": self.sponsor,
            "proposed_at": self.proposed_at,
            "approver": self.approver,
            "signed_at": self.signed_at,
            "revoked": dict(self.revoked) if self.revoked else None,
        }


def _need_person(actor: str, what: str) -> None:
    if not is_person(actor):
        raise ClassSetRefused(
            f"{what} is a person's act: {actor!r} is a miner, a model, the system or nobody",
            code=REFUSAL_NOT_A_PERSON,
        )


def apply(states: Mapping[str, VersionState], act: ClassSetAct) -> VersionState:
    """The version's state after ``act`` given every version of the organisation so far, or
    :class:`ClassSetRefused`. A proposal is the organisation's next number and is its
    sponsor's; a signature is a person's, names the digest it read, and is never the
    sponsor's (the library's one two-person rule); a revocation is a person's, with a reason."""
    if carries_credential(act.hashed()):
        raise ClassSetRefused(
            "an act carries no credential: the ledger is append-only", code=REFUSAL_CREDENTIAL
        )
    state = states.get(act.version_id)
    if act.act == ACT_PROPOSE:
        version = ClassSetVersion.from_dict(act.body.get("version") or {})
        if version.version_id != act.version_id or version.digest != act.digest:
            raise LedgerIntegrityError(f"class-set act {act.act_id[:8]}: not its version")
        _need_person(act.actor, "proposing a class set")
        if act.actor != version.proposed_by:
            raise ClassSetRefused(
                "a proposal is recorded under the sponsor it names", code=REFUSAL_NOT_A_PERSON
            )
        top = max((s.version.n for s in states.values() if s.version.org == act.org), default=0)
        if version.n != top + 1:
            raise ClassSetRefused(
                f"{act.org}'s next class set is v{top + 1}; a version is never proposed twice "
                f"or out of order — propose v{top + 1} with what changed",
                code=REFUSAL_OUT_OF_ORDER,
            )
        return VersionState(
            version=version, status=STATUS_PROPOSED, sponsor=act.actor, proposed_at=act.created
        )
    if state is None:
        raise ClassSetRefused(f"no class set {act.version_id}", code=REFUSAL_UNKNOWN_ENTRY)
    if act.act == ACT_SIGN:
        _need_person(act.actor, "signing a class set")
        if act.digest != state.version.digest:
            raise ClassSetRefused(
                f"{act.version_id} reads {state.version.digest[:12]}; the signature names "
                f"{act.digest[:12] or 'none'} — read it again",
                code=REFUSAL_VERSION_MISMATCH,
            )
        if state.status != STATUS_PROPOSED:
            raise ClassSetRefused(
                f"{act.version_id} is {state.status}: there is nothing to sign",
                code=REFUSAL_NOT_SIGNABLE,
            )
        refuse_same_person("class set", sponsor=state.sponsor, approver=act.actor)
        return replace(state, status=STATUS_SIGNED, approver=act.actor, signed_at=act.created)
    # ACT_REVOKE
    _need_person(act.actor, "revoking a class set")
    reason = str(act.body.get("reason", "")).strip()
    if not reason:
        raise ClassSetRefused("a revocation says why", code=REFUSAL_REASON_MISSING)
    if state.status == STATUS_REVOKED:
        raise ClassSetRefused(f"{act.version_id} is already revoked", code=REFUSAL_NOT_SIGNABLE)
    return replace(
        state,
        status=STATUS_REVOKED,
        revoked={"actor": act.actor, "reason": reason, "at": act.created},
    )


def fold(acts: Iterable[ClassSetAct]) -> dict[str, VersionState]:
    """version id → state over ``acts`` in append order. An act that no longer applies means
    the store was changed outside this module: raised, never skipped."""
    states: dict[str, VersionState] = {}
    for a in acts:
        try:
            states[a.version_id] = apply(states, a)
        except LibraryRefused as e:
            raise LedgerIntegrityError(
                f"class-set act {a.act_id[:8]} ({a.act} on {a.version_id}) no longer applies: {e}"
            ) from e
    return states


# ---------------------------------------------------------------------------
# The validity report
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Case:
    """One replayable commit as the report reads it: its repository and id, which set it is
    in, its churn tier (``size``), whether it is qualified (gold checked clean), its message,
    — when one is linked — its ticket as it stood at the parent's date, and the global class the
    miner gave it (``mined_class``, read from its paths: never an input to the rule, but what a
    reading's pool is keyed by, so measurability counts only commits mined under a class's
    parent)."""

    repo: str
    task_id: str
    split: str
    size: str
    message: TicketFields
    ticket: TicketFields | None = None
    qualified: bool = True
    mined_class: str = ""

    @property
    def fields(self) -> TicketFields:
        """What the rule reads for this commit: the linked ticket, else the message."""
        return self.ticket if self.ticket is not None else self.message


@dataclass(frozen=True)
class PersonLabel:
    """One person's label of one derivation commit under one version."""

    repo: str
    task_id: str
    slug: str
    labeller: str
    created: str = ""


@dataclass(frozen=True)
class Measure:
    """One line of the report: its value, the threshold, how many it was read over, its state
    (``pass``, ``fail`` or ``not_applicable``) and what it means in words."""

    name: str
    value: float | None
    threshold: str
    n: int
    state: str
    words: str
    detail: Mapping[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return self.state in ("pass", "not_applicable")

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "value": None if self.value is None else round(self.value, 4),
            "threshold": self.threshold,
            "n": self.n,
            "state": self.state,
            "words": self.words,
            "detail": dict(self.detail),
        }


@dataclass(frozen=True)
class ValidityReport:
    """The six measures ADR-0026 item 9 names and the override rate, whether the version
    passes (every measure but size agreement — which decides only whether points size a ticket,
    ADR-0026 item 8), the class and size cells with enough confirmation commits to route, and the
    commit counts behind them."""

    version_id: str
    measures: tuple[Measure, ...]
    routable_cells: tuple[tuple[str, str], ...]
    commits: int
    derivation: int
    confirmation: int

    def measure(self, name: str) -> Measure:
        return next(m for m in self.measures if m.name == name)

    @property
    def passes(self) -> bool:
        return all(m.passed for m in self.measures if m.name not in NOT_ROUTING_CONDITIONS)

    @property
    def size_from_points(self) -> bool:
        """Whether story points may size a ticket (the points-to-churn agreement passed)."""
        return self.measure("size_agreement").state == "pass"

    def to_dict(self) -> dict[str, Any]:
        return {
            "version_id": self.version_id,
            "passes": self.passes,
            "size_from_points": self.size_from_points,
            "measures": [m.to_dict() for m in self.measures],
            "routable_cells": [{"class": c, "size": s} for c, s in self.routable_cells],
            "commits": self.commits,
            "derivation": self.derivation,
            "confirmation": self.confirmation,
        }


def cohen_kappa(pairs: Sequence[tuple[str, str]]) -> float | None:
    """Cohen's κ for two raters over ``pairs``; ``None`` for no pairs. When chance agreement
    is total (one category only) κ is 1 for perfect agreement, else 0."""
    n = len(pairs)
    if not n:
        return None
    observed = sum(1 for a, b in pairs if a == b) / n
    cats = {x for p in pairs for x in p}
    left = {c: sum(1 for a, _ in pairs if a == c) / n for c in cats}
    right = {c: sum(1 for _, b in pairs if b == c) / n for c in cats}
    expected = sum(left[c] * right[c] for c in cats)
    if expected >= 1.0:
        return 1.0 if observed >= 1.0 else 0.0
    return (observed - expected) / (1.0 - expected)


def _share(k: int, n: int) -> float | None:
    return k / n if n else None


def _pct(x: float | None) -> str:
    return "—" if x is None else f"{x * 100:.1f}%"


def set_aside(repo: str, commit: str) -> bool:
    """Whether a derivation commit is set aside as a possible example: the first 16 hex digits
    of ``sha256(EXAMPLE_SEED + "|" + repo + "|" + commit)`` read as a fraction fall below
    :data:`EXAMPLE_SHARE` — fixed per commit, blind to every class and outcome."""
    digest = hashlib.sha256(f"{EXAMPLE_SEED}|{repo}|{commit}".encode()).hexdigest()
    return int(digest[:16], 16) / 16**16 < EXAMPLE_SHARE


def example_keys(cases: Iterable[Case]) -> set[tuple[str, str]]:
    """The (repository, commit) keys of the derivation commits set aside as examples: never
    offered for labelling and never read by the report, whether or not a page shows them."""
    return {
        (c.repo, c.task_id) for c in cases if c.split == DERIVATION and set_aside(c.repo, c.task_id)
    }


def examples_of(
    version: ClassSetVersion, cases: Iterable[Case], *, k: int = EXAMPLES_PER_CLASS
) -> dict[str, tuple[Case, ...]]:
    """class slug → its example commits: up to ``k`` of the set-aside derivation commits
    (:func:`example_keys`), in (repository, commit) order, the version's rule puts in it. A
    class's page shows them; no person labels a commit they were shown as the rule's answer
    (P-686)."""
    out: dict[str, list[Case]] = {c.slug: [] for c in version.classes}
    ordered = sorted(cases, key=lambda c: (c.repo, c.task_id))
    aside = example_keys(ordered)
    for case in ordered:
        if (case.repo, case.task_id) not in aside:
            continue
        slug = classify(version, case.fields).slug
        if slug in out and len(out[slug]) < k:
            out[slug].append(case)
    return {slug: tuple(v) for slug, v in out.items()}


def latest_person_labels(labels: Iterable[PersonLabel]) -> dict[tuple[str, str, str], str]:
    """(repo, task, labeller) → the labeller's latest class: a person may change their mind,
    and only their last word counts."""
    out: dict[tuple[str, str, str], str] = {}
    for lab in labels:
        out[(lab.repo, lab.task_id, lab.labeller)] = lab.slug
    return out


def validity_report(
    version: ClassSetVersion,
    cases: Sequence[Case],
    labels: Iterable[PersonLabel],
    *,
    points_tier: Callable[[float], str],
    intake_overrides: int = 0,
    intake_classified: int = 0,
) -> ValidityReport:
    """The validity report of ``version`` over its repositories' replayable commits
    (``cases``) and the person-labelled sample (``labels``). Only a label of a derivation
    commit counts, never one of a class's example commits (the labeller was shown the rule's
    answer) and never the sponsor's (the rule is their own words: κ would measure its author
    against it). ``points_tier`` maps story points to a size tier (intake's published scale);
    ``intake_overrides`` of ``intake_classified`` tickets carried a ``crb:class=`` override."""
    decided = {(c.repo, c.task_id): classify(version, c.fields) for c in cases}
    shown = example_keys(cases)
    n = len(cases)
    classified = sum(1 for d in decided.values() if d.classified)
    coverage = _share(classified, n)
    measures: list[Measure] = []
    measures.append(
        Measure(
            "coverage",
            coverage,
            f"at least {COVERAGE_MIN:.0%} of replayable commits in a named class",
            n,
            "pass" if coverage is not None and coverage >= COVERAGE_MIN else "fail",
            f"{classified} of {n} replayable commits fall in a named class ({_pct(coverage)}).",
        )
    )
    # agreement: the rule against a person, on derivation commits only
    derivation = {(c.repo, c.task_id) for c in cases if c.split == DERIVATION}
    pairs: list[tuple[str, str]] = []
    # the per-class minimum counts labelled COMMITS, as the sample does: two people labelling
    # the same three commits are still three commits of the class (P-681)
    in_class: dict[str, set[tuple[str, str]]] = {c.slug: set() for c in version.classes}
    sampled: set[tuple[str, str]] = set()
    skipped = {"sponsor": 0, "examples": 0}
    for (repo, task, who), slug in latest_person_labels(labels).items():
        if (repo, task) not in derivation:
            continue
        if who == version.proposed_by:
            skipped["sponsor"] += 1
            continue
        if (repo, task) in shown:
            skipped["examples"] += 1
            continue
        sampled.add((repo, task))
        pairs.append((decided[(repo, task)].slug, slug))
        if slug in in_class:
            in_class[slug].add((repo, task))
    per_class = {slug: len(keys) for slug, keys in in_class.items()}
    kappa = cohen_kappa(pairs)
    thin = sorted(s for s, k in per_class.items() if k < PER_CLASS_MIN)
    agree_ok = kappa is not None and kappa >= KAPPA_MIN and len(sampled) >= SAMPLE_MIN and not thin
    words = (
        f"κ = {kappa:.2f} between the rule and a person over {len(pairs)} labels of "
        f"{len(sampled)} derivation commits"
        if kappa is not None
        else "No derivation commit has a person's label yet"
    )
    if len(sampled) < SAMPLE_MIN:
        words += f"; the sample needs {SAMPLE_MIN - len(sampled)} more commits"
    if thin:
        words += f"; fewer than {PER_CLASS_MIN} labelled commits in {', '.join(thin)}"
    if skipped["sponsor"]:
        words += f"; {skipped['sponsor']} of the sponsor's own labels are not read"
    measures.append(
        Measure(
            "agreement",
            kappa,
            f"κ at least {KAPPA_MIN} over at least {SAMPLE_MIN} derivation commits, "
            f"at least {PER_CLASS_MIN} per class",
            len(sampled),
            "pass" if agree_ok else "fail",
            words + ".",
            {"per_class": dict(per_class), "labels": len(pairs), "set_aside": dict(skipped)},
        )
    )
    # stability: the rule applied again gives the same labels
    again = sum(1 for c in cases if classify(version, c.fields) == decided[(c.repo, c.task_id)])
    stability = _share(again, n)
    measures.append(
        Measure(
            "stability",
            stability,
            f"the rule repeats its own labels at least {STABILITY_MIN:.0%} of the time",
            n,
            "pass" if stability is not None and stability >= STABILITY_MIN else "fail",
            f"Applied twice, the rule gave the same class to {again} of {n} commits "
            "(it is a fixed rule, not a model).",
        )
    )
    # ticket consistency: the same class from the ticket and from the message
    linked = [(c, c.ticket) for c in cases if c.ticket is not None]
    same = sum(
        1 for c, t in linked if classify(version, t).slug == classify(version, c.message).slug
    )
    consistency = _share(same, len(linked))
    if len(linked) < TICKETS_MIN:
        state, words = (
            "not_applicable",
            f"{len(linked)} commits link a ticket; the check applies from {TICKETS_MIN}.",
        )
    else:
        state = (
            "pass" if consistency is not None and consistency >= TICKET_CONSISTENCY_MIN else "fail"
        )
        words = (
            f"The ticket and the message give the same class for {same} of {len(linked)} "
            f"linked commits ({_pct(consistency)})."
        )
    measures.append(
        Measure(
            "ticket_consistency",
            consistency,
            f"where at least {TICKETS_MIN} commits link a ticket, the same class from ticket "
            f"and message at least {TICKET_CONSISTENCY_MIN:.0%} of the time",
            len(linked),
            state,
            words,
        )
    )
    # size agreement: the tier the points name against the merged change's churn tier
    pointed = [(c, t.points) for c, t in linked if t.points is not None]
    order = ("XS", "S", "M", "L", "XL")
    equal = smaller = 0
    for c, points in pointed:
        named = points_tier(float(points))
        if named == c.size:
            equal += 1
        elif named in order and c.size in order and order.index(named) < order.index(c.size):
            smaller += 1
    eq_share, small_share = _share(equal, len(pointed)), _share(smaller, len(pointed))
    size_ok = (
        len(pointed) >= SIZE_TICKETS_MIN
        and eq_share is not None
        and eq_share >= SIZE_EQUAL_MIN
        and small_share is not None
        and small_share <= SIZE_SMALLER_MAX
    )
    measures.append(
        Measure(
            "size_agreement",
            eq_share,
            f"on at least {SIZE_TICKETS_MIN} pointed tickets, the points' tier equals the "
            f"churn tier at least {SIZE_EQUAL_MIN:.0%} and names a smaller tier at most "
            f"{SIZE_SMALLER_MAX:.0%} of the time",
            len(pointed),
            "pass" if size_ok else "fail",
            (
                f"{len(pointed)} linked tickets carry points; the points name the churn tier "
                f"for {equal} ({_pct(eq_share)}) and a smaller tier for {smaller} "
                f"({_pct(small_share)}). "
            )
            + (
                "Points size a ticket."
                if size_ok
                else "Until this passes, a pointed ticket reads its size's cell and the next "
                "larger one and meets the more demanding (ADR-0026 item 8)."
            ),
        )
    )
    # measurability: confirmation commits per class and size cell — only those a reading of
    # the class can pool, which are the commits mined under its parent (a reading's cell is
    # the parent's; P-682); the rest are counted as a diagnostic, never as measurable
    cells: dict[tuple[str, str], int] = {}
    elsewhere = 0
    for c in cases:
        d = decided[(c.repo, c.task_id)]
        if not (c.split == CONFIRMATION and c.qualified and d.classified):
            continue
        if c.mined_class != d.parent:
            elsewhere += 1
            continue
        cells[(d.slug, c.size)] = cells.get((d.slug, c.size), 0) + 1
    routable = tuple(sorted(k for k, v in cells.items() if v >= MEASURABLE_MIN))
    diagnostic = (
        f" {elsewhere} more qualified confirmation commit{'s' if elsewhere != 1 else ''} of "
        "these classes were mined under another global class, so no reading of the class can "
        "read them (the miner's class comes from the changed files; G-761)."
        if elsewhere
        else ""
    )
    measures.append(
        Measure(
            "measurability",
            float(len(routable)),
            f"at least {MEASURABLE_MIN} confirmation commits in each class and size cell it routes",
            sum(cells.values()),
            "pass" if routable else "fail",
            (
                f"{len(routable)} class and size cells hold {MEASURABLE_MIN} or more qualified "
                f"confirmation commits; the version routes only those."
                if routable
                else f"No class and size cell holds {MEASURABLE_MIN} qualified confirmation "
                "commits yet, so the version can route no cell."
            )
            + diagnostic,
            {
                "cells": [{"class": k[0], "size": k[1], "n": v} for k, v in sorted(cells.items())],
                "other_parent": elsewhere,
            },
        )
    )
    # the override rate: how often a person had to correct the rule
    over_replay = sum(1 for d in decided.values() if d.by == BY_OVERRIDE)
    total = classified + intake_classified
    rate = _share(over_replay + intake_overrides, total)
    measures.append(
        Measure(
            "override_rate",
            rate,
            f"at most {OVERRIDE_RATE_MAX:.0%} of classified tickets carry a crb:class= override "
            "(the product's proposal, pending the operator)",
            total,
            "pass" if rate is None or rate <= OVERRIDE_RATE_MAX else "fail",
            f"{over_replay + intake_overrides} of {total} classified tickets named their class "
            f"with crb:class= ({_pct(rate)}).",
        )
    )
    n_der = sum(1 for c in cases if c.split == DERIVATION)
    return ValidityReport(
        version_id=version.version_id,
        measures=tuple(measures),
        routable_cells=routable,
        commits=n,
        derivation=n_der,
        confirmation=n - n_der,
    )


# ---------------------------------------------------------------------------
# Routing and the reading's pool
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RouteVerdict:
    """Whether a version routes, the reason code, and the reason in words."""

    ok: bool
    code: str
    words: str

    def to_dict(self) -> dict[str, Any]:
        return {"routes": self.ok, "code": self.code, "words": self.words}


def routes(state: VersionState | None, report: ValidityReport | None) -> RouteVerdict:
    """A version routes only when it is signed by a person other than its sponsor, is not
    revoked, and its validity report passes. The global vocabulary always routes."""
    if state is None:
        return RouteVerdict(False, ROUTE_UNKNOWN, "No such class set.")
    if state.status == STATUS_REVOKED:
        return RouteVerdict(False, ROUTE_REVOKED, "The class set was revoked; it routes nothing.")
    if not state.signed:
        return RouteVerdict(
            False,
            ROUTE_UNSIGNED,
            "No approver other than its sponsor has signed it, so it routes nothing.",
        )
    if report is None or not report.passes:
        # only the checks that stop routing are named: size agreement decides whether points
        # size a ticket, never whether the version routes (DL-331; P-688)
        failed = [
            m.name
            for m in (report.measures if report else ())
            if not m.passed and m.name not in NOT_ROUTING_CONDITIONS
        ]
        return RouteVerdict(
            False,
            ROUTE_REPORT_FAILED,
            "Its validity report does not pass"
            + (f" ({', '.join(n.replace('_', ' ') for n in failed)})" if failed else "")
            + ", so it routes nothing.",
        )
    return RouteVerdict(True, ROUTE_OK, "Signed by two people and its validity report passes.")


def refuse_reading_pool(
    state: VersionState | None,
    report: ValidityReport | None,
    *,
    repo: str,
    org_class: str,
    pool: Sequence[str],
    now: str,
) -> None:
    """Raise :class:`~crb.core.reading.ReadingRefused` unless a reading on ``org_class`` of
    this version may be registered over ``pool`` in ``repo``: the version routes, names the
    class and covers the repository, the registration comes after the signature, and every
    pool commit is a confirmation commit — a commit that derived or separated a class never
    licenses it (ADR-0026 item 9). ``pool_seen`` is the reading machinery's own check."""
    verdict = routes(state, report)
    if not verdict.ok or state is None:
        raise ReadingRefused(
            f"a reading reads an organisation's class set only when it routes: {verdict.words}",
            code=REFUSAL_NOT_ROUTING,
            detail={"route": verdict.code},
        )
    version = state.version
    if version.class_of(org_class) is None:
        raise ReadingRefused(
            f"{version.version_id} has no class {org_class!r}", code=REFUSAL_NOT_ROUTING
        )
    if repo not in version.repos:
        raise ReadingRefused(
            f"{version.version_id} does not cover {repo}", code=REFUSAL_NOT_ROUTING
        )
    # the version is already signed when this runs, so the registration follows the signature
    # in the chain; the time is whole seconds, so the same second is after, never before
    if not now or not state.signed_at or now < state.signed_at:
        raise ReadingRefused(
            "a reading of a class set is registered after the set was signed",
            code=REFUSAL_NOT_ROUTING,
        )
    derived = sorted(c for c in pool if version.split(repo, c) == DERIVATION)
    if derived:
        raise ReadingRefused(
            f"{len(derived)} pool commit(s) are in the derivation set: a class set licenses "
            "only on confirmation commits it never used (ADR-0026 item 9)",
            code=REFUSAL_DERIVATION_COMMIT,
            detail={"commits": derived[:20], "n": len(derived)},
        )


def is_org_class_set(version_id: str) -> bool:
    """``True`` for an organisation's version (anything but the global vocabulary)."""
    return bool(version_id) and version_id != GLOBAL_CLASS_SET


__all__ = [
    "ACTS",
    "ACT_PROPOSE",
    "ACT_REVOKE",
    "ACT_SIGN",
    "BY_NONE",
    "BY_OVERRIDE",
    "BY_RULE",
    "CLASS_SET_SCHEMA",
    "CONFIRMATION",
    "COVERAGE_MIN",
    "DERIVATION",
    "DERIVATION_SHARE",
    "EXAMPLES_PER_CLASS",
    "EXAMPLE_SEED",
    "EXAMPLE_SHARE",
    "KAPPA_MIN",
    "MEASURABLE_MIN",
    "NOT_ROUTING_CONDITIONS",
    "OVERRIDE_RATE_MAX",
    "PER_CLASS_MIN",
    "REFUSAL_CONFIRMATION_LABEL",
    "REFUSAL_DERIVATION_COMMIT",
    "REFUSAL_EXAMPLE_LABEL",
    "REFUSAL_NOT_ROUTING",
    "REFUSAL_OUT_OF_ORDER",
    "REFUSAL_REPO_TAKEN",
    "REFUSAL_SPONSOR_LABEL",
    "ROUTE_OK",
    "ROUTE_REPORT_FAILED",
    "ROUTE_REVOKED",
    "ROUTE_UNKNOWN",
    "ROUTE_UNSIGNED",
    "SAMPLE_MIN",
    "SOURCE_MESSAGE",
    "SPLIT_SEED",
    "STATUS_PROPOSED",
    "STATUS_REVOKED",
    "STATUS_SIGNED",
    "TICKET_TIME_FIELDS",
    "Case",
    "ClassRule",
    "ClassSetAct",
    "ClassSetRefused",
    "ClassSetVersion",
    "Decision",
    "Measure",
    "OrgClass",
    "PersonLabel",
    "RouteVerdict",
    "TicketFields",
    "ValidityReport",
    "VersionState",
    "apply",
    "classify",
    "cohen_kappa",
    "example_keys",
    "examples_of",
    "fold",
    "from_message",
    "global_parents",
    "is_org_class_set",
    "latest_person_labels",
    "refuse_reading_pool",
    "routes",
    "set_aside",
    "split_of",
    "validity_report",
    "verify_chain",
]
