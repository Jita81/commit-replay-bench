"""A calibration build graded on a second person's held-out acceptance tests (ADR-0026 item 8).

Navigation
----------
What it is:   The factory suite for G-679 (``product.truth.215``): the calibration-build path
              that turns a build's first attempt into an ``S2`` row a forward reading counts.
What it does: Pins, on the real loop over the fixture repository, that a calibration build
              on a ceiling cell whose grant carries a second person's held-out tests is graded
              on them after the builder finishes — its FIRST attempt stamped ``context_arm: S2``
              and ``acceptance: held_out`` with the record's id, digest and result inside the
              row hash, ``acceptance.graded`` on the chain — and never opens a pull request;
              that the tests never reach the brief, the builder's tree while it works, the kept
              tree, the evidence chain or the grade ledger (the leak test); that a later attempt
              (the next rung, a rework, a second run of the ticket) is never graded on them; that
              the ticket's author, the funding approver and the run's submitter may not have
              written them; that tests written after the build was claimed are not used; and that
              the row the loop writes is the row a forward reading counts (P-690).
How:          ``tests/test_factory_loop.py``'s rig with an ``S3`` ceiling as the gate's reader
              and ``FactorySpec.held_out`` returning a record; a spying builder that reads its
              brief and every file of its tree while it builds.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0026-the-context-standard.md (items 1, 2 and 8)
Works with:   src/crb/factory/loop.py (``_held_out``, ``run_item``), src/crb/factory/build.py
              (``run_held_out``), src/crb/core/acceptance.py (the record, the stamp, the leak
              check), src/crb/core/reading.py (the forward reading that counts the row),
              tests/test_factory_loop.py (the rig)
Tested by:    this file
Touch when:   never for a new repository; the calibration-build path or the held-out stamp
              changes.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from crb.builders.base import BuildBrief, BuildOutcome, Rung
from crb.core.acceptance import (
    ACCEPTANCE_HELD_OUT,
    ACCEPTANCE_NONE,
    LABEL_ACCEPTANCE,
    LABEL_ACCEPTANCE_RESULT,
    LABEL_ACCEPTANCE_SHA,
    LABEL_ACCEPTANCE_WHY,
    RESULT_FAIL,
    RESULT_PASS,
    WHY_NO_TESTS,
    WHY_NOT_FIRST,
    WHY_SAME_PERSON,
    HeldOutTests,
    held_out_graded,
    leaked,
)
from crb.core.ledger import GradeRow, first_attempts
from crb.core.reading import (
    STATE_LOOK_PENDING,
    ReadingOutcome,
    arm_reading,
    register_forward,
    with_enrolment,
)
from crb.core.workspace import Workspace
from crb.factory import evidence as fe
from crb.factory import loop as fl
from crb.factory.standard import Readers, Standard
from fixtures import pyrepo as pr
from test_factory_build import OPERATOR, authored_multiply, multiply_item
from test_factory_loop import MultiBuilder, _creds, _rig

HELD_OUT_PATH = "tests/test_multiply_held_out.py"
HELD_OUT_PASSES = (
    "from calc import multiply\n\n\n"
    "def test_multiply_is_commutative_for_the_held_out_cases():\n"
    "    assert multiply(7, 6) == multiply(6, 7) == 42\n"
)
HELD_OUT_FAILS = (
    "from calc import multiply\n\n\n"
    "def test_multiply_rounds_the_held_out_case_up_to_the_answer():\n"
    "    assert multiply(7, 6) == 43\n"
)
#: Long before any claim: written, then the approver funded, then a run claimed the grant.
EARLY = "2026-01-01T00:00:00+00:00"
SECOND_PERSON = "operator:bea"
APPROVER = "approver:ada"


def _ceiling_readers() -> Readers:
    return Readers(standard_for=lambda cell: Standard("S3"), agreement_passed=False)


def _reader(
    content: str = HELD_OUT_PASSES, *, author: str = SECOND_PERSON, written_at: str = EARLY
) -> Any:
    """``FactorySpec.held_out``: the record for whatever grant the run claimed."""

    def read(item_id: str, grant: str) -> HeldOutTests:
        return HeldOutTests(
            repo="pyrepo",
            item_id=item_id,
            grant=grant,
            files=((HELD_OUT_PATH, content),),
            author=author,
            written_at=written_at,
            capability_class="bug.fix",
            size="XS",
            language="python",
        )

    return read


def _calibrate(rig: Any) -> fe.FactoryEvent:
    return rig.evidence.record_calibration("I-1", approver=APPROVER, reason="the forward reading")


@dataclass
class SpyBuilder(MultiBuilder):
    """The fake builder, recording its brief and every file of its tree while it builds."""

    seen_briefs: list[str] = field(default_factory=list)
    seen_trees: list[str] = field(default_factory=list)

    def build(
        self, workspace: Workspace, brief: BuildBrief, budget: Any, *, on_event: Any = None
    ) -> BuildOutcome:
        self.seen_briefs.append(json.dumps(brief.to_dict(), sort_keys=True))
        texts = []
        for p in sorted(workspace.root.rglob("*")):
            if p.is_file() and ".git" not in p.parts:
                try:
                    texts.append(p.read_text(encoding="utf-8"))
                except UnicodeDecodeError:
                    continue
        self.seen_trees.append("\n".join(texts))
        return super().build(workspace, brief, budget, on_event=on_event)


# --- the first attempt is an S2 row ----------------------------------------------------------


def test_a_calibration_builds_first_attempt_is_graded_on_held_out_tests_and_stamped_s2(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    rig = _rig(
        pyrepo,
        tmp_path,
        readers=_ceiling_readers(),
        held_out=_reader(),
        deliver=True,
        creds=_creds(),
    )
    grant = _calibrate(rig)
    out = rig.loop().run_item(multiply_item(), authored=authored_multiply())
    assert out.status == fl.STATUS_CALIBRATION_BUILD, out.error
    # a calibration build never opens a pull request and is never a delivery
    assert out.delivery is None and not rig.pushes and not rig.prs
    (row,) = list(rig.ledger.rows())
    record = _reader()("I-1", grant.event_id)
    assert row.context_arm == "S2" and row.labels["calibration"] == "true"
    assert row.labels[LABEL_ACCEPTANCE] == ACCEPTANCE_HELD_OUT
    assert row.labels[LABEL_ACCEPTANCE_SHA] == record.sha256
    assert row.labels[LABEL_ACCEPTANCE_RESULT] == RESULT_PASS
    assert LABEL_ACCEPTANCE_WHY not in row.labels
    assert held_out_graded(row.labels) and row.clean
    # the stamp is inside the row hash, at write: change it and the row no longer verifies
    rig.ledger.verify()
    forged = GradeRow.from_dict(
        {**row.to_dict(), "labels": {**row.labels, LABEL_ACCEPTANCE_RESULT: RESULT_FAIL}}
    )
    assert not forged.verify_hash()
    (graded,) = rig.evidence.events_for("I-1", fe.EV_ACCEPTANCE_GRADED)
    assert graded.payload["result"] == RESULT_PASS
    assert graded.payload["row_hash"] == row.row_hash
    assert graded.payload["grant"] == grant.event_id
    assert graded.payload["author"] == SECOND_PERSON


def test_held_out_tests_the_build_does_not_pass_make_its_first_attempt_a_miss(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    rig = _rig(pyrepo, tmp_path, readers=_ceiling_readers(), held_out=_reader(HELD_OUT_FAILS))
    _calibrate(rig)
    out = rig.loop().run_item(multiply_item(), authored=authored_multiply())
    assert out.status == fl.STATUS_CALIBRATION_BUILD
    (row,) = list(rig.ledger.rows())
    # the build passed the ticket's own failing test; the second person's tests say otherwise
    assert row.clean and row.labels[LABEL_ACCEPTANCE_RESULT] == RESULT_FAIL
    (fa,) = first_attempts([row])
    assert fa.gold_checked and not fa.clean


# --- the leak test ----------------------------------------------------------------------


def test_the_held_out_tests_never_reach_the_brief_or_any_builder_visible_path(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    builder = SpyBuilder()
    rig = _rig(pyrepo, tmp_path, readers=_ceiling_readers(), held_out=_reader(), builder=builder)
    grant = _calibrate(rig)
    out = rig.loop().run_item(multiply_item(), authored=authored_multiply())
    assert out.status == fl.STATUS_CALIBRATION_BUILD
    record = _reader()("I-1", grant.event_id)
    assert builder.seen_briefs and builder.seen_trees
    # an import both tests share says nothing: only the held-out tests' own lines count
    known = authored_multiply().content
    for text in (*builder.seen_briefs, *builder.seen_trees):
        assert leaked(text, record, known=known) == []
    # the check is real: it finds the tests where they are
    assert leaked(HELD_OUT_PASSES, record, known=known) == [HELD_OUT_PATH]
    # nothing the run writes carries them: the grade ledger, the chain, the evidence packs
    for f in (tmp_path / "grades.jsonl", tmp_path / "evidence.jsonl"):
        assert leaked(f.read_text(encoding="utf-8"), record, known=known) == []
    for pack in (tmp_path / "packs").rglob("*"):
        if pack.is_file():
            text = pack.read_text(encoding="utf-8", errors="ignore")
            assert leaked(text, record, known=known) == []
    # and the built tree is left as the builder left it
    for tree in (tmp_path / "scratch").rglob(Path(HELD_OUT_PATH).name):
        raise AssertionError(f"held-out test left in a tree: {tree}")


# --- a later attempt is never S2 ------------------------------------------------------------


def test_only_the_first_rung_is_graded_on_the_held_out_tests(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    """The first rung misbehaves; the second rung's clean build is a LATER attempt — graded on
    the ticket's own test only and stamped ``acceptance: none`` (``not_first_attempt``)."""
    builder = MultiBuilder(first_edit="\n\ndef multiply(a: int, b: int) -> int:\n    return 0\n")
    rig = _rig(
        pyrepo,
        tmp_path,
        readers=_ceiling_readers(),
        held_out=_reader(),
        builder=builder,
        ladder=(Rung("fake", "multi"), Rung("fake", "multi-2")),
    )
    _calibrate(rig)
    out = rig.loop().run_item(multiply_item(), authored=authored_multiply())
    assert out.status == fl.STATUS_CALIBRATION_BUILD, out.error
    first, second = list(rig.ledger.rows())
    assert first.trial == "r1" and held_out_graded(first.labels)
    assert first.labels[LABEL_ACCEPTANCE_RESULT] == RESULT_FAIL
    assert second.trial == "r2" and second.clean
    assert second.labels[LABEL_ACCEPTANCE] == ACCEPTANCE_NONE
    assert second.labels[LABEL_ACCEPTANCE_WHY] == WHY_NOT_FIRST
    assert not held_out_graded(second.labels)


