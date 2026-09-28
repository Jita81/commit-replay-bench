"""The warm-up policy of ``tests/conftest_langs.py``, hermetically (no daemon, no toolchain).

The helpers the docker and toolchain suites lean on turn "cannot warm up" into a *skip with
the reason* locally and a *failure* under ``CRB_TEST_STRICT_WARMUP=1``. This module pins
that policy for the one path a live daemon can break after the initial probe: ``docker image
inspect`` raising (``TimeoutExpired``, an ``OSError`` from the client) must go through the
same policy — recorded against the tag, skip or strict-fail — never surface as an
uncontrolled test error (CodeRabbit on PR #44). It also pins the network gate: a
``@pytest.mark.network`` test whose registry cannot be reached is a skip with the host and
the reason locally, and a failure under strict warm-up. And it pins the toolchain and docker
gates: a tool must answer, not merely be on PATH (a rustup proxy with no toolchain is on
PATH), a daemon must name its version (a docker CLI before 29 exits 0 without one), and a
tool the job declares in ``CRB_TEST_REQUIRE_TOOLS`` fails the test instead of skipping it
(P-741, P-742).

Navigation
----------
What it is:   Unit tests for the warm-up policy in tests/conftest_langs.py.
What it does: Monkeypatches ``subprocess.run`` to raise while the daemon probe reads
              "available", and asserts ``require_docker_image`` / ``ensure_docker_image``
              skip with the reason by default, fail under strict warm-up, and memoise the
              reason against the tag so the next caller sees the same outcome without a
              second subprocess; and that ``require_network`` (driven for every
              ``@pytest.mark.network`` test by the setup hook in tests/conftest.py) skips with
              the host and the reason when the registry is unreachable, fails under strict
              warm-up, counts any HTTP answer as reachable and probes each host once; and that
              ``require_tool`` / ``require_docker`` (driven by the same hook for every
              ``toolchain`` / ``docker`` marker) skip with the tool's own words when it does
              not work, fail when the job declares it, pass and ask once when it works, bound a
              tool that hangs, and ask each tool its own question.
How:          ``monkeypatch`` on ``subprocess.run`` / ``shutil.which`` /
              ``urllib.request.urlopen``, ``_DOCKER_REASON``, ``_IMAGES``, ``_NETWORK``,
              ``_TOOLS``, ``STRICT_WARMUP`` and ``CRB_TEST_REQUIRE_TOOLS``; small shell scripts
              standing in for a tool on a PATH of their own; ``pytest.raises(pytest.skip.Exception
              / pytest.fail.Exception)``.
Layer:        tests — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         none
Works with:   tests/conftest_langs.py (the subject), tests/conftest.py (the toolchain, docker
              and network setup hook), tests/test_sandbox_docker.py and
              tests/test_sandbox_images_docker.py (the callers whose skip/fail this shapes),
              tests/test_runners_setup.py (the network tests the hook gates)
Tested by:    tests/test_conftest_langs.py
Touch when:   never for a new repository (it tests the suite's own helpers; a new language's
              tool gets its probe in tests/conftest_langs.py and a case here); the warm-up policy
              or a tool gate changes shape (a new unavailable reason, a new strict mode), or a
              helper gains another subprocess call that could raise after the probe.
"""

from __future__ import annotations

import shutil
import subprocess
import urllib.error
import urllib.request
from collections.abc import Iterator
from email.message import Message
from pathlib import Path
from typing import Any

import pytest

try:  # tests/ is a package only if the conftest owner made it one
    from tests import conftest_langs as langs
except ImportError:  # pragma: no cover — layout-dependent
    import conftest_langs as langs  # type: ignore[no-redef]


@pytest.fixture
def daemon_answers(monkeypatch: pytest.MonkeyPatch) -> None:
    """The initial ``docker info`` probe read "available"; no memoised image state."""
    monkeypatch.setattr(langs, "_DOCKER_REASON", {"reason": ""})
    monkeypatch.setattr(langs, "_IMAGES", {})
    monkeypatch.setattr(shutil, "which", lambda _name: "/usr/bin/docker")


def _raising_run(exc: BaseException) -> Any:
    calls: list[list[str]] = []

    def run(argv: list[str], *_a: Any, **_kw: Any) -> subprocess.CompletedProcess[str]:
        calls.append(list(argv))
        raise exc

    run.calls = calls  # type: ignore[attr-defined]
    return run


