"""The context arm (ADR-0026 item 1): one grammar, one decision helper, never a pooled cell.

Navigation
----------
What it is:   Tests for ``crb.core.context_arm`` and the arm stamp the ledger writes on every
              row of apparatus 2.4 or later.
What it does: Pins the grammar (bases, modifiers in order, the author on ``S1``);
              ``context_arm_for``'s decisions (blind replay ``A0``, sighted replay ``S3``,
              ``+L`` with the loop on, an authored test ``S1@<author>``, a person's test
              ``S2``); the hashed stamp on a 2.4 row and the ledger's refusal of a row without
              one; and ``cell_stats`` refusing rows of two arms — two test authors, and the
              loop on and off, are two arms.
How:          Rows built with ``tests.fixtures.posture.posture_row`` at apparatus 2.4 and
              grades through ``grade_row_from_result``; no model, no docker.
Layer:        tests — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0026-the-context-standard.md (item 1), docs/adr/0025-routing-v2.md
Works with:   src/crb/core/context_arm.py (the grammar and ``context_arm_for``),
              src/crb/core/ledger.py (the hashed stamp and ``ContextArmsPooled``),
              tests/fixtures/posture.py (the 2.4 rows the tests build)
Tested by:    this file
Touch when:   an arm base or modifier is added (an ADR amending ADR-0026 item 1 first).
"""

from __future__ import annotations

from typing import Any

import pytest

from crb.core.context_arm import (
    LABEL_CONTEXT_ARM,
    TEST_AUTHORED,
    TEST_PERSON,
    ContextArmsPooled,
    context_arm_for,
    is_arm,
    parse_arm,
    rows_for_context_arm,
)
from crb.core.grade import Belts, GradeResult
from crb.core.ledger import (
    GradeRow,
    LedgerIntegrityError,
    cell_stats,
    grade_row_from_result,
)
from crb.core.spec import TaskSpec
from crb.core.taxonomy import GLOBAL_CLASS_SET, LABEL_TAXONOMY
from fixtures.posture import posture_result, posture_row

V24 = "2.4"


def _row(task: str, *, clean: bool = True, **kw: Any) -> GradeRow:
    belts = {"tests_unmodified": True, "target_green": clean, "no_new_failures": True}
    return posture_row(
        repo="r",
        task_id=task,
        clean=clean,
        source_changed=True,
        repo_lint_clean=None,
        capability_class="bug.fix",
        size="S",
        language="python",
        builder="b",
        model="m",
        provider="p",
        evidence_pack_hash="h" * 64 if clean else "",
        apparatus_version=V24,
        **belts,
        **kw,
    )


# --- the grammar -------------------------------------------------------------


@pytest.mark.parametrize(
    "arm",
    [
        "A0",
        "A0+L",
        "S1@claude-sonnet-5",
        "S1@claude-sonnet-5+facts@gpt-oss-120b",
        "S1@claude-sonnet-5+library@v3",
        "S1@claude-sonnet-5+facts@x+library@v1+L",
        "S2",
        "S3",
        "S3+L",
    ],
)
def test_every_arm_adr_0026_names_is_inside_the_grammar(arm: str) -> None:
    assert is_arm(arm)
    assert parse_arm(arm).id == arm


@pytest.mark.parametrize(
    "arm",
    ["", "S1", "S4", "A0@x", "S3+L+facts@x", "S1@a+library@v1+facts@x", "sighted", "S2@x"],
)
def test_an_arm_outside_the_grammar_is_refused(arm: str) -> None:
    assert not is_arm(arm)
    with pytest.raises(ValueError):
        parse_arm(arm)


def test_only_the_s1_family_and_s2_certify_s3_is_a_ceiling_and_a0_is_descriptive() -> None:
    assert parse_arm("S1@m").certifies and parse_arm("S2").certifies
    assert parse_arm("S3").ceiling and not parse_arm("S3").certifies
    assert parse_arm("A0+L").descriptive and not parse_arm("A0").certifies


# --- the one decision helper --------------------------------------------------


def test_context_arm_for_decides_a_replay_and_a_factory_row_from_what_its_brief_carried() -> None:
    assert context_arm_for(process_step="replay", mode="blind") == "A0"
    assert context_arm_for(process_step="replay", mode="blind", loop=True) == "A0+L"
    assert context_arm_for(process_step="replay", mode="sighted") == "S3"
    assert context_arm_for(process_step="replay", mode="sighted", loop=True) == "S3+L"
    authored = context_arm_for(
        process_step="factory", mode="sighted", test_source=TEST_AUTHORED, test_author="m-1"
    )
    assert authored == "S1@m-1"
    assert context_arm_for(process_step="factory", mode="sighted", test_source=TEST_PERSON) == "S2"
    with pytest.raises(ValueError, match="names whose failing test"):
        context_arm_for(process_step="factory", mode="sighted")


