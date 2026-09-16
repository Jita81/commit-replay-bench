"""crb.core.runners — every ``parse()`` on canned toolchain output, plus the base contract.

The command builders for go/node/jvm/cargo belong to the toolchain workstream;
here we pin the *parsers* (what turns raw output into failing test ids), the
scope resolution, the pytest command builder, and the fail-closed rule that an
unattributed non-zero exit is never "no new failures".

Navigation
----------
What it is:   The runners' parser suite — every ``parse()`` on canned toolchain output, plus the
              base contract.
What it does: Pins ``TestRun`` shapes, the registry, sorted / deduped target scopes, the belt
              scope policies, that a non-zero exit with no attributed ids is never "no new
              failures" (compile error, crash), timeout resolution, oracle validity (a test file
              must define a test), the pytest command locally and under docker, and each parser —
              pytest short summary (stdout and stderr), go ``-json``, node JUnit, vitest / jest /
              mocha JSON, surefire XML, cargo — including snapshot paths mapping to their owning
              test (nhsuk-react-components #253).
How:          ``ScriptedExecutor`` returns a canned ``ExecResult``; one case runs the real pytest
              on ``pyrepo`` as the end-to-end anchor.
Layer:        tests — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         none
Works with:   src/crb/core/runners/base.py (the contract), src/crb/core/runners/pytest_runner.py,
              src/crb/core/runners/go_runner.py, src/crb/core/runners/node_runners.py,
              src/crb/core/runners/jvm_runner.py and src/crb/core/runners/cargo_runner.py (the
              parsers under test), tests/test_runners_go.py (the same runners on real toolchains)
Tested by:    tests/test_runners_parsers.py
Touch when:   adding a runner (docs/CONTRIBUTING.md — a parser case on its real output, a
              fail-closed case, a scope case); a reporter's output format changes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from crb.core import runners
from crb.core.execution import Command, ExecResult, LocalExecutor
from crb.core.runners import base as rb
from crb.core.runners.cargo_runner import CargoRunner
from crb.core.runners.go_runner import GoRunner
from crb.core.runners.jvm_runner import MavenRunner
from crb.core.runners.node_runners import JestRunner, MochaRunner, NodeTestRunner, VitestRunner
from crb.core.runners.pytest_runner import PytestRunner
from crb.core.spec import BELT_AFFECTED_DIRS, BELT_BARE, BELT_TARGET_ONLY, Language, RepoConfig
from fixtures import pyrepo as pr


def _cfg(lang: Language, **kw: Any) -> RepoConfig:
    return RepoConfig(name="r", language=lang, **kw)


def _res(stdout: str = "", rc: int = 1, stderr: str = "") -> ExecResult:
    return ExecResult(rc, stdout, stderr, duration_s=0.5)


# ---------------------------------------------------------------------------
# TestRun + helpers
# ---------------------------------------------------------------------------


def test_test_run_green_red_and_to_dict() -> None:
    ok = rb.TestRun(0, frozenset())
    assert ok.green and not ok.red
    assert rb.TestRun(0, frozenset(), timed_out=True).red
    assert rb.TestRun(0, frozenset(), parse_error="x").red
    assert rb.TestRun(1, frozenset()).red
    d = rb.TestRun(1, frozenset({"b", "a"}), "tail", duration_s=1.23456).to_dict()
    assert d == {
        "returncode": 1,
        "failing": ["a", "b"],
        "tail": "tail",
        "timed_out": False,
        "duration_s": 1.235,
        "parse_error": "",
    }


def test_tail_of() -> None:
    text = "\n".join(str(i) for i in range(100)) + "\n\n"
    assert rb.tail_of(text, 3) == "97\n98\n99"
    assert rb.tail_of("", 5) == ""
    assert len(rb.tail_of(text).splitlines()) == rb.TAIL_LINES


def test_registry() -> None:
    assert runners.runner_names() == (
        "pytest",
        "go",
        "node",
        "vitest",
        "jest",
        "mocha",
        "maven",
        "cargo",
    )
    assert isinstance(runners.get_runner(_cfg(Language.PYTHON)), PytestRunner)
    assert isinstance(runners.get_runner(_cfg(Language.GO)), GoRunner)
    assert isinstance(runners.get_runner(_cfg(Language.JAVASCRIPT, runner="node")), NodeTestRunner)
    assert isinstance(runners.get_runner(_cfg(Language.JAVASCRIPT, runner="vitest")), VitestRunner)
    assert isinstance(runners.get_runner(_cfg(Language.JAVASCRIPT, runner="jest")), JestRunner)
    assert isinstance(runners.get_runner(_cfg(Language.JAVASCRIPT)), MochaRunner)
    assert isinstance(runners.get_runner(_cfg(Language.JVM)), MavenRunner)
    assert isinstance(runners.get_runner(_cfg(Language.RUST)), CargoRunner)
    cfg = _cfg(Language.PYTHON)
    object.__setattr__(cfg, "runner", "nose")  # bypass RepoConfig validation to reach the registry
    with pytest.raises(ValueError, match="no runner registered"):
        runners.get_runner(cfg)


# ---------------------------------------------------------------------------
# Base contract: scopes, fail-closed run(), oracle validity
# ---------------------------------------------------------------------------


def test_base_target_scope_is_sorted_and_deduped() -> None:
    r = PytestRunner(_cfg(Language.PYTHON))
    assert r.target_scope(["tests/b.py", "tests/a.py", "tests/b.py"]) == (
        "tests/a.py",
        "tests/b.py",
    )


def test_belt_scope_policies() -> None:
    files = ["tests/unit/test_a.py", "tests/unit/test_b.py", "tests/int/test_c.py", "test_top.py"]
    target = ("tests/int/test_c.py", "tests/unit/test_a.py")
    r = PytestRunner(_cfg(Language.PYTHON, belt_scope=BELT_TARGET_ONLY))
    assert r.belt_scope(target, files) == target
    r = PytestRunner(_cfg(Language.PYTHON, belt_scope=BELT_AFFECTED_DIRS))
    assert r.belt_scope(target, files) == ("tests/int/", "tests/unit/")
    r = PytestRunner(_cfg(Language.PYTHON, belt_scope=BELT_AFFECTED_DIRS, test_prefix="tests/"))
    assert r.belt_scope(target, ["test_top.py"]) == ("tests/",)  # no dirs → test_prefix
    r = PytestRunner(_cfg(Language.PYTHON, belt_scope=BELT_AFFECTED_DIRS))
    assert r.belt_scope(target, ["test_top.py"]) == rb.BARE
    r = PytestRunner(_cfg(Language.PYTHON, belt_scope=BELT_BARE))
    assert r.belt_scope(target, files) == rb.BARE
    r = PytestRunner(_cfg(Language.PYTHON, belt_scope=["tests/", "extra/"]))
    assert r.belt_scope(target, files) == ("tests/", "extra/")
    r = PytestRunner(_cfg(Language.PYTHON, belt_scope=["BARE"]))
    assert r.belt_scope(target, files) == rb.BARE


class ScriptedExecutor:
    """An executor that returns one canned ``ExecResult`` for every command — the parser's input."""

    name = "local"

    def __init__(self, result: ExecResult) -> None:
        self.result = result
        self.commands: list[Command] = []

    def run(self, cmd: Command) -> ExecResult:
        self.commands.append(cmd)
        return self.result

    def tool(self, name: str, host_override: str | None = None) -> str:
        return host_override or name

    def describe(self) -> dict[str, Any]:
        return {"executor": "scripted"}


