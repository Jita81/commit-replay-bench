"""crb.core.execution — LocalExecutor (real subprocesses) and DockerExecutor (fake runner).

No docker daemon is needed: the DockerExecutor is driven through an injected
``runner`` and a fake ``docker`` binary path, and every fail-closed branch is
asserted to raise :class:`SandboxUnavailable`.

Navigation
----------
What it is:   The executors' test suite: ``LocalExecutor`` on real subprocesses and
              ``DockerExecutor`` through a fake ``docker`` binary and an injected runner.
What it does: Pins ``Command`` validation, that the local executor filters the environment (an
              operator's secret never reaches a test run), layers command env over the base,
              kills the whole process group on timeout and on cancel, closes stdin so a test that
              blocks on input fails fast (click's termui tests); and that the docker executor
              probes the daemon, refuses root, dangerous mounts and a missing image, builds every
              hardening flag into ``docker run``, and raises ``SandboxUnavailable`` on a missing
              binary, a failed probe, exit 125 or a vanishing binary — a timeout is rc 124, never
              a pass. For ``DockerStream``: after an enforced kill (cancel, wall clock)
              ``lines()`` does not return before a BOUNDED confirmation attempt through
              ``docker inspect`` has ended — bounded by ``KILL_CONFIRM_S`` across every inspect
              call, so it can end WITHOUT confirming (``kill_confirmed`` is False and a warning
              names the container); ``inspect`` output is accepted only as the exact strings
              ``true`` / ``false`` (anything else is unknown, never a stop); a removed (``--rm``)
              container counts as stopped; a natural exit asks the daemon nothing. The same
              contract on the NON-stream path (``DockerExecutor.run`` under a cancel token —
              the belt / test runner's path): the cancel and the wall clock both end in a
              confirmed ``docker kill`` (``ExecResult.kill_confirmed`` True, ``container``
              named, the client's process group killed), an unconfirmed kill is recorded on
              ``unconfirmed_kills`` and handed to ``on_kill_unconfirmed`` (a raising callback
              is logged, never the result), and a removed container is confirmed.
How:          Real ``subprocess`` for the local half; ``FakeRunner`` records argv and scripts the
              daemon's answers for the docker half — no daemon is needed. ``DockerStream`` and
              the cancellable ``run`` path go against a fake ``docker`` script whose ``inspect``
              answers are scripted.
Layer:        tests — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0005-fail-closed-docker-sandbox.md
Works with:   src/crb/core/execution.py (under test), tests/test_sandbox_docker.py (the same
              executor against a real daemon), docs/SECURITY.md (the sandbox flags the argv test
              pins)
Tested by:    tests/test_execution.py
Touch when:   never for a new repository; a hardening flag is added or removed (the argv test lists
              every one; update docs/SECURITY.md with it); a new executor kind is registered in
              ``make_executor``.
"""

from __future__ import annotations

import errno
import io
import os
import shutil
import socket
import stat
import subprocess
import sys
import tarfile
import threading
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
    docker_server_version,
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
    assert s.tree == "copy" and s.work_size == "1g"  # ADR-0019 §7: a throwaway tree by default
    with pytest.raises(SandboxUnavailable, match="sandbox tree"):
        DockerSettings(image="img", tree="rw")


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


#: What a docker CLI before 29 answers a formatted ``docker info`` with when its daemon is
#: down: the template rendered empty, the error on stderr, and exit 0 (the fresh-clone job's
#: first run, 2026-09-28 — docs/PREVENTION.md P-744).
_EMPTY_INFO = subprocess.CompletedProcess(
    [],
    0,
    "\n",
    "Cannot connect to the Docker daemon at unix:///var/run/docker.sock. "
    "Is the docker daemon running?\n",
)


def test_a_daemon_probe_that_names_no_server_version_fails_closed() -> None:
    """Exit 0 alone is not an answer: the executor refuses unless the daemon named its
    version, and says what the CLI said."""
    with pytest.raises(SandboxUnavailable, match="not reachable: Cannot connect"):
        DockerExecutor(_settings(), runner=FakeRunner(_EMPTY_INFO))
    with pytest.raises(SandboxUnavailable, match="named no server version"):
        docker_server_version("/fake/docker", runner=FakeRunner(_ok("")))
    fr = FakeRunner(_ok("27.5.1\n"))
    assert docker_server_version("/fake/docker", runner=fr, timeout=7) == "27.5.1"
    assert fr.calls == [["/fake/docker", "info", "--format", "{{.ServerVersion}}"]]


