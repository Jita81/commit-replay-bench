"""crb.factory.build — the throwaway oracle commit, the ordinary grade path, and a
``process_step="factory"`` row whose false-Q1 invariant is intact.

This module also carries the hermetic harness (fake builders, the forward-mode
item on :mod:`fixtures.pyrepo`) that the delivery / review / loop tests import.

Navigation
----------
What it is:   The factory build step's test suite — the throwaway oracle commit, the ordinary
              grade path and a ``process_step="factory"`` row whose false-Q1 invariant is intact.
              Also the hermetic harness (fake builders, the forward-mode item on ``pyrepo``) the
              delivery, review and loop suites import.
What it does: Pins that the staged oracle commit contains only the test at HEAD and refuses
              bytes that are not the RED proof, that a green build produces a pack and a factory
              row, that the false-Q1 invariant holds on factory rows, that belt 1 catches an
              edited authored test, belt 3 a regression and belt 4 a no-change, that a builder
              exception is recorded and graded not clean, that the builder identity may not
              equal the test author, and that the ladder escalates until clean.
How:          ``Harness`` over ``pyrepo`` with ``prove_red`` → ``build`` under the real
              ``PytestRunner`` / ``LocalExecutor``; ``FakeBuilder`` writes the source a real
              builder would.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0001-four-belts-and-false-q1-at-write.md
Works with:   src/crb/factory/build.py (under test), src/crb/factory/testfirst.py (the RED
              proof it stages), src/crb/core/grade.py (the unchanged grader),
              src/crb/core/ledger.py (``PROCESS_FACTORY`` rows), tests/test_factory_delivery.py,
              tests/test_factory_review.py and tests/test_factory_loop.py (import this harness)
Tested by:    tests/test_factory_build.py
Touch when:   the build step gains a stage (a harness method and a case); never so that a
              factory row can be clean under a belt the replay row could not.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from crb.builders.base import Budget, BuildBrief, BuildOutcome, Rung
from crb.core.evidence import verify_pack
from crb.core.execution import LocalExecutor
from crb.core.grade import FalseQ1Violation
from crb.core.ledger import PROCESS_FACTORY, GradeRow, JsonlLedger
from crb.core.runners.pytest_runner import PytestRunner
from crb.core.workspace import Workspace
from crb.factory import build as fb
from crb.factory.backlog import KIND_CODE, BacklogItem
from crb.factory.testfirst import AuthoredTest, RedProof, SameIdentityError, prove_red
from fixtures import pyrepo as pr

# ---------------------------------------------------------------------------
# harness
# ---------------------------------------------------------------------------

SRC = pr.SRC
TEST_MULTIPLY = "tests/test_multiply.py"
TEST_MULTIPLY_SRC = (
    "from calc import multiply\n\n\ndef test_multiply():\n    assert multiply(3, 4) == 12\n"
)
TEST_MULTIPLY_WEAK = (
    "from calc import multiply\n\n\ndef test_multiply():\n    assert multiply(2, 2) == 4\n"
)
TEST_MULTIPLY_GREEN = "from calc import add\n\n\ndef test_add_again():\n    assert add(1, 1) == 2\n"

MULTIPLY_DEF = "\n\ndef multiply(a: int, b: int) -> int:\n    return a * b\n"
MULTIPLY_HARDCODED = (
    "\n\ndef multiply(a: int, b: int) -> int:\n"
    "    if a == 3 and b == 4:\n        return 12\n    return 0\n"
)
DIVIDE_DEF = "\n\ndef divide(a: int, b: int) -> float:\n    return a / b\n"
TEST_DIVIDE = "tests/test_divide.py"
TEST_DIVIDE_SRC = "from calc import divide\n\n\ndef test_divide():\n    assert divide(8, 2) == 4\n"

OPERATOR = "operator:po@example"

Edit = Callable[[Workspace], None]


def append_src(text: str) -> Edit:
    """An edit that appends ``text`` to the fixture's source module (how the fakes "implement")."""

    def _edit(ws: Workspace) -> None:
        p = ws.root / SRC
        p.write_text(p.read_text(encoding="utf-8") + text, encoding="utf-8")

    return _edit


def noop(ws: Workspace) -> None:
    """The builder did nothing: the authored test stays RED."""
    return None


