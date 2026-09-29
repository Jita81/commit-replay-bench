"""The ``builders`` health probe reports the test-only ``fixture_gold`` through the registry's
own switch — present only under ``CRB_ENABLE_FIXTURE_BUILDER=1``, absent under a production
``CRB_ENV`` whatever the switch says, and never counted as a credential.

Navigation
----------
What it is:   Tests for the ``fixture_gold`` reading of ``probe_builders`` and for the one
              function behind it, ``crb.core.fixture_builder_switch.fixture_builder_enabled``.
What it does: Pins that the probe says ``fixture_gold: true`` only when the switch is exactly
              ``1``; that ``CRB_ENV=prod`` / ``production`` (any case) makes it ``false`` with
              the switch still set — and makes the builder registry refuse the name at the same
              time, so ``/health`` and the worker can never disagree (the belt the critique
              asked for: a probe-only belt would let the worker accept what ``/health`` denied);
              and that the fixture never lifts the probe from ``degraded`` or joins
              ``configured``, because it is not a builder.
How:          ``probe_builders(env)`` and ``fixture_builder_enabled(env)`` over hand-built
              environments; the registry re-imported under ``monkeypatch.setenv``.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0004-builder-registry-sighted-and-blind.md
Works with:   src/crb/observability/probes.py (``probe_builders``),
              src/crb/core/fixture_builder_switch.py (the switch and the belt),
              src/crb/builders/__init__.py (the registration that reads the same function),
              ui/src/lib/builder.ts (``builderChoice`` reads the ``fixture_gold`` flag)
Tested by:    tests/test_probe_fixture_builder.py
Touch when:   never for a new repository; a deployment names production by another ``CRB_ENV``
              value (``PRODUCTION_ENVS``), or the probe's shape changes.
"""

from __future__ import annotations

import importlib

import pytest

from crb.core import fixture_builder_switch as sw
from crb.observability.probes import DEGRADED, OK, probe_builders


def _env(**kw: str) -> dict[str, str]:
    return dict(kw)


def test_builders_probe_reports_the_fixture_only_under_its_switch() -> None:
    off = probe_builders(_env())
    assert off.data["fixture_gold"] is False
    on = probe_builders(_env(CRB_ENABLE_FIXTURE_BUILDER="1"))
    assert on.data["fixture_gold"] is True
    # the belt: production denies the switch, so the probe reports the fixture absent
    for prod in ("prod", "production", "PROD", " Production "):
        belt = probe_builders(_env(CRB_ENABLE_FIXTURE_BUILDER="1", CRB_ENV=prod))
        assert belt.data["fixture_gold"] is False, prod
    # a non-production CRB_ENV leaves the switch to decide
    assert (
        probe_builders(_env(CRB_ENABLE_FIXTURE_BUILDER="1", CRB_ENV="dev")).data["fixture_gold"]
        is True
    )
    # ``1`` exactly: the registry's own rule, read through the same function
    for value in ("0", "true", "yes", " 1 x"):
        assert (
            probe_builders(_env(CRB_ENABLE_FIXTURE_BUILDER=value)).data["fixture_gold"] is False
        ), value


def test_the_fixture_is_never_a_credential(monkeypatch: pytest.MonkeyPatch) -> None:
    """Only the fixture: the probe stays ``degraded`` and ``configured`` names nothing —
    a deployment with only an instrument check has no builder to measure with."""
    # the CLI login is read from PATH, not from ``env``: a developer machine with ``claude``
    # on PATH must not turn this into a configured-builder reading
    monkeypatch.setattr("crb.observability.probes.shutil.which", lambda _name: None)
    r = probe_builders(_env(CRB_ENABLE_FIXTURE_BUILDER="1"))
    assert r.status == DEGRADED
    assert r.detail == "configured: none"
    assert r.data["fixture_gold"] is True
    # a real credential lifts it, and the fixture's flag is reported beside it, not among them
    r2 = probe_builders(_env(CRB_ENABLE_FIXTURE_BUILDER="1", ANTHROPIC_API_KEY="present"))
    assert r2.status == OK
    assert r2.detail == "configured: anthropic"
    assert r2.data["anthropic"] is True and r2.data["fixture_gold"] is True


def test_the_probe_and_the_registry_read_one_switch(monkeypatch: pytest.MonkeyPatch) -> None:
    """The belt sits inside the switch itself, so the worker's registry and the API's probe
    give the same answer under ``CRB_ENV=prod`` — never "absent on /health, accepted by the
    worker" (the gap the critique named)."""
    import crb.builders as builders

    monkeypatch.setenv(sw.ENABLE_ENV, "1")
    monkeypatch.setenv(sw.ENV_ENV, "prod")
    try:
        assert sw.fixture_builder_enabled() is False
        importlib.reload(builders)
        assert "fixture_gold" not in builders.builder_names()
        with pytest.raises(ValueError, match="unknown builder"):
            builders.get_builder("fixture_gold")
        assert probe_builders().data["fixture_gold"] is False

        monkeypatch.setenv(sw.ENV_ENV, "dev")
        assert sw.fixture_builder_enabled() is True
        importlib.reload(builders)
        assert "fixture_gold" in builders.builder_names()
        assert probe_builders().data["fixture_gold"] is True
    finally:
        monkeypatch.delenv(sw.ENABLE_ENV, raising=False)
        monkeypatch.delenv(sw.ENV_ENV, raising=False)
        importlib.reload(builders)
