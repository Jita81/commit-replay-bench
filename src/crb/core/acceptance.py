"""Held-out acceptance tests: the second person's tests a calibration build is graded on.

ADR-0026 item 8. A cell whose standard is only a ceiling (``S3`` alone — the commit's own tests)
admits a ticket only as a calibration build. For its first attempt to be an ``S2`` row that a
forward reading may count, a **second person** — not the ticket's author, not the approver who
funded the build, not the person who runs it — writes held-out acceptance tests from the ticket
alone, without seeing the build or the ticket's own failing test. The tests are stored with
their author, time and digest, never reach a brief or the builder's tree, and are run against
the build only after the builder has finished.

The record (:class:`HeldOutTests`, schema ``crb.acceptance.v1``) is bound to ONE calibration
grant (the ``calibration.funded`` event it answers), so a later run of the same ticket never
reuses it. The row labels a graded first attempt carries — inside the row hash, at write — are
the ONE statement of "graded on held-out acceptance tests" every reader applies
(:func:`held_out_graded`): the factory's writer, the ledger's routing first attempts and the
reading's count (P-690 — two labels for one fact had let a writer and its readers disagree).

Navigation
----------
What it is:   The held-out acceptance-test record, its digest, the two-person rule for who may
              write it, the row labels of an attempt graded on it and the rule every reader
              uses to recognise such a row.
What it does: Hashes a record's files into one digest and its body into an id; refuses a
              writer who is the ticket's author, the funding approver or the run's submitter;
              stamps ``acceptance: held_out`` with the record's id, digest and result (``pass``,
              ``fail`` or ``error``), or ``acceptance: none`` with why; finds a record's lines in
              any text (the leak check the tests apply to briefs and workspaces).
How:          Pure functions and one frozen dataclass over ``crb.core.evidence``'s canonical
              JSON and SHA-256; identities compare after the ``operator:`` / ``approver:``
              prefixes are removed.
Layer:        core — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0026-the-context-standard.md (items 2, 6 and 8)
Works with:   src/crb/core/reading.py (a forward reading enrols records and counts held-out
              rows), src/crb/core/ledger.py (routing first attempts read the same rule),
              src/crb/factory/build.py (runs the tests after the builder and stamps the row),
              src/crb/factory/loop.py (decides which attempt is graded on them),
              src/crb/server/acceptance.py (stores and serves the record)
Tested by:    tests/test_acceptance.py, tests/test_factory_held_out.py,
              tests/test_forward_reading.py
Touch when:   never for a new repository; a label is added to the stamp (here, and in
              docs/API.md, the Factory table); the two-person rule changes (an ADR amending
              ADR-0026 item 8 first).
Claims:       A held-out result says whether the build passed tests a second person wrote from
              the ticket alone; it is not a review and says nothing about code the tests do not
              reach (docs/EVIDENCE-AND-CLAIMS.md).
"""

from __future__ import annotations

import posixpath
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from crb.core.context_arm import BASE_S2, LABEL_CONTEXT_ARM, is_arm, parse_arm
from crb.core.evidence import canonical_json, sha256_text

SCHEMA = "crb.acceptance.v1"
#: The event a record is written as, on the repository's ``acceptance:<repo>`` trace.
EVENT_ACTION = "acceptance.written"
TRACE_PREFIX = "acceptance:"

#: THE label of how a factory attempt was graded (ADR-0026 items 2 and 8).
LABEL_ACCEPTANCE = "acceptance"
ACCEPTANCE_HELD_OUT = "held_out"
ACCEPTANCE_NONE = "none"
#: The record an attempt was graded on, its digest and the result.
LABEL_ACCEPTANCE_ID = "acceptance_id"
LABEL_ACCEPTANCE_SHA = "acceptance_sha256"
LABEL_ACCEPTANCE_RESULT = "acceptance_result"
#: Why an ``S2`` attempt was not graded on held-out tests (``acceptance: none``).
LABEL_ACCEPTANCE_WHY = "acceptance_why"

RESULT_PASS = "pass"  # noqa: S105 — a test result, not a credential
RESULT_FAIL = "fail"
#: The tests could not be run (a timeout, an unparseable report, the instrument failed):
#: an instrument failure, never a miss — the forward reading lets the ticket leave its pool.
RESULT_ERROR = "error"
RESULTS: tuple[str, ...] = (RESULT_PASS, RESULT_FAIL, RESULT_ERROR)

#: Why an attempt carries ``acceptance: none``.
WHY_NO_TESTS = "no_held_out_tests"
WHY_NOT_FIRST = "not_first_attempt"
WHY_SAME_PERSON = "same_person"
WHY_NOT_CALIBRATION = "not_a_calibration_build"

