"""One brief composer, and the leak guard on every context line (ADR-0026 items 1 and 7).

Navigation
----------
What it is:   The suite for G-934 (``product.truth.216``, ``stream-learn.automation.25``) and
              G-671 (``product.truth.206``): replay and the factory compose their briefs in one
              place, from the arm, and no context line carries the answer.
What it does: Pins that the replay adapter and the factory build compose identical briefs for
              one arm and one ticket but for the ticket's source; that a factory build carries
              the loop's overlay and lines only when its standard arm carries ``+L``; that a
              planted context line naming an identifier the commit introduced is refused and
              counted on the row; that a line learned from a newer commit never reaches an
              older one; and that a person-written library entry never reaches a retrospective
              brief.
How:          ``pyrepo`` with a recording builder: a blind replay through
              ``crb.core.run.run`` (``S1`` arm with a scripted author, or with a learning
              snapshot), a factory ``build_item`` through the test_factory_build harness, the
              factory loop rig for the ``+L`` rule, and ``compose`` / ``novel_tokens`` directly.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0026-the-context-standard.md
Works with:   src/crb/builders/brief.py (under test), src/crb/builders/adapter.py (the replay
              brief), src/crb/factory/build.py (the factory brief), src/crb/core/playbook.py
              (the time-order rule), src/crb/factory/loop.py (the +L rule)
Tested by:    tests/test_builders_brief.py
Touch when:   never for a new repository; the composer gains an input; a provenance label is added.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar

import pytest

import crb.builders as builders_pkg
from crb.builders import adapter
from crb.builders.base import STOP_DONE, Budget, BuildBrief, BuildOutcome, EscalationLadder, Rung
from crb.builders.brief import (
    LABEL_CONTEXT_ARM,
    LABEL_CTX_REFUSED,
    LABEL_CTX_TICKET,
    ContextEntry,
    S1Arm,
    Ticket,
    compose,
    novel_tokens,
)
from crb.core.execution import LocalExecutor
from crb.core.git import GitRepo
from crb.core.ledger import JsonlLedger
from crb.core.playbook import PlaybookLine, taught_before
from crb.core.prevention import AUTO_CONTEXT, LearningSnapshot
from crb.core.run import RunSpec, run
from crb.core.runners.pytest_runner import PytestRunner
from crb.core.workspace import Workspace
from crb.factory import loop as fl
from crb.factory.backlog import KIND_CODE, BacklogItem
from crb.factory.standard import Readers, Standard
from crb.factory.testfirst import AuthoredTest
from fixtures import pyrepo as pr
from fixtures.posture import witnessed_context_for
from test_factory_build import Harness, authored_multiply, multiply_item
from test_factory_loop import FakeTestAuthor, _rig

S1_PATH = "tests/test_s1_multiply.py"
S1_SRC = "from calc import multiply\n\n\ndef test_multiply():\n    assert multiply(3, 4) == 12\n"


class Recorder:
    """Registered as ``rec``: records the brief, then applies the commit's own patch."""

    name = "rec"
    briefs: ClassVar[list[BuildBrief]] = []

    def __init__(self, *, model: str = "m", provider: str = "", **cfg: Any) -> None:
        self.model = model
        self.provider = provider

    def describe(self) -> dict[str, Any]:
        return {"builder": self.name, "model": self.model}

    def build(
        self, workspace: Workspace, brief: BuildBrief, budget: Budget, *, on_event: Any = None
    ) -> BuildOutcome:
        Recorder.briefs.append(brief)
        pr.apply_gold(workspace)
        return BuildOutcome(
            builder=self.name,
            model=self.model,
            provider=self.provider,
            mode=brief.mode,
            done=True,
            stop_reason=STOP_DONE,
            budget=budget,
        )


