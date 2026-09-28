"""No test leaves a ``CRB_*`` variable in the process environment for the next one (P-302).

``crb.server.worker_main.settings_from_args`` sets ``CRB_HOME`` in ``os.environ`` on purpose
(builders read the secrets directory from the environment). A stream G test called it with a
temporary home and no guard, so every later test in the session ran with ``CRB_HOME``
pointing at a deleted temporary directory, and ``tests/test_lint.py`` — which asserts the
suite never runs against a real home — failed far from the cause, depending on test order.

Navigation
----------
What it is:   The tests of the suite-wide ``CRB_*`` environment guard.
What it does: Pins that the guard removes a ``CRB_*`` variable a test added, puts back one a
              test changed or deleted, leaves every other variable alone, and that the worker's
              settings reader, called as the executor-refusal test calls it, leaves no
              ``CRB_HOME`` behind once the guard has run; and that the autouse fixture wraps
              every test.
How:          Drives ``fixtures.env_guard.crb_env_restored`` by hand, as the autouse fixture in
              tests/conftest.py does around every test.
Layer:        tests — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         none
Works with:   tests/fixtures/env_guard.py (under test), tests/conftest.py (``_no_crb_env_leak``,
              the autouse fixture), src/crb/server/worker_main.py (``settings_from_args``, the
              writer that leaked)
Tested by:    tests/test_env_guard.py
Touch when:   the product starts reading configuration from a variable outside ``CRB_*``.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from fixtures.env_guard import CRB_ENV_PREFIX, crb_env_restored

PROBE = f"{CRB_ENV_PREFIX}ZZ_ENV_GUARD_PROBE"


def _run_guarded(body: object) -> None:
    gen = crb_env_restored()
    next(gen)
    assert callable(body)
    body()
    with pytest.raises(StopIteration):
        next(gen)


def test_a_crb_variable_a_test_adds_is_removed_after_it(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(PROBE, raising=False)
    _run_guarded(lambda: os.environ.__setitem__(PROBE, "leaked"))
    assert PROBE not in os.environ


def test_a_crb_variable_a_test_changes_or_deletes_is_put_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(PROBE, "before")
    _run_guarded(lambda: os.environ.__setitem__(PROBE, "after"))
    assert os.environ[PROBE] == "before"
    _run_guarded(lambda: os.environ.pop(PROBE))
    assert os.environ[PROBE] == "before"


def test_a_variable_outside_crb_is_left_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    other = "ZZ_ENV_GUARD_OTHER"
    monkeypatch.delenv(other, raising=False)
    try:
        _run_guarded(lambda: os.environ.__setitem__(other, "kept"))
        assert os.environ[other] == "kept"
    finally:
        os.environ.pop(other, None)


def test_the_worker_settings_reader_leaves_no_home_behind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The writer that leaked: ``settings_from_args`` sets ``CRB_HOME`` when it is unset."""
    from crb.server import worker_main

    monkeypatch.delenv("CRB_HOME", raising=False)
    args = worker_main.build_parser().parse_args(["--once"])
    env = {"CRB_HOME": str(tmp_path / "h"), "CRB_ENV": "dev"}
    _run_guarded(lambda: worker_main.settings_from_args(args, env))
    assert "CRB_HOME" not in os.environ


def test_the_guard_runs_around_every_test(request: pytest.FixtureRequest) -> None:
    """The guard is wired, not only written: the autouse fixture wraps this test too."""
    assert "_no_crb_env_leak" in request.fixturenames
