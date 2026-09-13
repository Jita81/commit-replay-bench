"""crb.core.execution — LocalExecutor (real subprocesses) and DockerExecutor (fake runner).

No docker daemon is needed: the DockerExecutor is driven through an injected
``runner`` and a fake ``docker`` binary path, and every fail-closed branch is
asserted to raise :class:`SandboxUnavailable`.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from crb.core import execution as ex
from crb.core.execution import (
    Command,
    DockerExecutor,
    DockerSettings,
    ExecResult,
    LocalExecutor,
    SandboxUnavailable,
    make_executor,
    sequence_env,
)

PY = sys.executable


def _cmd(*code: str, root: Path, **kw: Any) -> Command:
    return Command((PY, "-c", "\n".join(code)), root, **kw)


# ---------------------------------------------------------------------------
# Command / ExecResult
# ---------------------------------------------------------------------------


def test_command_validation_and_normalisation(tmp_path: Path) -> None:
    c = Command(["echo", 1], tmp_path / "sub" / "..", env={"A": "1"})  # type: ignore[list-item]
    assert c.argv == ("echo", "1")
    assert c.root == tmp_path.resolve()
    assert c.env == {"A": "1"}
    assert c.timeout == ex.DEFAULT_TIMEOUT_S
    assert c.cwd_rel == "." and c.writable_paths == () and c.network is False
    with pytest.raises(ValueError, match="argv"):
        Command((), tmp_path)
    with pytest.raises(ValueError, match="timeout"):
        Command(("x",), tmp_path, timeout=0)


def test_exec_result_properties() -> None:
    assert ExecResult(0, "out", "").ok
    assert not ExecResult(0, "", "", timed_out=True).ok
    assert not ExecResult(1, "", "").ok
    assert ExecResult(0, "a", "b").combined == "a\nb"
    assert ExecResult(0, "a", "").combined == "a"


def test_sequence_env() -> None:
    assert sequence_env({"A": "1"}, None, {"A": "2", "B": "3"}, {}) == {"A": "2", "B": "3"}
    assert sequence_env() == {}


# ---------------------------------------------------------------------------
# LocalExecutor
# ---------------------------------------------------------------------------


def test_local_runs_and_captures(tmp_path: Path) -> None:
    r = LocalExecutor().run(
        _cmd("import sys; print('hi'); print('err', file=sys.stderr)", root=tmp_path)
    )
    assert r.ok and r.returncode == 0
    assert r.stdout.strip() == "hi"
    assert r.stderr.strip() == "err"
    assert not r.timed_out
    assert r.duration_s > 0


def test_local_nonzero_exit(tmp_path: Path) -> None:
    r = LocalExecutor().run(_cmd("raise SystemExit(3)", root=tmp_path))
    assert r.returncode == 3 and not r.ok and not r.timed_out


def test_local_runs_in_cwd_rel(tmp_path: Path) -> None:
    (tmp_path / "sub").mkdir()
    r = LocalExecutor().run(_cmd("import os; print(os.getcwd())", root=tmp_path, cwd_rel="sub"))
    assert Path(r.stdout.strip()).resolve() == (tmp_path / "sub").resolve()


def test_local_env_is_filtered_secrets_do_not_leak(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_TOKEN", "sk-live-should-never-be-visible")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "nope")
    monkeypatch.setenv("TZ", "UTC")
    executor = LocalExecutor()  # base env is captured at construction
    r = executor.run(
        _cmd(
            "import os, json",
            "print(json.dumps({k: os.environ.get(k) for k in ['FAKE_TOKEN','AWS_SECRET_ACCESS_KEY','PATH','TZ','CI','NO_COLOR','PYTHONDONTWRITEBYTECODE','LANG']}))",
            root=tmp_path,
        )
    )
    import json

    seen = json.loads(r.stdout)
    assert seen["FAKE_TOKEN"] is None
    assert seen["AWS_SECRET_ACCESS_KEY"] is None
    assert seen["PATH"] == os.environ["PATH"]
    assert seen["TZ"] == "UTC"
    assert seen["CI"] == "1" and seen["NO_COLOR"] == "1" and seen["PYTHONDONTWRITEBYTECODE"] == "1"
    assert seen["LANG"]


def test_local_command_env_is_layered_over_base(tmp_path: Path) -> None:
    executor = LocalExecutor(base_env={"PATH": os.environ["PATH"], "BASE": "b", "OVER": "base"})
    r = executor.run(
        _cmd(
            "import os; print(os.environ['BASE'], os.environ['OVER'], os.environ.get('HOME','-'))",
            root=tmp_path,
            env={"OVER": "cmd"},
        )
    )
    assert r.stdout.split() == ["b", "cmd", "-"]


def test_local_timeout_kills_the_whole_process_group(tmp_path: Path) -> None:
    pidfile = tmp_path / "child.pid"
    code = (
        "import subprocess, sys, time\n"
        f"p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        f"open({str(pidfile)!r}, 'w').write(str(p.pid))\n"
        "time.sleep(60)\n"
    )
    started = time.monotonic()
    r = LocalExecutor().run(Command((PY, "-c", code), tmp_path, timeout=1))
    assert r.timed_out and r.returncode == 124
    assert time.monotonic() - started < 10
    child = int(pidfile.read_text())
    for _ in range(50):  # the grandchild must die with the group (reparented, then reaped)
        try:
            os.kill(child, 0)
        except ProcessLookupError:
            break
        state = subprocess.run(
            ["ps", "-o", "stat=", "-p", str(child)], capture_output=True, text=True
        ).stdout.strip()
        if not state or state.startswith("Z"):
            break
        time.sleep(0.1)
    else:
        pytest.fail(f"grandchild {child} survived the process-group kill")


def test_local_kill_group_falls_back_to_proc_kill() -> None:
    class FakeProc:
        pid = 999_999_999
        killed = False

        def kill(self) -> None:
            self.killed = True

    fp = FakeProc()
    LocalExecutor._kill_group(fp)  # type: ignore[arg-type]
    assert fp.killed


def test_local_tool_and_describe() -> None:
    e = LocalExecutor()
    assert e.name == "local"
    assert e.tool("python", "/custom/python") == "/custom/python"
    assert e.tool("definitely-not-a-binary-xyz") == "definitely-not-a-binary-xyz"
    assert e.tool("sh") == shutil.which("sh")
    assert e.describe() == {"executor": "local"}


# ---------------------------------------------------------------------------
# DockerSettings (fail-closed at construction)
# ---------------------------------------------------------------------------


def test_docker_settings_requires_image() -> None:
    with pytest.raises(SandboxUnavailable, match="image"):
        DockerSettings(image="")


@pytest.mark.parametrize("user", ["root", "0", "0:0", "ROOT:0", "", ":1000"])
def test_docker_settings_refuses_root(user: str) -> None:
    with pytest.raises(SandboxUnavailable, match="root"):
        DockerSettings(image="img", user=user)


@pytest.mark.parametrize("host", ["/var/run/docker.sock", "/", str(Path.home())])
def test_docker_settings_refuses_dangerous_mounts(host: str) -> None:
    with pytest.raises(SandboxUnavailable, match="refusing to mount"):
        DockerSettings(image="img", extra_ro_mounts={host: "/x"})


def test_docker_settings_defaults() -> None:
    s = DockerSettings(image="img")
    assert s.user == "65534:65534" and s.memory == "2g" and s.cpus == "2" and s.pids_limit == 512
    assert s.workdir == "/work" and s.extra_ro_mounts == {}


# ---------------------------------------------------------------------------
# DockerExecutor with an injected runner
# ---------------------------------------------------------------------------


class FakeRunner:
    """Records argv; answers the daemon probe and container runs from a script."""

    def __init__(self, *responses: subprocess.CompletedProcess[str] | BaseException) -> None:
        self.responses = list(responses)
        self.calls: list[list[str]] = []

    def __call__(self, argv: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append(list(argv))
        resp = (
            self.responses.pop(0)
            if self.responses
            else subprocess.CompletedProcess(argv, 0, "", "")
        )
        if isinstance(resp, BaseException):
            raise resp
        return resp


def _ok(out: str = "27.0") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], 0, out, "")


def _settings(**kw: Any) -> DockerSettings:
    return DockerSettings(image="crb/py:test", docker_binary="/fake/docker", **kw)


def test_docker_executor_probes_the_daemon(tmp_path: Path) -> None:
    fr = FakeRunner(_ok())
    d = DockerExecutor(_settings(), runner=fr)
    assert d.name == "docker" and d.docker == "/fake/docker"
    assert fr.calls == [["/fake/docker", "info", "--format", "{{.ServerVersion}}"]]
    assert d.tool("python", "/host/python") == "python"  # host overrides never apply inside
    assert d.describe() == {
        "executor": "docker",
        "image": "crb/py:test",
        "user": "65534:65534",
        "memory": "2g",
        "cpus": "2",
        "pids_limit": 512,
        "network": "none",
    }


def test_docker_no_binary_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda name: None)
    with pytest.raises(SandboxUnavailable, match="not found on PATH"):
        DockerExecutor(DockerSettings(image="img"), runner=FakeRunner(_ok()))


def test_docker_daemon_probe_failure_fails_closed() -> None:
    with pytest.raises(SandboxUnavailable, match="not reachable"):
        DockerExecutor(
            _settings(), runner=FakeRunner(subprocess.CompletedProcess([], 1, "", "Cannot connect"))
        )
    with pytest.raises(SandboxUnavailable, match="probe failed"):
        DockerExecutor(_settings(), runner=FakeRunner(FileNotFoundError("docker")))
    with pytest.raises(SandboxUnavailable, match="probe failed"):
        DockerExecutor(_settings(), runner=FakeRunner(subprocess.TimeoutExpired("docker", 30)))


def test_docker_build_argv_has_every_hardening_flag(tmp_path: Path) -> None:
    d = DockerExecutor(_settings(), runner=FakeRunner(_ok()), verify_daemon=False)
    cmd = Command(
        ("python", "-m", "pytest", "-q"), tmp_path, env={"PYTHONPATH": "/work/src"}, timeout=90
    )
    argv = d.build_argv(cmd)
    assert argv[:3] == ["/fake/docker", "run", "--rm"]
    for flag in [
        "--network=none",
        "--memory=2g",
        "--cpus=2",
        "--pids-limit=512",
        "--user=65534:65534",
        "--cap-drop=ALL",
        "--read-only",
        "--stop-timeout=90",
    ]:
        assert flag in argv, flag
    assert argv[argv.index("--security-opt") + 1] == "no-new-privileges"
    assert argv[argv.index("--tmpfs") + 1] == "/tmp:rw,nosuid,nodev,size=512m"
    mounts = [argv[i + 1] for i, a in enumerate(argv) if a == "--mount"]
    assert mounts == [f"type=bind,src={tmp_path.resolve()},dst=/work,readonly"]
    envs = [argv[i + 1] for i, a in enumerate(argv) if a == "--env"]
    assert envs == ["PYTHONPATH=/work/src", "HOME=/tmp", "CI=1", "NO_COLOR=1"]
    assert argv[argv.index("--workdir") + 1] == "/work"
    assert argv[-5:] == ["crb/py:test", "python", "-m", "pytest", "-q"]
    assert "--privileged" not in argv and "docker.sock" not in " ".join(argv)


def test_docker_build_argv_network_writable_paths_extra_mounts_and_cwd(tmp_path: Path) -> None:
    d = DockerExecutor(
        _settings(extra_ro_mounts={"/opt/gomod": "/gomod"}, workdir="/w"),
        runner=FakeRunner(_ok()),
        verify_daemon=False,
    )
    cmd = Command(
        ("mvn", "test"),
        tmp_path,
        cwd_rel="core",
        writable_paths=("target", "core/target/"),
        network=True,
        timeout=5,
    )
    argv = d.build_argv(cmd)
    assert "--network=bridge" in argv and "--network=none" not in argv
    assert "--cap-drop=ALL" in argv and "--read-only" in argv  # every other cap still applies
    mounts = [argv[i + 1] for i, a in enumerate(argv) if a == "--mount"]
    assert mounts == [
        f"type=bind,src={tmp_path.resolve()},dst=/w,readonly",
        f"type=bind,src={tmp_path.resolve() / 'target'},dst=/w/target",
        f"type=bind,src={tmp_path.resolve() / 'core/target/'},dst=/w/core/target",
        "type=bind,src=/opt/gomod,dst=/gomod,readonly",
    ]
    for rel in ("target", "core/target"):
        p = tmp_path / rel
        assert p.is_dir()
        assert stat.S_IMODE(p.stat().st_mode) & 0o777 == 0o777  # world-writable for uid 65534
    assert argv[argv.index("--workdir") + 1] == "/w/core"


def test_docker_run_returns_result_and_records_argv(tmp_path: Path) -> None:
    fr = FakeRunner(_ok(), subprocess.CompletedProcess([], 1, "FAILED t::x", "warn"))
    d = DockerExecutor(_settings(), runner=fr)
    r = d.run(Command(("pytest",), tmp_path, timeout=7))
    assert r.returncode == 1 and r.stdout == "FAILED t::x" and r.stderr == "warn"
    assert not r.timed_out and r.duration_s >= 0
    assert fr.calls[-1][:3] == ["/fake/docker", "run", "--rm"]


def test_docker_run_timeout_is_124_not_a_pass(tmp_path: Path) -> None:
    fr = FakeRunner(_ok(), subprocess.TimeoutExpired("docker", 7))
    r = DockerExecutor(_settings(), runner=fr).run(Command(("pytest",), tmp_path, timeout=7))
    assert r.timed_out and r.returncode == 124 and not r.ok
    assert "TIMEOUT" in r.stderr


def test_docker_run_exit_125_fails_closed(tmp_path: Path) -> None:
    fr = FakeRunner(_ok(), subprocess.CompletedProcess([], 125, "", "docker: image not found"))
    with pytest.raises(SandboxUnavailable, match="exit 125"):
        DockerExecutor(_settings(), runner=fr).run(Command(("pytest",), tmp_path))


def test_docker_run_binary_vanishing_fails_closed(tmp_path: Path) -> None:
    fr = FakeRunner(_ok(), FileNotFoundError("/fake/docker"))
    with pytest.raises(SandboxUnavailable, match="unusable at run time"):
        DockerExecutor(_settings(), runner=fr).run(Command(("pytest",), tmp_path))


# ---------------------------------------------------------------------------
# make_executor
# ---------------------------------------------------------------------------


def _fake_docker(dir_: Path, rc: int) -> str:
    """A real executable standing in for ``docker``: answers the daemon probe with ``rc``."""
    dir_.mkdir(parents=True, exist_ok=True)
    script = dir_ / "docker"
    script.write_text(f"#!/bin/sh\necho 27.0\nexit {rc}\n")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return str(script)


@pytest.mark.parametrize("kind", ["", "local", "LOCAL", "none", "host"])
def test_make_executor_local(kind: str) -> None:
    assert isinstance(make_executor(kind), LocalExecutor)


def test_make_executor_docker_requires_settings() -> None:
    with pytest.raises(SandboxUnavailable, match="requires DockerSettings"):
        make_executor("docker")


def test_make_executor_docker_with_a_live_probe(tmp_path: Path) -> None:
    good = DockerSettings(image="img", docker_binary=_fake_docker(tmp_path / "good", 0))
    e = make_executor("docker", docker=good)
    assert isinstance(e, DockerExecutor)
    bad = DockerSettings(image="img", docker_binary=_fake_docker(tmp_path / "bad", 1))
    with pytest.raises(SandboxUnavailable, match="not reachable"):
        make_executor("docker", docker=bad)


def test_make_executor_unknown_kind() -> None:
    with pytest.raises(ValueError, match="unknown executor"):
        make_executor("podman")


def test_local_executor_closes_stdin_so_input_fails_fast(tmp_path: Path) -> None:
    """A repository test that blocks on stdin (click's termui tests do) must fail
    immediately with EOF, never hang until the wall-clock timeout."""
    from crb.core.execution import Command, LocalExecutor

    cmd = Command(
        (sys.executable, "-c", "import sys; sys.stdin.readline(); print('read')"),
        tmp_path,
        timeout=10,
    )
    r = LocalExecutor().run(cmd)
    assert not r.timed_out and r.duration_s < 5
    assert "read" in r.stdout  # readline() returns '' at EOF instantly