#: The most files, and bytes per file, one record may hold.
MAX_FILES = 10
MAX_FILE_BYTES = 64_000

_PERSON_PREFIXES = ("operator:", "approver:", "user:")


def person(identity: str) -> str:
    """An identity without its role prefix: ``operator:u1`` and ``u1`` are one person."""
    s = (identity or "").strip()
    for p in _PERSON_PREFIXES:
        if s.startswith(p):
            return s[len(p) :]
    return s


def files_digest(files: Sequence[tuple[str, str]]) -> str:
    """SHA-256 of the files as canonical JSON: each path with its content's own SHA-256,
    sorted by path — the one digest a row, a page and a record quote."""
    body = sorted((p, sha256_text(c)) for p, c in files)
    return sha256_text(canonical_json([[p, h] for p, h in body]))


def path_refusal(path: str) -> str:
    """Why ``path`` cannot hold a held-out test, or ``""``: a relative path inside the
    repository, no ``..`` part, no leading ``/``."""
    p = (path or "").strip()
    if not p:
        return "a held-out test names its file"
    if p.startswith("/") or "\\" in p:
        return f"{p!r} is not a relative path inside the repository"
    norm = posixpath.normpath(p)
    if norm != p or norm.startswith("..") or "/../" in f"/{norm}/":
        return f"{p!r} is not a plain relative path (no '..', no './')"
    return ""