@pytest.mark.parametrize(
    "exc",
    [
        subprocess.TimeoutExpired(["docker", "image", "inspect", "x"], 60),
        OSError("docker client: broken pipe"),
    ],
    ids=["TimeoutExpired", "OSError"],
)
def test_require_docker_image_skips_with_the_reason_when_inspect_raises(
    daemon_answers: None, monkeypatch: pytest.MonkeyPatch, exc: BaseException
) -> None:
    monkeypatch.setattr(langs, "STRICT_WARMUP", False)
    run = _raising_run(exc)
    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(pytest.skip.Exception) as info:
        langs.require_docker_image("crb-sandbox-python:ci", "CRB_TEST_SANDBOX_IMAGE_PYTHON")
    msg = str(info.value)
    assert "docker image inspection of 'crb-sandbox-python:ci' failed" in msg
    assert "CRB_TEST_STRICT_WARMUP=1" in msg  # the skip says how to make it a failure
    assert run.calls == [["/usr/bin/docker", "image", "inspect", "crb-sandbox-python:ci"]]
    # recorded against the tag: the next caller skips for the same reason, no second call
    assert langs._IMAGES["crb-sandbox-python:ci"].startswith("docker image inspection")
    with pytest.raises(pytest.skip.Exception):
        langs.require_docker_image("crb-sandbox-python:ci", "CRB_TEST_SANDBOX_IMAGE_PYTHON")
    assert len(run.calls) == 1


