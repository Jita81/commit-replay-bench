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
from types import SimpleNamespace
from typing import Any

import pytest

from crb.builders.base import BuildBrief, BuildOutcome, Rung
from crb.core.acceptance import (
    ACCEPTANCE_HELD_OUT,
    ACCEPTANCE_NONE,
    LABEL_ACCEPTANCE,
    LABEL_ACCEPTANCE_RESULT,
    LABEL_ACCEPTANCE_SHA,
    LABEL_ACCEPTANCE_WHY,
    RESULT_ERROR,
    RESULT_FAIL,
    RESULT_PASS,
    WHY_NO_TESTS,
    WHY_NOT_FIRST,
    WHY_SAME_PERSON,
    HeldOutTests,
    held_out_graded,
    leaked,
)
from crb.core.execution import LocalExecutor, SandboxUnavailable
from crb.core.ledger import GradeRow, first_attempts
from crb.core.reading import (
    STATE_LOOK_PENDING,
    ReadingOutcome,
    arm_reading,
    register_forward,
    with_enrolment,
)
from crb.core.runners import base as runners
from crb.core.workspace import Workspace
from crb.factory import evidence as fe
from crb.factory import loop as fl
from crb.factory.build import run_held_out
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


# --- attempted before, read from the claim (P-692) -------------------------------------------

WRONG_MULTIPLY = "\n\ndef multiply(a: int, b: int) -> int:\n    return 0\n"


@dataclass
class DyingBuilder(MultiBuilder):
    """Rung 1 builds a wrong multiply; on rung 2 the sandbox goes away mid-ladder."""

    def build(
        self, workspace: Workspace, brief: BuildBrief, budget: Any, *, on_event: Any = None
    ) -> BuildOutcome:
        if self.calls >= 1:
            self.calls += 1
            raise SandboxUnavailable("the sandbox went away during rung 2")
        return super().build(workspace, brief, budget, on_event=on_event)


