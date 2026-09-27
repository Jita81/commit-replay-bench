"""The environment-setup phase of every runner (``setup`` / ``environment_ready``).

Hermetic parts (no network, no toolchain): the setup records, redaction of step
tails, the ``network=True`` marking, the docker refusal, the pytest install plan
(declared extras, ``pip`` / ``pip_fallback`` / ``uninstall``), interpreter
resolution, and the "never ready on the crb interpreter" rule.

Real parts run the actual toolchains on the fixture repos and are marked
``@pytest.mark.network`` when they install from a registry (``pip install`` of
pytest / the fixture distribution, ``npm install`` of mocha, Maven's warm-up) or
``@pytest.mark.toolchain(...)`` when they only need the binary. Each skips with
its reason when the tool is missing, and a network test skips with the host and the reason
when the registry it names is unreachable (tests/conftest.py); none decides a verdict.

Navigation
----------
What it is:   The environment-setup phase's test suite (``setup`` / ``environment_ready`` on every
              runner).
What it does: Pins the setup records and their redaction, the ``network=True`` marking, that
              setup fails closed under a sandbox executor, the pytest install plan (declared
              extras, ``pip`` / ``pip_fallback`` / ``uninstall``), interpreter resolution
              (explicit > venv > never the crb interpreter), that every registered runner answers
              the contract, that only pytest creates ``env_dir``, and the ``dist_info_stubs``
              option; the network- and toolchain-marked cases build a real venv, ``npm install``
              mocha, warm Maven and check go / cargo readiness.
How:          ``FakeExecutor`` scripts answers by argv substring for the hermetic half; the real
              half runs the toolchains on the fixture repositories and skips with the reason.
Layer:        tests — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0005-fail-closed-docker-sandbox.md
Works with:   src/crb/core/runners/base.py (``SetupSession`` / ``SetupResult``),
              src/crb/core/runners/pytest_runner.py (the install plan under test),
              src/crb/core/runners/node_runners.py (the npm plan), tests/fixtures/pyrepo.py (the
              ``add_pyproject_commit`` shape), docs/OPERATOR.md (environment setup — the only
              network phase, §2.1)
Tested by:    tests/test_runners_setup.py
Touch when:   onboarding a repository whose environment needs an option the plan lacks (add the
              ``runner_opts`` key, its hermetic case and its docs/OPERATOR.md entry); adding a
              runner (it must answer the setup contract).
"""

from __future__ import annotations

import os
import shutil
import stat
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from crb.core.execution import Command, ExecResult, LocalExecutor
from crb.core.runners import get_runner
from crb.core.runners.base import (
    SETUP_NOTHING,
    SETUP_SANDBOX_REFUSED,
    BaseRunner,
    SetupResult,
    SetupSession,
    SetupStep,
    failed_step_note,
    host_check,
)
from crb.core.runners.pytest_runner import (
    PytestRunner,
    declared_extras,
    split_pip_args,
    venv_python,
)
from crb.core.spec import Language, RepoConfig
from fixtures import pyrepo as pr
from fixtures.langs import commit_all

try:  # tests/ is a package only if the conftest owner made it one
    from tests import conftest_langs as langs
except ImportError:  # pragma: no cover — layout-dependent
    import conftest_langs as langs

# --- a scripted executor -------------------------------------------------------------------


class FakeExecutor:
    """Records every command; answers from ``script`` (argv-substring → (rc, out))."""

    def __init__(self, name: str = "local", script: dict[str, tuple[int, str]] | None = None):
        self.name = name
        self.script = dict(script or {})
        self.commands: list[Command] = []

    def tool(self, name: str, host_override: str | None = None) -> str:
        return host_override or name

    def describe(self) -> dict[str, Any]:
        return {"executor": self.name}

    def run(self, cmd: Command) -> ExecResult:
        self.commands.append(cmd)
        joined = " ".join(cmd.argv)
        for needle, (rc, out) in self.script.items():
            if needle in joined:
                return ExecResult(rc, out, "", False, 0.01)
        return ExecResult(0, "", "", False, 0.01)


