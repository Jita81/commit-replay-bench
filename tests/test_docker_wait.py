"""The bounded docker wait, and the ratchet that makes it the only way a test reads docker.

Navigation
----------
What it is:   The unit tests of tests/docker_wait.py (no daemon: ``subprocess.run`` is
              doubled) and the ratchet over every test module.
What it does: Pins #60's semantics — a failed query fails the check, every query is bounded
              by the time left, a slow last query after the name was listed reads as still
              listed, a daemon that never answers fails the check — and refuses any
              ``docker ps`` / ``docker container ls`` / ``docker network ls`` call in a test
              module other than the helper, proving on planted source that it catches each
              shape (docs/PREVENTION.md P-052).
How:          ``monkeypatch.setattr(subprocess, "run", …)`` for the helper; an ``ast`` walk
              for the ratchet: a call whose argv is ``[<docker>, "ps", …]``,
              ``[<docker>, "network", "ls", …]`` or ``_docker("ps", …)``.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0005-fail-closed-docker-sandbox.md
Works with:   tests/docker_wait.py (under test), tests/test_sandbox_docker.py (the real leak
              probe against a daemon), docs/PREVENTION.md (P-052, the row this ratchet
              closes)
Tested by:    tests/test_docker_wait.py
Touch when:   a test needs another docker listing: add it to tests/docker_wait.py and teach
              the ratchet its argv shape.
"""

from __future__ import annotations

import ast
import subprocess
import time
from pathlib import Path

import pytest

import docker_wait

ROOT = Path(__file__).resolve().parent.parent
TESTS = ROOT / "tests"
HELPER = "tests/docker_wait.py"
#: ``docker <these>`` reads what the daemon lists.
_LISTINGS: tuple[tuple[str, ...], ...] = (
    ("ps",),
    ("container", "ls"),
    ("container", "ps"),
    ("network", "ls"),
)


