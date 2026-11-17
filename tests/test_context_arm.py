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
ADRs:         docs/adr/0026-the-context-standard.md (item 1), docs/adr/0025-routing-v2.md,
              docs/adr/0054-accepted-plan-context-arm.md (the ``ctx.plan*`` arm)
Works with:   src/crb/core/context_arm.py (the grammar and ``context_arm_for``),
              src/crb/core/ledger.py (the hashed stamp and ``ContextArmsPooled``),
              tests/fixtures/posture.py (the 2.4 rows the tests build)
Tested by:    this file
Touch when:   never for a new repository; an arm base or modifier is added (an ADR amending ADR-0026
              item 1 first).
"""

from __future__ import annotations

from typing import Any

import pytest

from crb.core.context_arm import (
    CTX_NAME_RE,
    LABEL_CONTEXT_ARM,
    LABEL_CTX_CEILING,
    LABEL_CTX_CHARS,
    LABEL_CTX_DELIVERED,
    LABEL_CTX_GAP,
    LABEL_CTX_GAP_RULE,
    LABEL_CTX_SET,
    LABEL_CTX_SOURCE,
    PROVENANCE_LABELS,
    TEST_AUTHORED,
    TEST_PERSON,
    ContextArmsPooled,
    audited_plan_arm,
    context_arm_for,
    ctx_set_name,
    hindsight_arm,
    is_arm,
    measurement_only,
    parse_arm,
    plan_arm,
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


# --- the context-set arms (ADR-0050) -------------------------------------------------

HEX = "0123456789ab"
CTX_ARMS = [
    f"A0+library@ctx.oracle.{HEX}",
    f"A0+library@ctx.oracle-placebo.{HEX}",
    f"A0+library@ctx.mech.{HEX}",
    f"A0+library@ctx.mech-placebo.{HEX}",
    f"A0+library@ctx.plan.{HEX}",
    f"A0+library@ctx.plan-audited.{HEX}",
]
PRE_EXISTING_ARMS = [
    "A0",
    "A0+L",
    "S1@claude-sonnet-5",
    "S1@claude-sonnet-5+facts@gpt-oss-120b",
    "S1@claude-sonnet-5+library@v3",
    "S1@claude-sonnet-5+facts@x+library@v1+L",
    "S2",
    "S3",
    "S3+L",
    "A0+library@v1",
    "A0+library@ctx",
    "A0+library@ctxfoo",
]
#: Malformed names inside the reserved ``ctx.`` namespace: outside the grammar, so none can
#: parse as an ordinary, certifying library arm (ADR-0050 item 2).
MALFORMED_CTX_ARMS = [
    "A0+library@ctx.other.0123456789ab",
    "A0+library@ctx.oracle.0123456789AB",
    "A0+library@ctx.oracle.0123456789a",
    "A0+library@ctx.oracle.invalid",
    "S1@claude-sonnet-5+library@ctx.oracle.invalid",
    f"A0+library@ctx.mech.{HEX}0",
    f"A0+library@ctx.plan-placebo.{HEX}",
    f"A0+library@ctx.plan.{HEX}0",
    f"A0+library@ctx.plan-audited-placebo.{HEX}",
    f"A0+library@ctx.plan-audited.{HEX}0",
]


@pytest.mark.parametrize("arm", CTX_ARMS)
def test_every_context_set_arm_parses_under_the_unchanged_grammar(arm: str) -> None:
    assert is_arm(arm) and parse_arm(arm).id == arm
    name = ctx_set_name(arm)
    assert name == arm.removeprefix("A0+library@") and CTX_NAME_RE.match(name)
    assert measurement_only(arm)


def test_hindsight_is_the_oracle_set_and_its_placebo_never_a_mechanical_one() -> None:
    assert hindsight_arm(f"A0+library@ctx.oracle.{HEX}")
    assert hindsight_arm(f"A0+library@ctx.oracle-placebo.{HEX}")
    assert not hindsight_arm(f"A0+library@ctx.mech.{HEX}")
    assert not hindsight_arm(f"A0+library@ctx.mech-placebo.{HEX}")


def test_plan_arm_is_the_accepted_plan_set_only() -> None:
    assert plan_arm(f"A0+library@ctx.plan.{HEX}")
    for arm in CTX_ARMS[:4]:
        assert not plan_arm(arm)
    assert not hindsight_arm(f"A0+library@ctx.plan.{HEX}")
    for arm in (*PRE_EXISTING_ARMS, "", "not an arm", f"A0+library@ctx.plan-placebo.{HEX}"):
        assert not plan_arm(arm)


def test_audited_plan_arm_is_the_plan_audited_set_only_and_a_plan_arm() -> None:
    arm = f"A0+library@ctx.plan-audited.{HEX}"
    assert audited_plan_arm(arm) and plan_arm(arm) and measurement_only(arm)
    assert not hindsight_arm(arm)
    assert ctx_set_name(arm) == f"ctx.plan-audited.{HEX}"
    for other in (*CTX_ARMS[:5], *PRE_EXISTING_ARMS, *MALFORMED_CTX_ARMS, ""):
        assert not audited_plan_arm(other), other


def test_a_plan_arm_is_measurement_only() -> None:
    arm = f"A0+library@ctx.plan.{HEX}"
    assert measurement_only(arm)
    assert ctx_set_name(arm) == f"ctx.plan.{HEX}"


@pytest.mark.parametrize("arm", MALFORMED_CTX_ARMS)
def test_a_malformed_name_in_the_reserved_ctx_namespace_is_outside_the_grammar(
    arm: str,
) -> None:
    assert not is_arm(arm)
    with pytest.raises(ValueError):
        parse_arm(arm)
    assert ctx_set_name(arm) == "" and not measurement_only(arm)


@pytest.mark.parametrize("arm", [*PRE_EXISTING_ARMS, "", "not an arm"])
def test_no_pre_existing_arm_is_a_context_set_arm(arm: str) -> None:
    assert ctx_set_name(arm) == ""
    assert not measurement_only(arm) and not hindsight_arm(arm)


def test_the_context_set_stamps_are_provenance_never_the_arm() -> None:
    for label in (LABEL_CTX_SET, LABEL_CTX_SOURCE, LABEL_CTX_GAP, LABEL_CTX_GAP_RULE):
        assert label in PROVENANCE_LABELS
    for label in (LABEL_CTX_DELIVERED, LABEL_CTX_CHARS, LABEL_CTX_CEILING, "ctx_drafter"):
        assert label in PROVENANCE_LABELS
    for name in ("drafter", "saw", "accepted", "refused", "novel"):
        assert f"ctx_plan_{name}" in PROVENANCE_LABELS
    for name in ("guard", "would_refuse", "audit", "auditor"):  # ADR-0055
        assert f"ctx_plan_{name}" in PROVENANCE_LABELS
    assert LABEL_CONTEXT_ARM not in PROVENANCE_LABELS


def _ctx_labels(arm: str, source: str) -> dict[str, str]:
    return {
        LABEL_CONTEXT_ARM: arm,
        LABEL_CTX_SET: HEX + "f" * 52,
        LABEL_CTX_SOURCE: source,
        LABEL_CTX_GAP: "0",
        LABEL_CTX_GAP_RULE: "anchor.v1",
        LABEL_CTX_DELIVERED: "1",
        LABEL_CTX_CHARS: "40",
        LABEL_CTX_CEILING: "1",
    }


def test_a_treatment_and_its_placebo_never_pool_in_one_cell() -> None:
    oracle, placebo = CTX_ARMS[0], CTX_ARMS[1]
    treated = [_row(f"t{i}", mode="blind", labels=_ctx_labels(oracle, "oracle")) for i in range(2)]
    sham = [
        _row(f"p{i}", mode="blind", labels=_ctx_labels(placebo, "oracle-placebo")) for i in range(2)
    ]
    assert {r.context_arm for r in treated} == {oracle}
    with pytest.raises(ContextArmsPooled):
        cell_stats([*treated, *sham])
    assert cell_stats(rows_for_context_arm([*treated, *sham], placebo)).n == 2