def test_run_fails_closed_on_unattributed_failure(tmp_path: Path) -> None:
    """rc≠0 with no parsed failing ids (compile error, crash) must never read as green."""
    r = PytestRunner(_cfg(Language.PYTHON))
    run = r.run(ScriptedExecutor(_res("Segmentation fault", rc=139)), tmp_path, ["tests/"])
    assert run.returncode == 139
    assert run.failing == frozenset()
    assert run.parse_error == "unattributed failure (rc=139, no failing ids parsed)"
    assert run.red and not run.green
    assert run.tail == "Segmentation fault"
    assert run.duration_s == 0.5


def test_run_attributed_failure_has_no_parse_error(tmp_path: Path) -> None:
    r = PytestRunner(_cfg(Language.PYTHON))
    run = r.run(
        ScriptedExecutor(_res("FAILED tests/test_a.py::test_x - assert 1 == 2", rc=1)),
        tmp_path,
        ["tests/"],
    )
    assert run.failing == frozenset({"tests/test_a.py::test_x"})
    assert run.parse_error == "" and run.red


def test_run_green_and_timeout(tmp_path: Path) -> None:
    r = PytestRunner(_cfg(Language.PYTHON))
    assert r.run(ScriptedExecutor(_res("2 passed", rc=0)), tmp_path, []).green
    to = r.run(
        ScriptedExecutor(ExecResult(124, "partial", "", timed_out=True, duration_s=9)), tmp_path, []
    )
    assert to.timed_out and to.returncode == 124 and to.red
    assert to.failing == frozenset() and to.tail == "partial" and to.duration_s == 9