def test_require_docker_image_fails_under_strict_warmup_when_inspect_times_out(
    daemon_answers: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(langs, "STRICT_WARMUP", True)
    monkeypatch.setattr(
        subprocess,
        "run",
        _raising_run(subprocess.TimeoutExpired(["docker", "image", "inspect", "x"], 60)),
    )
    with pytest.raises(pytest.fail.Exception) as info:
        langs.require_docker_image("crb-sandbox-go:ci", "CRB_TEST_SANDBOX_IMAGE_GO")
    assert "[strict warm-up] docker image inspection of 'crb-sandbox-go:ci' failed" in str(
        info.value
    )
    assert "timed out after 60 seconds" in str(info.value)


def test_ensure_docker_image_uses_the_same_policy_when_inspect_raises(
    daemon_answers: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The build path shares the inspection: a raising inspect never reaches ``docker build``."""
    monkeypatch.setattr(langs, "STRICT_WARMUP", False)
    run = _raising_run(OSError("client gone"))
    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(
        pytest.skip.Exception, match="docker image inspection of 'crb-test-py:local'"
    ):
        langs.ensure_docker_image("crb-test-py:local", langs.TEST_IMAGE_DOCKERFILE)
    assert [c[1:3] for c in run.calls] == [["image", "inspect"]]


def test_require_docker_image_a_present_image_is_recorded_clean(
    daemon_answers: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The happy path still memoises '' (present) and asks the daemon once."""
    calls: list[list[str]] = []

    def run(argv: list[str], *_a: Any, **_kw: Any) -> subprocess.CompletedProcess[str]:
        calls.append(list(argv))
        return subprocess.CompletedProcess(argv, 0, "[]", "")

    monkeypatch.setattr(subprocess, "run", run)
    langs.require_docker_image("crb-sandbox-node:ci", "CRB_TEST_SANDBOX_IMAGE_NODE")
    langs.require_docker_image("crb-sandbox-node:ci", "CRB_TEST_SANDBOX_IMAGE_NODE")
    assert langs._IMAGES["crb-sandbox-node:ci"] == ""
    assert len(calls) == 1


@pytest.mark.parametrize("helper", ["require_docker_image", "ensure_docker_image"])
def test_a_missing_daemon_is_a_skip_on_every_call_even_under_strict_warmup(
    monkeypatch: pytest.MonkeyPatch, helper: str
) -> None:
    """The documented policy — a missing daemon is always a skip — must hold for the
    *second* caller too: the daemon reason is memoised by ``docker_unavailable_reason``
    already, and must never be recorded against a tag, where a later caller would re-raise
    it through ``warmup_unavailable`` and FAIL under ``CRB_TEST_STRICT_WARMUP=1``."""
    monkeypatch.setattr(langs, "STRICT_WARMUP", True)
    monkeypatch.setattr(langs, "_IMAGES", {})
    monkeypatch.setattr(langs, "_DOCKER_REASON", {"reason": "docker daemon not reachable"})
    monkeypatch.setattr(subprocess, "run", _raising_run(AssertionError("no subprocess may run")))
    args = (
        ("crb-sandbox-python:ci", "CRB_TEST_SANDBOX_IMAGE_PYTHON")
        if helper == "require_docker_image"
        else ("crb-test-py:local", langs.TEST_IMAGE_DOCKERFILE)
    )
    for _ in range(2):
        with pytest.raises(pytest.skip.Exception, match="docker daemon not reachable"):
            getattr(langs, helper)(*args)
    assert "crb-sandbox-python:ci" not in langs._IMAGES
    assert "crb-test-py:local" not in langs._IMAGES


# ---------------------------------------------------------------------------
# ``@pytest.mark.network``: skipped by reason when the registry is unreachable
# ---------------------------------------------------------------------------


def _opener(outcome: BaseException | None) -> Any:
    """A stand-in for ``urllib.request.urlopen`` that records the URL it was asked for."""
    calls: list[str] = []

    class _Response:
        def close(self) -> None:
            pass

    def urlopen(request: urllib.request.Request, *_a: Any, **_kw: Any) -> _Response:
        calls.append(request.full_url)
        if outcome is not None:
            raise outcome
        return _Response()

    urlopen.calls = calls
    return urlopen


@pytest.fixture
def no_probe_memo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(langs, "_NETWORK", {})


def test_an_unreachable_registry_skips_a_network_test_with_the_reason(
    no_probe_memo: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Offline, or behind a proxy that refuses: a skip that names the host and why, asked
    once per host per session (the assessment's root container failed four such tests)."""
    monkeypatch.setattr(langs, "STRICT_WARMUP", False)
    opener = _opener(urllib.error.URLError(OSError("Tunnel connection failed: 403 Forbidden")))
    monkeypatch.setattr(urllib.request, "urlopen", opener)
    for _ in range(2):
        with pytest.raises(pytest.skip.Exception) as info:
            langs.require_network(("pypi.org",))
    msg = str(info.value)
    assert "https://pypi.org/ is not reachable" in msg and "403 Forbidden" in msg
    assert "CRB_TEST_STRICT_WARMUP=1" in msg
    assert opener.calls == ["https://pypi.org/"]


def test_an_unreachable_registry_fails_under_strict_warmup(
    no_probe_memo: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """In CI the network is there: a registry it cannot reach is a failure, never a skip."""
    monkeypatch.setattr(langs, "STRICT_WARMUP", True)
    monkeypatch.setattr(urllib.request, "urlopen", _opener(TimeoutError("timed out")))
    with pytest.raises(pytest.fail.Exception, match=r"\[strict warm-up\].*registry\.npmjs\.org"):
        langs.require_network(("registry.npmjs.org",))


def test_any_http_answer_is_reachable_and_the_default_hosts_are_the_python_index(
    no_probe_memo: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An HTTP status — even 404 or 405 — means the host answered; with no hosts named on the
    marker the Python package index is what is probed."""
    monkeypatch.setattr(langs, "STRICT_WARMUP", True)
    opener = _opener(
        urllib.error.HTTPError("https://pypi.org/", 405, "Method Not Allowed", Message(), None)
    )
    monkeypatch.setattr(urllib.request, "urlopen", opener)
    langs.require_network()
    assert opener.calls == [f"https://{h}/" for h in langs.DEFAULT_NETWORK_HOSTS]
    assert all(langs._NETWORK[h] == "" for h in langs.DEFAULT_NETWORK_HOSTS)


class _Item:
    """The one part of a pytest item the setup hook reads."""

    def __init__(self, *marks: pytest.MarkDecorator) -> None:
        self._marks = {m.mark.name: m.mark for m in marks}

    def get_closest_marker(self, name: str) -> pytest.Mark | None:
        return self._marks.get(name)

    def iter_markers(self, name: str) -> Iterator[pytest.Mark]:
        return iter([self._marks[name]] if name in self._marks else [])


def test_the_setup_hook_probes_only_network_marked_tests_and_their_named_hosts(
    no_probe_memo: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``tests/conftest.py`` routes every ``@pytest.mark.network`` test through the probe —
    with the hosts the marker names — and leaves every other test alone."""
    import conftest as core_conftest

    monkeypatch.setattr(langs, "STRICT_WARMUP", False)
    opener = _opener(urllib.error.URLError(OSError("Network is unreachable")))
    monkeypatch.setattr(urllib.request, "urlopen", opener)
    core_conftest.pytest_runtest_setup(_Item(pytest.mark.slow))
    assert opener.calls == []
    with pytest.raises(pytest.skip.Exception, match=r"registry\.npmjs\.org"):
        core_conftest.pytest_runtest_setup(_Item(pytest.mark.network("registry.npmjs.org")))
    assert opener.calls == ["https://registry.npmjs.org/"]


# ---------------------------------------------------------------------------
# ``@pytest.mark.toolchain`` / ``@pytest.mark.docker``: the tool must WORK (P-741, P-742)
# ---------------------------------------------------------------------------

#: What a rustup proxy answers for a user with no toolchain (root on the fresh-clone job).
RUSTUP_NO_DEFAULT = (
    "error: rustup could not choose a version of cargo to run, because one wasn't specified "
    "explicitly, and no default is configured."
)


def _bin(tmp_path: Path, name: str, body: str) -> Path:
    """A ``name`` on a PATH of its own that runs ``body`` (a POSIX shell script)."""
    d = tmp_path / "bin"
    d.mkdir(exist_ok=True)
    tool = d / name
    tool.write_text("#!/bin/sh\n" + body + "\n", encoding="utf-8")
    tool.chmod(0o755)
    return d


def _must_pass(gate: Any, *args: Any) -> None:
    """Run a gate that must let the test through: a skip here is a FAILURE, or a regression
    that made the gate skip would read as a skipped test instead of a red one."""
    try:
        gate(*args)
    except pytest.skip.Exception as e:
        pytest.fail(f"the gate skipped where it must pass: {e}")


@pytest.fixture
def fresh_gates(monkeypatch: pytest.MonkeyPatch) -> None:
    """No memoised tool or daemon answer, no declared tools, no strict warm-up."""
    monkeypatch.setattr(langs, "_TOOLS", {})
    monkeypatch.setattr(langs, "_DOCKER_REASON", {})
    monkeypatch.delenv(langs.REQUIRE_TOOLS_ENV, raising=False)
    monkeypatch.setattr(langs, "STRICT_WARMUP", False)


def test_a_tool_on_path_that_cannot_run_is_skipped_with_what_it_said(
    fresh_gates: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The fresh-clone job's cargo: a rustup proxy on PATH with no toolchain for root. A PATH
    lookup said "available" and every cargo fixture then errored; the gate asks the tool to
    answer, and skips with the tool's own words."""
    monkeypatch.setenv(
        "PATH", str(_bin(tmp_path, "cargo", f'echo "{RUSTUP_NO_DEFAULT}" >&2; exit 1'))
    )
    assert shutil.which("cargo") is not None
    with pytest.raises(pytest.skip.Exception) as info:
        langs.require_tool("cargo")
    msg = str(info.value)
    assert msg.startswith("cargo unavailable: `cargo --version` exits 1")
    assert "no default is configured" in msg
    assert not langs.tool_usable("cargo")


def test_a_tool_the_job_declares_fails_instead_of_skipping(
    fresh_gates: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Where the job says it provides the tool, a broken or missing one is a failure: the
    tests that need it must run there, never skip quietly."""
    monkeypatch.setenv("PATH", str(_bin(tmp_path, "cargo", "exit 1")))
    monkeypatch.setenv(langs.REQUIRE_TOOLS_ENV, "go, cargo  node")
    assert langs.required_tools() == frozenset({"go", "cargo", "node"})
    with pytest.raises(pytest.fail.Exception, match=r"\[CRB_TEST_REQUIRE_TOOLS names cargo\]"):
        langs.require_tool("cargo")
    with pytest.raises(pytest.fail.Exception, match="go is not on PATH"):
        langs.require_tool("go")
    with pytest.raises(pytest.skip.Exception, match="mvn is not on PATH"):
        langs.require_tool("mvn")  # not declared: still a skip


def test_a_working_tool_passes_and_is_asked_once(
    fresh_gates: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = tmp_path / "calls"
    monkeypatch.setenv(
        "PATH", str(_bin(tmp_path, "node", f"echo \"$@\" >> '{calls}'; echo v22.0.0"))
    )
    monkeypatch.setenv(langs.REQUIRE_TOOLS_ENV, "node")
    for _ in range(3):
        _must_pass(langs.require_tool, "node")
    assert langs.tool_usable("node")
    assert calls.read_text(encoding="utf-8").split() == ["--version"]


def test_a_tool_that_hangs_is_bounded(
    fresh_gates: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(langs, "TOOL_PROBE_TIMEOUT_S", 1)
    monkeypatch.setenv("PATH", str(_bin(tmp_path, "mvn", "exec /bin/sleep 30")))
    with pytest.raises(pytest.skip.Exception, match=r"`mvn --version` did not answer within 1s"):
        langs.require_tool("mvn")


def test_each_tool_is_asked_its_own_question(
    fresh_gates: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``gofmt`` has no ``--version``: it formats a package from stdin; ``cargo-fmt`` is
    the rustfmt component through cargo; ``jdk`` is the fixture's JDK."""
    log = tmp_path / "log"
    d = _bin(tmp_path, "gofmt", f"echo gofmt \"$@\" >> '{log}'; /bin/cat")
    _bin(tmp_path, "cargo", f"echo cargo \"$@\" >> '{log}'")
    monkeypatch.setenv("PATH", str(d))
    _must_pass(langs.require_tool, "gofmt", "cargo-fmt")
    assert log.read_text(encoding="utf-8").splitlines() == ["gofmt -l", "cargo fmt --version"]
    jvmrepo = langs.fixture_module("jvmrepo")
    monkeypatch.setattr(jvmrepo, "java_home", lambda: "")
    with pytest.raises(pytest.skip.Exception, match="no JDK: neither brew openjdk nor"):
        langs.require_tool("jdk")


#: A docker CLI before 29 with its daemon stopped: a formatted ``docker info`` exits 0 with
#: the template rendered empty (the fresh-clone job's first run; ``docker run`` then failed).
OLD_CLI_NO_DAEMON = (
    'if [ "$1" = info ]; then echo; echo "Cannot connect to the Docker daemon at '
    'unix:///var/run/docker.sock. Is the docker daemon running?" >&2; exit 0; fi; exit 125'
)


def test_a_daemon_that_names_no_version_is_not_there(
    fresh_gates: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PATH", str(_bin(tmp_path, "docker", OLD_CLI_NO_DAEMON)))
    with pytest.raises(pytest.skip.Exception, match=r"docker unavailable: .*Cannot connect"):
        langs.require_docker()
    monkeypatch.setattr(langs, "_DOCKER_REASON", {})
    monkeypatch.setenv(langs.REQUIRE_TOOLS_ENV, "docker")
    with pytest.raises(pytest.fail.Exception, match=r"\[CRB_TEST_REQUIRE_TOOLS names docker\]"):
        langs.require_docker()


def test_a_daemon_that_names_its_version_answers(
    fresh_gates: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PATH", str(_bin(tmp_path, "docker", "echo 27.5.1")))
    monkeypatch.setenv(langs.REQUIRE_TOOLS_ENV, "docker")
    _must_pass(langs.require_docker)
    assert langs.docker_unavailable_reason() == ""


def test_the_setup_hook_gates_every_toolchain_and_docker_marker(
    fresh_gates: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``tests/conftest.py`` asks, before a marked test's fixtures are built, whether each
    tool its ``toolchain`` markers name works and whether a daemon answers for ``docker``."""
    import conftest as core_conftest

    d = _bin(tmp_path, "go", "echo go1.23")
    _bin(tmp_path, "docker", OLD_CLI_NO_DAEMON)
    monkeypatch.setenv("PATH", str(d))
    _must_pass(core_conftest.pytest_runtest_setup, _Item(pytest.mark.toolchain("go")))
    with pytest.raises(pytest.skip.Exception, match="cargo unavailable: cargo is not on PATH"):
        core_conftest.pytest_runtest_setup(_Item(pytest.mark.toolchain("go", "cargo")))
    with pytest.raises(pytest.skip.Exception, match="docker unavailable"):
        core_conftest.pytest_runtest_setup(_Item(pytest.mark.docker))