def tamper(ws: Workspace) -> None:
    """Edit the authored oracle so it passes trivially (belt 1 → disqualified)."""
    for rel in (TEST_MULTIPLY, TEST_DIVIDE):
        p = ws.root / rel
        if p.exists():
            p.write_text("def test_multiply():\n    assert True\n", encoding="utf-8")
    append_src(MULTIPLY_DEF)(ws)


def regression(ws: Workspace) -> None:
    """multiply is right, add is now wrong (belt 3)."""
    (ws.root / SRC).write_text(pr.SRC_REGRESSION + MULTIPLY_DEF, encoding="utf-8")


@dataclass
class FakeBuilder:
    """Writes the source a real builder would; reports a metered outcome."""

    name: str = "fake"
    model: str = "good"
    provider: str = "fake"
    edit: Edit = field(default_factory=lambda: append_src(MULTIPLY_DEF))
    raise_exc: bool = False
    briefs: list[BuildBrief] = field(default_factory=list)

    def build(
        self, workspace: Workspace, brief: BuildBrief, budget: Budget, *, on_event: Any = None
    ) -> BuildOutcome:
        self.briefs.append(brief)
        if self.raise_exc:
            raise RuntimeError("builder infrastructure exploded")
        self.edit(workspace)
        return BuildOutcome(
            builder=self.name,
            model=self.model,
            provider=self.provider,
            mode=brief.mode,
            done=True,
            summary="did the thing",
            turns=2,
            tokens_in=100,
            tokens_out=50,
            cost_usd=0.001,
            latency_s=0.1,
            stop_reason="done",
            budget=budget,
        )

    def describe(self) -> dict[str, Any]:
        return {"builder": self.name, "model": self.model}


def multiply_item(**kw: object) -> BacklogItem:
    """The forward-mode item: "add multiply to calc", with the structural facts
    the DoR gate needs.
    """
    base: dict[str, object] = {
        "id": "I-1",
        "title": "Add multiply to calc",
        "kind": KIND_CODE,
        "description": "calc needs a multiply(a, b) function.",
        "acceptance_criteria": ("multiply(3, 4) == 12",),
        "capability_class": "bug.fix",
        "size_estimate": "XS",
        "structural_facts": (
            "reproduction: `from calc import multiply` raises ImportError",
            "expected_behaviour: calc exposes multiply(a: int, b: int) -> int",
            "exact_value: multiply(3, 4) == 12",
        ),
    }
    base.update(kw)
    return BacklogItem(**base)  # type: ignore[arg-type]


def authored_multiply(content: str = TEST_MULTIPLY_SRC, author: str = OPERATOR) -> AuthoredTest:
    """The authored oracle for ``multiply_item`` (content and author
    overridable for the refusals).
    """
    return AuthoredTest(TEST_MULTIPLY, content, author)


@dataclass
class Harness:
    """The hermetic factory rig over ``pyrepo``: scratch, evidence dir, ledger and the real
    instrument; ``prove`` and ``build`` wrap the module functions with it.
    """

    repo: pr.PyRepo
    scratch: Path
    evidence_dir: Path
    ledger: JsonlLedger
    runner: PytestRunner
    executor: LocalExecutor

    @property
    def head(self) -> str:
        """The fixture repository's current HEAD sha (the base every proof is taken at)."""
        return self.repo.repo.rev_parse("HEAD")

    def prove(self, item: BacklogItem, authored: AuthoredTest) -> RedProof:
        """``prove_red`` for ``item`` / ``authored`` with the rig's instrument."""
        return prove_red(
            self.repo.repo,
            item,
            authored,
            config=self.repo.config,
            runner=self.runner,
            executor=self.executor,
            scratch=self.scratch,
        )

    def build(
        self,
        item: BacklogItem,
        authored: AuthoredTest,
        proof: RedProof,
        builder: FakeBuilder,
        *,
        events: list[tuple[str, Mapping[str, Any]]] | None = None,
        trial: str = "r1",
        ledger: bool = True,
    ) -> fb.BuildResult:
        """``build`` for ``item`` under ``builder`` with the rig's instrument; ``events`` collects
        the emitted ``(kind, payload)`` pairs when given.
        """
        return fb.build_item(
            self.repo.repo,
            item,
            authored,
            proof,
            builder=builder,
            budget=Budget(),
            config=self.repo.config,
            runner=self.runner,
            executor=self.executor,
            scratch=self.scratch,
            evidence_dir=self.evidence_dir,
            ledger=self.ledger if ledger else None,
            run_id="run-1",
            trial=trial,
            actor="tester",
            on_event=(lambda a, p: events.append((a, dict(p)))) if events is not None else None,
        )


