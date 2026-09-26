"""Belt 6 ``api_stable`` inside the grader and the ledger, on real fixture repositories.

Navigation
----------
What it is:   The falsifiable tests of belt 6 end to end: a Go module, a Python package and a
              Node package, each graded for real (``go test``, ``pytest``, ``node --test``) with
              the belt switched on, and the row the grade becomes.
What it does: Pins, per language, that an exported-signature change the gold did not make
              fails the belt (not clean, failure kind ``api``); that the gold's own API change
              made the same way passes; that a private change never fails it; that the belt is
              OFF by default and then leaves the grade and the row byte-for-byte as before; and
              that the ledger refuses a clean row whose label records belt 6 failed.
How:          Fixture repositories from ``tests/fixtures`` (the gold adds ``Sub`` / ``subtract``
              / ``sub``); the trial is the gold plus an edit; ``grade(..., evaluate_api=True)``;
              ``grade_row_from_result`` for the row.
Layer:        tests — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0024-working-by-construction.md,
              docs/adr/0001-four-belts-and-false-q1-at-write.md
Works with:   src/crb/core/grade.py (belt 6 folded into clean), src/crb/core/api_surface.py
              (the extractors), src/crb/core/ledger.py (the ``api`` kind and the label
              invariant), tests/fixtures/langs/gorepo.py (the Go repository),
              tests/fixtures/pyrepo.py (the Python repository), tests/fixtures/langs/noderepo.py
              (the JS repository)
Tested by:    tests/test_grade_api_belt.py
Touch when:   the clean rule, the failure-kind order or belt 6's recording changes.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from crb.core import grade as g
from crb.core.execution import LocalExecutor
from crb.core.git import GitRepo
from crb.core.ledger import (
    FAILURE_API,
    FAILURE_LINT,
    FalseQ1Violation,
    GradeRow,
    derive_failure_kind,
    failure_split,
    grade_row_from_result,
)
from crb.core.runners import get_runner
from crb.core.runners.pytest_runner import PytestRunner
from crb.core.spec import RepoConfig, TaskSpec
from crb.core.workspace import Workspace
from fixtures import pyrepo as pr

try:
    from tests import conftest_langs as langs
except ImportError:  # pragma: no cover - run from tests/ as the rootdir
    import conftest_langs as langs  # type: ignore[no-redef]


def _lang_task(feat_sha: str, config: RepoConfig, test_file: str, src: str) -> TaskSpec:
    r = get_runner(config)
    target = r.target_scope([test_file])
    return TaskSpec(
        task_id=feat_sha,
        repo=config.name,
        subject="feat: add sub",
        authored="2026-01-01T00:00:00+00:00",
        test_files=(test_file,),
        src_files=(src,),
        target_tests=target,
        belt_scope=r.belt_scope(target, [test_file]),
        language=config.language.value,
        red_checked=True,
    )


def _trial(tmp_path: Path, root: Path, sha: str, cfg: RepoConfig, test: str, src: str) -> Workspace:
    ws = Workspace.create(GitRepo(root), sha, tmp_path / "trial", config=cfg)
    ws.overlay_tests([test])
    ws.overlay_sources([src])  # the gold: belts 1–4 hold
    return ws


def _edit(ws: Workspace, rel: str, old: str, new: str) -> None:
    p = ws.root / rel
    text = p.read_text(encoding="utf-8")
    assert old in text, (rel, old)
    p.write_text(text.replace(old, new), encoding="utf-8")


# --- Go -------------------------------------------------------------------------------------

GO_CASES = {
    # the gold's Sub, and nothing else: the change the task asked for, made the same way
    "gold": (None, True, ""),
    # an exported signature the gold never changed: Add gains a variadic (tests still pass)
    "exported": (
        ("calc/calc.go", "func Add(a, b int) int", "func Add(a, b int, more ...int) int"),
        False,
        "changed:calc:Add",
    ),
    # a private helper: never API
    "private": (
        (
            "calc/calc.go",
            "func Add(a, b int) int { return a + b }",
            "func Add(a, b int) int { return add(a, b) }\n\n"
            "func add(a, b int) int { return a + b }",
        ),
        True,
        "",
    ),
}


@pytest.mark.skipif(not langs.has_tool("go"), reason="go not on PATH")
@pytest.mark.toolchain("go")
@pytest.mark.parametrize("case", sorted(GO_CASES))
def test_go_belt_six(tmp_path: Path, executor: LocalExecutor, case: str) -> None:
    gorepo = langs.fixture_module("gorepo")
    root, sha = gorepo.build(tmp_path)
    cfg = gorepo.config()
    edit, ok, finding = GO_CASES[case]
    ws = _trial(tmp_path, root, sha, cfg, gorepo.TEST_SUB, gorepo.SRC_SUB)
    try:
        if edit:
            _edit(ws, *edit)
        task = _lang_task(sha, cfg, gorepo.TEST_SUB, gorepo.SRC_SUB)
        res = g.grade(
            ws, task, config=cfg, runner=get_runner(cfg), executor=executor, evaluate_api=True
        )
        assert res.belts.target_green is True and res.belts.no_new_failures is True
        assert res.belts.api_stable is ok, res.to_dict()
        assert res.clean is ok
        assert res.api_run is not None
        if finding:
            assert [f.label for f in res.api_run.findings] == [finding]
            row = grade_row_from_result(res, task, pack_hash="p" * 64)
            assert row.failure_kind == FAILURE_API and row.labels["api_stable"] == "false"
            assert row.labels["api_findings"] == finding
        else:
            assert res.api_run.matched == 1  # the gold's Sub, mirrored
    finally:
        ws.remove()


# --- Python ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("old", "new", "ok"),
    [
        ("", "", True),  # the gold as it is
        (
            "def add(a: int, b: int) -> int:",
            "def add(a: int, b: int, *, strict: bool = False) -> int:",
            False,
        ),
        (
            "def subtract(a: int, b: int) -> int:",
            "def subtract(a: int, b: int, c: int = 0) -> int:",
            False,  # the gold adds subtract(a, b) — a different signature is a divergence
        ),
        (
            "    return a + b\n",
            "    return _plus(a, b)\n\n\ndef _plus(a, b):\n    return a + b\n",
            True,
        ),
    ],
    ids=["gold", "exported-change", "divergent-addition", "private-helper"],
)
def test_python_belt_six(
    pyrepo: pr.PyRepo,
    runner: PytestRunner,
    executor: LocalExecutor,
    tmp_path: Path,
    old: str,
    new: str,
    ok: bool,
) -> None:
    task = pyrepo.feat_task()
    ws = pyrepo.trial(tmp_path / "trial")
    try:
        ws.overlay_sources([pr.SRC])
        if old:
            _edit(ws, pr.SRC, old, new)
        res = g.grade(
            ws, task, config=pyrepo.config, runner=runner, executor=executor, evaluate_api=True
        )
        assert res.belts.target_green is True, res.to_dict()
        assert res.belts.api_stable is ok and res.clean is ok
        row = grade_row_from_result(res, task, pack_hash="p" * 64)
        assert row.labels["api_stable"] == ("true" if ok else "false")
        assert row.failure_kind == ("" if ok else FAILURE_API)
    finally:
        ws.remove()


def test_belt_six_is_off_by_default_and_then_the_grade_and_row_are_unchanged(
    pyrepo: pr.PyRepo, runner: PytestRunner, executor: LocalExecutor, tmp_path: Path
) -> None:
    task = pyrepo.feat_task()
    ws = pyrepo.trial(tmp_path / "trial")
    try:
        ws.overlay_sources([pr.SRC])
        _edit(ws, pr.SRC, "def add(a: int, b: int)", "def add(a: int, b: int, c: int = 0)")
        res = g.grade(ws, task, config=pyrepo.config, runner=runner, executor=executor)
        assert res.clean is True and res.api_run is None and res.belts.api_stable is None
        d = res.to_dict()
        assert "api_stable" not in d and "api_run" not in d
        row = grade_row_from_result(res, task, pack_hash="p" * 64)
        assert "api_stable" not in row.labels and "api_findings" not in row.labels
    finally:
        ws.remove()


# --- Node -----------------------------------------------------------------------------------


@pytest.mark.skipif(not langs.has_tool("node"), reason="node not on PATH")
@pytest.mark.toolchain("node")
@pytest.mark.parametrize(
    ("edit", "ok"),
    [
        (None, True),
        (("function add(a, b) {", "function add(a, b, c) {"), False),
        (
            ("function add(a, b) {\n  return a + b;", "function add(a, b) {\n  return plus(a, b);"),
            True,
        ),
    ],
    ids=["gold", "exported-arity", "private-body"],
)
def test_node_belt_six(
    tmp_path: Path, executor: LocalExecutor, edit: tuple[str, str] | None, ok: bool
) -> None:
    noderepo = langs.fixture_module("noderepo")
    root, sha = noderepo.build(tmp_path, "node")
    cfg = noderepo.config("node")
    test_file, src = noderepo.test_sub("node"), noderepo.SRC_SUB
    ws = _trial(tmp_path, root, sha, cfg, test_file, src)
    try:
        if edit:
            old, new = edit
            text = (ws.root / noderepo.SRC_ADD).read_text(encoding="utf-8")
            if "plus(" in new:
                text = text.replace(
                    "module.exports", "function plus(a, b) {\n  return a + b;\n}\n\nmodule.exports"
                )
            (ws.root / noderepo.SRC_ADD).write_text(text.replace(old, new), encoding="utf-8")
        task = _lang_task(sha, cfg, test_file, src)
        res = g.grade(
            ws, task, config=cfg, runner=get_runner(cfg), executor=executor, evaluate_api=True
        )
        assert res.belts.target_green is True and res.belts.no_new_failures is True, res.to_dict()
        assert res.belts.api_stable is ok and res.clean is ok
    finally:
        ws.remove()


# --- the rule order and the ledger ----------------------------------------------------------


def test_api_outranks_lint_and_both_come_after_budget() -> None:
    kind = derive_failure_kind(clean=False, disqualified=False, api_only=True, lint_only=True)
    assert kind == FAILURE_API
    assert derive_failure_kind(clean=False, disqualified=False, lint_only=True) == FAILURE_LINT
    assert (
        derive_failure_kind(clean=False, disqualified=False, stop_reason="max_turns", api_only=True)
        == "budget"
    )


def test_a_clean_row_that_records_belt_six_failed_is_a_false_q1() -> None:
    with pytest.raises(FalseQ1Violation, match="api_stable"):
        GradeRow(
            repo="r",
            task_id="a" * 40,
            clean=True,
            tests_unmodified=True,
            target_green=True,
            no_new_failures=True,
            source_changed=True,
            evidence_pack_hash="p" * 64,
            labels={"api_stable": "false"},
        )
    # and a GradeResult cannot be built clean with belt 6 False
    with pytest.raises(g.FalseQ1Violation):
        g.GradeResult("a" * 40, "r", "sighted", True, g.Belts(True, True, True, True, None, False))


def test_an_unpinned_row_derives_api_from_its_label_and_the_split_counts_it() -> None:
    row = GradeRow(
        repo="r",
        task_id="b" * 40,
        clean=False,
        tests_unmodified=True,
        target_green=True,
        no_new_failures=True,
        source_changed=True,
        evidence_pack_hash="p" * 64,
        labels={"api_stable": "false"},
    )
    assert row.failure_kind == FAILURE_API
    split = failure_split([row])
    assert split.api == 1 and split.n == 1 and split.model_n == 1
    assert split.to_dict()["api"] == 1
