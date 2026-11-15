"""``crb ctxset lint`` and the stated lines of ``show``/``compare`` (ADR-0052).

Navigation
----------
What it is:   The CLI suite for the offline ``crb ctxset lint FILE --clone DIR`` and the
              stated-set lines ``_meta_lines`` and ``compare_lines`` print.
What it does: Pins that a guard-clean stated entry lints ``ok`` (exit 0), that an undeclared
              answer is reported with ``req_undeclared_novel`` (exit 2), that a parse refusal
              is a one-line error naming its reason, that a non-stated set has nothing to
              guard, and that the stated banner, provenance, cost and drift lines print.
How:          The pyrepo ``feat: add subtract`` commit (tests/fixtures/pyrepo.py) as the clone;
              documents from tests/fixtures/ctx_rows.py; ``crb.cli.main.main``.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0052-stated-requirement-arms.md
Works with:   src/crb/cli/commands/ctxset.py (under test), src/crb/builders/brief.py
              (``req_guard``), tests/test_cli_ctxset.py
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
from fixtures.ctx_rows import ctx_doc, req_doc

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


def test_a_parse_refusal_is_a_one_line_error(
    pyrepo: pr.PyRepo, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    doc = req_doc(tasks=[pyrepo.feat_task().task_id], structure="table")
    code, _, err = _lint(doc, pyrepo, tmp_path, capsys)
    assert code == 2 and "refused " in err


def test_a_non_stated_set_has_nothing_to_guard(pyrepo: pr.PyRepo) -> None:
    assert cmd.lint_set(ctx_doc(tasks=[pyrepo.feat_task().task_id]), pyrepo.path) == []


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
