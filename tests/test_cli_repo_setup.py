"""``crb repo setup`` and the auto-setup in ``crb repo probe``, driven in-process.

Hermetic cases use a scripted runner (the environment phase is answered from a
script); the one real case (``@pytest.mark.network``) builds a genuine ``uv``
venv under ``<workdir>/envs/<name>`` and proves the probe then runs on it.
"""

from __future__ import annotations

import json
import shutil
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, ClassVar

import pytest

from crb.cli.commands import repo as repo_cmd
from crb.cli.main import main
from crb.core.runners.base import SetupResult, SetupStep
from crb.core.runners.pytest_runner import PytestRunner, venv_python
from fixtures import pyrepo as pr

Run = Callable[[Sequence[str]], tuple[int, str, str]]


@pytest.fixture
def workdir(tmp_path: Path) -> Path:
    return tmp_path / ".crb"


@pytest.fixture
def run(workdir: Path, capsys: pytest.CaptureFixture[str]) -> Run:
    def _run(argv: Sequence[str]) -> tuple[int, str, str]:
        capsys.readouterr()
        code = main([*argv, "--workdir", str(workdir)])
        out = capsys.readouterr()
        return code, out.out, out.err

    return _run


def _json(run: Run, argv: Sequence[str]) -> tuple[int, dict[str, Any]]:
    code, out, _ = run([*argv, "--json"])
    return code, json.loads(out)


def _register(run: Run, pyrepo: pr.PyRepo, name: str, *opts: str) -> None:
    argv = [
        "repo",
        "add",
        name,
        "--path",
        str(pyrepo.path),
        "--language",
        "py",
        "--src-prefix",
        "src/",
        "--test-prefix",
        "tests/",
        "--probe",
        pr.TEST_CALC,
        "--runner-opt",
        "pythonpath_suffix=/src",
    ]
    for o in opts:
        argv += ["--runner-opt", o]
    code, _, err = run(argv)
    assert code == 0, err


class ScriptedRunner(PytestRunner):
    ready: ClassVar[list[bool]] = [True]
    outcome: ClassVar[SetupResult] = SetupResult(True, (), "scripted", 0.0)
    calls: ClassVar[list[Path]] = []

    def environment_ready(self, root: Path, env_dir: Path) -> bool:
        cls = type(self)
        return cls.ready.pop(0) if len(cls.ready) > 1 else cls.ready[0]

    def setup(self, executor: Any, root: Path, *, env_dir: Path, timeout: int, **_: Any) -> Any:
        type(self).calls.append(Path(env_dir))
        return type(self).outcome


@pytest.fixture
def scripted(monkeypatch: pytest.MonkeyPatch) -> type[ScriptedRunner]:
    ScriptedRunner.ready = [True]
    ScriptedRunner.outcome = SetupResult(True, (), "scripted", 0.0)
    ScriptedRunner.calls = []
    monkeypatch.setattr(repo_cmd, "get_runner", lambda config: ScriptedRunner(config))
    return ScriptedRunner


# --- crb repo setup ----------------------------------------------------------------------


def test_setup_with_explicit_python_verifies_and_records_env_dir(
    run: Run, pyrepo: pr.PyRepo, workdir: Path
) -> None:
    _register(run, pyrepo, "demo", f"python={sys.executable}")
    code, d = _json(run, ["repo", "setup", "demo"])
    assert code == 0, d
    assert d["ok"] is True and d["ready"] is True and d["steps"] == []
    assert "runner_opts.python" in d["note"] and d["runner"] == "pytest"
    assert d["env_dir"] == str(workdir / "envs" / "demo") and d["executor"] == {"executor": "local"}
    stored = json.loads((workdir / "repos" / "demo.json").read_text(encoding="utf-8"))
    assert stored["env_dir"] == d["env_dir"]
    code, out, _ = run(["repo", "setup", "demo"])
    assert code == 0 and "demo: setup -> READY" in out
    # the recorded env_dir is what later commands use
    assert repo_cmd.env_dir_of(repo_cmd.Workdir(workdir), "demo") == workdir / "envs" / "demo"