def _fake_venv(env_dir: Path) -> Path:
    """A venv interpreter that EXISTS but cannot run (a plain file): lets the install
    plan be recorded by a fake executor without touching the network."""
    py = venv_python(env_dir)
    py.parent.mkdir(parents=True, exist_ok=True)
    py.write_text("#!/bin/sh\nexit 3\n", encoding="utf-8")
    py.chmod(py.stat().st_mode | stat.S_IXUSR)
    return py


def _argvs(ex: FakeExecutor) -> list[str]:
    return [" ".join(c.argv) for c in ex.commands]


# --- records -------------------------------------------------------------------------------


def test_setup_step_redacts_its_tail_at_construction() -> None:
    step = SetupStep(
        ("pip", "install", "x"),
        1,
        "Authorization: Bearer abcdefghijklmnop123456\nAKIAABCDEFGHIJKLMNOP\nleft as is",
        0.5,
    )
    assert "[REDACTED]" in step.tail and "[REDACTED-AWS]" in step.tail
    assert "abcdefghijklmnop123456" not in step.tail and "AKIAABCDEFGHIJKLMNOP" not in step.tail
    assert step.tail.endswith("left as is") and not step.ok
    assert step.to_dict() == {
        "argv": ["pip", "install", "x"],
        "rc": 1,
        "tail": step.tail,
        "duration_s": 0.5,
        "timed_out": False,
    }
    assert not SetupStep(("x",), 0, "", 0.0, timed_out=True).ok


def test_setup_result_round_trip_and_notes() -> None:
    ok_step = SetupStep(("a",), 0)
    bad = SetupStep(("b", "c"), 2, "boom")
    res = SetupResult(False, [ok_step, bad], "step 2 failed", 1.25)  # type: ignore[arg-type]
    assert isinstance(res.steps, tuple) and res.last_tail == "boom"
    assert res.to_dict() == {
        "ok": False,
        "steps": [ok_step.to_dict(), bad.to_dict()],
        "note": "step 2 failed",
        "duration_s": 1.25,
    }
    assert failed_step_note([ok_step, bad]) == "step 2 failed (rc=2): b c"
    assert failed_step_note([ok_step]) == "" and failed_step_note([]) == ""
    assert failed_step_note([bad, ok_step]) == ""  # the failure was recovered by a later step
    assert failed_step_note([SetupStep(("t",), 124, timed_out=True)]).startswith(
        "step 1 failed (timed out)"
    )
    assert SetupResult(True).last_tail == ""


def test_setup_session_marks_network_and_streams_steps(tmp_path: Path) -> None:
    ex = FakeExecutor(script={"fail": (7, "no such thing sk-live-abcdefghijklmnopqrstuvwxyz")})
    seen: list[SetupStep] = []
    session = SetupSession(ex, on_step=seen.append)
    first = session.run(Command(("echo", "ok"), tmp_path, timeout=5))
    assert first.ok and session.all_ok
    second = session.run(Command(("try", "fail"), tmp_path, timeout=5, network=True))
    assert not second.ok and second.rc == 7 and "[REDACTED-KEY]" in second.tail
    assert seen == [first, second] and not session.all_ok
    # every command reached the executor flagged as the network phase
    assert all(c.network for c in ex.commands) and len(ex.commands) == 2
    res = session.result(False, "x")
    assert res.steps == (first, second) and res.duration_s >= 0


def test_setup_session_records_a_missing_binary_as_rc_127(tmp_path: Path) -> None:
    session = SetupSession(LocalExecutor())
    step = session.run(Command((str(tmp_path / "no-such-tool"), "fetch"), tmp_path, timeout=5))
    assert step.rc == 127 and not step.ok and "FileNotFoundError" in step.tail
    assert session.result(False, failed_step_note(session.steps)).note.startswith(
        "step 1 failed (rc=127)"
    )


def test_host_check_fails_closed_on_missing_binary(tmp_path: Path) -> None:
    assert host_check([sys.executable, "-c", "pass"], tmp_path)
    assert not host_check([sys.executable, "-c", "raise SystemExit(3)"], tmp_path)
    assert not host_check([str(tmp_path / "no-such-binary"), "x"], tmp_path)


# --- base contract -----------------------------------------------------------------------