def test_run_timeout_resolution(tmp_path: Path) -> None:
    ex = ScriptedExecutor(_res("", rc=0))
    PytestRunner(_cfg(Language.PYTHON)).run(ex, tmp_path, [], timeout=42)
    assert ex.commands[-1].timeout == 42
    PytestRunner(_cfg(Language.PYTHON)).run(ex, tmp_path, [])
    assert ex.commands[-1].timeout == PytestRunner.default_timeout
    PytestRunner(_cfg(Language.PYTHON, runner_opts={"timeout": 7})).run(ex, tmp_path, [])
    assert ex.commands[-1].timeout == 7


def test_base_runner_abstracts(tmp_path: Path) -> None:
    base = rb.BaseRunner(_cfg(Language.PYTHON))
    with pytest.raises(NotImplementedError):
        base.command(tmp_path, [], executor=LocalExecutor(), timeout=1)
    with pytest.raises(NotImplementedError):
        base.parse(_res(), tmp_path)
    assert base.describe() == {"runner": "base"}
    assert base.opts == {}


def test_base_is_valid_oracle_requires_a_non_empty_file(tmp_path: Path) -> None:
    base = GoRunner(_cfg(Language.GO))
    (tmp_path / "a_test.go").write_text("package a\n")
    (tmp_path / "empty_test.go").write_text("")
    assert base.is_valid_oracle(tmp_path, "a_test.go")
    assert not base.is_valid_oracle(tmp_path, "empty_test.go")
    assert not base.is_valid_oracle(tmp_path, "missing_test.go")
    assert not base.is_valid_oracle(tmp_path, ".")  # a directory is not an oracle
    assert not base.is_valid_oracle(tmp_path, "x" * 4000 + "_test.go")  # ENAMETOOLONG → False


def test_pytest_is_valid_oracle_needs_a_test_definition(tmp_path: Path) -> None:
    r = PytestRunner(_cfg(Language.PYTHON))
    cases = {
        "def test_x(): pass\n": True,
        "async def test_x(): pass\n": True,
        "class TestThing:\n    pass\n": True,
        "    def test_indented(self): ...\n": True,
        "def helper(): pass\n": False,
        "test_x = 1\n": False,
        "": False,
    }
    for i, (content, expected) in enumerate(cases.items()):
        p = tmp_path / f"test_{i}.py"
        p.write_text(content)
        assert r.is_valid_oracle(tmp_path, p.name) is expected, content
    assert not r.is_valid_oracle(tmp_path, "nope.py")


# ---------------------------------------------------------------------------
# pytest: command + parser
# ---------------------------------------------------------------------------


def test_pytest_command_local(tmp_path: Path) -> None:
    r = PytestRunner(
        _cfg(
            Language.PYTHON,
            runner_opts={
                "python": "/venv/bin/python",
                "pythonpath_suffix": "/src",
                "env": {"DJANGO_SETTINGS_MODULE": "x"},
            },
        )
    )
    cmd = r.command(tmp_path, ["tests/test_a.py"], executor=LocalExecutor(), timeout=30)
    assert cmd.argv[:3] == ("/venv/bin/python", "-m", "pytest")
    assert "-rfE" in cmd.argv and "-p" in cmd.argv and "no:cacheprovider" in cmd.argv
    assert cmd.argv[-4:] == ("-o", "addopts=", "--continue-on-collection-errors", "tests/test_a.py")
    assert cmd.env["PYTHONPATH"] == f"{tmp_path.resolve()}/src"
    assert cmd.env["PYTHONHASHSEED"] == "0" and cmd.env["DJANGO_SETTINGS_MODULE"] == "x"
    assert cmd.writable_paths == (".pytest_scratch",) and cmd.timeout == 30