def test_setup_failure_exits_negative_with_the_steps(
    run: Run, pyrepo: pr.PyRepo, scripted: type[ScriptedRunner]
) -> None:
    _register(run, pyrepo, "demo")
    scripted.outcome = SetupResult(
        False,
        (
            SetupStep(("uv", "venv", "x"), 0, "", 0.1),
            SetupStep(("uv", "pip", "install", "-e", "."), 1, "ERROR: build failed", 0.2),
        ),
        "step 2 failed (rc=1): uv pip install -e .",
        0.3,
    )
    code, d = _json(run, ["repo", "setup", "demo"])
    assert code == 1 and d["ok"] is False and len(d["steps"]) == 2
    assert d["steps"][1]["tail"] == "ERROR: build failed"
    code, out, _ = run(["repo", "setup", "demo"])
    assert code == 1 and "setup -> FAILED" in out and "[2] rc=1" in out and "build failed" in out


def test_setup_unknown_repo_is_a_usage_error(run: Run) -> None:
    code, _, err = run(["repo", "setup", "ghost"])
    assert code == 2 and "unknown repo" in err


# --- crb repo probe auto-setup --------------------------------------------------------------


def test_probe_runs_setup_when_not_ready(
    run: Run, pyrepo: pr.PyRepo, scripted: type[ScriptedRunner], workdir: Path
) -> None:
    _register(run, pyrepo, "demo", f"python={sys.executable}")
    scripted.ready = [False, True]
    scripted.outcome = SetupResult(True, (SetupStep(("uv", "venv", "x"), 0),), "ready", 0.1)
    code, d = _json(run, ["repo", "probe", "demo"])
    assert code == 0, d
    assert d["green"] is True and d["setup"]["ok"] is True and len(d["setup"]["steps"]) == 1
    assert scripted.calls == [workdir / "envs" / "demo"]
    stored = json.loads((workdir / "repos" / "demo.json").read_text(encoding="utf-8"))
    assert stored["env_dir"] == str(workdir / "envs" / "demo")
    # ready → no setup, no "setup" key
    scripted.ready = [True]
    scripted.calls = []
    code, d = _json(run, ["repo", "probe", "demo"])
    assert code == 0 and "setup" not in d and scripted.calls == []
    code, out, _ = run(["repo", "probe", "demo"])
    assert code == 0 and "GREEN" in out and "setup ->" not in out


def test_probe_does_not_run_when_auto_setup_fails(
    run: Run, pyrepo: pr.PyRepo, scripted: type[ScriptedRunner]
) -> None:
    _register(run, pyrepo, "demo", f"python={sys.executable}")
    scripted.ready = [False]
    scripted.outcome = SetupResult(
        False, (SetupStep(("npm", "ci"), 1, "npm ERR! offline", 0.1),), "step 1 failed", 0.1
    )
    code, d = _json(run, ["repo", "probe", "demo"])
    assert code == 1 and d["green"] is False and d["setup"]["ok"] is False
    assert "returncode" not in d  # the probe never ran
    code, out, _ = run(["repo", "probe", "demo"])
    assert code == 1 and "probe not run (setup failed)" in out and "npm ERR! offline" in out


# --- the real thing -----------------------------------------------------------------------


@pytest.mark.network
@pytest.mark.skipif(shutil.which("uv") is None, reason="uv not on PATH")
def test_setup_builds_a_venv_and_probe_uses_it(run: Run, pyrepo: pr.PyRepo, workdir: Path) -> None:
    pyrepo.add_pyproject_commit()
    _register(run, pyrepo, "demo", f"uninstall={pr.DIST_NAME}")
    code, d = _json(run, ["repo", "setup", "demo", "--timeout", "600"])
    assert code == 0, d
    py = venv_python(workdir / "envs" / "demo")
    assert d["ok"] is True and d["ready"] is True and py.exists()
    verbs = [" ".join(s["argv"]) for s in d["steps"]]
    assert any(v.endswith("-e .[test]") for v in verbs) and any("uninstall" in v for v in verbs)
    code, d = _json(run, ["repo", "probe", "demo", "--timeout", "300"])
    assert code == 0 and d["green"] is True and "setup" not in d
