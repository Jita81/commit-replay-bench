"""The held-out acceptance-test record and its rules (ADR-0026 item 8).

Navigation
----------
What it is:   The unit suite of ``crb.core.acceptance``.
What it does: Pins that a record's digest covers every file and its id the whole body, so an
              edit is caught; that a path must be a plain relative path; that the second person
              is never the ticket's author, the funding approver or the run's submitter, however
              the identity is prefixed; that only POSITIVE evidence — the stamp, a digest and a
              result on an ``S2`` row — counts as held-out grading (P-690); and that the leak
              check finds a record's distinctive lines and ignores lines the builder may see.
How:          Pure calls on small records.
Layer:        tests — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0026-the-context-standard.md (item 8)
Works with:   src/crb/core/acceptance.py (under test), src/crb/core/context_arm.py (the S2
              arm the rule reads), tests/test_factory_held_out.py (the same rules on the loop's
              own rows)
Tested by:    this file
Touch when:   never for a new repository; a rule of the record changes.
"""

from __future__ import annotations

import dataclasses

import pytest

from crb.core.acceptance import (
    RESULT_FAIL,
    RESULT_PASS,
    WHY_NOT_FIRST,
    HeldOutTests,
    held_out_graded,
    held_out_labels,
    held_out_passes,
    leaked,
    none_labels,
    path_refusal,
    suggested_path,
    writer_refusal,
)
from crb.core.spec import RepoConfig

SRC = "def test_the_held_out_case_one():\n    assert compute(7, 6) == 42\n"


def _rec(**kw: object) -> HeldOutTests:
    base: dict[str, object] = {
        "repo": "cobra",
        "item_id": "T-1",
        "grant": "g1",
        "files": (("tests/test_a.py", SRC),),
        "author": "operator:bea",
        "written_at": "2026-09-28T10:00:00+00:00",
    }
    base.update(kw)
    return HeldOutTests(**base)  # type: ignore[arg-type]


def test_the_digest_covers_every_file_and_the_id_the_whole_record() -> None:
    rec = _rec()
    assert rec.verify() and len(rec.sha256) == 64 and rec.record_id.startswith("hot_")
    assert HeldOutTests.from_dict(rec.to_dict()) == rec
    other = (("tests/test_a.py", SRC + "# x\n"),)
    fresh = dataclasses.replace(rec, files=other, sha256="", record_id="")
    assert fresh.sha256 != rec.sha256 and fresh.verify()  # a fresh record re-hashes …
    assert not dataclasses.replace(rec, files=other).verify()  # … a stale digest is caught
    forged = HeldOutTests.from_dict({**rec.to_dict(), "files": [["tests/test_a.py", "x"]]})
    assert not forged.verify()  # … and so is a stored one whose files changed
    assert "files" not in rec.public() and rec.public()["paths"] == ["tests/test_a.py"]


@pytest.mark.parametrize(
    ("path", "ok"),
    [
        ("tests/test_a.py", True),
        ("", False),
        ("/etc/test_a.py", False),
        ("../test_a.py", False),
        ("tests/../../test_a.py", False),
        ("./tests/test_a.py", False),
        ("tests\\test_a.py", False),
    ],
)
def test_a_held_out_test_lives_at_a_plain_relative_path(path: str, ok: bool) -> None:
    assert (path_refusal(path) == "") is ok


def test_the_second_person_is_nobody_who_already_knows_what_the_build_must_pass() -> None:
    authors = ["operator:ann"]
    assert writer_refusal("bea", ticket_authors=authors, sponsor="approver:cat") == ""
    assert "author" in writer_refusal("ann", ticket_authors=authors, sponsor="cat")
    assert "funded" in writer_refusal("operator:cat", ticket_authors=authors, sponsor="cat")
    assert "run" in writer_refusal(
        "operator:dan", ticket_authors=authors, sponsor="cat", submitter="dan"
    )
    assert writer_refusal("", ticket_authors=authors, sponsor="cat")


def test_only_positive_evidence_counts_as_held_out_grading() -> None:
    rec = _rec()
    graded = {"context_arm": "S2", **held_out_labels(rec, RESULT_PASS)}
    assert held_out_graded(graded) and held_out_passes(graded)
    failed = {"context_arm": "S2", **held_out_labels(rec, RESULT_FAIL)}
    assert held_out_graded(failed) and not held_out_passes(failed)
    assert not held_out_graded({**graded, "context_arm": "S1@t1"})
    assert not held_out_graded({"context_arm": "S2", "acceptance": "held_out"})
    assert not held_out_graded({"context_arm": "S2", **none_labels(WHY_NOT_FIRST)})
    # a row the rule does not speak about is not held against it
    assert held_out_passes({"context_arm": "S3"})
    with pytest.raises(ValueError):
        held_out_labels(rec, "maybe")


def test_the_leak_check_finds_the_records_own_lines_and_ignores_known_ones() -> None:
    rec = _rec()
    assert leaked("nothing here", rec) == []
    assert leaked("x\n    assert compute(7, 6) == 42\n", rec) == ["tests/test_a.py"]
    known = "    assert compute(7, 6) == 42\n"
    assert leaked(known, rec, known=known) == []


@pytest.mark.parametrize(
    ("config", "expected"),
    [
        (
            {"language": "python", "test_prefix": "tests/", "ext": ".py"},
            "tests/test_i_1_held_out.py",
        ),
        ({"language": "go", "ext": ".go"}, "i_1_held_out_test.go"),
        ({"language": "rust", "ext": ".rs"}, "tests/i_1_held_out.rs"),
        (
            {"language": "jvm", "test_prefix": "src/test/java/", "ext": ".java"},
            "src/test/java/HeldOutI1Test.java",
        ),
        (
            {
                "language": "javascript",
                "test_mode": "suffix",
                "test_suffix": ".test.ts",
                "ext": ".ts",
            },
            "i_1_held_out.test.ts",
        ),
        ({"language": "python", "test_prefix": "", "ext": ".py"}, ""),
    ],
)
def test_the_suggested_path_is_one_each_layouts_runner_collects(
    config: dict[str, str], expected: str
) -> None:
    """verify_fwd_user: the page pre-filled a Python path on every repository — on a Go one,
    the default was refused and the refusal named no pattern. The suggestion is now one the
    repository's own layout rule (``RepoConfig.is_test``) accepts, or none."""
    repo = RepoConfig.from_dict("r", config)
    path = suggested_path(repo, "I-1")
    assert path == expected
    assert not path or repo.is_test(path)