def test_the_check_fails_when_docker_ps_itself_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """A ``docker ps`` that fails prints nothing — that is not proof the container went."""

    def failing(argv: list[str], **kw: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(argv, 1, "", "Cannot connect to the Docker daemon")

    monkeypatch.setattr(subprocess, "run", failing)
    with pytest.raises(pytest.fail.Exception, match="docker ps -aq failed"):
        docker_wait.gone("crb-any", within_s=1.0)


def test_the_check_never_waits_past_its_bound(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every query is bounded by the time left, so a stalled daemon cannot stretch the
    check past ``within_s``; a name still listed at the deadline reads as leaked."""
    timeouts: list[float] = []

    def still_listed(argv: list[str], **kw: float) -> subprocess.CompletedProcess[str]:
        timeouts.append(kw["timeout"])
        return subprocess.CompletedProcess(argv, 0, "abc123\n", "")

    monkeypatch.setattr(subprocess, "run", still_listed)
    started = time.monotonic()
    assert docker_wait.gone("crb-any", within_s=0.6) is False
    assert time.monotonic() - started < 10
    assert timeouts and all(0 < t <= 0.6 for t in timeouts), timeouts


def test_a_slow_last_query_reads_as_still_listed(monkeypatch: pytest.MonkeyPatch) -> None:
    """The daemon already answered that the name was there, so a last query that times out
    reads "still listed at the deadline" (False), never a failure blaming the daemon."""
    calls = {"n": 0}

    def listed_then_slow(argv: list[str], **kw: float) -> subprocess.CompletedProcess[str]:
        calls["n"] += 1
        if calls["n"] == 1:
            return subprocess.CompletedProcess(argv, 0, "abc123\n", "")
        raise subprocess.TimeoutExpired(argv, kw["timeout"])

    monkeypatch.setattr(subprocess, "run", listed_then_slow)
    assert docker_wait.gone("crb-any", within_s=1.0) is False
    assert calls["n"] == 2


def test_a_daemon_that_never_answers_fails_the_check(monkeypatch: pytest.MonkeyPatch) -> None:
    def silent(argv: list[str], **kw: float) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(argv, kw["timeout"])

    monkeypatch.setattr(subprocess, "run", silent)
    with pytest.raises(pytest.fail.Exception, match="did not answer"):
        docker_wait.network_gone("crb-any", within_s=1.0)


def test_a_name_that_leaves_the_listing_reads_as_gone(monkeypatch: pytest.MonkeyPatch) -> None:
    """Listed on the first query, gone on the second: the removal the daemon finished after
    the kill returned — the race the wait exists for. Each helper asks its own listing."""
    seen: list[list[str]] = []

    def removed_later(argv: list[str], **kw: float) -> subprocess.CompletedProcess[str]:
        seen.append(argv[1:-2])
        out = "abc123\n" if len(seen) % 2 == 1 else ""
        return subprocess.CompletedProcess(argv, 0, out, "")

    monkeypatch.setattr(subprocess, "run", removed_later)
    assert docker_wait.gone("crb-a", within_s=5.0) is True
    assert docker_wait.gone("crb-b", within_s=5.0, running_only=True) is True
    assert docker_wait.network_gone("crb-c", within_s=5.0) is True
    assert seen == [
        ["ps", "-aq"],
        ["ps", "-aq"],
        ["ps", "-q"],
        ["ps", "-q"],
        ["network", "ls", "-q"],
        ["network", "ls", "-q"],
    ]


# ---------------------------------------------------------------------------
# The ratchet: no docker listing is read anywhere but the helper
# ---------------------------------------------------------------------------


def _strings(node: ast.AST) -> list[str | None]:
    """A call argument as argv words: a string literal is itself, anything else ``None``."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, ast.List | ast.Tuple):
        return [
            e.value if isinstance(e, ast.Constant) and isinstance(e.value, str) else None
            for e in node.elts
        ]
    return [None]


def _lists(words: list[str | None]) -> bool:
    return any(tuple(words[: len(shape)]) == shape for shape in _LISTINGS)


def _callee(node: ast.Call) -> str:
    f = node.func
    return f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else ""


def docker_listing_reads(source: str, name: str = "<source>") -> list[str]:
    """Every call in ``source`` that asks docker to list containers or networks, as
    ``name:line``: an argv list ``[<docker>, "ps", …]`` (the binary a literal ``docker`` or
    any expression) or a ``_docker("ps", …)``-style wrapper call."""
    found: set[int] = set()
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        if "docker" in _callee(node).lower() and node.args:
            words = [w for a in node.args for w in _strings(a)]
            if _lists(words):
                found.add(node.lineno)
        for arg in node.args:
            if not isinstance(arg, ast.List | ast.Tuple) or len(arg.elts) < 2:
                continue
            words = _strings(arg)
            head = arg.elts[0]
            is_docker = words[0] == "docker" or not (
                isinstance(head, ast.Constant) and isinstance(head.value, str)
            )
            if is_docker and _lists(words[1:]):
                found.add(node.lineno)
    return [f"{name}:{line}" for line in sorted(found)]


def test_no_test_reads_a_docker_listing_except_through_the_bounded_wait() -> None:
    found: list[str] = []
    for path in sorted(TESTS.rglob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        if rel in (HELPER, "tests/test_docker_wait.py"):
            continue
        found += docker_listing_reads(path.read_text(encoding="utf-8"), rel)
    assert found == [], (
        "an instant docker listing races the daemon's own --rm removal (docs/PREVENTION.md "
        f"P-052); use tests/docker_wait.py's gone() or network_gone(): {found}"
    )


def test_the_ratchet_catches_every_shape_of_a_direct_listing() -> None:
    planted = """
import shutil, subprocess
def _docker(*args):
    return subprocess.run(["docker", *args])
def test_a():
    assert _docker("ps", "-a", "-q", "--filter", "name=x").stdout.strip() == ""
def test_b():
    docker = shutil.which("docker") or "docker"
    left = subprocess.run([docker, "ps", "-a", "-q"], capture_output=True).stdout
def test_c():
    subprocess.run(["docker", "network", "ls", "-q", "--filter", "name=x"])
def test_d():
    subprocess.run((shutil.which("docker"), "container", "ls", "-aq"))
"""
    assert docker_listing_reads(planted, "planted") == [
        "planted:6",
        "planted:9",
        "planted:11",
        "planted:13",
    ]


def test_the_ratchet_leaves_other_commands_alone() -> None:
    allowed = """
import subprocess
def test_ok(docker):
    subprocess.run(["ps", "-o", "stat=", "-p", "1"])
    subprocess.run([docker, "image", "inspect", "x"])
    subprocess.run(["docker", "run", "--rm", "img", "ps"])
    if argv[0] == "ps":
        pass
"""
    assert docker_listing_reads(allowed) == []