@pytest.fixture
def harness(pyrepo: pr.PyRepo, tmp_path: Path) -> Harness:
    """A fresh ``Harness`` per test (its own ledger and evidence dir under ``tmp_path``)."""
    return Harness(
        repo=pyrepo,
        scratch=tmp_path / "scratch",
        evidence_dir=tmp_path / "packs",
        ledger=JsonlLedger(tmp_path / "grades.jsonl"),
        runner=PytestRunner(pyrepo.config),
        executor=LocalExecutor(),
    )


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------


def test_stage_oracle_commit_contains_only_the_test_at_head(harness: Harness) -> None:
    item, authored = multiply_item(), authored_multiply()
    proof = harness.prove(item, authored)
    oc = fb.stage_oracle_commit(harness.repo.repo, item, authored, proof, scratch=harness.scratch)
    repo = harness.repo.repo
    assert oc.parent == harness.head == proof.base_sha
    assert repo.changed_files(oc.sha) == [TEST_MULTIPLY]
    assert oc.branch == "crb/factory/I-1/test"
    assert repo.rev_parse(oc.branch) == oc.sha
    assert oc.test_sha256 == authored.sha256
    # HEAD of the repo did not move
    assert repo.rev_parse("HEAD") == proof.base_sha


def test_stage_refuses_bytes_that_are_not_the_red_proof(harness: Harness) -> None:
    item, authored = multiply_item(), authored_multiply()
    proof = harness.prove(item, authored)
    edited = authored_multiply(TEST_MULTIPLY_SRC.replace("12", "13"))
    with pytest.raises(fb.OracleTampered):
        fb.stage_oracle_commit(harness.repo.repo, item, edited, proof, scratch=harness.scratch)


def test_green_build_produces_pack_and_factory_row(harness: Harness) -> None:
    item, authored = multiply_item(), authored_multiply()
    proof = harness.prove(item, authored)
    builder = FakeBuilder()
    events: list[tuple[str, Mapping[str, Any]]] = []
    res = harness.build(item, authored, proof, builder, events=events)
    try:
        assert res.clean and not res.disqualified
        assert res.grade.belts.all_true
        assert res.changed_files == (SRC,)
        assert res.rung == "fake:good"
        # the pack is written, hashes, and says factory
        assert res.pack_path.exists() and verify_pack(res.pack.to_dict())
        assert res.pack.apparatus.extra["process_step"] == PROCESS_FACTORY
        assert res.pack.notes["red_proof"]["test_sha256"] == proof.test_sha256
        assert res.task.task_id == res.oracle.sha and res.task.red_checked
        assert res.task.labels["item_id"] == "I-1"
        # the row is ledgered with process_step=factory and the chain verifies
        assert res.row is not None
        assert res.row.process_step == PROCESS_FACTORY
        assert res.row.clean and res.row.evidence_pack_hash == res.pack_hash
        assert res.row.cell.process_step == "factory"
        assert res.row.gold_clean is None
        assert res.row.labels["item_id"] == "I-1" and res.row.labels["test_author"] == OPERATOR
        assert harness.ledger.verify() == 1
        # the brief the builder saw: sighted, oracle visible, facts, no src paths
        brief = builder.briefs[0]
        assert brief.test_files == (TEST_MULTIPLY,) and brief.sighted
        assert any(f.startswith("reproduction:") for f in brief.spec_facts)
        assert "Acceptance criteria" in brief.message
        # the source build happened in a worktree at the parent (HEAD) with the test overlaid
        assert res.workspace is not None and res.workspace.parent == harness.head
        acts = [a for a, _ in events]
        assert "build.oracle_staged" in acts and "grade.belt" in acts and "ledger.append" in acts
    finally:
        res.close()


def test_false_q1_invariant_intact_on_factory_rows(harness: Harness) -> None:
    item, authored = multiply_item(), authored_multiply()
    proof = harness.prove(item, authored)
    res = harness.build(item, authored, proof, FakeBuilder(edit=noop))
    res.close()
    assert not res.clean and res.grade.belts.target_green is False
    assert res.row is not None and not res.row.clean
    with pytest.raises(FalseQ1Violation):
        GradeRow.from_dict({**res.row.to_dict(), "clean": True, "row_id": "x", "row_hash": ""})