# --- the stamp ------------------------------------------------------------------


def _task() -> TaskSpec:
    return TaskSpec(
        task_id="a" * 40,
        repo="r",
        subject="fix",
        authored="2026-01-01T00:00:00+00:00",
        test_files=("tests/test_x.py",),
        src_files=("x.py",),
        target_tests=("tests/test_x.py",),
        belt_scope=("tests/",),
        capability_class="bug.fix",
        size="S",
        language="python",
        gold_clean=True,
        labels={"change_id": "c" * 40},
    )


@pytest.mark.parametrize(
    ("mode", "labels", "want"),
    [
        ("sighted", {}, "S3"),
        ("blind", {}, "A0"),
        ("sighted", {"learn": "context"}, "S3+L"),
        ("blind", {"learn": "off"}, "A0"),
    ],
)
def test_a_24_row_stamps_its_context_arm_and_class_set_inside_its_hash(
    mode: str, labels: dict[str, str], want: str
) -> None:
    belts = Belts(True, True, True, True, None)
    result = posture_result("a" * 40, "r", mode, True, belts)
    row = grade_row_from_result(
        result, _task(), pack_hash="h" * 64, labels=labels, apparatus_version=V24
    )
    assert row.labels[LABEL_CONTEXT_ARM] == want and row.context_arm == want
    assert row.labels[LABEL_TAXONOMY] == GLOBAL_CLASS_SET and row.taxonomy == GLOBAL_CLASS_SET
    chained = row.chained("0" * 64)
    assert chained.verify_hash()
    # the stamp is hashed: another arm is another row hash
    forged = GradeRow(**{**chained.fields(), "labels": {**chained.labels, "context_arm": "S1@x"}})
    object.__setattr__(forged, "row_hash", chained.row_hash)
    assert not forged.verify_hash()


def test_a_23_row_is_written_as_it_always_was_with_no_arm_or_class_set() -> None:
    belts = Belts(True, True, True, True, None)
    result = GradeResult(
        "a" * 40,
        "r",
        "sighted",
        True,
        belts,
        posture_id="pst_" + "5" * 24,
        posture_class="local/inplace/host-env",
        qualification_id="q",
        lint_status="none_detected",
    )
    row = grade_row_from_result(
        result, _task(), pack_hash="h" * 64, labels={"context_arm": "S3"}, apparatus_version="2.3"
    )
    assert LABEL_CONTEXT_ARM not in row.labels and LABEL_TAXONOMY not in row.labels
    assert row.context_arm == "" and row.taxonomy == ""


def test_the_ledger_refuses_a_24_row_without_its_arm_or_class_set() -> None:
    with pytest.raises(LedgerIntegrityError, match="context_arm"):
        _row("a", labels={"context_arm": "sighted"})
    with pytest.raises(LedgerIntegrityError, match="taxonomy"):
        _row("a", labels={"taxonomy": "classes"})
    with pytest.raises(LedgerIntegrityError, match="S2 is a factory arm only"):
        _row("a", labels={"context_arm": "S2"})


# --- the pooling refusal -----------------------------------------------------------


def test_rows_of_two_context_arms_never_pool() -> None:
    s3 = [_row(f"s{i}") for i in range(3)]
    a0 = [_row(f"b{i}", mode="blind") for i in range(3)]
    assert {r.context_arm for r in s3} == {"S3"} and {r.context_arm for r in a0} == {"A0"}
    with pytest.raises(ContextArmsPooled, match="context arm"):
        cell_stats([*s3, *a0])
    assert cell_stats(rows_for_context_arm([*s3, *a0], "S3")).context_arm == "S3"
    assert cell_stats(a0).n == 3


def test_rows_of_two_test_authors_never_pool() -> None:
    one = [_row(f"x{i}", labels={"context_arm": "S1@claude-sonnet-5"}) for i in range(2)]
    two = [_row(f"y{i}", labels={"context_arm": "S1@gpt-oss-120b"}) for i in range(2)]
    with pytest.raises(ContextArmsPooled):
        cell_stats([*one, *two])
    assert cell_stats(one).context_arm == "S1@claude-sonnet-5"


def test_the_loop_on_and_off_are_two_arms_of_one_cell() -> None:
    off = [_row(f"o{i}", labels={"learn": "off"}) for i in range(2)]
    on = [_row(f"n{i}", labels={"learn": "context"}) for i in range(2)]
    assert {r.context_arm for r in off} == {"S3"} and {r.context_arm for r in on} == {"S3+L"}
    with pytest.raises(ContextArmsPooled):
        cell_stats([*off, *on])
