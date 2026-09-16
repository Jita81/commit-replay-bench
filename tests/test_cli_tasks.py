"""``crb tasks classes | label | label-llm`` — the class-axis audit table, the human
label (highest precedence), and the model path — over the file workdir the miner
writes and over the database the worker writes.

Navigation
----------
What it is:   ``crb tasks classes | label | label-llm``'s test suite — the class-axis audit table,
              the human label and the model path, over the file workdir and the database.
What it does: Pins the classes table (text and JSON), that a human label rewrites the task in
              place with the highest precedence, that ``label-llm`` over the workdir goes through
              the labeller factory, and that the DB store reads and writes the ``tasks`` table.
How:          A workdir with ``pyrepo`` registered and its one mined task on file; a scripted
              labeller; a temp SQLite store for the DB case.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         none
Works with:   src/crb/cli/commands/tasks.py (under test), src/crb/core/classify.py (the
              precedence rule), src/crb/builders/labeller.py (``make_labeller``),
              src/crb/store/models.py (the ``tasks`` table), tests/test_worker_label.py (the
              same labelling as a worker run kind)
Tested by:    tests/test_cli_tasks.py
Touch when:   a task store (file or database) gains a field the audit table should show; the
              label precedence changes (never below human).
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import pytest

from crb.cli.commands import Workdir
from crb.cli.commands import tasks as tasks_cmd
from crb.cli.main import main
from crb.core import classify as c
from crb.core.spec import TaskSpec
from crb.store import init_db, make_engine, make_session_factory
from crb.store.models import Repo, Task
from fixtures import pyrepo as pr

Run = Callable[[Sequence[str]], tuple[int, str, str]]


@pytest.fixture
def workdir(tmp_path: Path, pyrepo: pr.PyRepo) -> Path:
    """A workdir with the fixture repo registered and its one mined task on file."""
    wd = Workdir(tmp_path / ".crb")
    wd.save_repo(pyrepo.config, pyrepo.path)
    wd.append_tasks(pr.REPO_NAME, [pyrepo.feat_task()])
    return wd.root


@pytest.fixture
def run(workdir: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> Run:
    """``run(argv) -> (exit_code, stdout, stderr)`` with ``--workdir`` supplied."""
    monkeypatch.delenv("CRB_DATABASE_URL", raising=False)

    def _run(argv: Sequence[str]) -> tuple[int, str, str]:
        capsys.readouterr()
        code = main([*argv, "--workdir", str(workdir)])
        out = capsys.readouterr()
        return code, out.out, out.err

    return _run


def _tasks(workdir: Path) -> list[TaskSpec]:
    return Workdir(workdir).load_tasks(pr.REPO_NAME)


def test_classes_table_and_json(run: Run, pyrepo: pr.PyRepo) -> None:
    code, out, _ = run(["tasks", "classes", pr.REPO_NAME])
    assert code == 0
    header, _rule, row, _blank, summary = out.rstrip("\n").split("\n")
    assert header.split() == [
        "task",
        "subject",
        "path",
        "intent",
        "conf",
        "resolved",
        "source",
        "labeller",
    ]
    assert row.split() == [
        pyrepo.feat_sha[:10],
        "feat:",
        "add",
        "subtract",
        "bug.fix",
        "-",
        "-",
        "bug.fix",
        "path",
        "-",
    ]
    assert "1 task(s), shown 1; sources path=1; labelled 0/1, unclassified 0, human 0" in summary
    code, out, _ = run(["tasks", "classes", pr.REPO_NAME, "--json"])
    assert code == 0
    doc = json.loads(out)
    assert doc["n"] == 1 and doc["sources"] == {"path": 1} and doc["labels"]["labelled"] == 0
    (t,) = doc["tasks"]
    assert t["task_id"] == pyrepo.feat_sha and t["class_source"] == "path" and t["labeller"] == ""
    # filters
    assert (
        run(["tasks", "classes", pr.REPO_NAME, "--source", "intent", "--json"])[1].count(
            '"task_id"'
        )
        == 0
    )
    assert (
        run(["tasks", "classes", pr.REPO_NAME, "--unlabelled", "--json"])[1].count('"task_id"') == 1
    )
    code, _, err = run(["tasks", "classes", "ghost"])
    assert code == 2 and "no tasks for repo 'ghost'" in err


def test_human_label_rewrites_the_task_in_place_with_highest_precedence(
    run: Run, workdir: Path, pyrepo: pr.PyRepo
) -> None:
    code, out, _ = run(
        [
            "tasks",
            "label",
            pr.REPO_NAME,
            pyrepo.feat_sha[:10],
            "--class",
            "feature.add",
            "--by",
            "paul",
            "--rationale",
            "adds subtract()",
        ]
    )
    assert code == 0 and "bug.fix -> feature.add (human, human:paul)" in out
    (t,) = _tasks(workdir)
    assert t.capability_class == "feature.add" and t.path_class == "bug.fix"
    assert t.class_source == "human" and t.intent is not None and t.intent.is_human
    assert t.intent.confidence == 1.0 and t.intent.rationale == "adds subtract()"
    # the evidence hash was computed from the clone: the same digest a model would stamp
    assert (
        t.intent.evidence_hash
        == c.commit_evidence(pyrepo.repo, pyrepo.feat_sha, path_class="bug.fix").digest()
    )
    # nothing the miner measured moved; the file is still one line per task
    before = pyrepo.feat_task().to_dict()
    for k, v in before.items():
        if k not in {"capability_class", "intent", "class_source"}:
            assert t.to_dict()[k] == v, k
    assert (workdir / "tasks" / f"{pr.REPO_NAME}.jsonl").read_text().count("\n") == 1
    # the table shows the human label; JSON carries the full label
    code, out, _ = run(["tasks", "classes", pr.REPO_NAME, "--json"])
    (row,) = json.loads(out)["tasks"]
    assert row["class_source"] == "human" and row["labeller"] == "human:paul"
    assert row["capability_class"] == "feature.add" and row["intent_class"] == "feature.add"
    # a human may say "none of these"; a human may not invent a class; needs --by
    code, out, _ = run(
        ["tasks", "label", pr.REPO_NAME, pyrepo.feat_sha, "--class", "other", "--by", "paul"]
    )
    assert code == 0 and _tasks(workdir)[0].capability_class == "(unclassified)"
    code, _, err = run(
        ["tasks", "label", pr.REPO_NAME, pyrepo.feat_sha, "--class", "security.fix", "--by", "paul"]
    )
    assert code == 2 and "not in the vocabulary" in err
    code, _, err = run(["tasks", "label", pr.REPO_NAME, "abc", "--class", "perf", "--by", "paul"])
    assert code == 2 and "at least 7" in err
    code, _, err = run(
        ["tasks", "label", pr.REPO_NAME, "0000000", "--class", "perf", "--by", "paul"]
    )
    assert code == 2 and "no task" in err


def test_label_llm_over_the_workdir_uses_the_labeller_factory(
    run: Run, workdir: Path, pyrepo: pr.PyRepo, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    class Scripted:
        name = "fake_llm:m@p"

        def __init__(self) -> None:
            self.usage = type("U", (), {"to_dict": lambda _self: {"calls": 1}})()
            self.seen: list[dict[str, Any]] = []

        def label(self, **kw: Any) -> c.IntentLabel:
            self.seen.append(kw)
            return c.IntentLabel(
                "behavior.change", 0.88, "scripted", self.name, evidence_hash=c.evidence_hash(**kw)
            )

    scripted = Scripted()

    def fake_make(builder: str, **kw: Any) -> Scripted:
        calls.append((builder, kw))
        return scripted

    import crb.builders.labeller as lb

    monkeypatch.setattr(lb, "make_labeller", fake_make)
    code, out, _ = run(
        [
            "tasks",
            "label-llm",
            pr.REPO_NAME,
            "--builder",
            "claude_code",
            "--model",
            "claude-sonnet-5",
            "--config",
            "auth=cli",
            "--config",
            "effort=low",
        ]
    )
    assert code == 0, out
    assert "labelled 1/1 with fake_llm:m@p; 1 changed" in out
    assert "bug.fix -> behavior.change [behavior.change 0.88]" in out
    ((builder, kw),) = calls
    assert builder == "claude_code" and kw["model"] == "claude-sonnet-5"
    assert kw["builder_config"] == {"auth": "cli", "effort": "low"}
    (seen,) = scripted.seen
    assert seen["subject"] == "feat: add subtract" and seen["path_class"] == "bug.fix"
    assert "def subtract" not in json.dumps(seen, default=str)  # never the code
    (t,) = _tasks(workdir)
    assert t.capability_class == "behavior.change" and t.class_source == "intent"
    # a second run has nothing to do; --relabel redoes model labels but never a human's
    code, out, _ = run(["tasks", "label-llm", pr.REPO_NAME, "--builder", "claude_code", "--json"])
    assert code == 0 and json.loads(out)["candidates"] == 0
    run(["tasks", "label", pr.REPO_NAME, pyrepo.feat_sha, "--class", "perf", "--by", "paul"])
    code, out, _ = run(
        ["tasks", "label-llm", pr.REPO_NAME, "--builder", "claude_code", "--relabel", "--json"]
    )
    assert code == 0 and json.loads(out)["candidates"] == 0
    assert _tasks(workdir)[0].class_source == "human"
    monkeypatch.undo()  # the real factory refuses an unknown builder as a usage error
    code, _, err = run(["tasks", "label-llm", pr.REPO_NAME, "--builder", "nope"])
    assert code == 2 and "no labeller for builder" in err


def test_db_store_reads_and_writes_the_tasks_table(
    tmp_path: Path,
    pyrepo: pr.PyRepo,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = f"sqlite:///{tmp_path / 'crb.db'}"
    engine = make_engine(url)
    init_db(engine)
    factory = make_session_factory(engine)
    task = pyrepo.feat_task()
    with factory() as s:
        s.add(
            Repo(
                name=pr.REPO_NAME,
                language="python",
                runner="pytest",
                clone_path=str(pyrepo.path),
                config_json=pyrepo.config.to_dict(),
            )
        )
        s.add(
            Task(
                repo=task.repo,
                task_id=task.task_id,
                pool=task.pool,
                size=task.size,
                capability_class=task.capability_class,
                language=task.language,
                authored=task.authored,
                subject=task.subject,
                red_checked=task.red_checked,
                gold_clean=task.gold_clean,
                spec_json=task.to_dict(),
            )
        )
        s.commit()
    # the environment selects the database; --file overrides it back to the workdir
    monkeypatch.setenv("CRB_DATABASE_URL", url)
    code = main(
        ["tasks", "classes", pr.REPO_NAME, "--json", "--workdir", str(tmp_path / "nowhere")]
    )
    assert code == 0 and json.loads(capsys.readouterr().out)["n"] == 1
    code = main(
        ["tasks", "classes", pr.REPO_NAME, "--file", "--workdir", str(tmp_path / "nowhere")]
    )
    assert code == 2 and "no tasks" in capsys.readouterr().err
    code = main(
        [
            "tasks",
            "label",
            pr.REPO_NAME,
            task.task_id,
            "--class",
            "refactor",
            "--by",
            "reviewer",
            "--database-url",
            url,
            "--workdir",
            str(tmp_path),
        ]
    )
    assert code == 0 and "bug.fix -> refactor (human, human:reviewer)" in capsys.readouterr().out
    with factory() as s:
        row = s.get(Task, (pr.REPO_NAME, task.task_id))
        assert row is not None and row.capability_class == "refactor"
        spec = TaskSpec.from_dict(row.spec_json)
    assert spec.class_source == "human" and spec.intent is not None and spec.intent.evidence_hash
    store = tasks_cmd.DbStore(url)
    assert store.clone_path(pr.REPO_NAME) == pyrepo.path and store.clone_path("ghost") is None
    with pytest.raises(Exception, match="not in the database"):
        store.save(task.with_(task_id="f" * 40))
