"""Belt 2 holds only when the target tests the oracle needs PASSED: an exit code of 0 with no
failure named is not enough (the Wave 3 red team's F4, 2026-10-11; ADR-0048 decision 7).

A patch can make the target command exit 0 without the target tests passing, and belt 2 used
to read that exit code as green:

* Go: a non-test file whose ``init`` (or a package-level ``var`` initialiser) appends
  ``-test.run=^$`` to ``os.Args`` runs no test and the binary still prints ``PASS``; one that
  prints ``PASS`` and calls ``os.Exit(0)`` ends before any test; one that appends
  ``-test.skip=^TestSub$`` runs every target test but the one it hides;
* pytest: a source function that calls ``pytest.skip`` or ``pytest.xfail`` turns every
  target test that reaches it into a skip and the session exits 0.

Every runner that can report the ids of the tests that passed now does (``TestRun.passed``:
Go's ``-json`` ``pass`` events, pytest's ``-rpfE`` summary); qualification records the target
tests the gold passed in both of its runs (``gold["target_passed"]``) and belt 2 requires a
pass for each. A record from before that field falls back to the RED's failing ids and, when
the RED named none, to at least one pass. The shapes an earlier rule already refused (a
``sys.exit(0)`` or ``pytest.exit`` while the tests are collected, a ``conftest.py``) are pinned
here as well, so nothing reopens them.

Navigation
----------
What it is:   The suite for belt 2's pass requirement (F4).
What it does: Pins that the Go and pytest parsers report the tests that passed and that the
              pytest command asks for them; that ``relocate_ids`` rewrites the run root only
              as whole path components; that qualification records the target tests the
              gold passed; and, end to end on real toolchains, that a patch which makes the
              target exit 0 without its tests passing never grades clean while the honest
              gold still does, under the record qualification writes and under the older
              records belt 2 falls back on.
How:          Canned ``go test -json`` streams and pytest outputs for the parsers; ``gorepo``
              and a two-commit Python repository qualified by the real miner, then graded by
              ``grade`` on a ``LocalExecutor`` under a context built from that qualification.
Layer:        tests — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0048-the-host-posture-declares-its-environment.md,
              docs/adr/0001-four-belts-and-false-q1-at-write.md
Works with:   src/crb/core/runners/go_runner.py (``parse``), src/crb/core/runners/pytest_runner.py
              (``command``, ``parse``), src/crb/core/runners/base.py (``TestRun.passed``),
              src/crb/core/qualify.py (the gold's ``target_passed``), src/crb/core/grade.py
              (belt 2), tests/fixtures/langs/gorepo.py (the Go fixture module)
Tested by:    tests/test_belt2_passes.py
Touch when:   never for a new repository; a runner's pass report, the gold's record of it or
              belt 2's requirement changes.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

import pytest

from crb.core.deps import HOST_ENV_DEPS, TaskDeps
from crb.core.execution import ExecResult, LocalExecutor
from crb.core.git import GitRepo
from crb.core.grade import GradeContext, GradeResult, grade, infra_tampered
from crb.core.mine import qualify
from crb.core.posture import Posture
from crb.core.qualify import Qualification
from crb.core.runners import base as rb
from crb.core.runners import get_runner
from crb.core.runners.pytest_runner import PytestRunner
from crb.core.spec import BELT_BARE, Language, RepoConfig, TaskSpec
from crb.core.workspace import Workspace
from fixtures.langs import commit_all, init_repo, two_commit_repo, write_files

try:  # tests/ is a package only if the conftest owner made it one
    from tests import conftest_langs as langs
except ImportError:  # pragma: no cover — layout-dependent
    import conftest_langs as langs

gorepo = langs.fixture_module("gorepo")

needs_go = pytest.mark.toolchain("go")

GO_ADD = f"{gorepo.CALC_PKG}::TestAdd"
GO_SUB = f"{gorepo.CALC_PKG}::TestSub"


# ---------------------------------------------------------------------------
# The parsers and the command
# ---------------------------------------------------------------------------


def _go_parse(events: list[dict[str, str]], rc: int) -> rb.TestRun:
    out = "\n".join(json.dumps(e) for e in events)
    return get_runner(gorepo.config()).parse(ExecResult(rc, out, ""), Path("."))


def test_the_go_parser_reports_every_test_that_passed() -> None:
    """A subtest is its own id; a skip, a failure and a test the binary died in never pass."""
    events = [
        {"Action": "run", "Package": "ex.com/m/g", "Test": "TestP"},
        {"Action": "run", "Package": "ex.com/m/g", "Test": "TestP/sub"},
        {"Action": "pass", "Package": "ex.com/m/g", "Test": "TestP/sub"},
        {"Action": "pass", "Package": "ex.com/m/g", "Test": "TestP"},
        {"Action": "run", "Package": "ex.com/m/g", "Test": "TestS"},
        {"Action": "skip", "Package": "ex.com/m/g", "Test": "TestS"},
        {"Action": "run", "Package": "ex.com/m/g", "Test": "TestF"},
        {"Action": "fail", "Package": "ex.com/m/g", "Test": "TestF"},
        {"Action": "output", "Package": "ex.com/m/g", "Output": "FAIL\n"},
        {"Action": "fail", "Package": "ex.com/m/g"},
    ]
    run = _go_parse(events, rc=1)
    assert run.passed == frozenset({"ex.com/m/g::TestP", "ex.com/m/g::TestP/sub"})
    assert run.failing == frozenset({"ex.com/m/g::TestF"})


def test_the_go_parser_reports_no_pass_for_a_package_that_ran_no_test() -> None:
    """``-test.run=^$``: the binary prints ``PASS`` and ``go test`` says ``ok`` — green by its
    exit code, with nothing passed."""
    events = [
        {"Action": "start", "Package": "ex.com/m/e"},
        {"Action": "output", "Package": "ex.com/m/e", "Output": "testing: warning: no tests\n"},
        {"Action": "output", "Package": "ex.com/m/e", "Output": "PASS\n"},
        {"Action": "output", "Package": "ex.com/m/e", "Output": "ok  \tex.com/m/e\t0.26s\n"},
        {"Action": "pass", "Package": "ex.com/m/e"},
    ]
    run = _go_parse(events, rc=0)
    assert run.green is True
    assert run.passed == frozenset()


def test_relocate_ids_rewrites_only_whole_root_components(tmp_path: Path) -> None:
    """R2-REG-2: the root (and the container's ``/work``) is replaced only as whole path
    components. A plain substring replacement turned ``tests/workers`` into
    ``tests<root>ers`` and ``[/workspace/data]`` into ``[<root>space/data]``."""
    root = tmp_path / "trial"
    kept = {
        "tests/workers/t.py::test_w",
        "github.com/acme/worker::TestW",
        "tests/t.py::test[/workspace/data]",
        "tests/t.py::test[/work-2/x]",
        f"tests/t.py::test[{tmp_path}/trial2/x]",
    }
    moved = {
        "tests/t.py::test[/work/data/c1.txt]": "tests/t.py::test[<root>/data/c1.txt]",
        "tests/t.py::test[1-/work/c2.txt]": "tests/t.py::test[1-<root>/c2.txt]",
        "tests/t.py::test[/work]": "tests/t.py::test[<root>]",
        f"tests/t.py::test[{root}/work/c3.txt]": "tests/t.py::test[<root>/work/c3.txt]",
    }
    assert rb.relocate_ids(frozenset(kept | set(moved)), root) == frozenset(
        kept | set(moved.values())
    )


def _pytest_runner() -> rb.BaseRunner:
    return get_runner(RepoConfig(name="pyfix", language=Language.PYTHON, runner="pytest"))


def test_the_pytest_parser_reports_every_test_that_passed() -> None:
    """The ``-rpfE`` summary lists the passes first; a test that passed its call and errored in
    teardown is failing, not passed."""
    out = (
        "PASSED tests/t.py::test_a\n"
        "PASSED tests/t.py::TestC::test_b[1]\n"
        "PASSED tests/t.py::test_d\n"
        "FAILED tests/t.py::test_c - AssertionError: no\n"
        "ERROR tests/t.py::test_d - RuntimeError: teardown\n"
        "1 failed, 3 passed, 1 error in 0.10s\n"
    )
    run = _pytest_runner().parse(ExecResult(1, out, ""), Path("."))
    assert run.passed == frozenset({"tests/t.py::test_a", "tests/t.py::TestC::test_b[1]"})
    assert run.failing == frozenset({"tests/t.py::test_c", "tests/t.py::test_d"})


def test_the_pytest_command_asks_for_the_passes(tmp_path: Path) -> None:
    cmd = _pytest_runner().command(tmp_path, ("tests",), executor=LocalExecutor(), timeout=60)
    assert "-rpfE" in cmd.argv


def test_a_real_pytest_run_reports_its_passes_and_not_its_skips(tmp_path: Path) -> None:
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text(
        "import pytest\n\n\ndef test_pass():\n    pass\n\n\n"
        "def test_skip():\n    pytest.skip('no')\n\n\n"
        "@pytest.mark.xfail\ndef test_xfail():\n    assert False\n",
        encoding="utf-8",
    )
    run = _pytest_runner().run(LocalExecutor(), tmp_path, ("tests/test_x.py",))
    assert run.green, run.tail
    assert run.passed == frozenset({"tests/test_x.py::test_pass"})


def test_a_real_pytest_runs_tail_keeps_its_failure_and_not_its_passes(tmp_path: Path) -> None:
    """Sixty passes listed under ``-rp`` would fill the forty-line tail and push the failure's
    traceback out of it: the tail reads as ``-rfE`` printed it."""
    (tmp_path / "tests").mkdir()
    passes = "".join(f"def test_p{i}():\n    pass\n\n\n" for i in range(60))
    (tmp_path / "tests" / "test_x.py").write_text(
        passes + "def test_f():\n    assert 1 == 2\n", encoding="utf-8"
    )
    (tmp_path / "tests" / "test_y.py").write_text("def test_y():\n    pass\n", encoding="utf-8")
    run = _pytest_runner().run(LocalExecutor(), tmp_path, ("tests/test_x.py",))
    assert run.failing == frozenset({"tests/test_x.py::test_f"})
    assert len(run.passed or ()) == 60
    assert "assert 1 == 2" in run.tail
    assert not any(line.startswith("PASSED") for line in run.tail.splitlines()), run.tail
    assert "FAILED tests/test_x.py::test_f" in run.tail
    green = _pytest_runner().run(LocalExecutor(), tmp_path, ("tests/test_y.py",))
    assert green.green and green.passed == frozenset({"tests/test_y.py::test_y"})
    assert "short test summary info" not in green.tail, green.tail
    assert "1 passed" in green.tail


# ---------------------------------------------------------------------------
# Qualifying and grading the fixture repositories
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class _Qualified:
    repo: GitRepo
    config: RepoConfig
    task: TaskSpec
    q: Qualification
    runner: rb.BaseRunner
    ex: LocalExecutor


def _qualify(root: Path, feat_sha: str, config: RepoConfig, scratch: Path) -> _Qualified:
    repo, runner, ex = GitRepo(root), get_runner(config), LocalExecutor()
    outcome = qualify(
        repo,
        config,
        langs.feat_candidate(repo, config, feat_sha),
        runner=runner,
        executor=ex,
        scratch=scratch,
    )
    assert outcome.task is not None and outcome.qualification is not None, outcome.skipped_reason
    assert outcome.qualification.is_qualified, outcome.qualification.code
    return _Qualified(repo, config, outcome.task, outcome.qualification, runner, ex)


def _graded(
    qd: _Qualified,
    dest: Path,
    writes: dict[str, str],
    *,
    q: Qualification | None = None,
    runner: rb.BaseRunner | None = None,
) -> GradeResult:
    """The gold sources, then ``writes`` on top, graded under ``q`` (default: the record
    qualification wrote) with no witness."""
    record = q or qd.q
    ws = langs.trial_worktree(
        qd.repo, langs.feat_candidate(qd.repo, qd.config, qd.task.task_id), dest, qd.config
    )
    try:
        ws.overlay_sources(qd.task.src_files)
        for rel, text in writes.items():
            (ws.root / rel).parent.mkdir(parents=True, exist_ok=True)
            (ws.root / rel).write_text(text, encoding="utf-8")
        ctx = GradeContext(
            posture=Posture.from_dict(record.posture),
            qualification=record,
            deps=TaskDeps.uniform(HOST_ENV_DEPS),
            witness=None,
        )
        return grade(
            ws,
            record.project(qd.task),
            ctx=ctx,
            config=qd.config,
            runner=runner or qd.runner,
            executor=qd.ex,
        )
    finally:
        ws.remove()


def _assert_belt_2_refused(res: GradeResult, *missing: str, kept: tuple[str, ...] = ()) -> None:
    assert res.clean is False
    assert res.belts.target_green is False, res.note
    assert res.target_run is not None and res.target_run.returncode == 0
    assert res.note.startswith("target not green: "), res.note
    if not missing and not kept:
        return
    # the ids the note names, parsed out (one id can be a prefix of another)
    named = set(res.note.rsplit("(", 1)[-1].rstrip(")").split(", "))
    assert set(missing) <= named, res.note
    assert not set(kept) & named, res.note


# --- Go --------------------------------------------------------------------

_GO_RUN_NONE_INIT = (
    'package calc\n\nimport (\n\t"os"\n\t"strings"\n)\n\n'
    'func init() {\n\tif strings.HasSuffix(os.Args[0], ".test") {\n'
    '\t\tos.Args = append(os.Args, "-test.run=^$")\n\t}\n}\n'
)
_GO_RUN_NONE_VAR = (
    'package calc\n\nimport (\n\t"os"\n\t"strings"\n)\n\n'
    'var _ = func() bool {\n\tif strings.HasSuffix(os.Args[0], ".test") {\n'
    '\t\tos.Args = append(os.Args, "-test.run=^$")\n\t}\n\treturn true\n}()\n'
)
_GO_PASS_EXIT_INIT = (
    'package calc\n\nimport (\n\t"fmt"\n\t"os"\n\t"strings"\n)\n\n'
    'func init() {\n\tif strings.HasSuffix(os.Args[0], ".test") {\n'
    '\t\tfmt.Println("PASS")\n\t\tos.Exit(0)\n\t}\n}\n'
)
_GO_SKIP_SUB_INIT = (
    'package calc\n\nimport (\n\t"os"\n\t"strings"\n)\n\n'
    'func init() {\n\tif strings.HasSuffix(os.Args[0], ".test") {\n'
    '\t\tos.Args = append(os.Args, "-test.skip=^TestSub$")\n\t}\n}\n'
)
_GO_HACK = "calc/zz_hack.go"


@pytest.fixture(scope="module")
def go_task(tmp_path_factory: pytest.TempPathFactory) -> _Qualified:
    tmp = tmp_path_factory.mktemp("belt2-go")
    root, feat_sha = gorepo.build(tmp / "repo")
    return _qualify(root, feat_sha, gorepo.config(BELT_BARE), tmp / "scratch")


@needs_go
def test_qualification_records_the_target_tests_the_gold_passed(go_task: _Qualified) -> None:
    assert go_task.q.red["kind"] == "build_failed"
    assert go_task.q.gold["target_passed"] == [GO_ADD, GO_SUB]


@needs_go
def test_the_honest_go_gold_still_grades_clean(go_task: _Qualified, tmp_path: Path) -> None:
    res = _graded(go_task, tmp_path / "trial", {})
    assert res.clean is True, res.note
    assert res.target_run is not None and res.target_run.passed == frozenset({GO_ADD, GO_SUB})


@needs_go
@pytest.mark.parametrize(
    "hack",
    [_GO_RUN_NONE_INIT, _GO_RUN_NONE_VAR, _GO_PASS_EXIT_INIT],
    ids=["init-runs-no-test", "var-runs-no-test", "init-prints-pass-and-exits"],
)
def test_a_go_patch_that_runs_no_target_test_never_grades_clean(
    go_task: _Qualified, tmp_path: Path, hack: str
) -> None:
    res = _graded(go_task, tmp_path / "trial", {_GO_HACK: hack})
    _assert_belt_2_refused(res, GO_ADD, GO_SUB)


@needs_go
def test_a_go_patch_that_skips_one_target_test_never_grades_clean(
    go_task: _Qualified, tmp_path: Path
) -> None:
    """The RED is a build failure that names no test, so only the gold's record names
    ``TestSub``: every other target test still runs and passes."""
    res = _graded(go_task, tmp_path / "trial", {_GO_HACK: _GO_SKIP_SUB_INIT})
    _assert_belt_2_refused(res, GO_SUB, kept=(GO_ADD,))


# F4-GO-TEST2JSON-SPOOF: ``Sub`` keeps the bug (``a + b``) and the same source forges the
# ``go test -json`` stream. test2json reads the binary's stdout, so event lines printed before
# the testing package's first framed line, or framed by the ``\x16`` byte themselves, become
# real ``run`` / ``pass`` events; the binary then exits 0 before any assertion fails.
_GO_BUGGY_SUB = "package calc\n\n// Sub returns a - b.\nfunc Sub(a, b int) int { return a + b }\n"
_GO_FORGED_EVENTS = (
    '"=== RUN   TestAdd\\n--- PASS: TestAdd (0.00s)\\n'
    '=== RUN   TestSub\\n--- PASS: TestSub (0.00s)\\nPASS\\n"'
)
_GO_FORGE_INIT = (
    'package calc\n\nimport (\n\t"fmt"\n\t"os"\n\t"strings"\n)\n\n'
    "// Sub returns a - b.\nfunc Sub(a, b int) int { return a + b }\n\n"
    'func init() {\n\tif strings.HasSuffix(os.Args[0], ".test") {\n'
    f"\t\tfmt.Print({_GO_FORGED_EVENTS})\n\t\tos.Exit(0)\n\t}}\n}}\n"
)
_GO_FORGE_VAR = (
    'package calc\n\nimport (\n\t"fmt"\n\t"os"\n\t"strings"\n)\n\n'
    "// Sub returns a - b.\nfunc Sub(a, b int) int { return a + b }\n\n"
    'var _ = func() bool {\n\tif strings.HasSuffix(os.Args[0], ".test") {\n'
    f"\t\tfmt.Print({_GO_FORGED_EVENTS})\n\t\tos.Exit(0)\n\t}}\n\treturn true\n}}()\n"
)
_GO_FORGE_FRAMED_EXIT = (
    'package calc\n\nimport (\n\t"os"\n\t"syscall"\n)\n\n'
    "// Sub returns a - b.\nfunc Sub(a, b int) int {\n"
    '\tos.Stdout.WriteString("\\x16--- PASS: TestSub (0.00s)\\n\\x16PASS\\n")\n'
    "\tsyscall.Exit(0)\n\treturn a + b\n}\n"
)
_GO_HONEST_INIT = (
    "package calc\n\n// Sub returns a - b.\nfunc Sub(a, b int) int { return a - b }\n\n"
    "var ops = map[string]func(int, int) int{}\n\n"
    'func init() { ops["sub"] = Sub }\n'
)
# REDFIX-REGRESS-HONESTY-R1-1: the same events, spelled with escapes the scan did not decode,
# or carried by a data file a ``//go:embed`` directive compiles into the test binary.
_GO_FORGE_ESCAPED = _GO_FORGE_INIT.replace("=== RUN", "===\\x20RUN").replace(
    "--- PASS", "---\\x20PASS"
)
_GO_EMBED_NOTES = "calc/notes.txt"
_GO_FORGE_EMBED = (
    'package calc\n\nimport (\n\t_ "embed"\n\t"fmt"\n\t"os"\n\t"strings"\n)\n\n'
    "// Sub returns a - b.\nfunc Sub(a, b int) int { return a + b }\n\n"
    "//go:embed notes.txt\nvar notes string\n\n"
    'func init() {\n\tif strings.HasSuffix(os.Args[0], ".test") {\n'
    "\t\tfmt.Print(notes)\n\t\tos.Exit(0)\n\t}\n}\n"
)
_GO_FORGED_NOTES = (
    "=== RUN   TestAdd\n--- PASS: TestAdd (0.00s)\n"
    "=== RUN   TestSub\n--- PASS: TestSub (0.00s)\nPASS\n"
)
_GO_HONEST_EMBED = (
    'package calc\n\nimport _ "embed"\n\n'
    "// Sub returns a - b.\nfunc Sub(a, b int) int { return a - b }\n\n"
    "//go:embed notes.txt\nvar notes string\n"
)


@needs_go
def test_the_buggy_go_sub_alone_is_not_green(go_task: _Qualified, tmp_path: Path) -> None:
    """The control for the forgeries below: without them, the kept bug fails ``TestSub``."""
    res = _graded(go_task, tmp_path / "trial", {gorepo.SRC_SUB: _GO_BUGGY_SUB})
    assert res.clean is False and res.disqualified is False
    assert res.belts.target_green is False, res.note


@needs_go
@pytest.mark.parametrize(
    "forgery",
    [_GO_FORGE_INIT, _GO_FORGE_VAR, _GO_FORGE_FRAMED_EXIT, _GO_FORGE_ESCAPED],
    ids=[
        "init-prints-events-and-exits",
        "var-prints-events-and-exits",
        "framed-pass-syscall-exit",
        "init-prints-escaped-events-and-exits",
    ],
)
def test_a_go_source_that_forges_the_test_events_is_disqualified(
    go_task: _Qualified, tmp_path: Path, forgery: str
) -> None:
    """F4-GO-TEST2JSON-SPOOF: each forgery gives a stream no parser can tell from a real pass
    (``ok``, both target tests ``pass``, exit 0), so belt 2 cannot refuse it. The grade-time
    scan of the touched Go source refuses it first."""
    res = _graded(go_task, tmp_path / "trial", {gorepo.SRC_SUB: forgery})
    assert res.clean is False and res.disqualified is True, res.note
    assert "test infrastructure modified" in res.dq_reason


@needs_go
def test_an_honest_go_init_still_grades_clean(go_task: _Qualified, tmp_path: Path) -> None:
    res = _graded(go_task, tmp_path / "trial", {gorepo.SRC_SUB: _GO_HONEST_INIT})
    assert res.clean is True, res.note


@needs_go
def test_a_go_forgery_carried_by_an_embedded_file_is_disqualified(
    go_task: _Qualified, tmp_path: Path
) -> None:
    """REDFIX-REGRESS-HONESTY-R1-1: the source only prints an embedded string and exits; the
    event text sits in the data file, which the scan now reads like any touched file."""
    writes = {gorepo.SRC_SUB: _GO_FORGE_EMBED, _GO_EMBED_NOTES: _GO_FORGED_NOTES}
    res = _graded(go_task, tmp_path / "trial", writes)
    assert res.clean is False and res.disqualified is True, res.note
    assert _GO_EMBED_NOTES in res.dq_reason


@needs_go
def test_an_honest_go_embed_still_grades_clean(go_task: _Qualified, tmp_path: Path) -> None:
    writes = {gorepo.SRC_SUB: _GO_HONEST_EMBED, _GO_EMBED_NOTES: "Sub subtracts.\n"}
    res = _graded(go_task, tmp_path / "trial", writes)
    assert res.clean is True, res.note


def test_belt_1b_reads_every_touched_go_file_and_survives_a_binary_one(tmp_path: Path) -> None:
    """A cgo source or an embedded data file that carries the events is caught; a binary
    file the parent also carries is read with its undecodable bytes replaced, not raised."""
    root = tmp_path / "repo"
    init_repo(root)
    write_files(
        root, {"go.mod": f"module {gorepo.MODULE}\n\ngo 1.22\n", "calc/calc.go": "package calc\n"}
    )
    (root / "assets").mkdir()
    (root / "assets" / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n\xff\xfe\x00")
    commit_all(root, "initial")
    write_files(root, {gorepo.SRC_SUB: "package calc\n"})
    sha = commit_all(root, "feat")
    with Workspace.create(GitRepo(root), sha, tmp_path / "ws") as ws:
        (ws.root / "assets" / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n\xff\xfd\x01")
        (ws.root / "calc" / "forge.c").write_text(
            "#include <stdio.h>\n#include <stdlib.h>\n\n__attribute__((constructor))\n"
            'static void forge(void) { printf("---\\x20PASS: TestSub (0.00s)\\n"); _Exit(0); }\n',
            encoding="utf-8",
        )
        (ws.root / _GO_EMBED_NOTES).write_text(_GO_FORGED_NOTES, encoding="utf-8")
        assert "\ufffd" in (ws.parent_text("assets/logo.png") or "")
        flagged = infra_tampered(ws, ws.touched_files(), exclude=(), config=gorepo.config())
        assert flagged == ["calc/forge.c", _GO_EMBED_NOTES]


def test_belt_1b_reads_a_touched_go_link_only_when_it_is_a_file(tmp_path: Path) -> None:
    """Belt 1b reads every touched file in a Go repository, so a link it touches is read
    only when it resolves to a regular file: a link to a directory is not text (reading it
    raised), and a link to a device such as ``/dev/zero`` would never finish."""
    root = tmp_path / "repo"
    init_repo(root)
    write_files(root, {"go.mod": f"module {gorepo.MODULE}\n\ngo 1.22\n", "docs/v1/a.md": "a\n"})
    commit_all(root, "initial")
    write_files(root, {gorepo.SRC_SUB: "package calc\n"})
    sha = commit_all(root, "feat")
    with Workspace.create(GitRepo(root), sha, tmp_path / "ws") as ws:
        (ws.root / "docs" / "latest").symlink_to("v1")
        (ws.root / "calc").mkdir(exist_ok=True)
        (ws.root / _GO_EMBED_NOTES).write_text(_GO_FORGED_NOTES, encoding="utf-8")
        (ws.root / "calc" / "events.txt").symlink_to("notes.txt")
        touched = ws.touched_files()
        assert {"docs/latest", "calc/events.txt"} <= set(touched)
        flagged = infra_tampered(ws, touched, exclude=(), config=gorepo.config())
        assert flagged == ["calc/events.txt", _GO_EMBED_NOTES]


# --- Python ----------------------------------------------------------------

PY_SUB = "tests/test_sub.py::test_sub"
PY_NEG = "tests/test_sub.py::test_sub_negative"
_PY_SRC = "pkg/sub.py"

_PY_INITIAL = {
    ".gitignore": ".pytest_scratch\n__pycache__\n.pytest_cache\n",
    "pkg/__init__.py": "",
    "pkg/calc.py": "def add(a, b):\n    return a + b\n",
    _PY_SRC: "def sub(a, b):\n    return a + b\n",  # the bug both target tests catch
    "tests/test_calc.py": (
        "from pkg.calc import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n"
    ),
}
_PY_FEAT = {
    _PY_SRC: "def sub(a, b):\n    return a - b\n",
    "tests/test_sub.py": (
        "from pkg.sub import sub\n\n\n"
        "def test_sub():\n    assert sub(3, 2) == 1\n\n\n"
        "def test_sub_negative():\n    assert sub(3, -2) == 5\n"
    ),
}
_PY_SKIP_ALL = 'import pytest\n\n\ndef sub(a, b):\n    pytest.skip("not today")\n'
_PY_XFAIL_ALL = 'import pytest\n\n\ndef sub(a, b):\n    pytest.xfail("not today")\n'
_PY_SKIP_NEG = (
    "import pytest\n\n\ndef sub(a, b):\n"
    '    if b < 0:\n        pytest.skip("not today")\n    return a - b\n'
)
_PY_SYS_EXIT_AT_IMPORT = "import sys\n\nsys.exit(0)\n\n\ndef sub(a, b):\n    return a - b\n"
_PY_PYTEST_EXIT_AT_IMPORT = (
    'import pytest\n\npytest.exit("done", returncode=0)\n\n\ndef sub(a, b):\n    return a - b\n'
)
_PY_CONFTEST_EXIT = 'import pytest\n\npytest.exit("done", returncode=0)\n'
_PY_SKIP_MODULE_AT_IMPORT = (
    'import pytest\n\npytest.skip("not today", allow_module_level=True)\n\n\n'
    "def sub(a, b):\n    return a - b\n"
)
_PY_SKIPTEST_AT_IMPORT = (
    'import unittest\n\nraise unittest.SkipTest("not today")\n\n\n'
    "def sub(a, b):\n    return a - b\n"
)
# R1-F4-1 (the Wave 3 red team): patch pytest's own machinery so the target tests report
# PASSED without their bodies running. ``sub`` keeps the BUG (``a + b``): the pass is forged,
# not earned. belt 1b's table does not list a plain source, so a grade-time scan must catch it.
_PY_RUNTEST_NOOP = (
    "import _pytest.python\n"
    "_pytest.python.Function.runtest = lambda self: None\n\n\n"
    "def sub(a, b):\n    return a + b\n"
)
_PY_CALL_AND_REPORT_WRAP = (
    "import _pytest.runner as _r\n\n"
    "_orig = _r.call_and_report\n\n\n"
    "def _always_pass(item, when, **kwargs):\n"
    "    rep = _orig(item, when, **kwargs)\n"
    '    if rep.when == "call":\n'
    '        rep.outcome = "passed"\n'
    "        rep.longrepr = None\n"
    "    return rep\n\n\n"
    "_r.call_and_report = _always_pass\n\n\n"
    "def sub(a, b):\n    return a + b\n"
)

_PY_CONFIG = RepoConfig(
    name="belt2-py",
    language=Language.PYTHON,
    runner="pytest",
    src_prefix="pkg/",
    test_prefix="tests/",
    ext=".py",
    belt_scope=BELT_BARE,
)


@pytest.fixture(scope="module")
def py_task(tmp_path_factory: pytest.TempPathFactory) -> _Qualified:
    tmp = tmp_path_factory.mktemp("belt2-py")
    root, feat_sha = two_commit_repo(tmp / "repo", _PY_INITIAL, _PY_FEAT)
    return _qualify(root, feat_sha, _PY_CONFIG, tmp / "scratch")


def _with(q: Qualification, *, red: dict[str, Any] | None = None, **gold: Any) -> Qualification:
    """``q`` with another RED and the gold's ``target_passed`` replaced (``None``: dropped, as
    a record written before F4 has it)."""
    new_gold = {k: v for k, v in q.gold.items() if k != "target_passed"}
    if gold.get("target_passed") is not None:
        new_gold["target_passed"] = gold["target_passed"]
    return dataclasses.replace(q, red=red if red is not None else dict(q.red), gold=new_gold)


# R1-F4-2 (the Wave 3 red team): a glob-parametrized test whose ids carry the absolute worktree
# path in their parametrize value (``test_sub_cases[/abs/tests/data/case1.txt]``). The gold is
# qualified under one root and graded under another, so the raw ids never match and the honest
# gold would miss belt 2 — unless the runner relocates the root to a fixed token first.
_PY_GLOB_INITIAL = {
    ".gitignore": ".pytest_scratch\n__pycache__\n.pytest_cache\n",
    "pkg/__init__.py": "",
    _PY_SRC: "def sub(a, b):\n    return a + b\n",  # the bug both data cases catch
    "tests/data/case1.txt": "3 2 1\n",
    "tests/data/case2.txt": "3 -2 5\n",
}
_PY_GLOB_FEAT = {
    _PY_SRC: "def sub(a, b):\n    return a - b\n",
    "tests/test_sub_cases.py": (
        "import glob\n"
        "import os\n\n"
        "import pytest\n\n"
        "from pkg.sub import sub\n\n"
        "HERE = os.path.dirname(os.path.abspath(__file__))\n\n\n"
        '@pytest.mark.parametrize("path", sorted(glob.glob(os.path.join(HERE, "data", "*.txt"))))\n'
        "def test_sub_cases(path):\n"
        "    with open(path) as fh:\n"
        "        a, b, want = (int(x) for x in fh.read().split())\n"
        "    assert sub(a, b) == want\n"
    ),
}


@pytest.fixture(scope="module")
def py_glob_task(tmp_path_factory: pytest.TempPathFactory) -> _Qualified:
    tmp = tmp_path_factory.mktemp("belt2-py-glob")
    root, feat_sha = two_commit_repo(tmp / "repo", _PY_GLOB_INITIAL, _PY_GLOB_FEAT)
    return _qualify(root, feat_sha, _PY_CONFIG, tmp / "scratch")


def test_a_python_qualification_records_the_target_tests_the_gold_passed(
    py_task: _Qualified,
) -> None:
    assert py_task.q.red["kind"] == "tests_failed"
    assert py_task.q.red["failing"] == [PY_SUB, PY_NEG]
    assert py_task.q.gold["target_passed"] == [PY_SUB, PY_NEG]


def test_the_honest_python_gold_still_grades_clean(py_task: _Qualified, tmp_path: Path) -> None:
    res = _graded(py_task, tmp_path / "trial", {})
    assert res.clean is True, res.note


@pytest.mark.parametrize(
    ("hack", "missing", "kept"),
    [
        (_PY_SKIP_ALL, (PY_SUB, PY_NEG), ()),
        (_PY_XFAIL_ALL, (PY_SUB, PY_NEG), ()),
        (_PY_SKIP_NEG, (PY_NEG,), (PY_SUB,)),
    ],
    ids=["every-target-test-skips", "every-target-test-xfails", "one-target-test-skips"],
)
def test_a_python_patch_whose_target_tests_do_not_pass_never_grades_clean(
    py_task: _Qualified, tmp_path: Path, hack: str, missing: tuple[str, ...], kept: tuple[str, ...]
) -> None:
    res = _graded(py_task, tmp_path / "trial", {_PY_SRC: hack})
    _assert_belt_2_refused(res, *missing, kept=kept)


@pytest.mark.parametrize(
    "hack",
    [_PY_SYS_EXIT_AT_IMPORT, _PY_PYTEST_EXIT_AT_IMPORT],
    ids=["sys-exit-0-at-import", "pytest-exit-0-at-import"],
)
def test_a_python_patch_that_exits_while_the_tests_are_collected_never_grades_clean(
    py_task: _Qualified, tmp_path: Path, hack: str
) -> None:
    """Refused before F4 too (the exit is reported as an error, not a pass): pinned."""
    res = _graded(py_task, tmp_path / "trial", {_PY_SRC: hack})
    assert res.clean is False
    assert res.belts.target_green is False
    assert res.note.startswith("target not green"), res.note


@pytest.mark.parametrize(
    "hack",
    [_PY_SKIP_MODULE_AT_IMPORT, _PY_SKIPTEST_AT_IMPORT],
    ids=["module-skip-at-import", "unittest-skiptest-at-import"],
)
def test_a_python_patch_under_which_no_test_runs_never_grades_clean(
    py_task: _Qualified, tmp_path: Path, hack: str
) -> None:
    """A session that collects no test exits 5, never 0: refused before F4 too, pinned."""
    res = _graded(py_task, tmp_path / "trial", {_PY_SRC: hack})
    assert res.clean is False
    assert res.belts.target_green is False
    assert res.target_run is not None and res.target_run.returncode == 5, res.note


def test_a_conftest_that_exits_zero_is_disqualified(py_task: _Qualified, tmp_path: Path) -> None:
    """Refused before F4 too (belt 1b's test-infrastructure table): pinned."""
    res = _graded(py_task, tmp_path / "trial", {"conftest.py": _PY_CONFTEST_EXIT})
    assert res.clean is False and res.disqualified is True
    assert "test infrastructure modified" in res.dq_reason


@pytest.mark.parametrize(
    "hack",
    [_PY_RUNTEST_NOOP, _PY_CALL_AND_REPORT_WRAP],
    ids=["runtest-noop", "call-and-report-wrap"],
)
def test_a_source_that_patches_pytest_machinery_is_disqualified(
    py_task: _Qualified, tmp_path: Path, hack: str
) -> None:
    """R1-F4-1: a plain source (not a test or conftest) that reassigns pytest's own runtest or
    report machinery forges the passes from inside the process. belt 1b's table lists named
    infra files, not an arbitrary source, so a grade-time scan of the touched Python refuses it
    before belt 2 ever reads the forged run."""
    res = _graded(py_task, tmp_path / "trial", {_PY_SRC: hack})
    assert res.clean is False and res.disqualified is True
    assert "test infrastructure modified" in res.dq_reason


def test_the_honest_python_glob_gold_grades_clean(py_glob_task: _Qualified, tmp_path: Path) -> None:
    """R1-F4-2: the gold's PASSED ids carry the absolute worktree path inside their parametrize
    value. ``relocate_ids`` rewrites the root to ``<root>`` so the ids compare across the
    qualify root and the grade root; without it belt 2's ``target_passed`` check would refuse
    the honest gold. Clean both with the gold's record and when it falls back to the RED ids."""
    captured = py_glob_task.q.gold["target_passed"]
    assert len(captured) == 2, captured
    assert all(i.startswith("tests/test_sub_cases.py::test_sub_cases[<root>/") for i in captured)
    assert _graded(py_glob_task, tmp_path / "trial", {}).clean is True
    old = _with(py_glob_task.q, target_passed=None)
    assert _graded(py_glob_task, tmp_path / "fallback", {}, q=old).clean is True


# --- the records belt 2 falls back on --------------------------------------


def test_a_record_from_before_the_gold_passes_requires_every_red_id(
    py_task: _Qualified, tmp_path: Path
) -> None:
    old = _with(py_task.q)
    assert "target_passed" not in old.gold
    _assert_belt_2_refused(
        _graded(py_task, tmp_path / "skip", {_PY_SRC: _PY_SKIP_NEG}, q=old), PY_NEG, kept=(PY_SUB,)
    )
    assert _graded(py_task, tmp_path / "honest", {}, q=old).clean is True


def test_a_red_that_names_a_file_is_met_by_the_passes_inside_it(
    py_task: _Qualified, tmp_path: Path
) -> None:
    """A collection error names the file (``ERROR tests/test_sub.py``); any pass in it meets
    that id — the fallback is weaker than the gold's record, never weaker than the floor."""
    old = _with(py_task.q, red={"kind": "tests_failed", "failing": ["tests/test_sub.py"]})
    assert _graded(py_task, tmp_path / "honest", {}, q=old).clean is True
    _assert_belt_2_refused(
        _graded(py_task, tmp_path / "skip", {_PY_SRC: _PY_SKIP_ALL}, q=old), "tests/test_sub.py"
    )


def test_a_record_whose_red_names_nothing_still_needs_one_pass(
    py_task: _Qualified, tmp_path: Path
) -> None:
    """The discovery, ad hoc and factory records name no RED id: the floor is one pass."""
    old = _with(py_task.q, red={"kind": "discovery", "failing": []})
    res = _graded(py_task, tmp_path / "skip", {_PY_SRC: _PY_SKIP_ALL}, q=old)
    _assert_belt_2_refused(res)
    assert "no target test passed" in res.note
    assert _graded(py_task, tmp_path / "one", {_PY_SRC: _PY_SKIP_NEG}, q=old).clean is True


def test_a_gold_that_passed_no_target_test_requires_none(
    py_task: _Qualified, tmp_path: Path
) -> None:
    """A gold whose target tests all skip passed nothing; requiring a pass would refuse the
    gold itself. Belt 2 then reads the exit code alone (a weak oracle, not a hidden one)."""
    vacuous = _with(py_task.q, target_passed=[])
    assert _graded(py_task, tmp_path / "skip", {_PY_SRC: _PY_SKIP_ALL}, q=vacuous).clean is True


class _NoPassReport(PytestRunner):
    """A runner that does not report passes (cargo, the JVM and node runners today)."""

    def parse(self, result: ExecResult, root: Path) -> rb.TestRun:
        return dataclasses.replace(super().parse(result, root), passed=None)


def test_a_runner_that_reports_no_passes_reads_the_exit_code_as_before(
    py_task: _Qualified, tmp_path: Path
) -> None:
    res = _graded(
        py_task,
        tmp_path / "skip",
        {_PY_SRC: _PY_SKIP_ALL},
        runner=_NoPassReport(py_task.config),
    )
    assert res.belts.target_green is True and res.clean is True, res.note