def test_a_second_calibration_run_of_the_same_ticket_is_never_graded_on_held_out_tests(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    rig = _rig(pyrepo, tmp_path, readers=_ceiling_readers(), held_out=_reader())
    _calibrate(rig)
    rig.loop().run_item(multiply_item(), authored=authored_multiply())
    _calibrate(rig)  # a second grant, and a record for it
    again = rig.loop().run_item(multiply_item(), authored=authored_multiply())
    assert again.status == fl.STATUS_CALIBRATION_BUILD
    rows = list(rig.ledger.rows())
    assert held_out_graded(rows[0].labels) and not held_out_graded(rows[-1].labels)
    assert rows[-1].labels[LABEL_ACCEPTANCE_WHY] == WHY_NOT_FIRST


# --- the second person -----------------------------------------------------------------


def test_the_tests_are_not_used_when_written_by_the_author_the_sponsor_or_the_submitter(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    for i, author in enumerate((OPERATOR, APPROVER, "operator:tester")):
        rig = _rig(
            pyrepo,
            tmp_path / f"p{i}",
            readers=_ceiling_readers(),
            held_out=_reader(author=author),
        )
        _calibrate(rig)
        out = rig.loop().run_item(multiply_item(), authored=authored_multiply())
        assert out.status == fl.STATUS_CALIBRATION_BUILD
        (row,) = list(rig.ledger.rows())
        assert row.labels[LABEL_ACCEPTANCE] == ACCEPTANCE_NONE, author
        assert row.labels[LABEL_ACCEPTANCE_WHY] == WHY_SAME_PERSON, author
        assert rig.evidence.events_for("I-1", fe.EV_ACCEPTANCE_GRADED) == []


def test_tests_written_after_the_build_was_claimed_are_not_used(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    rig = _rig(
        pyrepo,
        tmp_path,
        readers=_ceiling_readers(),
        held_out=_reader(written_at="2099-01-01T00:00:00+00:00"),
    )
    _calibrate(rig)
    rig.loop().run_item(multiply_item(), authored=authored_multiply())
    (row,) = list(rig.ledger.rows())
    assert row.labels[LABEL_ACCEPTANCE_WHY] == WHY_NO_TESTS


def test_a_build_that_is_not_a_calibration_build_is_never_graded_on_held_out_tests(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    """An ordinary build on a proven ``S2`` standard is not a forward reading's row."""
    rig = _rig(pyrepo, tmp_path, held_out=_reader())
    out = rig.loop().run_item(multiply_item(), authored=authored_multiply())
    assert out.status == fl.STATUS_ACCEPTED
    (row,) = list(rig.ledger.rows())
    assert row.labels[LABEL_ACCEPTANCE] == ACCEPTANCE_NONE
    assert not held_out_graded(row.labels)


# --- the writer and the reader agree (P-690) ------------------------------------------------


def test_the_row_the_loop_writes_is_the_row_a_forward_reading_counts(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    """P-690: the factory's writer and the forward reading's counter spell "graded on held-out
    acceptance tests" one way — the loop's own row, not a hand-made one, is counted."""
    from crb.core.reading import Reading
    from crb.core.reading import evaluate as _evaluate
    from fixtures.readings import commits, register_reading, rows_for

    rig = _rig(pyrepo, tmp_path, readers=_ceiling_readers(), held_out=_reader())
    grant = _calibrate(rig)
    rig.loop().run_item(multiply_item(), authored=authored_multiply())
    (row,) = list(rig.ledger.rows())
    # a ceiling on the fixture's replay cell, and its forward reading on the factory's cell
    cell = {
        "process_step": "replay",
        "capability_class": "bug.fix",
        "size": "XS",
        "language": "python",
        "builder": "fake",
        "model": "multi",
        "provider": row.provider,
    }
    pool = commits(20, prefix="fx")
    reading: Reading = register_reading(
        pool, hierarchy=("S3",), repo="pyrepo", cell=cell, now="2000-01-01T00:00:00+00:00"
    )
    ceiling: ReadingOutcome = _evaluate(
        reading, rows_for([True] * 20, pool, arm="S3", repo="pyrepo", cell=cell)
    )
    fwd = register_forward(
        ceiling=ceiling,
        builder=row.builder,
        model=row.model,
        provider=row.provider,
        actor="op",
        existing=[reading],
        now="2000-01-01T00:00:01+00:00",
    )
    fwd = type(fwd).from_dict({**fwd.to_dict(), "checks_arm": row.checks_arm, "reading_id": ""})
    record = _reader()("I-1", grant.event_id)
    arm = arm_reading(with_enrolment(fwd, [record]), "S2", [row])
    assert arm.look.state == STATE_LOOK_PENDING and arm.look.counted == 1 and arm.look.clean == 1