def test_pytest_command_docker_rewrites_pythonpath(tmp_path: Path) -> None:
    class DockerLike(ScriptedExecutor):
        name = "docker"

    r = PytestRunner(_cfg(Language.PYTHON, runner_opts={"pythonpath_suffix": f":{tmp_path}/lib"}))
    cmd = r.command(tmp_path, [], executor=DockerLike(_res()), timeout=1)
    assert cmd.argv[0] == "python"
    assert cmd.env["PYTHONPATH"] == "/work:/work/lib"


def test_pytest_parse_short_summary(tmp_path: Path) -> None:
    out = """\
....F.E
=================================== FAILURES ===================================
____________________________________ test_x ____________________________________
assert 1 == 2
=========================== short test summary info ============================
FAILED tests/test_a.py::test_x - assert 1 == 2
FAILED tests/test_a.py::TestK::test_y[param-1] - KeyError
ERROR tests/test_b.py - ImportError: cannot import name 'z'
ERROR tests/test_c.py::test_setup
3 failed, 4 passed, 2 errors in 0.12s
"""
    run = PytestRunner(_cfg(Language.PYTHON)).parse(_res(out, rc=1), tmp_path)
    assert run.failing == frozenset(
        {
            "tests/test_a.py::test_x",
            "tests/test_a.py::TestK::test_y[param-1]",
            "tests/test_b.py",
            "tests/test_c.py::test_setup",
        }
    )
    assert run.returncode == 1 and run.parse_error == ""
    assert run.tail.endswith("2 errors in 0.12s")
    assert rb.parse_pytest_failures("nothing here") == frozenset()
    assert rb.parse_pytest_failures("  FAILED indented::x") == frozenset()  # anchored at line start


def test_pytest_parse_reads_stderr_too(tmp_path: Path) -> None:
    run = PytestRunner(_cfg(Language.PYTHON)).parse(
        _res("", rc=1, stderr="FAILED t.py::a"), tmp_path
    )
    assert run.failing == frozenset({"t.py::a"})


def test_pytest_end_to_end_on_the_fixture(pyrepo: pr.PyRepo, tmp_path: Path) -> None:
    """The real toolchain: RED at the parent with the oracle overlaid, GREEN with gold."""
    r = PytestRunner(pyrepo.config)
    ws = pyrepo.trial(tmp_path / "ws")
    try:
        red = r.run(LocalExecutor(), ws.root, [pr.TEST_SUBTRACT])
        assert red.red and red.failing == frozenset({pr.TEST_SUBTRACT}) and red.parse_error == ""
        pr.apply_gold(ws)
        green = r.run(LocalExecutor(), ws.root, [pr.TEST_SUBTRACT])
        assert green.green and green.failing == frozenset()
        belt = r.run(LocalExecutor(), ws.root, rb.BARE)  # testpaths from pytest.ini
        assert belt.green
    finally:
        ws.remove()


# ---------------------------------------------------------------------------
# go test -json
# ---------------------------------------------------------------------------


def test_go_parse(tmp_path: Path) -> None:
    out = "\n".join(
        [
            '{"Action":"run","Package":"github.com/x/gin/render","Test":"TestJSON"}',
            '{"Action":"output","Package":"github.com/x/gin/render","Test":"TestJSON","Output":"--- FAIL: TestJSON\\n"}',
            '{"Action":"fail","Package":"github.com/x/gin/render","Test":"TestJSON","Elapsed":0.01}',
            '{"Action":"pass","Package":"github.com/x/gin/render","Test":"TestXML","Elapsed":0.01}',
            '{"Action":"fail","Package":"github.com/x/gin/render","Elapsed":0.5}',  # package-level: no Test
            "not json at all",
            '{"Action":"fail","Package":"github.com/x/gin/binding","Test":"TestForm/sub"}',
        ]
    )
    run = GoRunner(_cfg(Language.GO)).parse(_res(out), tmp_path)
    assert run.failing == frozenset(
        {"github.com/x/gin/render::TestJSON", "github.com/x/gin/binding::TestForm/sub"}
    )
    assert run.returncode == 1 and run.parse_error == ""


