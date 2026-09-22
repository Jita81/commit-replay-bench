"""The warm-up policy of ``tests/conftest_langs.py``, hermetically (no daemon, no toolchain).

The helpers the docker and toolchain suites lean on turn "cannot warm up" into a *skip with
the reason* locally and a *failure* under ``CRB_TEST_STRICT_WARMUP=1``. This module pins
that policy for the one path a live daemon can break after the initial probe: ``docker image
inspect`` raising (``TimeoutExpired``, an ``OSError`` from the client) must go through the
same policy — recorded against the tag, skip or strict-fail — never surface as an
uncontrolled test error (CodeRabbit on PR #44).

Navigation
----------
What it is:   Unit tests for the warm-up policy in tests/conftest_langs.py.
What it does: Monkeypatches ``subprocess.run`` to raise while the daemon probe reads
              "available", and asserts ``require_docker_image`` / ``ensure_docker_image``
              skip with the reason by default, fail under strict warm-up, and memoise the
              reason against the tag so the next caller sees the same outcome without a
              second subprocess.
How:          ``monkeypatch`` on ``subprocess.run`` / ``shutil.which``, ``_DOCKER_REASON``,
              ``_IMAGES`` and ``STRICT_WARMUP``; ``pytest.raises(pytest.skip.Exception /
              pytest.fail.Exception)``.
Layer:        tests — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         none
Works with:   tests/conftest_langs.py (the subject), tests/test_sandbox_docker.py and
              tests/test_sandbox_images_docker.py (the callers whose skip/fail this shapes)
Tested by:    tests/test_conftest_langs.py
Touch when:   the warm-up policy changes shape (a new unavailable reason, a new strict mode),
              or a helper gains another subprocess call that could raise after the probe.
"""

from __future__ import annotations

import shutil
import subprocess
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