def _config(runner: str, language: Language, **opts: Any) -> RepoConfig:
    return RepoConfig(name=f"fix-{runner}", language=language, runner=runner, runner_opts=opts)


def test_base_runner_default_is_a_no_op(tmp_path: Path) -> None:
    class Bare(BaseRunner):
        name = "bare"

    r = Bare(_config("pytest", Language.PYTHON))
    res = r.setup(FakeExecutor(), tmp_path, env_dir=tmp_path / "env", timeout=0)
    assert res == SetupResult(True, (), SETUP_NOTHING, 0.0)
    assert r.environment_ready(tmp_path, tmp_path / "env")
    assert r.env_dir is None and Bare(r.config, env_dir=tmp_path).env_dir == tmp_path
    assert r.setup_timeout(0) == 1800 and r.setup_timeout(7) == 7
    assert Bare(_config("pytest", Language.PYTHON, setup_timeout=42)).setup_timeout(0) == 42


@pytest.mark.parametrize(
    ("runner", "language"),
    [
        ("pytest", Language.PYTHON),
        ("node", Language.JAVASCRIPT),
        ("jest", Language.JAVASCRIPT),
        ("go", Language.GO),
        ("maven", Language.JVM),
        ("cargo", Language.RUST),
    ],
)
def test_setup_refuses_a_sandbox_executor(runner: str, language: Language, tmp_path: Path) -> None:
    """Setup is a host phase; under docker it fails closed instead of pretending."""
    ex = FakeExecutor(name="docker")
    res = get_runner(_config(runner, language)).setup(
        ex, tmp_path, env_dir=tmp_path / "env", timeout=0
    )
    assert res.ok is False and res.note == SETUP_SANDBOX_REFUSED and res.steps == ()
    assert ex.commands == []


# --- pytest: interpreter resolution + install plan (hermetic) ------------------------------


def test_split_pip_args_and_declared_extras(tmp_path: Path) -> None:
    assert split_pip_args(["-e .[test]", "pytest"]) == ["-e", ".[test]", "pytest"]
    # a bare string splits on whitespace, never per character (A12 finding)
    assert split_pip_args("-e . pytest") == ["-e", ".", "pytest"]
    assert split_pip_args("pytest") == ["pytest"]
    assert split_pip_args(["django", "-r", "requirements/test.txt"]) == [
        "django",
        "-r",
        "requirements/test.txt",
    ]
    assert declared_extras(tmp_path) == frozenset()
    (tmp_path / "pyproject.toml").write_text("this is not toml [[", encoding="utf-8")
    assert declared_extras(tmp_path) == frozenset()
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\n[project.optional-dependencies]\ndev = ["a"]\ntests = ["b"]\n',
        encoding="utf-8",
    )
    assert declared_extras(tmp_path) == frozenset({"dev", "tests"})


def test_python_for_prefers_explicit_then_venv_then_crb_interpreter(tmp_path: Path) -> None:
    env_dir = tmp_path / "env"
    root = tmp_path / "root"
    root.mkdir()
    r = PytestRunner(_config("pytest", Language.PYTHON))
    # nothing configured, no venv → the crb interpreter (the pre-setup behaviour)
    assert r.configured_python(root, env_dir) is None
    assert r.python_for(root, env_dir) == sys.executable
    assert r.python_for(root, None) == sys.executable
    # a venv exists → it wins
    py = _fake_venv(env_dir)
    assert r.python_for(root, env_dir) == str(py)
    # explicit runner_opts.python beats the venv; a relative path resolves against root
    explicit = PytestRunner(_config("pytest", Language.PYTHON, python="/opt/py/bin/python"))
    assert explicit.python_for(root, env_dir) == "/opt/py/bin/python"
    rel = PytestRunner(_config("pytest", Language.PYTHON, python=".venv/bin/python"))
    assert rel.python_for(root, env_dir) == str(root / ".venv/bin/python")
    bare = PytestRunner(_config("pytest", Language.PYTHON, python="python3.12"))
    assert bare.python_for(root, env_dir) == "python3.12"


