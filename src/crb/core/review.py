"""Human review ledger — a person's post-hoc verdict on ONE graded row, ledgered.

The grade ledger records what the instrument *measured*; the sign-off ledger records
a human's attestation about a *cell*. Neither has a place for what the 2026-09-13
critical-friend review (§5 plays 05/07, action #3) found missing: a reviewer reads
an accepted patch, finds a behavioural gap the oracle could not see, and that finding
has nowhere to live. A :class:`ReviewRecord` is that finding: a verdict on one
:class:`~crb.core.ledger.GradeRow`, keyed by the row's chain hash, in its own
append-only, hash-chained JSONL ledger (:class:`JsonlReviewLedger`) with the same
discipline as the other two.

The patch-hash anchor (the ONE rule)
------------------------------------
A reviewer attests to *bytes*, not to a description of them. Every review that
carries a verdict names ``patch_sha256_reviewed`` — the SHA-256 of the unified diff
the reviewer read — and the write boundary refuses the record unless that hash equals
the graded row's evidence pack ``grade.diff.diff_sha256``
(:func:`check_patch_anchor`, raising :class:`ReviewRefused`). The pack's hash is the
anchor: a retained worktree is *served* against it and never stored twice
(ADR-0006 amendment), and a review of a patch whose bytes cannot be reproduced —
the worktree is gone, or redaction changed them — cannot be written. Only a
``not_reviewed`` record (the reviewer looked and could not review) carries no hash.

**Whose pack.** The pack is the REVIEWED ROW's — resolved from the row named by
``grade_row_hash``, never from the record's own ``evidence_pack_hash`` field. The
independent review pass (2026-09-14, finding 5) wrote a review of row A carrying
row B's pack hash and B's diff hash: the store looked the pack up by the record's
field and accepted it. :func:`check_review_anchor` is the one rule both ledgers
apply: the record's ``evidence_pack_hash`` must equal the row's; a pack handed in
by a caller must be *self-certifying* (its ``pack_hash`` recomputes and equals the
row's); a record with a verdict is never appended without that pack. The JSONL
ledger cannot look the row up itself, so its ``append`` requires the pack (and
takes the row when the caller has it); the DB ledger resolves both.

Verdicts and findings
---------------------
``findings`` is the list of what the reviewer saw, each ``{kind, note, file, line}``
with ``kind`` in :data:`FINDING_KINDS`; ``verdict`` is the headline, derived from the
findings by ONE rule (:func:`derive_verdict`: the most severe finding kind, ``ok``
when there is none) and checked at construction so a record can never say ``ok``
over a ``regression``. ``mergeable`` is the reviewer's separate answer to "would a
maintainer merge this as-is" (``None`` = not answered); a ``regression`` finding
refuses ``mergeable=True`` — a known regression is never mergeable.

Reviews are governance evidence and are kept forever (``docs/DATA-RETENTION.md``).
A later review of the same row is a new record; the latest per row is the standing
verdict (:func:`latest_reviews`), which :func:`review_cell_stats` joins onto the
graded rows so a capability cell can say how many of its accepted rows a human has
read and how many of those had a defect.

Navigation
----------
What it is:   The review ledger — ``ReviewRecord`` (one human's verdict on one graded row,
              anchored to the bytes they read), its append-only JSONL ledger, the anchor
              rule both ledgers apply, and the per-cell review statistics.
What it does: Derives a record's headline verdict from its findings by one rule and refuses
              a record that contradicts them; refuses any verdict whose patch hash is not
              the reviewed row's pack ``diff_sha256`` or whose pack is not that row's own;
              chains records; joins the standing verdict per row onto cells so the map can
              show how many accepted rows a human read and how many had a defect. Records
              are kept forever.
How:          ``ReviewRecord.__post_init__`` (vocabulary, ``derive_verdict``, hash shape,
              regression ⇒ not mergeable) → ``check_review_anchor`` (row match, pack
              self-certifies via ``verify_pack``, ``check_patch_anchor``) → ``chained`` +
              fsync; readers: ``latest_reviews`` → ``review_cell_stats`` projected like the
              capability map.
Layer:        core — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0002-append-only-hash-chained-ledger.md,
              docs/adr/0006-zero-raw-retention-and-evidence-packs.md
Works with:   src/crb/core/ledger.py (the GradeRow a review names; the chain helpers),
              src/crb/core/evidence.py (the pack whose ``diff_sha256`` is the anchor;
              ``verify_pack``), src/crb/store/ledger.py (``DbReviewLedger`` — same records,
              resolves the row and pack itself), src/crb/server/routes/reviews.py (the
              write boundary; ``ReviewRefused`` → 422), src/crb/core/capability.py (the
              cell projection the statistics mirror), src/crb/core/redact.py (notes and
              statements are redacted at construction)
Tested by:    tests/test_review.py, tests/test_store_reviews.py, tests/test_server_routes_reviews.py
Touch when:   never for a new repository; adding a verdict or finding kind changes
              ``SEVERITY`` and every consumer's copy (docs/API.md#reviews-human-verdicts-on-graded-rows,
              the UI) — bump ``REVIEW_SCHEMA`` if the hashed body changes; the anchor rule
              is a governance control (docs/reviews/human-review-guide.md) and is never
              relaxed for convenience.
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from crb.core.evidence import canonical_json, sha256_text, utc_now_iso, verify_pack
from crb.core.ledger import CELL_FIELDS, GENESIS_HASH, CellKey, GradeRow, LedgerIntegrityError
from crb.core.redact import redact
from crb.core.version import APPARATUS_VERSION

REVIEW_SCHEMA = "crb.review.v1"

# --- verdicts (the vocabulary) ----------------------------------------------------
#: The reviewer read the patch and found nothing to report.
VERDICT_OK = "ok"
#: A behavioural gap: the patch does not do what the change was meant to do.
VERDICT_DEFECT = "defect"
#: The patch breaks something the tests did not cover.
VERDICT_REGRESSION = "regression"
#: The patch changes a public API / shape a maintainer would not accept as-is.
VERDICT_API_CHANGE = "api_change"
#: Working code the repository's conventions would reject (naming, structure, docs).
VERDICT_STYLE = "style"
#: The reviewer looked but could not review (no patch to read, out of their remit).
VERDICT_NOT_REVIEWED = "not_reviewed"
VERDICTS: tuple[str, ...] = (
    VERDICT_OK,
    VERDICT_DEFECT,
    VERDICT_REGRESSION,
    VERDICT_API_CHANGE,
    VERDICT_STYLE,
    VERDICT_NOT_REVIEWED,
)
#: The kinds a finding may carry (a finding is always *something*; ``ok`` and
#: ``not_reviewed`` are headlines, never findings).
FINDING_KINDS: tuple[str, ...] = (
    VERDICT_REGRESSION,
    VERDICT_DEFECT,
    VERDICT_API_CHANGE,
    VERDICT_STYLE,
)
#: Most severe first — the order :func:`derive_verdict` picks the headline by.
SEVERITY: tuple[str, ...] = FINDING_KINDS
#: The verdicts that count as "a human found a defect" in the cell statistics.
DEFECT_VERDICTS: tuple[str, ...] = (VERDICT_REGRESSION, VERDICT_DEFECT)

_SHA256_LEN = 64
_HEX = frozenset("0123456789abcdef")


class ReviewRefused(ValueError):
    """The write boundary refused a review. Mapped to HTTP 422 by the API.

    ``code`` names the rule that failed: ``patch_hash_mismatch`` (the reviewer's hash
    is not the pack's), ``patch_hash_missing`` (a verdict without a hash),
    ``no_diff_in_pack`` (the graded row's pack recorded no diff — there is no patch
    to attest to), ``row_hash_missing`` (no graded row named), ``row_not_found`` (the
    named row is not in the grade ledger), ``row_mismatch`` (the row handed in is not
    the one the record names), ``pack_hash_mismatch`` (the record's — or the caller's
    — pack is not the reviewed row's), ``pack_required`` (a verdict with no pack to
    anchor it to).
    """

    def __init__(self, message: str, *, code: str, expected: Any = None, observed: Any = None):
        super().__init__(message)
        self.code = code
        self.expected = expected
        self.observed = observed


REFUSAL_PATCH_HASH_MISMATCH = "patch_hash_mismatch"
REFUSAL_PATCH_HASH_MISSING = "patch_hash_missing"
REFUSAL_NO_DIFF_IN_PACK = "no_diff_in_pack"
REFUSAL_ROW_HASH_MISSING = "row_hash_missing"
REFUSAL_ROW_NOT_FOUND = "row_not_found"
REFUSAL_ROW_MISMATCH = "row_mismatch"
REFUSAL_PACK_MISMATCH = "pack_hash_mismatch"
REFUSAL_PACK_REQUIRED = "pack_required"


def is_sha256(value: str) -> bool:
    """A 64-character lowercase hex digest — the only shape a patch hash may take."""
    return len(value) == _SHA256_LEN and all(ch in _HEX for ch in value)


def derive_verdict(findings: Sequence[Finding]) -> str:
    """THE rule that names a review's headline: the most severe finding kind
    (:data:`SEVERITY` order), or ``ok`` when there are no findings. ``not_reviewed``
    is never derived — it is the reviewer's explicit statement that they did not
    review, and a record carrying it may hold no findings."""
    kinds = {f.kind for f in findings}
    for kind in SEVERITY:
        if kind in kinds:
            return kind
    return VERDICT_OK


@dataclass(frozen=True)
class Finding:
    """One thing the reviewer saw: its kind, a note, and where (``file`` / ``line``
    optional — a finding about the change as a whole names neither)."""

    kind: str
    note: str
    file: str = ""
    line: int | None = None

    def __post_init__(self) -> None:
        if self.kind not in FINDING_KINDS:
            raise ValueError(f"finding kind must be one of {FINDING_KINDS}, got {self.kind!r}")
        if not self.note or not self.note.strip():
            raise ValueError("a finding needs a note")
        if self.line is not None and (not isinstance(self.line, int) or self.line < 1):
            raise ValueError("finding line must be a positive integer or null")
        object.__setattr__(self, "note", redact(self.note.strip()))
        object.__setattr__(self, "file", redact(self.file.strip()))

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "note": self.note, "file": self.file, "line": self.line}

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> Finding:
        line = d.get("line")
        return cls(
            kind=str(d.get("kind", "")),
            note=str(d.get("note", "")),
            file=str(d.get("file", "") or ""),
            line=None if line in (None, "") else int(line),
        )


@dataclass(frozen=True)
class ReviewRecord:
    """One human verdict on one graded row. ``grade_row_hash`` is the reviewed
    :class:`~crb.core.ledger.GradeRow`'s chain hash; ``row_hash`` is this record's own
    (every ledger record in crb names its own hash ``row_hash``)."""

    grade_row_hash: str
    repo: str
    task_id: str
    reviewer: str
    statement: str
    verdict: str = VERDICT_OK
    findings: tuple[Finding, ...] = ()
    mergeable: bool | None = None
    patch_sha256_reviewed: str = ""
    evidence_pack_hash: str = ""
    apparatus_version: str = APPARATUS_VERSION
    created: str = field(default_factory=utc_now_iso)
    schema: str = REVIEW_SCHEMA
    review_id: str = ""
    prev_hash: str = ""
    row_hash: str = ""

    def __post_init__(self) -> None:
        if not self.grade_row_hash:
            raise ReviewRefused(
                "a review must name the graded row it is about (grade_row_hash)",
                code=REFUSAL_ROW_HASH_MISSING,
            )
        if not self.repo:
            raise ValueError("repo is required")
        if not self.task_id:
            raise ValueError("task_id is required")
        if not self.reviewer:
            raise ValueError("reviewer is required (who reviewed)")
        if self.verdict not in VERDICTS:
            raise ValueError(f"verdict must be one of {VERDICTS}, got {self.verdict!r}")
        if not self.statement or not self.statement.strip():
            raise ValueError("statement is required (what the reviewer concluded, in words)")
        findings = tuple(
            f if isinstance(f, Finding) else Finding.from_dict(f) for f in self.findings
        )
        object.__setattr__(self, "findings", findings)
        if self.verdict == VERDICT_NOT_REVIEWED:
            if findings:
                raise ValueError("a not_reviewed record carries no findings")
            if self.mergeable is not None:
                raise ValueError("a not_reviewed record cannot answer mergeable")
            if self.patch_sha256_reviewed:
                raise ValueError("a not_reviewed record names no patch hash (nothing was read)")
        else:
            derived = derive_verdict(findings)
            if self.verdict != derived:
                raise ValueError(
                    f"verdict {self.verdict!r} contradicts the findings "
                    f"(derived {derived!r} from kinds {sorted({f.kind for f in findings})})"
                )
            if not self.patch_sha256_reviewed:
                raise ReviewRefused(
                    "a review with a verdict must name the sha256 of the patch it read",
                    code=REFUSAL_PATCH_HASH_MISSING,
                )
            if not is_sha256(self.patch_sha256_reviewed):
                raise ValueError(
                    "patch_sha256_reviewed must be a 64-character lowercase hex digest"
                )
            if self.mergeable is True and any(f.kind == VERDICT_REGRESSION for f in findings):
                raise ValueError("a change with a regression finding cannot be mergeable")
        object.__setattr__(self, "statement", redact(self.statement.strip()))
        if not self.review_id:
            object.__setattr__(self, "review_id", uuid.uuid4().hex)

    # --- derived -------------------------------------------------------------------
    @property
    def is_defect(self) -> bool:
        """The standing verdict says a human found a defect or a regression."""
        return self.verdict in DEFECT_VERDICTS

    @property
    def reviewed(self) -> bool:
        """Did the reviewer actually read the patch (anything but ``not_reviewed``)?"""
        return self.verdict != VERDICT_NOT_REVIEWED

    # --- hashing ---------------------------------------------------------------------
    def body(self) -> dict[str, Any]:
        """Everything hashed: every field but ``row_hash``; findings as dicts."""
        out: dict[str, Any] = {}
        for k in self.__dataclass_fields__:
            if k == "row_hash":
                continue
            v = getattr(self, k)
            out[k] = [f.to_dict() for f in v] if k == "findings" else v
        return out

    def compute_hash(self) -> str:
        """SHA-256 of the canonical JSON of :meth:`body` (``prev_hash`` included)."""
        return sha256_text(canonical_json(self.body()))

    def chained(self, prev_hash: str) -> ReviewRecord:
        """A copy with ``prev_hash`` set and ``row_hash`` computed (the ledger's job)."""
        rec = replace(self, prev_hash=prev_hash)
        object.__setattr__(rec, "row_hash", rec.compute_hash())
        return rec

    def verify_hash(self) -> bool:
        """``True`` iff the stored ``row_hash`` is the hash of the body as read back."""
        return bool(self.row_hash) and self.row_hash == self.compute_hash()

    # --- serialisation -----------------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        """The body plus ``row_hash`` — the stored line."""
        d = self.body()
        d["row_hash"] = self.row_hash
        return d

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> ReviewRecord:
        """Rebuild from a stored line; the construction rules run again on the way in."""
        kw = {k: d[k] for k in cls.__dataclass_fields__ if k in d}
        raw = kw.get("findings") or ()
        kw["findings"] = tuple(f if isinstance(f, Finding) else Finding.from_dict(f) for f in raw)
        return cls(**kw)


# ---------------------------------------------------------------------------
# The anchor
# ---------------------------------------------------------------------------


def pack_diff_sha256(pack: Mapping[str, Any]) -> str:
    """The ``grade.diff.diff_sha256`` a serialised evidence pack carries (``""`` when
    the pack recorded no diff — an imported pack, or a trial that changed nothing)."""
    grade = pack.get("grade")
    if not isinstance(grade, Mapping):
        return ""
    diff = grade.get("diff")
    if not isinstance(diff, Mapping):
        return ""
    return str(diff.get("diff_sha256", "") or "")


def check_patch_anchor(record: ReviewRecord, pack: Mapping[str, Any]) -> None:
    """Refuse ``record`` unless the hash it attests to IS the pack's ``diff_sha256``.

    A ``not_reviewed`` record passes (it attests to nothing). Otherwise the pack must
    record a diff and the two hashes must be equal — a reviewer never attests to bytes
    the instrument did not grade.
    """
    if not record.reviewed:
        return
    expected = pack_diff_sha256(pack)
    if not expected:
        raise ReviewRefused(
            "the graded row's evidence pack records no diff — there is no patch to review",
            code=REFUSAL_NO_DIFF_IN_PACK,
            expected="",
            observed=record.patch_sha256_reviewed,
        )
    if record.patch_sha256_reviewed != expected:
        raise ReviewRefused(
            "patch_sha256_reviewed does not match the evidence pack's diff_sha256 — the "
            "reviewer must attest to the exact bytes the instrument graded",
            code=REFUSAL_PATCH_HASH_MISMATCH,
            expected=expected,
            observed=record.patch_sha256_reviewed,
        )


def pack_is_authentic(pack: Mapping[str, Any], pack_hash: str) -> bool:
    """``pack`` is the pack ``pack_hash`` names: its ``pack_hash`` recomputes from its
    own body (:func:`~crb.core.evidence.verify_pack`) and equals ``pack_hash``. A pack
    is content-addressed, so a caller's copy proves itself or it does not count."""
    return bool(pack_hash) and pack.get("pack_hash") == pack_hash and verify_pack(pack)


def check_review_anchor(
    record: ReviewRecord,
    *,
    pack: Mapping[str, Any] | None,
    row: GradeRow | None = None,
) -> None:
    """THE anchor rule both ledgers apply before chaining a review (module docstring).

    * ``row`` (the reviewed :class:`~crb.core.ledger.GradeRow`, when the caller has
      it) must be the row the record names, and the record's ``evidence_pack_hash``
      must be the row's — a record cannot borrow another row's pack.
    * A record with a verdict needs ``pack``; the pack must be self-certifying for the
      record's ``evidence_pack_hash`` (:func:`pack_is_authentic`); then the patch
      anchor (:func:`check_patch_anchor`) must hold.
    * A ``not_reviewed`` record needs no pack; one handed in must still be the row's.
    """
    if row is not None:
        if row.row_hash != record.grade_row_hash:
            raise ReviewRefused(
                "the graded row handed in is not the row the review names",
                code=REFUSAL_ROW_MISMATCH,
                expected=record.grade_row_hash,
                observed=row.row_hash,
            )
        if row.evidence_pack_hash != record.evidence_pack_hash:
            raise ReviewRefused(
                "the review's evidence_pack_hash is not the reviewed row's — a review is "
                "anchored to its own row's pack, never another's",
                code=REFUSAL_PACK_MISMATCH,
                expected=row.evidence_pack_hash,
                observed=record.evidence_pack_hash,
            )
    if pack is not None and not pack_is_authentic(pack, record.evidence_pack_hash):
        raise ReviewRefused(
            "the evidence pack handed in is not the reviewed row's (its hash does not "
            "recompute to the record's evidence_pack_hash)",
            code=REFUSAL_PACK_MISMATCH,
            expected=record.evidence_pack_hash,
            observed=str(pack.get("pack_hash", "") or ""),
        )
    if not record.reviewed:
        return
    if pack is None:
        raise ReviewRefused(
            "a review with a verdict cannot be appended without the reviewed row's "
            "evidence pack — there is nothing to anchor it to",
            code=REFUSAL_PACK_REQUIRED,
            expected=record.evidence_pack_hash,
            observed=record.patch_sha256_reviewed,
        )
    check_patch_anchor(record, pack)


# ---------------------------------------------------------------------------
# JSONL ledger (append-only, hash-chained)
# ---------------------------------------------------------------------------


class JsonlReviewLedger:
    """Portable stdlib review ledger. Same chain discipline as the grade ledger."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def _last_hash(self) -> str:
        """The last record's ``row_hash`` (tail read, as the grade ledger does), or
        :data:`GENESIS_HASH` for an empty or absent file."""
        if not self.path.exists() or self.path.stat().st_size == 0:
            return GENESIS_HASH
        last = ""
        with self.path.open("rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            step = min(size, 65536)
            f.seek(size - step)
            chunk = f.read().decode("utf-8", errors="replace")
        for line in reversed(chunk.splitlines()):
            if line.strip():
                last = line
                break
        if not last:
            return GENESIS_HASH
        row_hash = str(json.loads(last).get("row_hash", ""))
        if not row_hash:
            raise LedgerIntegrityError(f"last review in {self.path} has no row_hash")
        return row_hash

    def append(
        self,
        record: ReviewRecord,
        *,
        pack: Mapping[str, Any] | None = None,
        row: GradeRow | None = None,
    ) -> ReviewRecord:
        """Anchor-check (:func:`check_review_anchor`), chain and append. Returns the
        chained record.

        The JSONL ledger is the portable reference and cannot look the reviewed row or
        its pack up itself, so the caller supplies them: ``pack`` is REQUIRED for a
        record with a verdict (a self-certifying copy of the row's pack — refused
        otherwise), and ``row`` is checked whenever the caller has it. There is no
        unchecked path: a verdict without its pack is refused, never chained.
        """
        check_review_anchor(record, pack=pack, row=row)
        chained = record.chained(self._last_hash())
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(chained.to_dict(), sort_keys=True, ensure_ascii=False)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
            f.flush()
            os.fsync(f.fileno())
        return chained

    def records(self) -> Iterator[ReviewRecord]:
        """Every record in file order; nothing for an absent file."""
        if not self.path.exists():
            return
        with self.path.open("r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    yield ReviewRecord.from_dict(json.loads(line))

    def verify(self) -> int:
        """Walk the chain; return the record count; raise on any break."""
        return verify_review_chain(self.records())


def verify_review_chain(records: Iterable[ReviewRecord]) -> int:
    """Prove ``records`` is an unbroken chain from genesis (the review twin of
    :func:`~crb.core.ledger.verify_chain`); raises :class:`LedgerIntegrityError`."""
    prev = GENESIS_HASH
    n = 0
    for rec in records:
        n += 1
        if rec.prev_hash != prev:
            raise LedgerIntegrityError(f"review {n} ({rec.review_id[:8]}) prev_hash mismatch")
        if not rec.verify_hash():
            raise LedgerIntegrityError(f"review {n} ({rec.review_id[:8]}) row_hash mismatch")
        prev = rec.row_hash
    return n


# ---------------------------------------------------------------------------
# Per-cell statistics (joined onto the graded rows)
# ---------------------------------------------------------------------------


def latest_reviews(records: Iterable[ReviewRecord]) -> dict[str, ReviewRecord]:
    """The standing verdict per graded row: the LAST record (chain order) for each
    ``grade_row_hash``. A later review supersedes an earlier one; nothing is edited."""
    latest: dict[str, ReviewRecord] = {}
    for rec in records:
        latest[rec.grade_row_hash] = rec
    return latest


@dataclass(frozen=True)
class ReviewCellStats:
    """How much of one cell a human has read, and what they found.

    ``n_reviewed`` counts the cell's graded rows whose standing verdict is a real
    review (not ``not_reviewed``); ``n_review_defects`` those whose standing verdict is
    ``defect`` or ``regression``; the ``n_<verdict>`` fields split ``n_reviewed`` (plus
    ``n_not_reviewed``, which sits outside it); ``n_mergeable`` / ``n_not_mergeable``
    count the reviewer's answer where one was given. ``n_rows`` is the cell's eligible
    row count, so a reader sees the denominator next to the numerator.
    """

    cell: CellKey
    n_rows: int
    n_reviewed: int
    n_review_defects: int
    n_ok: int = 0
    n_defect: int = 0
    n_regression: int = 0
    n_api_change: int = 0
    n_style: int = 0
    n_not_reviewed: int = 0
    n_mergeable: int = 0
    n_not_mergeable: int = 0

    def __post_init__(self) -> None:
        by_verdict = (
            self.n_ok + self.n_defect + self.n_regression + self.n_api_change + self.n_style
        )
        if self.n_reviewed != by_verdict:
            raise ValueError("n_reviewed must equal the sum of the reviewed verdict counts")
        if self.n_review_defects != self.n_defect + self.n_regression:
            raise ValueError("n_review_defects must equal n_defect + n_regression")

    @property
    def reviewed_share(self) -> float:
        """The share of the cell's eligible rows a human actually read."""
        return self.n_reviewed / self.n_rows if self.n_rows else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.cell.to_dict(),
            "n_rows": self.n_rows,
            "n_reviewed": self.n_reviewed,
            "n_review_defects": self.n_review_defects,
            "reviewed_share": round(self.reviewed_share, 4),
            "n_ok": self.n_ok,
            "n_defect": self.n_defect,
            "n_regression": self.n_regression,
            "n_api_change": self.n_api_change,
            "n_style": self.n_style,
            "n_not_reviewed": self.n_not_reviewed,
            "n_mergeable": self.n_mergeable,
            "n_not_mergeable": self.n_not_mergeable,
        }


def _projected(key: CellKey, projection: Sequence[str]) -> CellKey:
    """The key with every non-projected field wildcarded (the capability map's
    ``projected_key``, repeated here so this module does not import the map)."""
    proj = set(projection)
    return CellKey(**{f: (getattr(key, f) if f in proj else "*") for f in CELL_FIELDS})


def review_cell_stats(
    rows: Iterable[GradeRow],
    reviews: Iterable[ReviewRecord],
    *,
    projection: Sequence[str] = CELL_FIELDS,
) -> list[ReviewCellStats]:
    """Join the standing review per row onto the rows' cells (projected to
    ``projection``, ``"*"`` elsewhere — the same keying the capability map uses) and
    count. Pure: takes rows and records, touches no store. A review whose row is not
    among ``rows`` is ignored; a row with no review counts only in ``n_rows``.
    Cells are returned in first-seen row order."""
    unknown = [f for f in projection if f not in CELL_FIELDS]
    if not projection or unknown:
        raise ValueError(
            f"projection must be a non-empty subset of {CELL_FIELDS}, got {projection!r}"
        )
    standing = latest_reviews(reviews)
    groups: dict[tuple[str, ...], list[GradeRow]] = {}
    for r in rows:
        if not r.eligible:
            continue
        groups.setdefault(_projected(r.cell, projection).to_tuple(), []).append(r)
    out: list[ReviewCellStats] = []
    for key_tuple, cell_rows in groups.items():
        counts = dict.fromkeys(VERDICTS, 0)
        mergeable = not_mergeable = 0
        for r in cell_rows:
            rec = standing.get(r.row_hash)
            if rec is None:
                continue
            counts[rec.verdict] += 1
            if rec.mergeable is True:
                mergeable += 1
            elif rec.mergeable is False:
                not_mergeable += 1
        reviewed = sum(counts[v] for v in VERDICTS if v != VERDICT_NOT_REVIEWED)
        out.append(
            ReviewCellStats(
                cell=CellKey(*key_tuple),
                n_rows=len(cell_rows),
                n_reviewed=reviewed,
                n_review_defects=counts[VERDICT_DEFECT] + counts[VERDICT_REGRESSION],
                n_ok=counts[VERDICT_OK],
                n_defect=counts[VERDICT_DEFECT],
                n_regression=counts[VERDICT_REGRESSION],
                n_api_change=counts[VERDICT_API_CHANGE],
                n_style=counts[VERDICT_STYLE],
                n_not_reviewed=counts[VERDICT_NOT_REVIEWED],
                n_mergeable=mergeable,
                n_not_mergeable=not_mergeable,
            )
        )
    return out


__all__ = [
    "DEFECT_VERDICTS",
    "FINDING_KINDS",
    "REFUSAL_NO_DIFF_IN_PACK",
    "REFUSAL_PACK_MISMATCH",
    "REFUSAL_PACK_REQUIRED",
    "REFUSAL_PATCH_HASH_MISMATCH",
    "REFUSAL_PATCH_HASH_MISSING",
    "REFUSAL_ROW_HASH_MISSING",
    "REFUSAL_ROW_MISMATCH",
    "REFUSAL_ROW_NOT_FOUND",
    "REVIEW_SCHEMA",
    "SEVERITY",
    "VERDICTS",
    "VERDICT_API_CHANGE",
    "VERDICT_DEFECT",
    "VERDICT_NOT_REVIEWED",
    "VERDICT_OK",
    "VERDICT_REGRESSION",
    "VERDICT_STYLE",
    "Finding",
    "JsonlReviewLedger",
    "ReviewCellStats",
    "ReviewRecord",
    "ReviewRefused",
    "check_patch_anchor",
    "check_review_anchor",
    "derive_verdict",
    "is_sha256",
    "latest_reviews",
    "pack_diff_sha256",
    "pack_is_authentic",
    "review_cell_stats",
    "verify_review_chain",
]