@pytest.fixture(autouse=True)
def _register(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(builders_pkg._REGISTRY, "rec", Recorder)
    Recorder.briefs = []


def _replay(
    pyrepo: pr.PyRepo,
    tmp_path: Path,
    *,
    s1: S1Arm | None = None,
    learning: LearningSnapshot | None = None,
    commit_dates: Any = None,
) -> tuple[list[Any], Any]:
    """One blind replay of the fixture's feat commit with the recording builder."""
    runner = PytestRunner(pyrepo.config)
    executor = LocalExecutor()
    ladder = EscalationLadder((Rung("rec", "m"),))
    ledger = JsonlLedger(tmp_path / "ledger.jsonl")
    spec = RunSpec(
        run_id="run-brief",
        config=pyrepo.config,
        runner=runner,
        executor=executor,
        scratch=tmp_path / "scratch",
        ledger=ledger,
        evidence_dir=tmp_path / "evidence",
        mode="blind",
        ladder=adapter.ladder_labels(ladder),
        context_for=witnessed_context_for(
            pyrepo.repo,
            pyrepo.config,
            runner=runner,
            executor=executor,
            scratch=tmp_path / "scratch",
        ),
    )
    fn = adapter.build_fn_for(
        ladder,
        budget=Budget(),
        runner=runner,
        executor=executor,
        config=pyrepo.config,
        s1=s1,
        learning=learning,
        commit_dates=commit_dates,
    )
    summary = run(spec, pyrepo.repo, [pyrepo.feat_task()], fn)
    return list(ledger.rows()), summary


def _author(path: str = S1_PATH, content: str = S1_SRC) -> S1Arm:
    def write(ws: Any, subject: str, message: str) -> tuple[str, str]:
        return path, content

    return S1Arm(author=write, author_model="t1", author_stamp="fake-author")


def _normalised(brief: BuildBrief, root: str) -> dict[str, Any]:
    return {
        "subject": brief.subject,
        "message": brief.message,
        "mode": brief.mode,
        "test_files": brief.test_files,
        "target_tests": brief.target_tests,
        "test_command": brief.test_command.replace(root, "<root>"),
        "harness_command": brief.harness_command.replace(root, "<root>"),
        "spec_facts": brief.spec_facts,
        "playbook": brief.playbook,
        "finish_checks": brief.finish_checks,
        "rules": brief.rules,
    }


# --- one composer ----------------------------------------------------------------------------


def test_one_composer_builds_the_replay_and_the_factory_brief_for_one_arm(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    """A replay on arm ``S1@t1`` and a factory build of the same ticket on the same arm get
    the same brief and the same arm and provenance labels — all but the ticket's source."""
    rows, _ = _replay(pyrepo, tmp_path / "replay", s1=_author())
    (row,) = rows
    replay_brief = Recorder.briefs[-1]
    task = pyrepo.feat_task()

    h = Harness(
        repo=pyrepo,
        scratch=tmp_path / "factory" / "scratch",
        evidence_dir=tmp_path / "factory" / "packs",
        ledger=JsonlLedger(tmp_path / "factory" / "grades.jsonl"),
        runner=PytestRunner(pyrepo.config),
        executor=LocalExecutor(),
    )
    item = BacklogItem(
        id="I-9",
        title=task.subject,
        kind=KIND_CODE,
        description=task.subject,
        capability_class=task.capability_class,
    )
    authored = AuthoredTest(S1_PATH, S1_SRC, "author:t1")
    proof = h.prove(item, authored)
    res = fb_build(h, item, authored, proof)
    factory_brief = Recorder.briefs[-1]

    def root_of(brief: BuildBrief) -> str:
        return brief.harness_command.split("PYTHONPATH=")[-1].split("/src")[0].strip("'\" ")

    assert _normalised(replay_brief, root_of(replay_brief)) == _normalised(
        factory_brief, root_of(factory_brief)
    )
    replay_labels = {
        k: v for k, v in row.labels.items() if k.startswith("ctx_") or k == LABEL_CONTEXT_ARM
    }
    factory_labels = {
        k: v for k, v in res.labels.items() if k.startswith("ctx_") or k == LABEL_CONTEXT_ARM
    }
    assert replay_labels[LABEL_CONTEXT_ARM] == factory_labels[LABEL_CONTEXT_ARM] == "S1@t1"
    assert replay_labels.pop(LABEL_CTX_TICKET) == "message"
    assert factory_labels.pop(LABEL_CTX_TICKET).startswith("ticket@")
    assert replay_labels == factory_labels


def fb_build(h: Harness, item: BacklogItem, authored: AuthoredTest, proof: Any) -> Any:
    """``build_item`` on the S1 arm with the recording builder."""
    from crb.factory import build as fb

    return fb.build_item(
        h.repo.repo,
        item,
        authored,
        proof,
        builder=Recorder(model="m"),
        budget=Budget(),
        config=h.repo.config,
        runner=h.runner,
        executor=h.executor,
        scratch=h.scratch,
        evidence_dir=h.evidence_dir,
        ledger=h.ledger,
        run_id="run-f",
        arm="S1@t1",
        author_stamp="fake-author",
    )


def test_a_factory_build_carries_the_loops_overlay_only_when_its_standard_arm_carries_plus_l(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    """ADR-0026 item 8: an ``S1`` standard in a loop-on repository builds loop-off (no line,
    ``learn: off``); an ``S1+L`` standard carries the overlay and the ``learn*`` labels."""
    line = PlaybookLine(
        line_id="pl-1",
        template_id="format_before_finish",
        signature="lint:E501",
        text="Run the formatter before you finish.",
        taught_by_tasks=("c-old-1", "c-old-2"),
    )
    snap = LearningSnapshot(
        repo="pyrepo",
        auto_apply=AUTO_CONTEXT,
        lines=(line,),
        overlay={"checks": {"format_step": True}},
    )
    author = FakeTestAuthor(tests={"I-1": (S1_PATH, S1_SRC)})
    builder = fl_builder()
    for arm, loop_on in (("S1@t1", False), ("S1@t1+L", True)):
        sub = tmp_path / arm.replace("@", "-").replace("+", "-")
        sub.mkdir()
        rig = _rig(
            pyrepo,
            sub,
            readers=Readers(standard_for=lambda cell, a=arm: Standard(a, signed=True)),  # type: ignore[misc]
            author=author,
            builder=builder,
            learning=snap,
        )
        out = rig.loop().run_item(multiply_item(), authored=authored_multiply())
        assert out.status == fl.STATUS_ACCEPTED, out.error
        row = list(rig.ledger.rows())[-1]
        brief = builder.briefs[-1]
        assert row.labels[LABEL_CONTEXT_ARM] == arm
        if loop_on:
            assert brief.playbook == (line.text,)
            assert row.labels["learn"] == AUTO_CONTEXT and row.labels["learn_lines"] == "pl-1"
            assert row.labels["learn_overlay"] == snap.overlay_digest
        else:
            assert brief.playbook == ()
            assert row.labels["learn"] == "off" and "learn_lines" not in row.labels
            assert "learn_overlay" not in row.labels


def fl_builder() -> Any:
    from test_factory_loop import MultiBuilder

    return MultiBuilder()


# --- the leak guard ------------------------------------------------------------------------


def test_a_planted_line_naming_an_identifier_the_commit_introduced_is_refused_and_counted(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    """The feat commit introduces ``subtract``. A context line naming it is refused by the
    composer and counted on the row; the builder never sees it, nor the token."""
    task = pyrepo.feat_task()
    novel = novel_tokens(
        pyrepo.repo, parent=pyrepo.initial_sha, commit=task.task_id, paths=task.src_files
    )
    assert "subtract" in novel and "add" not in novel
    planted = "Keep subtract a pure function of its two arguments."
    composed = compose(
        "A0",
        Ticket(task.subject, task.subject),
        repo=task.repo,
        language=task.language,
        mode="blind",
        facts=(planted, "The package is calc."),
        novel=novel,
    )
    assert composed.refused == (planted,)
    assert composed.brief.spec_facts == ("The package is calc.",)
    assert composed.labels[LABEL_CTX_REFUSED] == "1"

    # on the row: a learned line planted with the token (its slots carry none, so the
    # playbook's file-name leak gate passes it — only the composer's guard stops it)
    line = PlaybookLine(
        line_id="pl-leak",
        template_id="keep_public_api",
        signature="api:x",
        text=f"{planted}",
        taught_by_tasks=("c-old-1", "c-old-2"),
    )
    snap = LearningSnapshot(repo="pyrepo", auto_apply=AUTO_CONTEXT, lines=(line,))

    def dates(shas: Any) -> dict[str, str]:
        return {s: ("000000000001" if s.startswith("c-old") else "000000000009") for s in shas}

    rows, _ = _replay(pyrepo, tmp_path, learning=snap, commit_dates=dates)
    (row,) = rows
    assert row.labels[LABEL_CTX_REFUSED] == "1"
    assert "pl-leak" in row.labels["learn_dropped"] and "learn_lines" not in row.labels
    assert Recorder.briefs[-1].playbook == ()
    assert row.labels[LABEL_CONTEXT_ARM] == "A0+L"


def test_a_line_learned_from_a_newer_commit_never_reaches_an_older_one(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    """A line reaches commit T only when every other commit that taught it is older than T.
    One newer teacher drops it — in the rule, and on the replayed row."""
    old_line = PlaybookLine("pl-old", "t", "s", "Run the tests before you finish.", ("a", "b"))
    new_line = PlaybookLine("pl-new", "t", "s", "Format the code before you finish.", ("a", "z"))
    dates = {"a": "000000000001", "b": "000000000002", "z": "000000000099", "T": "000000000050"}
    kept, dropped = taught_before([old_line, new_line], "T", task_date=dates["T"], dates=dates)
    assert [ln.line_id for ln in kept] == ["pl-old"] and dropped == ["pl-new"]
    # an undated teacher, or fewer than two others, is never enough
    assert taught_before([old_line], "T", task_date="", dates=dates)[0] == []
    assert (
        taught_before([PlaybookLine("x", "t", "s", "y", ("a",))], "T", task_date="5", dates=dates)[
            0
        ]
        == []
    )

    snap = LearningSnapshot(repo="pyrepo", auto_apply=AUTO_CONTEXT, lines=(old_line, new_line))
    feat = pyrepo.feat_task().task_id

    def git_dates(shas: Any) -> dict[str, str]:
        return {s: dates.get(s, dates["T"] if s == feat else "") for s in shas}

    rows, _ = _replay(pyrepo, tmp_path, learning=snap, commit_dates=git_dates)
    (row,) = rows
    assert row.labels["learn_lines"] == "pl-old"
    assert "pl-new" in row.labels["learn_dropped"]
    assert Recorder.briefs[-1].playbook == (old_line.text,)


def test_a_person_written_entry_never_reaches_a_retrospective_brief() -> None:
    """A retrospective brief takes a fact or library entry only when it was produced
    mechanically at or before the reading's pool began."""
    pool = "2026-09-01T00:00:00+00:00"
    entries = (
        ContextEntry(
            "lib-1",
            "The calc package exposes pure functions.",
            "v1",
            "2026-08-01T00:00:00+00:00",
            mechanical=True,
        ),
        ContextEntry(
            "lib-2", "Prefer small helpers.", "v1", "2026-08-01T00:00:00+00:00", mechanical=False
        ),
        ContextEntry(
            "lib-3",
            "Name the new helper clearly.",
            "v1",
            "2026-09-20T00:00:00+00:00",
            mechanical=True,
        ),
    )
    composed = compose(
        "A0+library@v1",
        Ticket("feat: add subtract", "feat: add subtract"),
        repo="pyrepo",
        language="python",
        mode="blind",
        library=entries,
        retrospective=True,
        pool_began=pool,
    )
    assert composed.brief.spec_facts == ("The calc package exposes pure functions.",)
    assert [e.entry_id for e in composed.library] == ["lib-1"]
    assert composed.labels[LABEL_CTX_REFUSED] == "2"
    # prospectively (the factory) the same entries all reach the brief
    forward = compose(
        "S2+library@v1",
        Ticket("x", "x", "ticket@2026-09-27"),
        repo="pyrepo",
        language="python",
        mode="sighted",
        library=entries,
    )
    assert len(forward.brief.spec_facts) == 3


def test_a_planted_line_naming_only_what_the_held_out_test_introduced_is_refused(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    """The gold post-image includes the commit's own tests. ``test_subtract_negative``
    exists only in the held-out test the feat commit added; a learned line naming it (its
    slots carry nothing, so the playbook's file-name gate passes it) is refused by the
    composer and counted on the row. It fails if the guard reads the source files alone."""
    line = PlaybookLine(
        line_id="pl-test-leak",
        template_id="keep_public_api",
        signature="api:y",
        text="Cover the case test_subtract_negative checks before you finish.",
        taught_by_tasks=("c-old-1", "c-old-2"),
    )
    snap = LearningSnapshot(repo="pyrepo", auto_apply=AUTO_CONTEXT, lines=(line,))

    def dates(shas: Any) -> dict[str, str]:
        return {s: ("000000000001" if s.startswith("c-old") else "000000000009") for s in shas}

    rows, _ = _replay(pyrepo, tmp_path, learning=snap, commit_dates=dates)
    (row,) = rows
    assert row.labels[LABEL_CTX_REFUSED] == "1"
    assert "pl-test-leak" in row.labels["learn_dropped"]
    assert Recorder.briefs[-1].playbook == ()


def test_a_literal_only_the_held_out_test_introduced_is_novel(tmp_path: Path) -> None:
    """An expected value that appears only in the commit's new test is a token the commit
    introduced: a context line naming it is refused."""
    root = tmp_path / "lit"
    root.mkdir()
    pr.git(root, "init", "-q")
    (root / "calc.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    pr.git(root, "add", "-A")
    pr.git(root, "commit", "-q", "-m", "init")
    parent = pr.git(root, "rev-parse", "HEAD")
    (root / "calc.py").write_text(
        "def add(a, b):\n    return a + b\n\n\ndef subtract(a, b):\n    return a - b\n",
        encoding="utf-8",
    )
    (root / "tests").mkdir()
    (root / "tests" / "test_subtract.py").write_text(
        "from calc import subtract\n\n\ndef test_sign():\n    assert subtract(1000, 1337) == -337\n",
        encoding="utf-8",
    )
    pr.git(root, "add", "-A")
    pr.git(root, "commit", "-q", "-m", "feat: add subtract")
    commit = pr.git(root, "rev-parse", "HEAD")
    novel = novel_tokens(
        GitRepo(root),
        parent=parent,
        commit=commit,
        paths=("calc.py", "tests/test_subtract.py"),
    )
    assert {"1000", "1337", "337"} <= novel
    line = "The expected result for these inputs is 337 below zero."
    composed = compose(
        "A0",
        Ticket("feat: add subtract", "feat: add subtract"),
        repo="lit",
        language="python",
        mode="blind",
        learned=(line,),
        novel=novel,
        retrospective=True,
    )
    assert composed.refused == (line,) and composed.brief.playbook == ()


def test_a_bare_fact_never_reaches_a_retrospective_brief() -> None:
    """A fact with no provenance cannot show it was produced mechanically before the pool
    began, so a retrospective brief refuses it and counts it; a prospective brief (the
    factory) takes it."""
    back = compose(
        "A0",
        Ticket("feat: add subtract", "feat: add subtract"),
        repo="pyrepo",
        language="python",
        mode="blind",
        facts=("The package is calc.",),
        retrospective=True,
    )
    assert back.brief.spec_facts == ()
    assert back.refused == ("The package is calc.",)
    assert back.labels[LABEL_CTX_REFUSED] == "1"
    forward = compose(
        "S2",
        Ticket("x", "x", "ticket@2026-09-27"),
        repo="pyrepo",
        language="python",
        mode="sighted",
        facts=("The package is calc.",),
    )
    assert forward.brief.spec_facts == ("The package is calc.",)