def test_go_parse_ignores_stderr_and_target_scope() -> None:
    r = GoRunner(_cfg(Language.GO))
    assert (
        r.parse(_res("", rc=1, stderr='{"Action":"fail","Test":"X"}'), Path()).failing
        == frozenset()
    )
    assert r.target_scope(
        ["render/json_test.go", "render/xml_test.go", "gin_test.go", "b/c/d_test.go"]
    ) == (
        "./",
        "./b/c",
        "./render",
    )


# ---------------------------------------------------------------------------
# node --test (junit)
# ---------------------------------------------------------------------------

_JUNIT = """<?xml version="1.0" encoding="utf-8"?>
<testsuites>
  <testsuite name="app" tests="3" failures="1" errors="1">
    <testcase name="responds 200" classname="app"/>
    <testcase name="handles errors" classname="app"><failure message="expected 500"/></testcase>
    <testcase name="boots" classname="app"><error message="TypeError"/></testcase>
    <testcase name="skipped one" classname="app"><skipped/></testcase>
  </testsuite>
</testsuites>
"""


def test_node_junit_parse(tmp_path: Path) -> None:
    run = NodeTestRunner(_cfg(Language.JAVASCRIPT, runner="node")).parse(_res(_JUNIT), tmp_path)
    assert run.failing == frozenset({"handles errors", "boots"})
    assert run.parse_error == ""


def test_node_junit_parse_error_fails_closed(tmp_path: Path) -> None:
    r = NodeTestRunner(_cfg(Language.JAVASCRIPT, runner="node"))
    run = r.parse(_res("<testsuites><broken", rc=0), tmp_path)
    assert run.parse_error == "junit parse error"
    assert run.returncode == 1  # a "0" with unparsable output is forced red
    assert run.red
    assert r.parse(_res("", rc=0), tmp_path).green  # empty stdout → empty suite, honest rc


# ---------------------------------------------------------------------------
# vitest / jest JSON
# ---------------------------------------------------------------------------

_VITEST_JSON = """some banner line
{"numTotalTests":3,"testResults":[{"name":"/w/src/a.test.ts","assertionResults":[
 {"fullName":"add works","status":"passed"},
 {"fullName":"sub works","status":"failed"},
 {"title":"no-fullname","status":"failed"}]},
 {"name":"/w/src/b.test.ts","assertionResults":"not-a-list"}]}
trailing noise"""


def test_vitest_parse(tmp_path: Path) -> None:
    run = VitestRunner(_cfg(Language.JAVASCRIPT, runner="vitest")).parse(
        _res(_VITEST_JSON), tmp_path
    )
    assert run.failing == frozenset({"sub works", "no-fullname"})
    assert run.parse_error == ""


def test_vitest_missing_json_fails_closed(tmp_path: Path) -> None:
    run = VitestRunner(_cfg(Language.JAVASCRIPT, runner="vitest")).parse(
        _res("no json", rc=0), tmp_path
    )
    assert run.parse_error == "vitest json missing" and run.returncode == 1 and run.red
    run = VitestRunner(_cfg(Language.JAVASCRIPT, runner="vitest")).parse(
        _res("[1,2]", rc=0), tmp_path
    )
    assert run.parse_error == "vitest json missing"  # a list is not a report


_JEST_JSON = """{"success":false,"testResults":[
 {"name":"/w/a.test.js","testResults":[{"fullName":"A does x","status":"failed"},{"fullName":"A does y","status":"passed"}]},
 {"name":"/w/b.test.js","assertionResults":[{"title":"B legacy","status":"failed"}]}]}"""


def test_jest_parse(tmp_path: Path) -> None:
    run = JestRunner(_cfg(Language.JAVASCRIPT, runner="jest")).parse(_res(_JEST_JSON), tmp_path)
    assert run.failing == frozenset({"A does x", "B legacy"})
    bad = JestRunner(_cfg(Language.JAVASCRIPT, runner="jest")).parse(
        _res("{broken", rc=1), tmp_path
    )
    assert bad.parse_error == "jest json missing" and bad.returncode == 1