def test_docker_build_argv_has_every_hardening_flag(tmp_path: Path) -> None:
    d = DockerExecutor(_settings(tree="readonly"), runner=FakeRunner(_ok()), verify_daemon=False)
    cmd = Command(
        ("python", "-m", "pytest", "-q"), tmp_path, env={"PYTHONPATH": "/work/src"}, timeout=90
    )
    argv = d.build_argv(cmd)
    assert argv[:3] == ["/fake/docker", "run", "--rm"]
    for flag in [
        "--pull=never",  # the worker never pulls: an absent image fails closed (exit 125)
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
    assert argv[argv.index("--tmpfs") + 1] == "/tmp:rw,noexec,nosuid,nodev,size=512m"
    mounts = [argv[i + 1] for i, a in enumerate(argv) if a == "--mount"]
    assert mounts == [f"type=bind,src={tmp_path.resolve()},dst=/work,readonly"]
    envs = [argv[i + 1] for i, a in enumerate(argv) if a == "--env"]
    assert envs == ["PYTHONPATH=/work/src", "HOME=/tmp", "CI=1", "NO_COLOR=1"]
    assert argv[argv.index("--workdir") + 1] == "/work"
    assert argv[-5:] == ["crb/py:test", "python", "-m", "pytest", "-q"]
    assert "--privileged" not in argv and "docker.sock" not in " ".join(argv)


def test_docker_build_argv_exec_tmp_is_declared_per_command(tmp_path: Path) -> None:
    """The tmpfs is ``noexec`` by statement, not by the runtime's default; only a command
    whose toolchain runs what it builds under ``/tmp`` (``go test``) gets ``exec`` — and it
    still gets ``nosuid,nodev``, the size cap and every other flag."""
    d = DockerExecutor(_settings(), runner=FakeRunner(_ok()), verify_daemon=False)
    plain = d.build_argv(Command(("python", "-m", "pytest"), tmp_path))
    plain_tmpfs = plain[plain.index("--tmpfs") + 1]
    assert plain_tmpfs == "/tmp:rw,noexec,nosuid,nodev,size=512m"
    assert "noexec" in plain_tmpfs.split(",") and "exec" not in plain_tmpfs.split(",")
    go = d.build_argv(Command(("go", "test", "-json", "./..."), tmp_path, exec_tmp=True))
    go_tmpfs = go[go.index("--tmpfs") + 1]
    assert go_tmpfs == "/tmp:rw,exec,nosuid,nodev,size=512m"
    assert "exec" in go_tmpfs.split(",") and "noexec" not in go_tmpfs.split(",")
    # every other option is byte-identical: only the tmpfs options (and the argv) differ
    head_plain = plain[: plain.index("crb/py:test")]
    head_go = go[: go.index("crb/py:test")]
    head_go[head_go.index("--tmpfs") + 1] = head_plain[head_plain.index("--tmpfs") + 1]
    assert head_go == head_plain
    assert "--read-only" in go and "--cap-drop=ALL" in go and "--network=none" in go


def test_docker_build_argv_writable_paths_extra_mounts_and_cwd(tmp_path: Path) -> None:
    d = DockerExecutor(
        _settings(extra_ro_mounts={"/opt/gomod": "/gomod"}, workdir="/w", tree="readonly"),
        runner=FakeRunner(_ok()),
        verify_daemon=False,
    )
    cmd = Command(
        ("mvn", "test"),
        tmp_path,
        cwd_rel="core",
        writable_paths=("target", "core/target/"),
        timeout=5,
    )
    argv = d.build_argv(cmd)
    assert "--network=none" in argv and "--network=bridge" not in argv
    assert "--cap-drop=ALL" in argv and "--read-only" in argv
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
        assert (
            stat.S_IMODE(p.stat().st_mode) & 0o777 == 0o733
        )  # writable for uid 65534, never world-listable
    assert argv[argv.index("--workdir") + 1] == "/w/core"


def test_readonly_tree_keeps_todays_argv(tmp_path: Path) -> None:
    """``tree: readonly`` is the shape every run had before ADR-0019, token for token."""
    d = DockerExecutor(_settings(tree="readonly"), runner=FakeRunner(_ok()), verify_daemon=False)
    argv = d.build_argv(Command(("go", "test", "./..."), tmp_path, exec_tmp=True, timeout=60))
    assert argv == [
        "/fake/docker",
        "run",
        "--rm",
        "--pull=never",
        "--network=none",
        "--memory=2g",
        "--cpus=2",
        "--pids-limit=512",
        "--user=65534:65534",
        "--cap-drop=ALL",
        "--security-opt",
        "no-new-privileges",
        "--read-only",
        "--tmpfs",
        "/tmp:rw,exec,nosuid,nodev,size=512m",
        "--mount",
        f"type=bind,src={tmp_path.resolve()},dst=/work,readonly",
        "--env",
        "HOME=/tmp",
        "--env",
        "CI=1",
        "--env",
        "NO_COLOR=1",
        "--workdir",
        "/work",
        "--stop-timeout=60",
        "crb/py:test",
        "go",
        "test",
        "./...",
    ]


def test_copy_tree_argv_streams_the_worktree_over_stdin_into_a_sized_exec_tmpfs_at_work(
    tmp_path: Path,
) -> None:
    """The default tree (ADR-0019 §7): NO worktree mount — the host streams the tree in on
    stdin (``--interactive``) — a size-capped tmpfs at ``/work`` (``exec`` because the tree
    was always executable to its own tests, and ``nosuid,nodev``), a declared writable path
    still bound from the worktree, and the command run by ``sh`` in the copy only once the
    stream's sentinel arrived; the command's own stdin stays ``/dev/null``."""
    d = DockerExecutor(_settings(work_size="3g"), runner=FakeRunner(_ok()), verify_daemon=False)
    cmd = Command(
        ("python", "-m", "pytest", "-q"),
        tmp_path,
        cwd_rel="pkg",
        env={"PYTHONPATH": "/work"},
        writable_paths=(".pytest_scratch",),
        timeout=90,
    )
    argv = d.build_argv(cmd, sentinel="0123456789abcdef")
    script = (
        "tar -C /work -xf - && [ -e /work/.crb-tree-0123456789abcdef ] "
        "&& { rm -f /work/.crb-tree-0123456789abcdef || :; } "
        "|| { echo crb:tree-copy-failed >&2; exit 97; }; "
        'cd "/work/$0" && exec "$@" </dev/null'
    )
    assert argv == [
        "/fake/docker",
        "run",
        "--rm",
        "--pull=never",
        "--network=none",
        "--memory=2g",
        "--cpus=2",
        "--pids-limit=512",
        "--user=65534:65534",
        "--cap-drop=ALL",
        "--security-opt",
        "no-new-privileges",
        "--read-only",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,nodev,size=512m",
        "--interactive",
        "--tmpfs",
        "/work:rw,exec,nosuid,nodev,size=3g,uid=65534,gid=65534,mode=0700",
        "--mount",
        f"type=bind,src={tmp_path.resolve() / '.pytest_scratch'},dst=/work/.pytest_scratch",
        "--env",
        "PYTHONPATH=/work",
        "--env",
        "HOME=/tmp",
        "--env",
        "CI=1",
        "--env",
        "NO_COLOR=1",
        "--workdir",
        "/work",
        "--stop-timeout=90",
        "crb/py:test",
        "/bin/sh",
        "-c",
        script,
        "pkg",
        "python",
        "-m",
        "pytest",
        "-q",
    ]
    # the worktree reaches the container only as the stream: no bind of the tree itself
    assert not any(f"src={tmp_path.resolve()}," in a for a in argv)
    # no sentinel named: a fresh random one per argv, never a fixed, guessable name
    drawn = [d.build_argv(cmd)[-6] for _ in range(2)]
    assert drawn[0] != drawn[1] and all(".crb-tree-" in x for x in drawn)
    facts = d.posture_facts()
    assert facts["tree"] == "copy" and facts["limits"].endswith(",work=3g")
    ro = DockerExecutor(_settings(tree="readonly"), runner=FakeRunner(_ok()), verify_daemon=False)
    ro_facts = ro.posture_facts()
    assert ro_facts["tree"] == "readonly" and "work=" not in ro_facts["limits"]
    assert LocalExecutor().posture_facts() == {
        "executor": "local",
        "tree": "inplace",
        "network": "host",
    }
    # the builder's own fixer writes the worktree itself: "." keeps today's shape
    fixer = d.build_argv(Command(("gofmt", "-w", "x.go"), tmp_path, writable_paths=(".",)))
    assert "/bin/sh" not in fixer
    assert f"type=bind,src={tmp_path.resolve()},dst=/work,readonly" in fixer
    assert any(a.endswith("dst=/work/.") for a in fixer)  # the fixer's rw bind, as before


def test_once_the_posture_names_the_image_by_id_every_container_runs_that_id(
    tmp_path: Path,
) -> None:
    """The posture names the image by content id; a container started by tag would run
    whatever the tag points at NOW — a rebuild mid-run would grade a trial on bytes no
    posture or qualification names. After ``image_id()`` every argv carries the id."""
    ident = "sha256:" + "9" * 64
    d = DockerExecutor(_settings(), runner=FakeRunner(_ok(ident)), verify_daemon=False)
    before = d.build_argv(Command(("go", "test"), tmp_path))
    assert "crb/py:test" in before  # nothing has named the id yet (an ad hoc grade)
    assert d.posture_facts()["image_id"] == ident
    for tree in ("copy", "readonly"):
        d.settings = _settings(tree=tree)
        argv = d.build_argv(Command(("go", "test"), tmp_path))
        assert ident in argv and "crb/py:test" not in argv, argv
    assert d.posture_facts()["image_ref"] == "crb/py:test"  # the stamp still names the tag


def test_network_true_is_refused_under_docker(tmp_path: Path) -> None:
    d = DockerExecutor(_settings(), runner=FakeRunner(_ok()), verify_daemon=False)
    for tree in ("copy", "readonly"):
        ex = DockerExecutor(_settings(tree=tree), runner=FakeRunner(_ok()), verify_daemon=False)
        with pytest.raises(SandboxUnavailable, match="never installed in the sandbox"):
            ex.build_argv(Command(("npm", "ci"), tmp_path, network=True))
    with pytest.raises(SandboxUnavailable, match="provisioned per task"):
        d.run(Command(("pip", "install", "x"), tmp_path, network=True))


def test_a_bundle_mount_outside_the_store_is_refused(tmp_path: Path) -> None:
    from crb.core.deps import BundleMount
    from crb.provision.store import BundleStore

    store = BundleStore(tmp_path / "deps")
    st = store.stage()
    (st / "out" / "gomod").mkdir()
    key = "dep_" + "4" * 64
    store.seal(st, {"lang": "go", "key": key})
    good = store.mount(key, "go", "gomod", "/deps/gomod")
    d = DockerExecutor(_settings(), runner=FakeRunner(_ok()), verify_daemon=False)
    argv = d.build_argv(Command(("go", "test"), tmp_path, ro_mounts=(good,)))
    assert f"type=bind,src={good.host_path.resolve()},dst=/deps/gomod,readonly" in argv
    forged = object.__new__(BundleMount)
    object.__setattr__(forged, "host_path", tmp_path / "evil" / "go" / key)
    object.__setattr__(forged, "container_path", "/deps/gomod")
    object.__setattr__(forged, "key", key)
    with pytest.raises(SandboxUnavailable, match="registered bundle store"):
        d.build_argv(Command(("go", "test"), tmp_path, ro_mounts=(forged,)))
    # a sealed set someone made writable again is refused at use, too
    (good.host_path).chmod(0o755)
    with pytest.raises(SandboxUnavailable, match="not sealed"):
        d.build_argv(Command(("go", "test"), tmp_path, ro_mounts=(good,)))


@pytest.mark.parametrize("tree", ["copy", "readonly"])
def test_a_command_that_reads_no_tree_mounts_none_copies_none_and_walks_none(
    tmp_path: Path, tree: str
) -> None:
    """``Command(tree=False)`` (a toolchain version probe): the sandbox mounts no worktree,
    runs no copy script and never walks the tree to make it readable — the probe costs a
    container, not a copy of the clone (CodeRabbit on PR #56). A writable path makes no
    sense without a tree and is refused."""
    root = tmp_path / "clone"
    (root / ".git").mkdir(parents=True)
    (root / "private.txt").write_text("x", encoding="utf-8")
    (root / "private.txt").chmod(0o600)
    fr = FakeRunner(_ok(), _ok("go version go1.26.8 linux/arm64"))
    d = DockerExecutor(_settings(tree=tree), runner=fr)
    cmd = Command(("go", "version"), root, tree=False, timeout=30)
    argv = d.build_argv(cmd)
    assert not any(str(root) in a for a in argv), argv
    assert "/bin/sh" not in argv and argv[-2:] == ["go", "version"]
    assert "/work:rw,noexec,nosuid,nodev,size=16m,uid=65534,gid=65534,mode=0700" in argv
    assert d.run(cmd).stdout.startswith("go version")
    assert stat.S_IMODE(os.lstat(root / "private.txt").st_mode) == 0o600  # never walked
    with pytest.raises(ValueError, match="writable"):
        Command(("go", "version"), root, tree=False, writable_paths=("out",))


@pytest.mark.parametrize("tree", ["copy", "readonly"])
def test_docker_run_lets_the_sandbox_uid_read_the_tree_never_write_never_through_a_link(
    tmp_path: Path, tree: str
) -> None:
    """Host modes never hide the tree from the sandbox uid (PR #56, sandbox-images): before
    the container starts, every directory and file the worker owns gains read (and search on
    a directory) for its owner and for others — a file executable by its owner becomes so
    for others. No write bit is ever added, the owner's execute bit (git's mode) is never
    changed, a link is never followed, the command's own writable paths are left to
    ``build_argv``, and in the copy tree ``node_modules`` (never copied) is not walked."""

    def mode(p: Path) -> int:
        return stat.S_IMODE(os.lstat(p).st_mode)

    root = tmp_path / "tree"
    planted = {
        "locked/sub/inner.txt": 0o644,
        "owner_only.txt": 0o600,
        "no_bits.txt": 0o000,
        "run.sh": 0o700,
        "node_modules/pkg.js": 0o600,
    }
    for rel, m in planted.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text("x", encoding="utf-8")
        (root / rel).chmod(m)
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    outside.chmod(0o600)
    (root / "link").symlink_to(outside)
    (root / ".pytest_scratch").mkdir()
    (root / "locked" / "sub").chmod(0o000)
    (root / "locked").chmod(0o000)
    try:
        d = DockerExecutor(_settings(tree=tree), runner=FakeRunner(_ok(), _ok("")))
        d.run(Command(("pytest",), root, writable_paths=(".pytest_scratch",)))
        assert mode(root / "locked") == 0o505 and mode(root / "locked" / "sub") == 0o505
        assert mode(root / "locked" / "sub" / "inner.txt") == 0o644
        assert mode(root / "owner_only.txt") == 0o604
        assert mode(root / "no_bits.txt") == 0o404
        assert mode(root / "run.sh") == 0o705
        assert mode(outside) == 0o600  # never through the link
        assert mode(root / ".pytest_scratch") == 0o733  # build_argv's, not widened
        assert mode(root / "node_modules" / "pkg.js") == (0o600 if tree == "copy" else 0o604)
    finally:
        for p in (root / "locked", root / "locked" / "sub"):
            p.chmod(0o755)


def test_tree_copy_failure_is_an_env_error_not_a_verdict(tmp_path: Path) -> None:
    from crb.core.runners import get_runner
    from crb.core.spec import Language, RepoConfig

    failed = subprocess.CompletedProcess([], 97, "", "tar: short read\ncrb:tree-copy-failed\n")
    fr = FakeRunner(_ok(), failed)
    r = DockerExecutor(_settings(), runner=fr).run(Command(("pytest",), tmp_path))
    assert r.env_error == "tree_copy_failed" and not r.ok
    # a test that merely exits 97 is not an environment error
    fr2 = FakeRunner(_ok(), subprocess.CompletedProcess([], 97, "", "boom"))
    assert DockerExecutor(_settings(), runner=fr2).run(Command(("x",), tmp_path)).env_error == ""
    # through a runner: red, no failing id attributed, the environment named
    runner = get_runner(RepoConfig(name="fx", language=Language.PYTHON, runner="pytest"))
    fr3 = FakeRunner(_ok(), failed)
    run = runner.run(DockerExecutor(_settings(), runner=fr3), tmp_path, ("tests/x.py",))
    assert run.env_error == "tree_copy_failed" and run.red and run.failing == frozenset()
    assert run.parse_error == "environment: tree_copy_failed"
    assert run.to_dict()["env_error"] == "tree_copy_failed"


# ---------------------------------------------------------------------------
# TreeStream — the HOST writes the tree the container extracts (virtiofs, 2026-10-23)
# ---------------------------------------------------------------------------


def _members(tree: ex.TreeStream) -> tuple[list[tarfile.TarInfo], dict[str, bytes]]:
    buf = io.BytesIO()
    tree.write(buf)
    buf.seek(0)
    with tarfile.open(fileobj=buf, mode="r:") as tf:
        members = tf.getmembers()
        data = {}
        for m in members:
            f = tf.extractfile(m) if m.isreg() else None
            if f is not None:
                data[m.name] = f.read()
    return members, data


def test_tree_stream_archives_the_whole_tree_and_ends_with_its_sentinel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every entry but the excluded root-relative paths and what lies under them (a nested
    ``node_modules`` stays, as GNU ``tar --exclude=./node_modules`` kept it), depth-first —
    a directory, then all it holds, then its next sibling, as ``tar -c`` orders it — links as links (never followed), a hard link as one, a FIFO as a
    FIFO, a socket skipped, no host owner, whole-second times, the host's modes — and the
    empty sentinel LAST; ``complete`` only once it was handed to the archive."""
    root = tmp_path / "wt"
    (root / "pkg" / "sub").mkdir(parents=True)
    (root / "pkg" / "a.go").write_text("package pkg\n")
    big = os.urandom(70_000)  # more than one tar record
    (root / "pkg" / "sub" / "b.go").write_bytes(big)
    (root / "run.sh").write_text("#!/bin/sh\n")
    (root / "run.sh").chmod(0o755)
    (root / "link").symlink_to("/etc/passwd")
    os.link(root / "pkg" / "a.go", root / "hard.go")
    (root / "node_modules" / "dep").mkdir(parents=True)
    (root / ".pytest_scratch").mkdir()
    (root / ".pytest_scratch" / "junit.xml").write_text("a previous command's report")
    (root / "pkg" / "node_modules").mkdir()
    os.mkfifo(root / "fifo")
    monkeypatch.chdir(root)  # a short relative name: AF_UNIX paths are capped at ~104 bytes
    sock = socket.socket(socket.AF_UNIX)
    sock.bind("sock")
    try:
        tree = ex.TreeStream(root, exclude=("node_modules", ".pytest_scratch/"), sentinel="ab" * 8)
        assert not tree.complete
        members, data = _members(tree)
    finally:
        sock.close()
    assert tree.complete
    assert [m.name for m in members] == [
        ".",
        "fifo",
        "hard.go",
        "link",
        "pkg",
        "pkg/a.go",
        "pkg/node_modules",
        "pkg/sub",
        "pkg/sub/b.go",
        "run.sh",
        ".crb-tree-" + "ab" * 8,
    ]
    by = {m.name: m for m in members}
    assert by["."].isdir() and by["pkg"].isdir() and by["pkg/node_modules"].isdir()
    assert by["link"].issym() and by["link"].linkname == "/etc/passwd"
    assert by["hard.go"].isreg() and by["pkg/a.go"].islnk()
    assert by["pkg/a.go"].linkname == "hard.go"
    assert by["fifo"].isfifo()
    assert by["run.sh"].mode & 0o777 == 0o755
    assert data["pkg/sub/b.go"] == big and data["hard.go"] == b"package pkg\n"
    mark = members[-1]
    assert mark.isreg() and mark.size == 0
    for m in members:
        assert (m.uid, m.gid, m.uname, m.gname) == (0, 0, "", "")
        assert m.mtime == int(m.mtime)


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads a mode-000 path")
def test_tree_stream_fails_on_a_path_it_cannot_read_and_names_it_relative_to_the_root(
    tmp_path: Path,
) -> None:
    """A path the host cannot read is an error naming it relative to the tree — never left
    out, never the host path — whether a file it cannot open or a directory it cannot
    list; the sentinel is never written after it."""
    root = tmp_path / "wt"
    (root / "d").mkdir(parents=True)
    (root / "d" / "locked.txt").write_text("secret")
    (root / "d" / "locked.txt").chmod(0)
    (root / "e").mkdir()
    try:
        tree = ex.TreeStream(root, sentinel="cd" * 8)
        with pytest.raises(OSError, match=r"could not read d/locked\.txt") as e:
            tree.write(io.BytesIO())
        assert str(tmp_path) not in str(e.value) and not tree.complete
        (root / "d" / "locked.txt").chmod(0o644)
        (root / "e").chmod(0)
        tree = ex.TreeStream(root, sentinel="cd" * 8)
        with pytest.raises(OSError, match=r"could not read e:") as e:
            tree.write(io.BytesIO())
        assert str(tmp_path) not in str(e.value) and not tree.complete
    finally:
        (root / "e").chmod(0o755)
        (root / "d" / "locked.txt").chmod(0o644)


def test_tree_stream_fails_on_a_directory_it_opened_but_could_not_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A directory that opened but could not be listed (an I/O error, say) fails the copy
    naming it — it is never streamed as an empty directory."""
    root = tmp_path / "wt"
    (root / "d").mkdir(parents=True)
    (root / "d" / "x.txt").write_text("x")
    d_ino = (root / "d").stat().st_ino
    real_scandir = os.scandir

    def cannot_list(path: Any) -> Any:
        if isinstance(path, int) and os.fstat(path).st_ino == d_ino:
            raise OSError(errno.EIO, "Input/output error")
        return real_scandir(path)

    monkeypatch.setattr(ex.os, "scandir", cannot_list)
    tree = ex.TreeStream(root, sentinel="78" * 8)
    with pytest.raises(OSError, match=r"could not read d: Input/output error"):
        tree.write(io.BytesIO())
    assert not tree.complete


@pytest.mark.parametrize("swap", ["link", "directory"])
def test_tree_stream_never_reads_outside_the_root_through_a_swapped_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, swap: str
) -> None:
    """A directory swapped, after it was looked at and before it is opened, for a link to a
    directory outside the tree is refused at the open (never followed); one swapped for
    another directory is refused as not the one looked at. Either way the copy fails
    closed naming the path, and nothing from outside the root reaches the stream."""
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("from outside the tree")
    root = tmp_path / "wt"
    (root / "d").mkdir(parents=True)
    (root / "d" / "inside.txt").write_text("inside")
    real_open = os.open

    def swapped_first(path: Any, flags: int, mode: int = 0o777, *, dir_fd: Any = None) -> int:
        if path == "d" and dir_fd is not None:
            (root / "d").rename(tmp_path / "d.before")
            if swap == "link":
                (root / "d").symlink_to(outside)
            else:
                outside.rename(root / "d")
        return real_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(ex.os, "open", swapped_first)
    out = io.BytesIO()
    tree = ex.TreeStream(root, sentinel="12" * 8)
    with pytest.raises(OSError, match=r"could not read d:") as e:
        tree.write(out)
    # a link is refused by the open itself (Linux says ENOTDIR, macOS ELOOP); a directory
    # by its identity
    assert e.value.errno in ((errno.ELOOP, errno.ENOTDIR) if swap == "link" else (0,))
    assert b"from outside the tree" not in out.getvalue() and not tree.complete


