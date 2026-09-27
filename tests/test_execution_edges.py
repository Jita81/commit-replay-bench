"""The executor's edges (ADR-0025 item 13; P-053, P-054; G-971).

* ``make_executor("")`` returned the LOCAL executor, so an empty executor setting ran a
  repository's tests on the host instead of failing (P-053). Now ``local`` and ``docker``
  are the only kinds; ``""``, ``none`` and ``host`` raise ``ValueError`` naming the setting.
* Every docker launch path read exit 125 as ``SandboxUnavailable``, so a suite that itself
  exits 125 stopped the run as if the daemon had failed (P-054). Now 125 is a launch failure
  only when the docker CLI said so on stderr, or the run printed nothing; one table of
  docker output serves all three launch paths.

Navigation
----------
What it is:   The tests of ``make_executor``'s refusal of an empty kind and of the one rule that
              tells docker's exit 125 from a container's.
What it does: Pins the rule against docker CLI output — the three 29.6.1 lines captured on this
              host on 2026-09-27 (a missing image, an unknown flag, an invalid reference) and the
              daemon's documented shapes of docker 24 to 28 — and runs every case through the
              injected-runner path, the polled ``Popen`` path and ``DockerStream``.
How:          ``docker_launch_failed`` directly; ``DockerExecutor.run`` with a scripted runner;
              ``DockerExecutor.run`` and ``DockerStream`` against a fake ``docker`` script that
              prints the case's output and exits 125.
Layer:        tests — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0005-fail-closed-docker-sandbox.md; ADR-0025 item 13 (stream G; the draft
              stream R commits)
Works with:   src/crb/core/execution.py (under test), tests/test_execution.py (the executor's
              own suite), docs/PREVENTION.md (P-053 and P-054, the rows these tests close)
Tested by:    tests/test_execution_edges.py
Touch when:   a docker release words its launch failures differently (add the captured line).
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path
from typing import Any

import pytest

from crb.core import execution as ex
from crb.core.execution import (
    Command,
    DockerExecutor,
    DockerSettings,
    SandboxUnavailable,
    make_executor,
)

#: (stdout, stderr, is docker's own launch failure)
CASES: list[tuple[str, str, bool]] = [
    # docker 29.6.1, captured on this host on 2026-09-27
    (
        "",
        "docker: Error response from daemon: No such image: crb-g-no-such-image:never\n\n"
        "Run 'docker run --help' for more information\n",
        True,
    ),
    (
        "",
        "unknown flag: --bogus-flag\n\nUsage:  docker run [OPTIONS] IMAGE [COMMAND] [ARG...]\n\n"
        "Run 'docker run --help' for more information\n",
        True,
    ),
    (
        "",
        "docker: invalid reference format: repository name (library/Bad Ref) must be "
        "lowercase\n\nRun 'docker run --help' for more information\n",
        True,
    ),
    # the daemon's shapes in docker 24 to 28
    (
        "",
        "Unable to find image 'crb/py:test' locally\ndocker: Error response from daemon: "
        "pull access denied for crb/py, repository does not exist or may require 'docker "
        "login'.\nSee 'docker run --help'.\n",
        True,
    ),
    ("", "Error response from daemon: Conflict. The container name is already in use.\n", True),
    ("", "unknown shorthand flag: 'z' in -z\nSee 'docker run --help'.\n", True),
    ("", "", True),  # nothing printed at all: the container never ran
    # a suite that exits 125 itself: the container ran and said so
    ("collected 3 items\ntests/test_x.py ..F\n", "", False),
    ("", "bisect: skipping this commit (exit 125)\n", False),
    ("ok\n", "warning: docker: is a word a test may print mid-line\n", False),
]


@pytest.mark.parametrize(("stdout", "stderr", "launch"), CASES)
def test_the_rule_tells_dockers_125_from_the_containers(
    stdout: str, stderr: str, launch: bool
) -> None:
    assert ex.docker_launch_failed(stdout, stderr) is launch


def _settings(binary: str) -> DockerSettings:
    return DockerSettings(image="crb/py:test", docker_binary=binary)


def _fake_docker(dir_: Path, stdout: str, stderr: str) -> str:
    """A ``docker`` whose ``run`` prints the case's output and exits 125."""
    dir_.mkdir(parents=True, exist_ok=True)
    (dir_ / "out").write_text(stdout, encoding="utf-8")
    (dir_ / "err").write_text(stderr, encoding="utf-8")
    script = dir_ / "docker"
    script.write_text(
        "#!/bin/sh\n"
        'case "$1" in\n'
        f'  run) cat "{dir_ / "out"}"; cat "{dir_ / "err"}" >&2; exit 125 ;;\n'
        "  *) echo 27.0 ;;\n"
        "esac\n"
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return str(script)


def _injected(tmp: Path, stdout: str, stderr: str) -> Any:
    def runner(argv: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:
        if argv[1] == "info":
            return subprocess.CompletedProcess(argv, 0, "27.0", "")
        return subprocess.CompletedProcess(argv, 125, stdout, stderr)

    d = DockerExecutor(_settings("/fake/docker"), runner=runner)
    return d.run(Command(("pytest",), tmp, timeout=30))


def _polled(tmp: Path, stdout: str, stderr: str) -> Any:
    d = DockerExecutor(_settings(_fake_docker(tmp / "bin", stdout, stderr)))
    return d.run(Command(("pytest",), tmp, timeout=30))


def _stream(tmp: Path, stdout: str, stderr: str) -> Any:
    docker = _fake_docker(tmp / "bin", stdout, stderr)
    s = ex.DockerStream(
        [docker, "run", "--rm", "--name", "crb-edge"],
        docker=docker,
        name="crb-edge",
        env={"PATH": os.environ.get("PATH", "")},
        timeout_s=30,
    )
    return list(s.lines())


@pytest.mark.parametrize(
    "path", [_injected, _polled, _stream], ids=["injected", "polled", "stream"]
)
@pytest.mark.parametrize(("stdout", "stderr", "launch"), CASES)
def test_every_launch_path_reads_125_by_the_one_rule(
    tmp_path: Path, path: Any, stdout: str, stderr: str, launch: bool
) -> None:
    work = tmp_path / "work"
    work.mkdir()
    if launch:
        with pytest.raises(SandboxUnavailable, match="exit 125"):
            path(tmp_path if path is not _injected else work, stdout, stderr)
        return
    got = path(tmp_path if path is not _injected else work, stdout, stderr)
    if path is _stream:
        assert got == stdout.splitlines()
    else:
        assert got.returncode == 125 and not got.ok and got.stdout == stdout


@pytest.mark.parametrize("kind", ["", "   ", "none", "host", "podman"])
def test_make_executor_accepts_local_or_docker_only(kind: str) -> None:
    with pytest.raises(ValueError, match="expected 'local' or 'docker'") as exc:
        make_executor(kind)
    assert "CRB_SANDBOX__EXECUTOR" in str(exc.value)


def test_make_executor_local_is_local() -> None:
    assert isinstance(make_executor("local"), ex.LocalExecutor)
    assert isinstance(make_executor(" LOCAL "), ex.LocalExecutor)