def test_environment_ready_never_counts_the_crb_interpreter(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    """The crb process has pytest, but it does not carry the repo's dependencies."""
    r = PytestRunner(pr.default_config(runner_opts={"pythonpath_suffix": "/src"}))
    assert not r.environment_ready(pyrepo.path, tmp_path / "env")
    # an explicit interpreter that imports pytest IS ready (the CLI / worker fixtures)
    assert PytestRunner(pyrepo.config).environment_ready(pyrepo.path, tmp_path / "env")
    # an explicit interpreter that does not exist is not
    missing = PytestRunner(pr.default_config(runner_opts={"python": str(tmp_path / "nope")}))
    assert not missing.environment_ready(pyrepo.path, tmp_path / "env")


def test_command_uses_the_bound_env_dir_venv(pyrepo: pr.PyRepo, tmp_path: Path) -> None:
    env_dir = tmp_path / "env"
    py = _fake_venv(env_dir)
    r = PytestRunner(pr.default_config(runner_opts={"pythonpath_suffix": "/src"}))
    assert r.command(pyrepo.path, ("tests/",), executor=LocalExecutor(), timeout=5).argv[0] == (
        sys.executable
    )
    r.env_dir = env_dir
    cmd = r.command(pyrepo.path, ("tests/",), executor=LocalExecutor(), timeout=5)
    assert cmd.argv[0] == str(py) and cmd.argv[1:3] == ("-m", "pytest")
    # docker ignores host interpreters entirely
    docker = FakeExecutor(name="docker")
    assert r.command(pyrepo.path, ("tests/",), executor=docker, timeout=5).argv[0] == "python"


def test_pytest_explicit_python_is_verified_not_installed_into(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    ex = FakeExecutor()
    ok = PytestRunner(pyrepo.config).setup(ex, pyrepo.path, env_dir=tmp_path / "env", timeout=0)
    assert ok.ok and ok.steps == () and "runner_opts.python" in ok.note
    bad = PytestRunner(pr.default_config(runner_opts={"python": str(tmp_path / "nope")}))
    res = bad.setup(ex, pyrepo.path, env_dir=tmp_path / "env", timeout=0)
    assert not res.ok and res.steps == () and "cannot import pytest" in res.note
    assert ex.commands == []  # nothing was ever run against the operator's interpreter


def test_pytest_default_plan_uses_the_declared_extra_then_pytest_then_uninstall(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    pyrepo.add_pyproject_commit()
    env_dir = tmp_path / "env"
    _fake_venv(env_dir)  # the venv step is skipped: the interpreter already exists
    ex = FakeExecutor()
    r = PytestRunner(
        pr.default_config(runner_opts={"pythonpath_suffix": "/src", "uninstall": ["calc"]})
    )
    res = r.setup(ex, pyrepo.path, env_dir=env_dir, timeout=30)
    argvs = _argvs(ex)
    assert len(argvs) == 3
    assert argvs[0].endswith("-e .[test]") and "install" in argvs[0]
    assert argvs[1].endswith(" pytest") and "install" in argvs[1]
    assert argvs[2].endswith(" calc") and "uninstall" in argvs[2]
    assert all(c.network for c in ex.commands) and all(c.timeout == 30 for c in ex.commands)
    assert all(str(c.root) == str(pyrepo.path.resolve()) for c in ex.commands)
    # every step exited 0 but the (fake) interpreter cannot import pytest → NOT ready
    assert not res.ok and res.note == "steps succeeded but the environment is not ready"
    assert [s.ok for s in res.steps] == [True, True, True]


def test_pytest_default_plan_falls_back_to_a_plain_editable_install(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    pyrepo.add_pyproject_commit()
    _fake_venv(tmp_path / "env")
    ex = FakeExecutor(script={".[test]": (1, "ERROR: extra deps unresolvable")})
    r = PytestRunner(pr.default_config(runner_opts={"pythonpath_suffix": "/src"}))
    res = r.setup(ex, pyrepo.path, env_dir=tmp_path / "env", timeout=30)
    argvs = _argvs(ex)
    assert argvs[0].endswith("-e .[test]") and argvs[1].endswith("-e .")
    assert argvs[2].endswith(" pytest")
    assert [s.rc for s in res.steps] == [1, 0, 0]
    # no project file at all → no editable install, just pytest
    ex2 = FakeExecutor()
    r2 = PytestRunner(pr.default_config(runner_opts={"pythonpath_suffix": "/src"}))
    (pyrepo.path / pr.PYPROJECT).unlink()
    r2.setup(ex2, pyrepo.path, env_dir=tmp_path / "env", timeout=30)
    assert len(ex2.commands) == 1 and _argvs(ex2)[0].endswith(" pytest")


def test_pytest_explicit_pip_list_then_fallback_stops_on_failure(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    _fake_venv(tmp_path / "env")
    ex = FakeExecutor(script={"requirements/test.txt": (2, "no such file")})
    r = PytestRunner(
        pr.default_config(
            runner_opts={
                "pip": ["calc", "pytest", "-r", "requirements/test.txt"],
                "pip_fallback": ["calc", "pytest"],
                "uninstall": ["calc"],
            }
        )
    )
    res = r.setup(ex, pyrepo.path, env_dir=tmp_path / "env", timeout=30)
    argvs = _argvs(ex)
    assert argvs[0].endswith("calc pytest -r requirements/test.txt")
    assert argvs[1].endswith(" calc pytest") and "install" in argvs[1]
    assert argvs[2].endswith(" calc") and "uninstall" in argvs[2]
    assert [s.rc for s in res.steps] == [2, 0, 0]
    # primary AND fallback fail → stop there, record both, no uninstall
    ex2 = FakeExecutor(script={"install": (1, "resolution failed")})
    res2 = r.setup(ex2, pyrepo.path, env_dir=tmp_path / "env", timeout=30)
    assert len(ex2.commands) == 2 and not res2.ok
    assert res2.note.startswith("step 2 failed (rc=1)") and res2.last_tail == "resolution failed"
    assert [s.rc for s in res2.steps] == [1, 1]


def test_pytest_venv_creation_failure_is_reported(pyrepo: pr.PyRepo, tmp_path: Path) -> None:
    ex = FakeExecutor(script={"venv": (1, "cannot create")})
    r = PytestRunner(pr.default_config(runner_opts={"pythonpath_suffix": "/src"}))
    res = r.setup(ex, pyrepo.path, env_dir=tmp_path / "env", timeout=0)
    assert not res.ok and res.note == "virtualenv creation failed" and len(res.steps) == 1
    # the venv command names the env_dir venv and the base interpreter
    argv = ex.commands[0].argv
    assert str(tmp_path / "env" / "venv") in argv and sys.executable in argv
    # a venv command that "succeeds" without producing the interpreter is also a failure
    ex2 = FakeExecutor()
    res2 = r.setup(ex2, pyrepo.path, env_dir=tmp_path / "env2", timeout=0)
    assert not res2.ok and "is missing" in res2.note and len(res2.steps) == 1


# --- pytest: the real thing --------------------------------------------------------------


@pytest.mark.network
@pytest.mark.skipif(shutil.which("uv") is None, reason="uv not on PATH")
def test_pytest_setup_builds_a_real_venv_and_the_command_uses_it(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    pyrepo.add_pyproject_commit()
    env_dir = tmp_path / "envs" / pr.REPO_NAME
    r = PytestRunner(
        pr.default_config(runner_opts={"pythonpath_suffix": "/src", "uninstall": [pr.DIST_NAME]})
    )
    assert not r.environment_ready(pyrepo.path, env_dir)
    seen: list[SetupStep] = []
    res = r.setup(LocalExecutor(), pyrepo.path, env_dir=env_dir, timeout=600, on_step=seen.append)
    assert res.ok, res.to_dict()
    assert res.note == "ready" and list(res.steps) == seen
    verbs = [" ".join(s.argv) for s in res.steps]
    assert "venv" in verbs[0] and verbs[1].endswith("-e .[test]") and verbs[2].endswith("pytest")
    assert "uninstall" in verbs[3] and verbs[3].endswith(pr.DIST_NAME)
    assert all(s.ok for s in res.steps) and res.duration_s > 0
    assert r.environment_ready(pyrepo.path, env_dir)
    py = venv_python(env_dir)
    assert py.exists() and r.python_for(pyrepo.path, env_dir) == str(py)
    # the census invariant: the distribution is gone, the worktree's source is what runs
    r.env_dir = env_dir
    cmd = r.command(pyrepo.path, ("tests/",), executor=LocalExecutor(), timeout=120)
    assert cmd.argv[0] == str(py)
    run = r.run(LocalExecutor(), pyrepo.path, ("tests/",), timeout=120)
    assert run.green, run.tail
    probe = host_check(
        [str(py), "-c", "import importlib.metadata as m; m.version('calc')"], tmp_path
    )
    assert probe is False  # uninstalled
    # idempotent: a second setup keeps the venv and is still ready
    again = r.setup(LocalExecutor(), pyrepo.path, env_dir=env_dir, timeout=600)
    assert again.ok and again.steps[0].argv[1:3] != ("venv", "-q")
    assert "install" in again.steps[0].argv


@pytest.mark.network
@pytest.mark.skipif(shutil.which("uv") is None, reason="uv not on PATH")
def test_pytest_setup_real_pip_fallback(pyrepo: pr.PyRepo, tmp_path: Path) -> None:
    env_dir = tmp_path / "env"
    r = PytestRunner(
        pr.default_config(
            runner_opts={
                "pythonpath_suffix": "/src",
                "pip": ["crb-no-such-distribution-8f3a1c"],
                "pip_fallback": ["pytest"],
            }
        )
    )
    res = r.setup(LocalExecutor(), pyrepo.path, env_dir=env_dir, timeout=600)
    assert res.ok, res.to_dict()
    assert res.note == "ready (step 2 failed; fallback succeeded)"
    rcs = [s.rc for s in res.steps]
    assert rcs[0] == 0 and rcs[1] != 0 and rcs[2] == 0  # venv, primary (fails), fallback
    assert "crb-no-such-distribution-8f3a1c" in res.steps[1].tail
    assert r.environment_ready(pyrepo.path, env_dir)


# --- node ----------------------------------------------------------------------------------

noderepo = langs.fixture_module("noderepo")


def test_node_dependency_free_repo_is_ready_as_it_stands(tmp_path: Path) -> None:
    root, _ = noderepo.build(tmp_path, "node")
    r = get_runner(noderepo.config("node"))
    assert r.environment_ready(root, tmp_path / "env")
    # declare a dependency → not ready until node_modules/.bin exists
    (root / "package.json").write_text(
        '{"name": "x", "version": "0.0.1", "devDependencies": {"mocha": "^11"}}\n',
        encoding="utf-8",
    )
    assert not r.environment_ready(root, tmp_path / "env")
    (root / "node_modules" / ".bin").mkdir(parents=True)
    assert r.environment_ready(root, tmp_path / "env")


def test_node_setup_plan(tmp_path: Path) -> None:
    root, _ = noderepo.build(tmp_path, "mocha")
    r = get_runner(noderepo.config("mocha"))
    ex = FakeExecutor()
    res = r.setup(ex, root, env_dir=tmp_path / "env", timeout=99)
    (cmd,) = ex.commands
    assert cmd.argv[:2] == ("npm", "install") and "--no-audit" in cmd.argv
    assert cmd.network and cmd.timeout == 99 and cmd.writable_paths == ("node_modules",)
    assert res.ok  # package.json declares nothing, so the fake install leaves it ready
    (root / "package-lock.json").write_text("{}", encoding="utf-8")
    r.setup(ex, root, env_dir=tmp_path / "env", timeout=0)
    assert ex.commands[-1].argv[:2] == ("npm", "ci")
    (root / "package.json").unlink()
    none = r.setup(ex, root, env_dir=tmp_path / "env", timeout=0)
    assert not none.ok and "package.json" in none.note and len(ex.commands) == 2


@pytest.mark.network("registry.npmjs.org")
@pytest.mark.toolchain("npm")
@pytest.mark.skipif(not langs.has_tool("npm"), reason="npm not on PATH")
def test_node_setup_installs_node_modules_for_real(tmp_path: Path) -> None:
    root, _ = noderepo.build(tmp_path, "mocha")
    pkg = (root / "package.json").read_text(encoding="utf-8")
    (root / "package.json").write_text(
        pkg.replace('"private": true,', '"private": true,\n  "devDependencies": {"mocha": "^11"},'),
        encoding="utf-8",
    )
    commit_all(root, "build: declare mocha")
    r = get_runner(noderepo.config("mocha"))
    assert not r.environment_ready(root, tmp_path / "env")
    res = r.setup(LocalExecutor(), root, env_dir=tmp_path / "env", timeout=600)
    assert res.ok, res.to_dict()
    assert (root / "node_modules" / ".bin" / "mocha").exists()
    assert r.environment_ready(root, tmp_path / "env")
    run = r.run(LocalExecutor(), root, (), timeout=300)
    assert run.green, run.tail


# --- go ------------------------------------------------------------------------------------

gorepo = langs.fixture_module("gorepo")


@pytest.mark.toolchain("go")
@pytest.mark.skipif(not langs.has_tool("go"), reason="go not on PATH")
def test_go_setup_and_readiness(tmp_path: Path) -> None:
    root, _ = gorepo.build(tmp_path)
    r = get_runner(gorepo.config())
    env_dir = tmp_path / "env"
    assert r.environment_ready(root, env_dir)  # no external modules: resolvable offline
    res = r.setup(LocalExecutor(), root, env_dir=env_dir, timeout=300)
    assert res.ok, res.to_dict()
    assert len(res.steps) == 1 and res.steps[0].argv[1:] == ("mod", "download")
    # an IMPORTED module that is not in the cache → not ready (offline resolution
    # fails closed; a merely-required-but-unused module would still build)
    (root / "go.mod").write_text(
        f"module {gorepo.MODULE}\n\ngo 1.22\n\nrequire example.invalid/crb-missing v1.2.3\n",
        encoding="utf-8",
    )
    (root / "calc" / "dep.go").write_text(
        'package calc\n\nimport _ "example.invalid/crb-missing"\n', encoding="utf-8"
    )
    assert not r.environment_ready(root, env_dir)


def test_go_setup_needs_a_module(tmp_path: Path) -> None:
    r = get_runner(gorepo.config())
    res = r.setup(FakeExecutor(), tmp_path, env_dir=tmp_path / "env", timeout=0)
    assert not res.ok and "go.mod" in res.note


# --- maven ---------------------------------------------------------------------------------

jvmrepo = langs.fixture_module("jvmrepo")


def test_maven_setup_plan(tmp_path: Path) -> None:
    root, _ = jvmrepo.build(tmp_path)
    cfg = RepoConfig(
        name="jvmfix",
        language=Language.JVM,
        runner="maven",
        src_prefix="src/main/java/",
        test_prefix="src/test/java/",
        runner_opts={"maven_flags": ["-Denforcer.skip=true"], "java_home": "/opt/jdk"},
    )
    r = get_runner(cfg)
    ex = FakeExecutor()
    r.setup(ex, root, env_dir=tmp_path / "env", timeout=0)
    (cmd,) = ex.commands
    assert cmd.argv == ("mvn", "-q", "-B", "-Denforcer.skip=true", "test", "-DskipTests")
    assert cmd.network and cmd.env == {"JAVA_HOME": "/opt/jdk"} and "target" in cmd.writable_paths
    assert "-o" not in cmd.argv  # setup is the ONLINE phase; the test command stays offline
    (root / "pom.xml").unlink()
    assert "pom.xml" in r.setup(ex, root, env_dir=tmp_path / "env", timeout=0).note


@pytest.mark.network("repo.maven.apache.org")
@pytest.mark.toolchain("mvn")
@pytest.mark.skipif(not langs.has_tool("mvn"), reason="mvn not on PATH")
@pytest.mark.skipif(not jvmrepo.java_home(), reason="no JDK: neither brew openjdk nor $JAVA_HOME")
def test_maven_setup_warms_the_local_repository(tmp_path: Path) -> None:
    root, _ = jvmrepo.build(tmp_path)
    r = get_runner(jvmrepo.config(offline=True))
    env_dir = tmp_path / "env"
    res = r.setup(LocalExecutor(), root, env_dir=env_dir, timeout=900)
    assert res.ok, res.to_dict()
    assert res.steps[0].argv[-2:] == ("test", "-DskipTests")
    assert r.environment_ready(root, env_dir)
    # the offline test command now resolves everything setup warmed
    run = r.run(LocalExecutor(), root, (), timeout=600)
    assert run.green, run.tail


# --- cargo ---------------------------------------------------------------------------------

rustrepo = langs.fixture_module("rustrepo")


@pytest.mark.toolchain("cargo")
@pytest.mark.skipif(not langs.has_tool("cargo"), reason="cargo not on PATH")
def test_cargo_setup_and_readiness(tmp_path: Path) -> None:
    root, _ = rustrepo.build(tmp_path)
    r = get_runner(rustrepo.config())
    env_dir = tmp_path / "env"
    assert r.environment_ready(root, env_dir)  # no dependencies: metadata resolves offline
    res = r.setup(LocalExecutor(), root, env_dir=env_dir, timeout=300)
    assert res.ok, res.to_dict()
    assert res.steps[0].argv[1:] == ("fetch",) and res.steps[0].ok
    (root / "Cargo.toml").write_text(
        '[package]\nname = "calc"\nversion = "0.1.0"\nedition = "2021"\n\n'
        '[dependencies]\ncrb-no-such-crate-8f3a1c = "9.9.9"\n',
        encoding="utf-8",
    )
    assert not r.environment_ready(root, env_dir)


def test_cargo_setup_needs_a_manifest(tmp_path: Path) -> None:
    r = get_runner(rustrepo.config())
    res = r.setup(FakeExecutor(), tmp_path, env_dir=tmp_path / "env", timeout=0)
    assert not res.ok and "Cargo.toml" in res.note


# --- the registry exposes the contract ---------------------------------------------------------


def test_every_registered_runner_answers_the_setup_contract(tmp_path: Path) -> None:
    for runner, language in [
        ("pytest", Language.PYTHON),
        ("go", Language.GO),
        ("node", Language.JAVASCRIPT),
        ("vitest", Language.JAVASCRIPT),
        ("jest", Language.JAVASCRIPT),
        ("mocha", Language.JAVASCRIPT),
        ("maven", Language.JVM),
        ("cargo", Language.RUST),
    ]:
        r = get_runner(_config(runner, language))
        ready: Callable[[Path, Path], bool] = r.environment_ready
        assert isinstance(ready(tmp_path, tmp_path / "env"), bool)
        res = r.setup(FakeExecutor(), tmp_path, env_dir=tmp_path / "env", timeout=0)
        assert isinstance(res, SetupResult) and isinstance(res.ok, bool)


def test_setup_env_dir_is_created_for_the_venv_only(pyrepo: pr.PyRepo, tmp_path: Path) -> None:
    """node/go/maven/cargo keep nothing under env_dir; pytest creates it on demand."""
    env_dir = tmp_path / "envs" / "x"
    for runner, language in [("go", Language.GO), ("cargo", Language.RUST)]:
        get_runner(_config(runner, language)).setup(
            FakeExecutor(), tmp_path, env_dir=env_dir, timeout=0
        )
    assert not env_dir.exists()
    r = PytestRunner(pr.default_config(runner_opts={"pythonpath_suffix": "/src"}))
    r.setup(FakeExecutor(), pyrepo.path, env_dir=env_dir, timeout=0)
    assert env_dir.is_dir() and os.access(env_dir, os.W_OK)


def test_dist_info_stub_makes_importlib_metadata_resolve_without_shadowing(tmp_path: Path) -> None:
    """`runner_opts.dist_info_stubs`: a METADATA-only distribution so a test asserting the
    package reports a real version passes while the code still comes from the worktree
    (NHSDigital/mesh-client `test_get_version`, 2026-09-14)."""
    import subprocess
    import sys

    from crb.core.runners.pytest_runner import write_dist_info_stub

    venv = tmp_path / "venv"
    subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
    python = venv / "bin" / "python"
    d = write_dist_info_stub(python, "Mesh-Client", "0.0.0+crb")
    assert d.name == "mesh_client-0.0.0+crb.dist-info"
    out = subprocess.run(
        [
            str(python),
            "-c",
            "from importlib.metadata import version; print(version('mesh-client'))",
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert out == "0.0.0+crb"
    # nothing importable was installed: the stub carries no package files
    rc = subprocess.run([str(python), "-c", "import mesh_client"], capture_output=True).returncode
    assert rc != 0
