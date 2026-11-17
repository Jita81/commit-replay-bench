"""``crb ctxset lint`` and the stated lines of ``show``/``compare`` (ADR-0052, ADR-0054).

Navigation
----------
What it is:   The CLI suite for the offline ``crb ctxset lint FILE --clone DIR`` and the
              stated-set lines ``_meta_lines`` and ``compare_lines`` print.
What it does: Pins that a guard-clean stated entry lints ``ok`` (exit 0), that an undeclared
              answer is reported with ``req_undeclared_novel`` (exit 2), that a parse refusal
              is a one-line error naming its reason, that a non-stated set has nothing to
              guard, that an accepted-plan set is linted through ``plan_guard`` (an
              audited-bypass one, ADR-0055, withheld on structural reasons only, its lookalike
              reasons listed), and that the stated banner, provenance, cost and drift lines
              and an audited set's record line print.
How:          The pyrepo ``feat: add subtract`` commit (tests/fixtures/pyrepo.py) as the clone;
              documents from tests/fixtures/ctx_rows.py; ``crb.cli.main.main``.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0052-stated-requirement-arms.md,
              docs/adr/0054-accepted-plan-context-arm.md,
              docs/adr/0055-audited-bypass-plan-arm.md
Works with:   src/crb/cli/commands/ctxset.py (under test), src/crb/builders/brief.py
              (``req_guard``, ``plan_guard``), tests/test_cli_ctxset.py (the v1 CLI tests)
Tested by:    tests/test_cli_ctxset_lint.py
Touch when:   never for a new repository; the lint verb or the stated output lines change.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from crb.cli.commands import ctxset as cmd
from crb.cli.main import main
from crb.core import ctx_compare as cc
from crb.core import ctxset
from crb.core import stated as st
from fixtures import pyrepo as pr
from fixtures.ctx_rows import PLAN, ctx_doc, plan_doc, req_doc

SAFE = "The calculator keeps the existing add function working unchanged"
LEAK = "Add a subtract function beside add"


@pytest.fixture(autouse=True)
def _no_ambient_crb_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        if key.startswith("CRB_"):
            monkeypatch.delenv(key, raising=False)


def _lint(
    doc: dict[str, Any], pyrepo: pr.PyRepo, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> tuple[int, str, str]:
    path = tmp_path / "set.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    capsys.readouterr()
    code = main(["ctxset", "lint", str(path), "--clone", str(pyrepo.path)])
    out = capsys.readouterr()
    return code, out.out, out.err


def test_a_guard_clean_entry_lints_ok(
    pyrepo: pr.PyRepo, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    task = pyrepo.feat_task()
    code, out, _ = _lint(req_doc(tasks=[task.task_id], statement=SAFE), pyrepo, tmp_path, capsys)
    assert code == 0, out
    assert f"{task.task_id[:12]}  ok" in out and "1/1 entries pass" in out
    assert SAFE not in out


def test_an_undeclared_answer_is_reported_and_exits_2(
    pyrepo: pr.PyRepo, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    task = pyrepo.feat_task()
    code, out, err = _lint(req_doc(tasks=[task.task_id], statement=LEAK), pyrepo, tmp_path, capsys)
    assert code == 2 and "1 entry withheld" in err
    assert st.REASON_UNDECLARED_NOVEL in out and LEAK not in out


def test_lint_json_lists_each_entrys_reasons(
    pyrepo: pr.PyRepo, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    task = pyrepo.feat_task()
    results = cmd.lint_set(req_doc(tasks=[task.task_id], statement=LEAK), pyrepo.path)
    ((tid, reasons),) = results
    assert tid == task.task_id and st.REASON_UNDECLARED_NOVEL in reasons


def test_an_unreadable_changed_blob_is_an_error_not_an_empty_file(
    pyrepo: pr.PyRepo,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Review 4580636576: a changed blob the commit holds but the read fails on is never read
    as empty (it would add no novel tokens); only a path the commit lacks reads empty."""
    from crb.core.git import GitRepo

    task = pyrepo.feat_task()
    real = GitRepo.show_file

    def failing(self: GitRepo, sha: str, path: str) -> str | None:
        return None if sha == task.task_id and path == pr.SRC else real(self, sha, path)

    monkeypatch.setattr(GitRepo, "show_file", failing)
    code, out, err = _lint(req_doc(tasks=[task.task_id], statement=SAFE), pyrepo, tmp_path, capsys)
    assert code == 2 and "not readable" in err
    assert f"{task.task_id[:12]}  ok" not in out