def test_tree_stream_builds_each_header_from_the_one_look_it_read_the_entry_by(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An entry swapped for a regular file after it was looked at is archived as what was
    looked at — never a regular header with no body, which tears the stream (Python 3.12's
    ``addfile`` writes one) — so every later member, the sentinel last, still reads."""
    root = tmp_path / "wt"
    root.mkdir()
    os.mkfifo(root / "p")
    (root / "z.txt").write_text("after")
    swapped: list[bool] = []

    def looked_then_swapped(real: Any) -> Any:
        def look(path: Any, *a: Any, **k: Any) -> Any:
            st = real(path, *a, **k)
            named = isinstance(path, (str, os.PathLike)) and os.path.basename(os.fspath(path))
            if not swapped and named == "p":
                swapped.append(True)
                (root / "p").unlink()
                (root / "p").write_bytes(b"x" * 5000)
            return st

        return look

    monkeypatch.setattr(ex.os, "stat", looked_then_swapped(os.stat))
    monkeypatch.setattr(ex.os, "lstat", looked_then_swapped(os.lstat))
    tree = ex.TreeStream(root, sentinel="34" * 8)
    members, data = _members(tree)
    assert swapped and [m.name for m in members] == [".", "p", "z.txt", ".crb-tree-" + "34" * 8]
    assert members[1].isfifo() and members[1].size == 0
    assert data["z.txt"] == b"after" and tree.complete


def test_tree_stream_closes_a_file_swapped_for_a_directory_before_it_was_opened(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A file swapped for a directory after it was looked at opens as that directory: the
    copy fails closed naming it, and the descriptor that open returned is closed, never
    leaked — a worker streams tree after tree and must not run out of them."""
    root = tmp_path / "wt"
    root.mkdir()
    (root / "f.txt").write_text("a file")
    swapped: list[bool] = []
    real_stat = os.stat

    def looked_then_swapped(path: Any, *a: Any, **k: Any) -> Any:
        st = real_stat(path, *a, **k)
        if not swapped and path == "f.txt":
            swapped.append(True)
            (root / "f.txt").unlink()
            (root / "f.txt").mkdir()
        return st

    def open_fds() -> int:
        return len(os.listdir("/dev/fd"))

    monkeypatch.setattr(ex.os, "stat", looked_then_swapped)
    before = open_fds()
    tree = ex.TreeStream(root, sentinel="78" * 8)
    with pytest.raises(OSError, match=r"could not read f\.txt:"):
        tree.write(io.BytesIO())
    assert swapped and open_fds() == before and not tree.complete


def test_tree_stream_holds_no_member_per_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A stream is never read back, so it keeps nothing per entry: the archive's member list
    is empty at every member it writes, however wide the tree."""
    root = tmp_path / "wt"
    root.mkdir()
    for i in range(200):
        (root / f"f{i:03}.txt").write_text(str(i))
    held: list[int] = []
    real_addfile = tarfile.TarFile.addfile

    def counted(self: tarfile.TarFile, *a: Any, **k: Any) -> None:
        held.append(len(self.members))
        real_addfile(self, *a, **k)

    monkeypatch.setattr(tarfile.TarFile, "addfile", counted)
    members, _ = _members(ex.TreeStream(root, sentinel="56" * 8))
    assert len(members) == 202 and len(held) == 202 and max(held) == 0


@pytest.mark.parametrize("bad", ["", "abc", "ABCDEF0123456789", "../../etc/x", "a" * 65])
def test_tree_stream_refuses_a_sentinel_that_is_not_a_hex_token(tmp_path: Path, bad: str) -> None:
    """The sentinel lands in a shell script and a file name: hex only, 8 to 64 characters."""
    with pytest.raises(ValueError, match="sentinel"):
        ex.TreeStream(tmp_path, sentinel=bad)


def test_the_feeder_records_a_stream_cut_before_its_sentinel_never_one_after(
    tmp_path: Path,
) -> None:
    """A reader that went away before the sentinel is a problem the result must carry —
    for a tree small enough that the archive still held its sentinel when the pipe broke,
    too; a whole stream read to its end is none; a pipe that broke once the sentinel was
    written (the container stopped reading the end-of-archive padding) is the container's
    to judge by the sentinel, so it is no problem here either."""
    root = tmp_path / "wt"
    root.mkdir()
    (root / "big.bin").write_bytes(os.urandom(1 << 20))  # more than any pipe buffer
    r, w = os.pipe()
    os.close(r)  # nobody reads
    problems: list[str] = []
    ex._feed_tree(ex.TreeStream(root, sentinel="ef" * 8), w, problems)
    assert problems == ["the container stopped reading the tree before it ended"]

    tiny = tmp_path / "tiny"
    tiny.mkdir()
    (tiny / "a.txt").write_text("small")  # the whole stream fits in one record on the host
    r, w = os.pipe()
    os.close(r)
    problems = []
    small = ex.TreeStream(tiny, sentinel="ef" * 8)
    ex._feed_tree(small, w, problems)
    assert problems == ["the container stopped reading the tree before it ended"]
    assert not small.complete

    r, w = os.pipe()
    got = bytearray()

    def drain() -> None:
        with os.fdopen(r, "rb") as f:
            got.extend(f.read())

    reader = threading.Thread(target=drain)
    reader.start()
    problems = []
    tree = ex.TreeStream(root, sentinel="ef" * 8)
    ex._feed_tree(tree, w, problems)
    reader.join(10)
    assert problems == [] and tree.complete
    with tarfile.open(fileobj=io.BytesIO(bytes(got)), mode="r:") as tf:
        assert tf.getnames()[-1] == ".crb-tree-" + "ef" * 8

    class CutAfterTheSentinel(ex.TreeStream):
        def write(self, out: Any) -> None:
            super().write(out)
            raise BrokenPipeError(32, "Broken pipe")

    r, w = os.pipe()
    reader = threading.Thread(target=lambda: os.fdopen(r, "rb").read())
    reader.start()
    problems = []
    ex._feed_tree(CutAfterTheSentinel(root, sentinel="ef" * 8), w, problems)
    reader.join(10)
    assert problems == []


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads a mode-000 path")
def test_a_tree_the_host_could_not_stream_is_tree_copy_failed_whatever_the_client_exits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The feeder could not read a path, so the container never got the sentinel and never
    ran the command: the result is ``tree_copy_failed`` — rc 97 with the marker, the path
    named relative to the tree and no host path — even when the client itself exited 0."""
    docker = tmp_path / "docker"
    docker.write_text("#!/bin/sh\ncat > /dev/null\necho ran\n")  # reads the stream, exits 0
    docker.chmod(0o755)
    root = tmp_path / "wt"
    root.mkdir()
    (root / "a.txt").write_text("fine")
    (root / "z.txt").write_text("secret")
    monkeypatch.setattr(ex, "grant_sandbox_read", lambda *a, **k: None)  # keep the mode 000
    (root / "z.txt").chmod(0)
    try:
        e = DockerExecutor(
            DockerSettings(image="img", docker_binary=str(docker)), verify_daemon=False
        )
        r = e.run(Command(("go", "test"), root, timeout=30))
    finally:
        (root / "z.txt").chmod(0o644)
    assert r.returncode == ex.TREE_COPY_RC and r.env_error == "tree_copy_failed" and not r.ok
    assert "crb: the tree copy could not read z.txt" in r.stderr
    assert ex.TREE_COPY_MARKER in r.stderr and str(tmp_path) not in r.stderr
    assert r.stdout == "ran\n" and not (r.cancelled or r.timed_out)


def test_a_feeder_the_host_cannot_start_is_tree_copy_failed_and_never_hangs_the_container(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The host could not start the feeder thread (it is out of threads): its end of the
    pipe is closed, so the container reads an empty stream and exits instead of waiting on
    its stdin for ever, and the result is ``tree_copy_failed`` saying why."""
    docker = tmp_path / "docker"
    docker.write_text("#!/bin/sh\ncat > /dev/null\necho ran\n")  # reads the stream to EOF
    docker.chmod(0o755)
    root = tmp_path / "wt"
    root.mkdir()
    (root / "a.txt").write_text("fine")
    real_start = threading.Thread.start

    def no_feeder(self: threading.Thread) -> None:
        if self.name.startswith("crb-tree-"):
            raise RuntimeError("can't start new thread")
        real_start(self)

    monkeypatch.setattr(threading.Thread, "start", no_feeder)
    e = DockerExecutor(DockerSettings(image="img", docker_binary=str(docker)), verify_daemon=False)
    r = e.run(Command(("go", "test"), root, timeout=10))
    assert r.returncode == ex.TREE_COPY_RC and r.env_error == "tree_copy_failed" and not r.ok
    assert "crb: the tree could not be written (RuntimeError)" in r.stderr
    assert r.stdout == "ran\n" and not (r.cancelled or r.timed_out)


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


@pytest.mark.parametrize("kind", ["local", "LOCAL"])
def test_make_executor_local(kind: str) -> None:
    # "", "none" and "host" once meant local too: an empty setting ran tests on the host
    # (P-120) — tests/test_execution_edges.py pins that they are refused
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


def test_local_executor_cancel_kills_the_running_command(tmp_path: Path) -> None:
    """A cancel token that flips to True kills the child (process group) promptly:
    rc=130, cancelled=True, well before the wall-clock timeout."""
    import threading
    import time

    from crb.core.execution import Command, LocalExecutor

    flag = threading.Event()
    threading.Timer(1.5, flag.set).start()
    ex = LocalExecutor(cancel=flag.is_set)
    t0 = time.monotonic()
    r = ex.run(Command((sys.executable, "-c", "import time; time.sleep(60)"), tmp_path, timeout=60))
    assert r.cancelled and r.returncode == 130 and not r.timed_out and not r.ok
    assert time.monotonic() - t0 < 10


# ---------------------------------------------------------------------------
# DockerStream — an enforced kill is CONFIRMED before the stream ends
# ---------------------------------------------------------------------------


def _fake_docker_stream(dir_: Path, *, inspect: str) -> tuple[str, Path]:
    """A ``docker`` stand-in for :class:`DockerStream`: ``run`` prints one line and
    sleeps as a container would, ``kill`` and ``inspect`` are logged to ``calls``.
    ``inspect`` scripts the daemon's answers — ``true:N`` says Running=true N times
    then false, ``always-true`` never stops, ``no-such`` answers as a removed
    (``--rm``) container does: exit 1 + "No such container"."""
    dir_.mkdir(parents=True, exist_ok=True)
    calls = dir_ / "calls"
    calls.write_text("")
    if inspect == "always-true":
        answer = "echo true"
    elif inspect == "no-such":
        answer = 'echo "Error: No such container: $4" >&2; exit 1'
    else:
        n = int(inspect.split(":", 1)[1])
        answer = (
            f'if [ "$(grep -c inspect "{calls}")" -le {n} ]; then echo true; else echo false; fi'
        )
    script = dir_ / "docker"
    script.write_text(
        "#!/bin/sh\n"
        'case "$1" in\n'
        "  run) echo hello; sleep 60 ;;\n"
        f'  kill) echo kill >> "{calls}" ;;\n'
        f'  inspect) echo inspect >> "{calls}"; {answer} ;;\n'
        "esac\n"
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return str(script), calls


def _stream(docker: str, *, timeout_s: int = 60, cancel: Any = None) -> ex.DockerStream:
    return ex.DockerStream(
        [docker, "run", "--rm", "--name", "crb-test"],
        docker=docker,
        name="crb-test",
        env={"PATH": os.environ.get("PATH", "")},
        timeout_s=timeout_s,
        cancel=cancel,
    )


def test_docker_stream_confirms_the_kill_by_polling_inspect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cancel → ``docker kill`` → ``docker inspect`` is polled until Running=false, and
    ``lines()`` does not return before that: the container is down by construction."""
    monkeypatch.setattr(ex.DockerStream, "KILL_CONFIRM_STEP_S", 0.02)
    docker, calls = _fake_docker_stream(tmp_path, inspect="true:2")
    flag = {"cancel": False}
    monkeypatch.setattr(ex, "_CANCEL_POLL_S", 0.05)
    h = _stream(docker, cancel=lambda: flag["cancel"])
    it = h.lines()
    assert next(it) == "hello"
    flag["cancel"] = True
    list(it)
    assert h.cancelled and not h.timed_out
    assert h.kill_confirmed is True  # recorded before lines() returned
    log = calls.read_text().split()
    assert log.count("kill") >= 1
    assert log.count("inspect") == 3  # true, true, false — the loop kept asking


def test_docker_stream_kill_confirmation_is_bounded_and_warns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A daemon that never reports the container stopped cannot hang the reader: the
    poll gives up at ``KILL_CONFIRM_S``, ``kill_confirmed`` is False, and a warning names
    the container. The bound (1 s) leaves room for two inspect spawns on a loaded machine,
    and the upper limit only has to tell "bounded" from "never ends" (P-014)."""
    monkeypatch.setattr(ex.DockerStream, "KILL_CONFIRM_S", 1.0)
    monkeypatch.setattr(ex.DockerStream, "KILL_CONFIRM_STEP_S", 0.05)
    docker, calls = _fake_docker_stream(tmp_path, inspect="always-true")
    h = _stream(docker, timeout_s=1)
    t0 = time.monotonic()
    with caplog.at_level("WARNING", logger="crb.core.execution"):
        out = list(h.lines())
    elapsed = time.monotonic() - t0
    assert out == ["hello"]
    assert h.timed_out and not h.cancelled
    assert h.kill_confirmed is False
    assert 2.0 <= elapsed < 10  # the wall clock, then the whole bound — and no longer
    assert calls.read_text().split().count("inspect") >= 2  # the loop kept asking
    assert any(
        "crb-test" in r.message and "not confirmed stopped" in r.message for r in caplog.records
    )


def test_docker_stream_treats_a_removed_container_as_stopped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``--rm`` reaps asynchronously: ``inspect`` answering "No such container" is
    confirmation, not an error to retry."""
    docker, calls = _fake_docker_stream(tmp_path, inspect="no-such")
    h = _stream(docker, timeout_s=1)
    list(h.lines())
    assert h.timed_out and h.kill_confirmed is True
    assert calls.read_text().split().count("inspect") == 1


def test_docker_stream_natural_exit_asks_the_daemon_nothing(tmp_path: Path) -> None:
    """No kill was issued → nothing to confirm: ``kill_confirmed`` stays None and neither
    ``docker kill`` nor ``docker inspect`` runs."""
    docker, calls = _fake_docker_stream(tmp_path, inspect="always-true")
    script = Path(docker)
    script.write_text(script.read_text().replace("echo hello; sleep 60", "echo hello"))
    h = _stream(docker)
    assert list(h.lines()) == ["hello"]
    assert not h.timed_out and not h.cancelled and h.kill_confirmed is None
    assert calls.read_text() == ""


def test_wait_container_stopped_reads_the_daemon_honestly(tmp_path: Path) -> None:
    """The one-question helper: exit 0 + "false" is stopped, exit 0 + "true" is running,
    a missing container is gone, an unaskable daemon is unknown (and keeps polling to
    the bound rather than claiming a stop)."""
    docker, _ = _fake_docker_stream(tmp_path / "a", inspect="true:0")
    assert ex.container_stopped(docker, "x") is True
    docker, _ = _fake_docker_stream(tmp_path / "b", inspect="always-true")
    assert ex.container_stopped(docker, "x") is False
    docker, _ = _fake_docker_stream(tmp_path / "c", inspect="no-such")
    assert ex.container_stopped(docker, "x") is True
    assert ex.container_stopped(str(tmp_path / "missing" / "docker"), "x") is None
    assert (
        ex.wait_container_stopped(
            str(tmp_path / "missing" / "docker"), "x", timeout_s=0.1, step_s=0.02
        )
        is False
    )


def _scripted_inspect(dir_: Path, body: str) -> str:
    """A ``docker`` whose ``inspect`` runs ``body`` (a shell fragment) — for the parse and
    budget cases; ``kill`` is a no-op."""
    dir_.mkdir(parents=True, exist_ok=True)
    script = dir_ / "docker"
    script.write_text('#!/bin/sh\ncase "$1" in\n  kill) : ;;\n  inspect) ' + body + " ;;\nesac\n")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return str(script)


@pytest.mark.parametrize(
    ("output", "expected"),
    [
        ("true", False),
        ("false", True),
        ("", None),  # exit 0 with nothing said is NOT a stop
        ("True", None),  # exact strings only — no case folding
        ("FALSE", None),
        ("false extra", None),
        ("<no value>", None),  # the template did not resolve
        ("null", None),
    ],
)
def test_container_stopped_accepts_only_the_exact_true_and_false(
    tmp_path: Path, output: str, expected: bool | None
) -> None:
    """Exit 0 + anything but the exact ``true`` / ``false`` is UNKNOWN — the poll keeps
    asking to the bound rather than reading a malformed answer as a confirmed stop."""
    docker = _scripted_inspect(tmp_path, f"printf '%s\\n' '{output}'")
    assert ex.container_stopped(docker, "x") is expected


def test_container_stopped_non_zero_without_no_such_is_unknown(tmp_path: Path) -> None:
    docker = _scripted_inspect(tmp_path, 'echo "Cannot connect to the Docker daemon" >&2; exit 1')
    assert ex.container_stopped(docker, "x") is None


def test_wait_container_stopped_never_exceeds_its_budget_across_inspect_calls(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Each ``inspect`` gets only the REMAINING budget: a daemon that answers slowly (here:
    never — every call sleeps past the bound) cannot stretch the wait to ``timeout_s`` plus a
    whole inspect timeout, and an answer that arrives after the bound is not waited for."""
    docker = _scripted_inspect(tmp_path, "sleep 10; echo false")
    t0 = time.monotonic()
    with caplog.at_level("WARNING", logger="crb.core.execution"):
        assert ex.wait_container_stopped(docker, "slow", timeout_s=0.5, step_s=0.02) is False
    elapsed = time.monotonic() - t0
    # the bound, not the bound + 10 s; the gap tolerates a loaded machine (P-014)
    assert 0.5 <= elapsed < 5.0, elapsed
    assert any("slow" in r.message and "not confirmed" in r.message for r in caplog.records)


def test_wait_container_stopped_caps_each_inspect_to_the_remaining_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The budget handed to every ``inspect`` call is the time left, never more."""
    budgets: list[float] = []

    def fake_stopped(docker: str, name: str, *, timeout_s: float = 10.0) -> bool | None:
        budgets.append(timeout_s)
        time.sleep(0.03)
        return None

    monkeypatch.setattr(ex, "container_stopped", fake_stopped)
    assert ex.wait_container_stopped("docker", "x", timeout_s=0.2, step_s=0.01) is False
    assert budgets and all(0 < b <= 0.2 for b in budgets)
    assert budgets == sorted(budgets, reverse=True)  # strictly less time each round


# ---------------------------------------------------------------------------
# DockerExecutor.run under a cancel token — the non-stream kill is confirmed the same way
# ---------------------------------------------------------------------------


def _cancellable(docker: str, *, cancel: Any, on_kill: Any = None) -> DockerExecutor:
    return DockerExecutor(
        DockerSettings(image="img", docker_binary=docker),
        verify_daemon=False,
        cancel=cancel,
        on_kill_unconfirmed=on_kill,
    )


def test_docker_run_cancel_confirms_the_kill_and_names_the_container(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cancel mid-command → ``docker kill`` → ``docker inspect`` polled until Running=false:
    rc 130, ``cancelled``, ``kill_confirmed`` True, the container named on the result, no
    report (nothing was unconfirmed) — and the client is gone, well inside the wall clock."""
    monkeypatch.setattr(ex, "_CANCEL_POLL_S", 0.05)
    monkeypatch.setattr(DockerExecutor, "KILL_CONFIRM_STEP_S", 0.02)
    docker, calls = _fake_docker_stream(tmp_path, inspect="true:1")
    flag = {"cancel": False}
    reports: list[ex.UnconfirmedKill] = []
    e = _cancellable(docker, cancel=lambda: flag["cancel"], on_kill=reports.append)
    threading.Timer(0.3, lambda: flag.__setitem__("cancel", True)).start()
    t0 = time.monotonic()
    r = e.run(Command(("sleep", "60"), tmp_path, timeout=60))
    assert time.monotonic() - t0 < 10
    assert r.cancelled and r.returncode == 130 and not r.timed_out and not r.ok
    assert r.kill_confirmed is True and r.container.startswith("crb-")
    assert "hello" in r.stdout  # what the container wrote before the kill is kept
    log = calls.read_text().split()
    assert log.count("kill") == 1 and log.count("inspect") == 2  # true, then false
    assert e.unconfirmed_kills == [] and reports == []


def test_docker_run_cancel_unconfirmed_kill_is_reported_and_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A daemon that never reports the container stopped: the attempt ends at
    ``KILL_CONFIRM_S``, ``kill_confirmed`` is False on the result, the kill is on
    ``unconfirmed_kills`` and handed to ``on_kill_unconfirmed`` BEFORE ``run`` returns
    (the worker records and reaps it), a warning names the container — and a callback
    that raises is logged, never the command's result. The bound (1 s) leaves room for two
    inspect spawns on a loaded machine (it failed at 0.3 s under load: P-014)."""
    monkeypatch.setattr(ex, "_CANCEL_POLL_S", 0.05)
    monkeypatch.setattr(DockerExecutor, "KILL_CONFIRM_S", 1.0)
    monkeypatch.setattr(DockerExecutor, "KILL_CONFIRM_STEP_S", 0.05)
    docker, calls = _fake_docker_stream(tmp_path, inspect="always-true")
    flag = {"cancel": False}
    reports: list[ex.UnconfirmedKill] = []

    def report(kill: ex.UnconfirmedKill) -> None:
        reports.append(kill)
        raise RuntimeError("the worker's sink is down")

    e = _cancellable(docker, cancel=lambda: flag["cancel"], on_kill=report)
    threading.Timer(0.2, lambda: flag.__setitem__("cancel", True)).start()
    t0 = time.monotonic()
    with caplog.at_level("WARNING", logger="crb.core.execution"):
        r = e.run(Command(("sleep", "60"), tmp_path, timeout=60))
    elapsed = time.monotonic() - t0
    assert 1.2 <= elapsed < 10  # the cancel, then the whole bound — and no longer
    assert r.cancelled and r.returncode == 130 and r.kill_confirmed is False
    assert r.container.startswith("crb-")
    assert reports == [ex.UnconfirmedKill(container=r.container, bound_s=1.0)]
    assert e.unconfirmed_kills == reports
    assert calls.read_text().split().count("inspect") >= 2  # the loop kept asking
    messages = [rec.message for rec in caplog.records]
    assert any(r.container in m and "not confirmed stopped" in m for m in messages)
    assert any("on_kill_unconfirmed failed" in m for m in messages)


def test_docker_run_wall_clock_kill_treats_a_removed_container_as_confirmed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The wall clock ends in the same kill: ``--rm`` reaps asynchronously, so an
    ``inspect`` answering "No such container" is confirmation after one question — rc 124,
    ``timed_out``, ``kill_confirmed`` True, nothing reported."""
    monkeypatch.setattr(ex, "_CANCEL_POLL_S", 0.05)
    docker, calls = _fake_docker_stream(tmp_path, inspect="no-such")
    reports: list[ex.UnconfirmedKill] = []
    e = _cancellable(docker, cancel=lambda: False, on_kill=reports.append)
    r = e.run(Command(("sleep", "60"), tmp_path, timeout=1))
    assert r.timed_out and not r.cancelled and r.returncode == 124
    assert r.kill_confirmed is True and r.container.startswith("crb-")
    log = calls.read_text().split()
    assert log.count("kill") == 1 and log.count("inspect") == 1
    assert reports == [] and e.unconfirmed_kills == []


def test_docker_run_without_a_cancel_token_still_kills_the_container_on_the_wall_clock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The CLI's executors carry no cancel token (``build_executor`` passes none). The
    wall clock must still end in a confirmed ``docker kill`` of the CONTAINER — the plain
    ``subprocess.run(timeout=…)`` path would kill only the ``docker run`` client and leave
    the container running. So a real daemon always takes the polled path."""
    monkeypatch.setattr(ex, "_CANCEL_POLL_S", 0.05)
    docker, calls = _fake_docker_stream(tmp_path, inspect="no-such")
    e = _cancellable(docker, cancel=None)
    r = e.run(Command(("sleep", "60"), tmp_path, timeout=1))
    assert r.timed_out and not r.cancelled and r.returncode == 124
    assert r.kill_confirmed is True and r.container.startswith("crb-")
    log = calls.read_text().split()
    assert log.count("kill") == 1 and log.count("inspect") == 1


def test_docker_run_natural_exit_confirms_nothing(tmp_path: Path) -> None:
    """No kill was issued → ``kill_confirmed`` stays None (the container is still named)
    and the daemon is asked nothing."""
    docker, calls = _fake_docker_stream(tmp_path, inspect="always-true")
    script = Path(docker)
    script.write_text(script.read_text().replace("echo hello; sleep 60", "echo hello"))
    e = _cancellable(docker, cancel=lambda: False)
    r = e.run(Command(("true",), tmp_path, timeout=10))
    assert r.ok and r.stdout.strip() == "hello"
    assert r.kill_confirmed is None and r.container.startswith("crb-")
    assert calls.read_text() == ""


def test_make_executor_hands_the_report_to_the_docker_executor_only(tmp_path: Path) -> None:
    reports: list[ex.UnconfirmedKill] = []
    local = make_executor("local", cancel=lambda: False, on_kill_unconfirmed=reports.append)
    assert isinstance(local, LocalExecutor)
    good = DockerSettings(image="img", docker_binary=_fake_docker(tmp_path / "good", 0))
    d = make_executor(
        "docker", docker=good, cancel=lambda: False, on_kill_unconfirmed=reports.append
    )
    assert isinstance(d, DockerExecutor)
    kill = ex.UnconfirmedKill(container="crb-x", bound_s=1.0)
    d._report_unconfirmed(kill)
    assert reports == [kill] and d.unconfirmed_kills == [kill]