def test_a_run_that_dies_after_its_first_rung_leaves_the_ticket_attempted(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    """verify_fwd_attack: rung 1's held-out-graded row was on the ledger while the chain had no
    build (builds were recorded after the whole ladder) — so a second grant's tests were
    accepted and its first rung, the ticket's SECOND attempt, was stamped S2. Each attempt is
    now on the chain as it is graded, and any claimed grant makes the ticket attempted."""
    two = (Rung("fake", "multi"), Rung("fake", "multi-2"))
    rig = _rig(
        pyrepo,
        tmp_path,
        readers=_ceiling_readers(),
        held_out=_reader(),
        builder=DyingBuilder(first_edit=WRONG_MULTIPLY),
        ladder=two,
    )
    _calibrate(rig)
    with pytest.raises(SandboxUnavailable):
        rig.loop().run_item(multiply_item(), authored=authored_multiply())
    (first,) = list(rig.ledger.rows())
    assert first.trial == "r1" and held_out_graded(first.labels)
    # the first rung is on the chain as soon as it is graded, not when the ladder returns
    (built,) = rig.evidence.events_for("I-1", fe.EV_BUILD)
    assert built.payload["row_hash"] == first.row_hash
    (graded,) = rig.evidence.events_for("I-1", fe.EV_ACCEPTANCE_GRADED)
    assert graded.payload["row_hash"] == first.row_hash
    # the claim alone makes the ticket attempted, whatever the chain's builds say
    events = rig.evidence.events()
    claimed = rig.evidence.events_for("I-1", fe.EV_CALIBRATION_CLAIMED)[0].payload["grant"]
    assert fe.attempted_before(events, "I-1", grant="another-grant")
    assert not fe.attempted_before(
        [e for e in events if e.kind != fe.EV_BUILD], "I-1", grant=claimed
    )
    # a second grant and its (fresh) tests: the next run's first rung is never S2 held-out
    again = _rig(pyrepo, tmp_path, readers=_ceiling_readers(), held_out=_reader())
    _calibrate(again)
    out = again.loop().run_item(multiply_item(), authored=authored_multiply())
    assert out.status == fl.STATUS_CALIBRATION_BUILD, out.error
    later = list(again.ledger.rows())[-1]
    assert later.trial == "r1" and not held_out_graded(later.labels)
    assert later.labels[LABEL_ACCEPTANCE_WHY] == WHY_NOT_FIRST


def test_a_claim_with_no_build_makes_the_ticket_attempted(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    """A run that claimed its grant and died before building anything: the ticket's next
    calibration build is still not its first attempt."""
    rig = _rig(pyrepo, tmp_path, readers=_ceiling_readers(), held_out=_reader())
    first = _calibrate(rig)
    assert rig.evidence.claim_calibration("I-1", first.event_id, run_id="died")
    _calibrate(rig)
    rig.loop().run_item(multiply_item(), authored=authored_multiply())
    (row,) = list(rig.ledger.rows())
    assert row.labels[LABEL_ACCEPTANCE_WHY] == WHY_NOT_FIRST and not held_out_graded(row.labels)


def test_a_calibration_build_not_graded_says_why_on_the_chain_before_it_is_built(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    """verify_fwd_user: an assignment read "being built" for ever when the run built without
    the tests. The loop now records ``acceptance.not_graded`` with why BEFORE the build."""
    rig = _rig(pyrepo, tmp_path, readers=_ceiling_readers(), held_out=_reader(author=APPROVER))
    grant = _calibrate(rig)
    rig.loop().run_item(multiply_item(), authored=authored_multiply())
    (refused,) = rig.evidence.events_for("I-1", fe.EV_ACCEPTANCE_NOT_GRADED)
    assert refused.payload["grant"] == grant.event_id
    assert refused.payload["why"] == WHY_SAME_PERSON
    kinds = [e.kind for e in rig.evidence.events_for("I-1")]
    assert kinds.index(fe.EV_ACCEPTANCE_NOT_GRADED) < kinds.index(fe.EV_BUILD)
    # no record at all: the same event, with its own why
    bare = _rig(pyrepo, tmp_path / "bare", readers=_ceiling_readers())
    _calibrate(bare)
    bare.loop().run_item(multiply_item(), authored=authored_multiply())
    (none,) = bare.evidence.events_for("I-1", fe.EV_ACCEPTANCE_NOT_GRADED)
    assert none.payload["why"] == WHY_NO_TESTS


# --- whoever froze or evolved the ticket (verify_fwd_evidence F7b) ---------------------------


def test_whoever_froze_or_evolved_the_ticket_may_not_have_written_its_tests(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    """The ticket's author includes whoever froze a backlog naming it and whoever registered it
    as an evolution — a person other than the one who attached its failing test."""
    for i, record in enumerate(("freeze", "evolve")):
        rig = _rig(pyrepo, tmp_path / record, readers=_ceiling_readers(), held_out=_reader())
        by_bea = fe.FactoryEvidence(rig.evidence.store, actor=SECOND_PERSON, repo="pyrepo")
        if record == "freeze":
            by_bea.record_freeze(backlog_hash="b" * 64, item_ids=["I-1"], frozen_at=EARLY)
        else:
            by_bea.record_evolution(
                item_id="I-1", supersedes="I-0", backlog_hash="b" * 64, evolutions_hash=str(i)
            )
        _calibrate(rig)
        rig.loop().run_item(multiply_item(), authored=authored_multiply())
        (row,) = list(rig.ledger.rows())
        assert row.labels[LABEL_ACCEPTANCE_WHY] == WHY_SAME_PERSON, record
        assert rig.evidence.events_for("I-1", fe.EV_ACCEPTANCE_GRADED) == []


# --- a build that hangs on the held-out cases (P-693) ----------------------------------------


@dataclass
class _Runner:
    """A runner double: the held-out run returns ``run``."""

    run: runners.TestRun

    def target_scope(self, paths: Any) -> tuple[str, ...]:
        return tuple(paths)

    def run_for(self, *_a: Any, **_kw: Any) -> runners.TestRun:
        return self.run


def _held_out_result(tmp_path: Path, run: runners.TestRun) -> str:
    rec = _reader()("I-1", "g")
    ws = SimpleNamespace(root=tmp_path)
    return run_held_out(
        ws,  # type: ignore[arg-type]
        rec,
        runner=_Runner(run),  # type: ignore[arg-type]
        executor=LocalExecutor(),
        timeout=5,
        deps=SimpleNamespace(parent=None),  # type: ignore[arg-type]
    )


def test_a_build_that_hangs_on_the_held_out_cases_is_a_miss(tmp_path: Path) -> None:
    """verify_fwd_attack: a timeout was ``error``, which lets the ticket leave the forward
    reading's pool — the grader reads a target run that times out as the build's own miss."""
    assert (
        _held_out_result(tmp_path, runners.TestRun(1, frozenset(), timed_out=True)) == RESULT_FAIL
    )
    assert _held_out_result(tmp_path, runners.TestRun(1, frozenset({"t"}))) == RESULT_FAIL
    assert _held_out_result(tmp_path, runners.TestRun(0, frozenset())) == RESULT_PASS
    # the instrument, not the build: still an error, never a miss
    assert (
        _held_out_result(tmp_path, runners.TestRun(1, frozenset(), parse_error="junk"))
        == RESULT_ERROR
    )
    # and the tests are taken out of the tree again
    assert not (tmp_path / HELD_OUT_PATH).exists()