@dataclass(frozen=True)
class HeldOutTests:
    """One second person's held-out acceptance tests for one calibration grant."""

    repo: str
    item_id: str
    grant: str
    files: tuple[tuple[str, str], ...]
    author: str
    written_at: str
    capability_class: str = ""
    size: str = ""
    language: str = ""
    schema: str = SCHEMA
    sha256: str = ""
    record_id: str = ""

    def __post_init__(self) -> None:
        files = tuple(sorted((str(p), str(c)) for p, c in self.files))
        object.__setattr__(self, "files", files)
        if not self.sha256:
            object.__setattr__(self, "sha256", files_digest(files))
        if not self.record_id:
            object.__setattr__(
                self, "record_id", "hot_" + sha256_text(canonical_json(self.body()))[:24]
            )

    @property
    def paths(self) -> tuple[str, ...]:
        return tuple(p for p, _ in self.files)

    def body(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "repo": self.repo,
            "item_id": self.item_id,
            "grant": self.grant,
            "files": [[p, c] for p, c in self.files],
            "sha256": self.sha256,
            "author": self.author,
            "written_at": self.written_at,
            "capability_class": self.capability_class,
            "size": self.size,
            "language": self.language,
        }

    def to_dict(self) -> dict[str, Any]:
        """The stored record, content included — never served to a reader."""
        return {**self.body(), "record_id": self.record_id}

    def public(self) -> dict[str, Any]:
        """What a page may show: who wrote it, when, the digest and the paths — never the
        tests themselves (the builder's brief never has them, and neither does a viewer)."""
        return {
            "record_id": self.record_id,
            "item_id": self.item_id,
            "grant": self.grant,
            "author": self.author,
            "written_at": self.written_at,
            "sha256": self.sha256,
            "paths": list(self.paths),
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> HeldOutTests:
        return cls(
            repo=str(d.get("repo", "")),
            item_id=str(d.get("item_id", "")),
            grant=str(d.get("grant", "")),
            files=tuple((str(p), str(c)) for p, c in d.get("files") or ()),
            author=str(d.get("author", "")),
            written_at=str(d.get("written_at", "")),
            capability_class=str(d.get("capability_class", "")),
            size=str(d.get("size", "")),
            language=str(d.get("language", "")),
            schema=str(d.get("schema", SCHEMA)),
            sha256=str(d.get("sha256", "")),
            record_id=str(d.get("record_id", "")),
        )

    def verify(self) -> bool:
        """The stored digest and id are the ones the files and the body give."""
        fresh = replace(self, sha256="", record_id="")
        return fresh.sha256 == self.sha256 and fresh.record_id == self.record_id


def writer_refusal(
    writer: str, *, ticket_authors: Iterable[str], sponsor: str, submitter: str = ""
) -> str:
    """Why ``writer`` may not write (or have graded) held-out tests for a calibration build,
    or ``""``. The second person is never the ticket's author (who attached its failing test
    or put the ticket forward), never the approver who funded the build, and never the person
    whose run builds it — each already knows what the build is meant to pass."""
    who = person(writer)
    if not who:
        return "held-out acceptance tests name the person who wrote them"
    if any(who == person(a) for a in ticket_authors if person(a)):
        return "the ticket's author may not write its held-out acceptance tests"
    if person(sponsor) and who == person(sponsor):
        return "the approver who funded the calibration build may not write its held-out tests"
    if person(submitter) and who == person(submitter):
        return "the person whose run builds the ticket may not have written its held-out tests"
    return ""


def held_out_labels(record: HeldOutTests, result: str) -> dict[str, str]:
    """The labels of an attempt graded on ``record`` — stamped inside the row hash."""
    if result not in RESULTS:
        raise ValueError(f"held-out result {result!r} is not one of {RESULTS}")
    return {
        LABEL_ACCEPTANCE: ACCEPTANCE_HELD_OUT,
        LABEL_ACCEPTANCE_ID: record.record_id,
        LABEL_ACCEPTANCE_SHA: record.sha256,
        LABEL_ACCEPTANCE_RESULT: result,
    }


def none_labels(why: str) -> dict[str, str]:
    """The labels of an ``S2`` attempt NOT graded on held-out tests, and why."""
    return {LABEL_ACCEPTANCE: ACCEPTANCE_NONE, LABEL_ACCEPTANCE_WHY: why}


def held_out_graded(labels: Mapping[str, str]) -> bool:
    """THE rule (P-690): a row counts as graded on held-out acceptance tests only when its arm
    is ``S2`` and it carries POSITIVE evidence — ``acceptance: held_out`` with the record's
    digest and a result. A row graded only on the test its builder saw is clean almost by
    construction, so the absence of the stamp, or ``none``, never counts."""
    arm = labels.get(LABEL_CONTEXT_ARM, "")
    return (
        is_arm(arm)
        and parse_arm(arm).base == BASE_S2
        and labels.get(LABEL_ACCEPTANCE, "") == ACCEPTANCE_HELD_OUT
        and bool(labels.get(LABEL_ACCEPTANCE_SHA, ""))
        and labels.get(LABEL_ACCEPTANCE_RESULT, "") in RESULTS
    )


def held_out_result(labels: Mapping[str, str]) -> str:
    """``pass`` / ``fail`` / ``error`` for a held-out-graded row, else ``""``."""
    return labels.get(LABEL_ACCEPTANCE_RESULT, "") if held_out_graded(labels) else ""


def held_out_passes(labels: Mapping[str, str]) -> bool:
    """Whether a row's held-out tests do not stand against it: ``True`` for a row that was
    not graded on held-out tests (the rule is silent), else only for ``pass``."""
    return not held_out_graded(labels) or held_out_result(labels) == RESULT_PASS


#: The shortest line the leak check compares: shorter lines (``import pytest``) are common.
LEAK_MIN_LINE = 16


def leaked(text: str, record: HeldOutTests, *, known: str = "") -> list[str]:
    """The record's paths any of whose distinctive lines appear in ``text`` — the leak check a
    brief and a builder's tree are held to. A line is distinctive when, stripped, it is at
    least :data:`LEAK_MIN_LINE` characters and not in ``known`` (text the builder may see
    anyway: the ticket's own failing test, the repository's files — an import both tests
    share says nothing). ``[]`` means none."""
    seen = {ln.strip() for ln in known.splitlines()}
    out: list[str] = []
    for path, content in record.files:
        lines = {
            ln.strip()
            for ln in content.splitlines()
            if len(ln.strip()) >= LEAK_MIN_LINE and ln.strip() not in seen
        }
        if content.strip() and (content.strip() in text or any(ln in text for ln in lines)):
            out.append(path)
    return out


def trace_for(repo: str) -> str:
    """The event trace a repository's held-out records are written on."""
    return TRACE_PREFIX + repo


__all__ = [
    "ACCEPTANCE_HELD_OUT",
    "ACCEPTANCE_NONE",
    "EVENT_ACTION",
    "LABEL_ACCEPTANCE",
    "LABEL_ACCEPTANCE_ID",
    "LABEL_ACCEPTANCE_RESULT",
    "LABEL_ACCEPTANCE_SHA",
    "LABEL_ACCEPTANCE_WHY",
    "MAX_FILES",
    "MAX_FILE_BYTES",
    "RESULTS",
    "RESULT_ERROR",
    "RESULT_FAIL",
    "RESULT_PASS",
    "SCHEMA",
    "WHY_NOT_CALIBRATION",
    "WHY_NOT_FIRST",
    "WHY_NO_TESTS",
    "WHY_SAME_PERSON",
    "HeldOutTests",
    "files_digest",
    "held_out_graded",
    "held_out_labels",
    "held_out_passes",
    "held_out_result",
    "leaked",
    "none_labels",
    "path_refusal",
    "person",
    "trace_for",
    "writer_refusal",
]