def test_belt_1_catches_an_edited_authored_test(harness: Harness) -> None:
    item, authored = multiply_item(), authored_multiply()
    proof = harness.prove(item, authored)
    res = harness.build(item, authored, proof, FakeBuilder(edit=tamper))
    res.close()
    assert res.disqualified and res.grade.belts.tests_unmodified is False
    assert res.grade.tamper_files == (TEST_MULTIPLY,)
    assert res.row is not None and res.row.disqualified and not res.row.clean


def test_belt_3_catches_a_regression_and_belt_4_a_no_change(harness: Harness) -> None:
    item, authored = multiply_item(), authored_multiply()
    proof = harness.prove(item, authored)
    reg = harness.build(item, authored, proof, FakeBuilder(edit=regression))
    reg.close()
    assert not reg.clean and reg.grade.belts.no_new_failures is False
    assert set(reg.grade.new_failures) == set(pr.TEST_CALC_IDS)
    # baseline captured at HEAD with the oracle overlaid: the oracle's own RED is the baseline
    assert reg.task.baseline_failing == (f"{TEST_MULTIPLY}",)
    non = harness.build(item, authored, proof, FakeBuilder(edit=noop), trial="r2")
    non.close()
    assert non.task.src_files == (fb.NO_SOURCE_CHANGE,)
    assert non.grade.belts.source_changed is None  # never reached: belt 2 failed first


def test_builder_exception_is_recorded_and_graded_not_clean(harness: Harness) -> None:
    item, authored = multiply_item(), authored_multiply()
    proof = harness.prove(item, authored)
    res = harness.build(item, authored, proof, FakeBuilder(raise_exc=True), ledger=False)
    res.close()
    assert not res.clean and "exploded" in res.error
    assert res.row is None and res.outcome is None
    assert res.pack.notes["builder_error"] == res.error


def test_builder_identity_may_not_equal_test_author(harness: Harness) -> None:
    item = multiply_item()
    authored = AuthoredTest(TEST_MULTIPLY, TEST_MULTIPLY_SRC, "fake:good")
    proof = harness.prove(item, authored)
    with pytest.raises(SameIdentityError):
        harness.build(item, authored, proof, FakeBuilder())
    with pytest.raises(SameIdentityError):
        harness.build(item, authored, proof, FakeBuilder(name="Fake", model="GOOD"))
    # a different model of the same builder is a different identity
    res = harness.build(item, authored, proof, FakeBuilder(model="other"))
    res.close()
    assert res.clean


def test_build_ladder_escalates_until_clean(harness: Harness) -> None:
    item, authored = multiply_item(), authored_multiply()
    proof = harness.prove(item, authored)
    rungs = (Rung("fake", "weak"), Rung("fake", "good"), Rung("fake", "never"))
    builders = {
        "fake:weak": FakeBuilder(model="weak", edit=noop),
        "fake:good": FakeBuilder(model="good"),
        "fake:never": FakeBuilder(model="never"),
    }
    results = fb.build_ladder(
        harness.repo.repo,
        item,
        authored,
        proof,
        rungs=rungs,
        builder_for=lambda r: builders[r.label],
        budget=Budget(),
        config=harness.repo.config,
        runner=harness.runner,
        executor=harness.executor,
        scratch=harness.scratch,
        evidence_dir=harness.evidence_dir,
        ledger=harness.ledger,
        run_id="run-1",
    )
    try:
        assert [r.trial for r in results] == ["r1", "r2"]
        assert [r.clean for r in results] == [False, True]
        assert results[0].closed and not results[1].closed
        assert harness.ledger.verify() == 2
        assert not builders["fake:never"].briefs
    finally:
        results[-1].close()
    with pytest.raises(SameIdentityError):
        fb.build_ladder(
            harness.repo.repo,
            item,
            AuthoredTest(TEST_MULTIPLY, TEST_MULTIPLY_SRC, "fake:good"),
            proof,
            rungs=rungs,
            builder_for=lambda r: builders[r.label],
            budget=Budget(),
            config=harness.repo.config,
            runner=harness.runner,
            executor=harness.executor,
            scratch=harness.scratch,
            evidence_dir=harness.evidence_dir,
        )
