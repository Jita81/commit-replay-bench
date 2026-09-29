"""The ``builders`` health probe reports the test-only ``fixture_gold`` through the registry's
own switch — present only under ``CRB_ENABLE_FIXTURE_BUILDER=1``, absent under a production
``CRB_ENV`` whatever the switch says, and never counted as a credential.

Navigation
----------
What it is:   Tests for the ``fixture_gold`` reading of ``probe_builders`` and for the one
              function behind it, ``crb.core.fixture_builder_switch.fixture_builder_enabled``.
What it does: Pins that the probe says ``fixture_gold: true`` only when the switch is exactly
              ``1`` under a non-production ``CRB_ENV``; that ``CRB_ENV=prod`` / ``production``
              (any case) — and ``CRB_ENV`` unset or empty, the server's own default posture
              (P-664) — makes it ``false`` with the switch still set, and makes the builder
              registry refuse the name at the same time, so ``/health`` and the worker can
              never disagree (the belt the critique asked for: a probe-only belt would let the
              worker accept what ``/health`` denied); that the belt's reading of the default
              agrees with ``Settings.env``; and that the fixture never lifts the probe from
              ``degraded`` or joins ``configured``, because it is not a builder.
How:          ``probe_builders(env)`` and ``fixture_builder_enabled(env)`` over hand-built
              environments; the registry re-imported under ``monkeypatch.setenv``;
              ``Settings`` built with ``CRB_ENV`` unset beside ``is_production({})``.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0004-builder-registry-sighted-and-blind.md
Works with:   src/crb/observability/probes.py (``probe_builders``),
              src/crb/core/fixture_builder_switch.py (the switch and the belt),
              src/crb/server/settings.py (``Settings.env`` — the default the belt mirrors),
              src/crb/builders/__init__.py (the registration that reads the same function),
              ui/src/lib/builder.ts (``builderChoice`` reads the ``fixture_gold`` flag)
Tested by:    tests/test_probe_fixture_builder.py
Touch when:   never for a new repository; a deployment names production by another ``CRB_ENV``
              value (``PRODUCTION_ENVS``), or the probe's shape changes.
"""

from __future__ import annotations

import importlib
import os
from pathlib import Path

import pytest

from crb.core import fixture_builder_switch as sw
from crb.observability.probes import DEGRADED, OK, probe_builders


def _env(**kw: str) -> dict[str, str]:
    return dict(kw)


def test_builders_probe_reports_the_fixture_only_under_its_switch() -> None:
    off = probe_builders(_env(CRB_ENV="dev"))
    assert off.data["fixture_gold"] is False
    on = probe_builders(_env(CRB_ENABLE_FIXTURE_BUILDER="1", CRB_ENV="dev"))
    assert on.data["fixture_gold"] is True
    # the belt: production denies the switch, so the probe reports the fixture absent — and
    # production is the DEFAULT: ``CRB_ENV`` unset or empty is what a bare-metal deployment
    # that followed docs/DEPLOYMENT.md §11 runs with (P-664)
    for prod in ("prod", "production", "PROD", " Production ", "", "  "):
        belt = probe_builders(_env(CRB_ENABLE_FIXTURE_BUILDER="1", CRB_ENV=prod))
        assert belt.data["fixture_gold"] is False, repr(prod)
    assert probe_builders(_env(CRB_ENABLE_FIXTURE_BUILDER="1")).data["fixture_gold"] is False
    # ``1`` exactly: the registry's own rule, read through the same function
    for value in ("0", "true", "yes", " 1 x"):
        assert (
            probe_builders(_env(CRB_ENABLE_FIXTURE_BUILDER=value, CRB_ENV="dev")).data[
                "fixture_gold"
            ]
            is False
        ), value


def test_the_belt_reads_the_default_posture_the_server_does(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Two readers of one default: with ``CRB_ENV`` unset the server is in production posture
    (``Settings.env == "prod"``, ``is_dev`` False) and so is the belt (``is_production`` True);
    with ``CRB_ENV=dev`` both relax. A belt that read the default the other way let
    ``CRB_ENABLE_FIXTURE_BUILDER=1`` register the fixture in a process the server itself
    called production (P-664)."""
    from crb.server.settings import Settings

    for key in list(os.environ):
        if key.startswith("CRB_"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("CRB_SECRET_KEY", "x" * 48)
    monkeypatch.setenv("CRB_ALLOW_TEMP_HOME", "true")
    monkeypatch.setenv("CRB_HOME", str(tmp_path))
    unset = Settings()
    assert unset.env == "prod" and unset.is_dev is False
    assert sw.is_production() is True
    assert sw.fixture_builder_enabled({sw.ENABLE_ENV: "1"}) is False
    monkeypatch.setenv(sw.ENV_ENV, "dev")
    dev = Settings()
    assert dev.env == "dev" and dev.is_dev is True
    assert sw.is_production() is False
    assert sw.fixture_builder_enabled() is False  # the switch itself is still unset
    monkeypatch.setenv(sw.ENABLE_ENV, "1")
    assert sw.fixture_builder_enabled() is True


def test_the_fixture_is_never_a_credential(monkeypatch: pytest.MonkeyPatch) -> None:
    """Only the fixture: the probe stays ``degraded`` and ``configured`` names nothing —
    a deployment with only an instrument check has no builder to measure with."""
    # the CLI login is read from PATH, not from ``env``: a developer machine with ``claude``
    # on PATH must not turn this into a configured-builder reading
    monkeypatch.setattr("crb.observability.probes.shutil.which", lambda _name: None)
    r = probe_builders(_env(CRB_ENABLE_FIXTURE_BUILDER="1", CRB_ENV="dev"))
    assert r.status == DEGRADED
    assert r.detail == "configured: none"
    assert r.data["fixture_gold"] is True
    # a real credential lifts it, and the fixture's flag is reported beside it, not among them
    r2 = probe_builders(
        _env(CRB_ENABLE_FIXTURE_BUILDER="1", CRB_ENV="dev", ANTHROPIC_API_KEY="present")
    )
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
