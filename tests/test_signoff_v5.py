"""signoff-policy.v4 and crb.signoff.v5 (ADR-0025 item 9 as ADR-0026 item 6 amends it).

Navigation
----------
What it is:   Tests for the sign-off rule of routing.v2: a sign-off only for the cell's standard
              arm, only when its registered reading delivers; the v5 record's stamps; the
              overlay lifting only a cell read on the same arm, class-set version and reading.
What it does: Refuses a sign-off on an ``S3`` ceiling, on an arm whose look is pending and on a
              leaner-than-standard arm; writes one on the standard arm and stamps the context
              arm, the class-set version and the reading's id under its row hash; shows the
              record lifting its own cell and no cell of another arm, version or reading; and
              keeps a v4 record verifying under its frozen body.
How:          Sealed 2.4 rows and a registered reading from ``tests.fixtures.readings``, routed
              by the capability map, signed through ``JsonlSignoffLedger``.
Layer:        tests — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0025-routing-v2.md (item 9), docs/adr/0026-the-context-standard.md
Works with:   src/crb/core/signoff.py (the policy and the v5 record under test),
              src/crb/core/capability.py (the cells a sign-off is written against),
              tests/fixtures/readings.py (the proven reading the cells are read on)
Tested by:    this file
Touch when:   the sign-off policy or record version moves.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from crb.core import signoff as so
from crb.core.capability import (
    PROJECTION_CLASS_SIZE,
    TIER_HUMAN_VERIFIED,
    CapabilityCell,
    ReadingBook,
    build_capability_map,
)
from crb.core.context_arm import rows_for_context_arm
from crb.core.ledger import GradeRow
from crb.core.reading import Reading
from crb.core.routing import ControlsVerdict
from fixtures.readings import REPO, S1, commits, register_reading, rows_for, sealed_row

PASSED = ControlsVerdict(
    passed=True, constructible=6, total=7, escapes=0, run_id="ctl-1", apparatus_version="2.4"
)


def _cell(arm: str, rows: list[GradeRow], readings: list[Reading]) -> CapabilityCell:
    cmap = build_capability_map(
        rows_for_context_arm(rows, arm),
        projection=PROJECTION_CLASS_SIZE,
        controls=PASSED,
        oracle_by_task={r.task_id: 0.9 for r in rows},
        readings=ReadingBook.evaluate(readings, rows),
    )
    return cmap.get(capability_class="bug.fix", size="XS")


def _proven(prefix: str = "p") -> tuple[Reading, list[GradeRow]]:
    reading = register_reading(commits(40, prefix))
    rows = [*rows_for([True] * 20, reading.pool), *rows_for([True] * 20, reading.pool, arm=S1)]
    return reading, rows


def _record(cell: CapabilityCell) -> so.SignoffRecord:
    del cell  # the scope is the cell's class and size; the evidence is stamped at write
    return so.SignoffRecord(
        repo=REPO,
        capability_class="bug.fix",
        size="XS",
        verifier="bob",
        verifier_kind="local",
        attestation=so.Attestation(
            reviewed_task_id="a" * 40,
            reviewed_row_hash="c" * 64,
            statement="I read the accepted diff and it does what the ticket asks.",
        ),
    )


def _codes(cell: CapabilityCell) -> list[str]:
    return [r.code for r in so.evaluate_signoff(_record(cell), cell, repo=REPO)]


def test_a_sign_off_is_refused_unless_the_standard_arms_reading_delivers(tmp_path: Path) -> None:
    reading, rows = _proven()
    assert "not_standard:ceiling" in _codes(_cell("S3", rows, [reading]))
    pending = register_reading(commits(40, "q"))
    pend_rows = [*rows_for([True] * 20, pending.pool), *rows_for([True] * 10, pending.pool, arm=S1)]
    assert so.REFUSAL_LOOK_PENDING in _codes(_cell(S1, pend_rows, [pending]))
    unregistered = [sealed_row(c, arm=S1) for c in commits(25, "u")]
    assert "not_standard:reading_unregistered" in _codes(_cell(S1, unregistered, []))
    for refused in ("not_standard:ceiling", so.REFUSAL_LOOK_PENDING):
        assert not so.SignoffRefusal(refused, "x").overridable
    standard = _cell(S1, rows, [reading])
    assert so.evaluate_signoff(_record(standard), standard, repo=REPO) == ()
    written = so.JsonlSignoffLedger(tmp_path / "s.jsonl").append(
        _record(standard), standard, repo=REPO, controls=PASSED
    )
    assert written.schema == "crb.signoff.v5" and written.verify_hash()
    assert (written.context_arm, written.taxonomy) == (S1, "global/classes@v1")
    assert written.reading_id == reading.reading_id and written.n_tasks_at_signoff == 20
    assert written.controls_apparatus == "2.4"
    # the stamps are hashed: another arm under the same hash no longer verifies
    assert not replace(written, context_arm="S3").verify_hash()
    assert not replace(written, reading_id="rdg_other").verify_hash()
    assert not replace(written, taxonomy="acme/classes@v1").verify_hash()


def test_a_sign_off_lifts_only_the_arm_and_class_set_version_it_was_signed_on(
    tmp_path: Path,
) -> None:
    reading, rows = _proven()
    standard = _cell(S1, rows, [reading])
    record = so.JsonlSignoffLedger(tmp_path / "s.jsonl").append(
        _record(standard), standard, repo=REPO, controls=PASSED
    )
    lifted = so.apply_signoffs([standard], [record], repo=REPO)[0]
    assert lifted.verification_tier == TIER_HUMAN_VERIFIED
    # another arm of the same scope: the S3 ceiling is never lifted by the S1 sign-off
    s3 = _cell("S3", rows, [reading])
    assert so.apply_signoffs([s3], [record], repo=REPO)[0].verification_tier != (
        TIER_HUMAN_VERIFIED
    )
    assert record.is_stale(s3)
    # another class-set version of the same arm: nothing lifts
    other_rows = [
        sealed_row(r.task_id, arm=S1, labels={"taxonomy": "acme/classes@v1"})
        for r in rows
        if r.context_arm == S1
    ]
    other_version = _cell(S1, other_rows, [])
    assert so.apply_signoffs([other_version], [record], repo=REPO)[0].verification_tier != (
        TIER_HUMAN_VERIFIED
    )
    # another reading of the same arm and version (a later one speaks for the cell): stale
    later = register_reading(commits(40, "z"), existing=[reading], now="2026-09-27T10:30:00+00:00")
    later_rows = [
        *rows,
        *rows_for([True] * 20, later.pool, created="2026-09-27T12:00:00+00:00"),
        *rows_for([True] * 20, later.pool, arm=S1, created="2026-09-27T12:00:00+00:00"),
    ]
    relit = _cell(S1, later_rows, [reading, later])
    assert relit.decision is not None and relit.decision.reading_id == later.reading_id
    assert record.is_stale(relit)
    assert so.apply_signoffs([relit], [record], repo=REPO)[0].verification_tier != (
        TIER_HUMAN_VERIFIED
    )


def test_a_v4_record_keeps_verifying_under_its_frozen_body() -> None:
    v4 = so.SignoffRecord(
        repo=REPO,
        capability_class="bug.fix",
        verifier="bob",
        checks_arm="off",
        posture_class="docker/copy/sealed",
        schema="crb.signoff.v4",
    ).chained("0" * 64)
    assert v4.verify_hash()
    assert set(v4.body()) == set(so._V4_BODY_FIELDS)
    assert "reading_id" not in v4.body()


def test_the_policy_is_signoff_policy_v4() -> None:
    assert so.SIGNOFF_POLICY_VERSION == "signoff-policy.v4"
    assert so.SIGNOFF_SCHEMA == "crb.signoff.v5"
    with pytest.raises(ValueError):
        so.SignoffRefusal("not_a_code", "x")


def test_the_ui_names_the_signoff_policy_the_server_writes() -> None:
    """P-130: the Sign-off and Posture screens read the policy version from ONE UI constant
    (the served ``policy_version`` replaces it once the preview answers), and that constant is
    the one the server writes — a bump that forgets the UI fails here, not in a walkthrough."""
    import re

    ui = Path(__file__).resolve().parent.parent / "ui" / "src" / "screens"
    contract = (ui / "Signoff" / "contract.ts").read_text(encoding="utf-8")
    m = re.search(r"export const SIGNOFF_POLICY_VERSION = '([^']+)'", contract)
    assert m and m.group(1) == so.SIGNOFF_POLICY_VERSION
    for screen in (ui / "Posture" / "PosturePage.tsx", ui / "Signoff" / "SignoffPage.tsx"):
        assert not re.search(r"signoff-policy\.v\d", screen.read_text(encoding="utf-8")), screen