def test_a_parse_refusal_is_a_one_line_error(
    pyrepo: pr.PyRepo, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    doc = req_doc(tasks=[pyrepo.feat_task().task_id], structure="table")
    code, _, err = _lint(doc, pyrepo, tmp_path, capsys)
    assert code == 2 and "refused " in err


def test_a_non_stated_set_has_nothing_to_guard(pyrepo: pr.PyRepo) -> None:
    assert cmd.lint_set(ctx_doc(tasks=[pyrepo.feat_task().task_id]), pyrepo.path) == []


def test_an_accepted_plan_set_is_linted_through_plan_guard(
    pyrepo: pr.PyRepo, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    task = pyrepo.feat_task()
    parent = pyrepo.repo.parent(task.task_id)
    clean = {**PLAN, "files": [pr.SRC], "tests": ["Cover the new operation with a unit test"]}
    ok = plan_doc(tasks=[task.task_id], plan=clean, source_rev=parent)
    assert cmd.lint_set(ok, pyrepo.path) == [(task.task_id, [])]
    code, out, _ = _lint(ok, pyrepo, tmp_path, capsys)
    assert code == 0 and "1/1 entries pass the guard" in out
    leaky = plan_doc(tasks=[task.task_id], plan={**clean, "tests": [f"Extend {pr.TEST_SUBTRACT}"]})
    ((_tid, why),) = cmd.lint_set(leaky, pyrepo.path)
    assert "plan_test_path" in why
    code, out, err = _lint(leaky, pyrepo, tmp_path, capsys)
    assert code == 2 and "plan_test_path" in out and "1 entry withheld" in err


def test_an_audited_plan_set_lints_its_lookalike_reasons_as_a_bypass(
    pyrepo: pr.PyRepo, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """ADR-0055: an audited-bypass set is withheld on structural reasons only, as a run
    composes it; the lookalike reasons it would have tripped are listed, not refused."""
    task = pyrepo.feat_task()
    parent = pyrepo.repo.parent(task.task_id)
    leaky = {**PLAN, "files": [pr.SRC], "tests": [f"Extend {pr.TEST_SUBTRACT}"]}
    doc = plan_doc(tasks=[task.task_id], plan=leaky, source_rev=parent, audited=True)
    code, out, err = _lint(doc, pyrepo, tmp_path, capsys)
    assert code == 0, err
    assert f"{task.task_id[:12]}  ok (audited bypass of " in out and "plan_test_path" in out
    assert "1/1 entries pass the guard" in out
    path = tmp_path / "set.json"
    capsys.readouterr()
    assert main(["ctxset", "lint", str(path), "--clone", str(pyrepo.path), "--json"]) == 0
    ((entry,),) = (json.loads(capsys.readouterr().out)["entries"],)
    assert entry["reasons"] == [] and "plan_test_path" in entry["would_refuse"]
    guarded = plan_doc(tasks=[task.task_id], plan=leaky, source_rev=parent)
    code, out, _ = _lint(guarded, pyrepo, tmp_path, capsys)
    assert code == 2 and "audited bypass" not in out


def test_show_prints_an_audited_sets_record() -> None:
    lines = cmd._meta_lines(
        {
            "name": "ctx.plan-audited.0123456789ab",
            "source": "plan-audited",
            "tasks": 1,
            "repo": "cobra",
            "digest": "0" * 64,
            "arm": "A0+library@ctx.plan-audited.0123456789ab",
            "audited": True,
            "audit_record_sha256": "a" * 64,
        }
    )
    assert any(line == f"audited    yes (record {'a' * 12})" for line in lines)


def test_show_prints_a_stated_sets_structure_and_items_digest() -> None:
    cset = ctxset.parse(req_doc())
    lines = cmd._meta_lines(
        {
            "name": cset.name,
            "source": cset.source,
            "tasks": len(cset.task_ids),
            "repo": cset.repo,
            "digest": cset.digest,
            "arm": cset.arm,
            "stated": True,
            "structure": cset.structure,
            "saw": list(cset.saw),
            "items_digest": cset.items_digest,
        }
    )
    assert any(line.startswith("stated     prose") for line in lines)
    assert any(cset.items_digest in line for line in lines)


def test_compare_prints_the_stated_banner_provenance_cost_and_drift() -> None:
    side = {"k": 1, "n": 4, "ci_low": 0.05, "ci_high": 0.7}
    d = {
        "banner": cc.STATED_BANNER,
        "provenance": {st.PROV_NOWHERE: 4},
        "control_arm": "A0",
        "treatment_arm": "A0+library@ctx.req.0123456789ab",
        "control": side,
        "treatment": side,
        "b": 0,
        "c": 0,
        "p": 1.0,
        "cost": {"paired_cost_usd_diff": {"n": 4, "median": 0.1, "iqr": [0.0, 0.2]}},
        "drift": True,
    }
    lines = cmd.compare_lines(d)
    assert lines[0] == cc.STATED_BANNER and lines[1].startswith("provenance ")
    assert any(line.startswith("paired cost diff") for line in lines)
    assert lines[-1].startswith("drift:")
    # a task unpriced on either side is shown as unpriced, never folded into n
    d["cost"] = {"paired_cost_usd_diff": {"n": 0, "n_missing": 2, "median": None}}
    assert "paired cost diff (usd) median None n 0 (unpriced 2)" in cmd.compare_lines(d)


def test_a_non_ascii_changed_path_is_read_not_display_quoted(tmp_path: Path) -> None:
    """Review 4580935916: git display-quotes a non-ASCII path (``"src/caf\\303\\251.py"``);
    read so, the view finds no such file and an undeclared identifier added there lints ok."""
    import subprocess

    root = tmp_path / "repo"
    root.mkdir()

    def git(*args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(root), *args], check=True, capture_output=True, text=True
        ).stdout.strip()

    git("init", "-q")
    git("config", "user.email", "fixture@example.invalid")
    git("config", "user.name", "fixture")
    git("config", "core.quotePath", "true")
    (root / "src").mkdir()
    (root / "tests").mkdir()
    src, test = root / "src" / "café.py", root / "tests" / "test_café.py"
    src.write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    test.write_text("def test_add():\n    assert True\n", encoding="utf-8")
    git("add", "-A")
    git("commit", "-q", "-m", "parent")
    src.write_text(src.read_text() + "\n\ndef subtract(a, b):\n    return a - b\n")
    git("add", "-A")
    git("commit", "-q", "-m", "change")
    sha = git("rev-parse", "HEAD")
    ((tid, reasons),) = cmd.lint_set(req_doc(tasks=[sha], statement=LEAK), root)
    assert tid == sha and st.REASON_UNDECLARED_NOVEL in reasons


def test_an_asserted_literal_is_withheld_unless_the_commit_message_states_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """``req_asserted_literal`` reads the commit message as the request: an item repeating a
    literal the held-out test asserts is withheld, with the advice line, until the message
    states that text itself."""
    import subprocess

    root = tmp_path / "repo"
    root.mkdir()

    def git(*args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(root), *args], check=True, capture_output=True, text=True
        ).stdout.strip()

    git("init", "-q")
    git("config", "user.email", "fixture@example.invalid")
    git("config", "user.name", "fixture")
    (root / "tests").mkdir()
    # the parent holds each word of the statement, never four of the literal's in a row
    words = "# Dividing fails with the text: here zero, divide or cannot.\n"
    (root / "calc.py").write_text(words + "def div(a, b):\n    return a / b\n", encoding="utf-8")
    test = root / "tests" / "test_calc.py"
    test.write_text("def test_div():\n    assert True\n", encoding="utf-8")
    git("add", "-A")
    git("commit", "-q", "-m", "parent")
    parent = git("rev-parse", "HEAD")
    asserted = "    with pytest.raises(ValueError, match='cannot divide %s by zero here'):\n"
    changed = test.read_text() + asserted + "        div(1, 0)\n"
    statement = "Dividing by zero fails with the text: Cannot divide by zero here"
    for message, withheld in (
        ("fix: refuse a zero divisor", True),
        ("fix: refuse a zero divisor\n\nSay: cannot divide by zero here.", False),
    ):
        git("checkout", "-q", "--detach", parent)
        test.write_text(changed, encoding="utf-8")
        git("add", "-A")
        git("commit", "-q", "-m", message)
        sha = git("rev-parse", "HEAD")
        path = tmp_path / "set.json"
        path.write_text(json.dumps(req_doc(tasks=[sha], statement=statement)), encoding="utf-8")
        capsys.readouterr()
        code = main(["ctxset", "lint", str(path), "--clone", str(root)])
        out = capsys.readouterr().out
        assert (code == 2) is withheld, out
        assert (st.ASSERTED_LITERAL_ADVICE in out) is withheld, out