# ---------------------------------------------------------------------------
# mocha JSON
# ---------------------------------------------------------------------------

_MOCHA_JSON = """{"stats":{"tests":3,"failures":2},
"failures":[{"title":"works","fullTitle":"app works ","err":{}},{"title":"only-title"}],
"passes":[{"fullTitle":"app boots"}]}"""


def test_mocha_parse(tmp_path: Path) -> None:
    run = MochaRunner(_cfg(Language.JAVASCRIPT)).parse(_res(_MOCHA_JSON), tmp_path)
    assert run.failing == frozenset({"app works", "only-title"})
    bad = MochaRunner(_cfg(Language.JAVASCRIPT)).parse(_res("", rc=0), tmp_path)
    assert bad.parse_error == "mocha json missing" and bad.red


# ---------------------------------------------------------------------------
# maven surefire XML on a tmp tree
# ---------------------------------------------------------------------------


def test_maven_parse_surefire_reports(tmp_path: Path) -> None:
    reports = tmp_path / "core" / "target" / "surefire-reports"
    reports.mkdir(parents=True)
    (reports / "TEST-com.x.FooTest.xml").write_text(
        """<testsuite name="com.x.FooTest">
  <testcase classname="com.x.FooTest" name="ok"/>
  <testcase classname="com.x.FooTest" name="fails"><failure message="x"/></testcase>
  <testcase classname="com.x.FooTest" name="errors"><error type="E"/></testcase>
</testsuite>"""
    )
    (reports / "TEST-com.x.BarTest.xml").write_text(
        "<testsuite><testcase classname='com.x.BarTest' name='ok'/></testsuite>"
    )
    (reports / "TEST-com.x.Broken.xml").write_text("<testsuite><testcase")  # unparsable → skipped
    (reports / "com.x.FooTest.txt").write_text("not xml")  # not matched
    run = MavenRunner(_cfg(Language.JVM)).parse(_res("[ERROR] Tests run: 3, Failures: 1"), tmp_path)
    assert run.failing == frozenset({"com.x.FooTest::fails", "com.x.FooTest::errors"})
    assert run.parse_error == ""


def test_maven_parse_without_reports_and_target_scope(tmp_path: Path) -> None:
    r = MavenRunner(_cfg(Language.JVM))
    assert r.parse(_res("", rc=0), tmp_path).green
    assert r.target_scope(
        ["src/test/java/com/x/FooTest.java", "core/src/test/java/BarIT.java"]
    ) == ("BarIT", "FooTest")


# ---------------------------------------------------------------------------
# cargo test
# ---------------------------------------------------------------------------


def test_cargo_parse(tmp_path: Path) -> None:
    out = """running 3 tests
test builder::env::basic ... ok
test builder::env::override ... FAILED
test parse::empty ... FAILED
test ignored_one ... ignored

failures:
    builder::env::override
    parse::empty

test result: FAILED. 1 passed; 2 failed; 1 ignored
"""
    run = CargoRunner(_cfg(Language.RUST)).parse(_res(out), tmp_path)
    assert run.failing == frozenset({"builder::env::override", "parse::empty"})
    assert run.parse_error == ""


def test_cargo_target_scope() -> None:
    r = CargoRunner(_cfg(Language.RUST))
    assert r.target_scope(["tests/foo.rs", "tests/builder/env.rs", "src/lib.rs"]) == (
        "ALL",
        "builder",
        "foo",
    )


def test_snapshot_paths_map_to_their_owning_test() -> None:
    """A snapshot-only commit (NHSDigital/nhsuk-react-components #253) still has an
    executable oracle: the test that owns the snapshot."""
    from crb.core.runners.node_runners import snapshot_to_test

    assert (
        snapshot_to_test("src/a/__tests__/__snapshots__/Radios.test.tsx.snap")
        == "src/a/__tests__/Radios.test.tsx"
    )
    assert snapshot_to_test("src/a/__tests__/Radios.test.tsx") == "src/a/__tests__/Radios.test.tsx"
