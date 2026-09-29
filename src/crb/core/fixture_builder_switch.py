"""The ONE read of the test-only builder's switch, shared by the registry and the probe.

``fixture_gold`` (:mod:`crb.builders.fixture_gold`) replays a commit's own source: an
instrument check, never a measurement. It joins the builder registry only when
``CRB_ENABLE_FIXTURE_BUILDER=1`` is set AND ``CRB_ENV`` names a non-production environment
(``dev``); the belt is that production is the DEFAULT posture, as ``crb.server.settings``
reads it — ``CRB_ENV`` unset or empty is ``prod`` there (Secure cookies, a key required, a
temporary home refused), so it is production here too, and ``prod`` / ``production`` by name
deny the switch whatever it says (P-664). The ``builders`` health probe reports the same
answer through the same function, so ``/health`` can never say the fixture is absent while
the worker would accept it, or the reverse.

Navigation
----------
What it is:   ``fixture_builder_enabled(env)`` — the switch plus the production belt — and the
              two environment names it reads.
What it does: Answers ``True`` for ``CRB_ENABLE_FIXTURE_BUILDER`` exactly ``1`` (whitespace
              stripped) when ``CRB_ENV`` is set to a non-production name; anything else (the
              switch unset, ``0`` or ``true``; ``CRB_ENV`` unset, empty or a production name) is
              ``False`` — the same default posture ``Settings.env`` has. It lives in ``crb.core`` so
              the registry (``crb.builders``) and the probe (``crb.observability``), siblings
              under the layer contract, read one function instead of two switches.
How:          A pure read of the mapping it is given (``os.environ`` by default); no import
              beyond the standard library.
Layer:        core — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0004-builder-registry-sighted-and-blind.md
Works with:   src/crb/builders/fixture_gold.py (re-exports it; the builder's identity),
              src/crb/builders/__init__.py (registers the builder on its answer),
              src/crb/observability/probes.py (``probe_builders`` reports ``fixture_gold`` on it),
              src/crb/server/settings.py (``env: Env = "prod"`` — the default this belt
              mirrors; tests/test_probe_fixture_builder.py pins the two agree),
              scripts/walkthrough.sh (sets the switch under ``CRB_ENV=dev``),
              deploy/docker-compose.yml (``CRB_ENV`` defaults to ``prod`` — the belt holds)
Tested by:    tests/test_builders_fixture_gold.py, tests/test_probe_fixture_builder.py
Touch when:   never for a new repository; a deployment names its production environment by
              another ``CRB_ENV`` value — add it to ``PRODUCTION_ENVS`` so the belt still holds;
              ``Settings.env`` changes its default (keep ``is_production`` the same rule).
"""

from __future__ import annotations

import os
from collections.abc import Mapping

#: The environment switch that registers the builder (``1`` only).
ENABLE_ENV = "CRB_ENABLE_FIXTURE_BUILDER"

#: The process environment name the belt reads (``crb.server.settings`` reads the same name).
ENV_ENV = "CRB_ENV"

#: ``CRB_ENV`` values that mean production: the switch is ignored under any of them.
PRODUCTION_ENVS: frozenset[str] = frozenset({"prod", "production"})


def is_production(env: Mapping[str, str] | None = None) -> bool:
    """The process is in production posture: ``CRB_ENV`` unset or empty (the server's own
    default, ``Settings.env = "prod"``), or naming production (``prod`` / ``production``, any
    case, whitespace stripped). Only an explicit non-production name is not production."""
    e = env if env is not None else os.environ
    value = e.get(ENV_ENV, "").strip().lower()
    return value == "" or value in PRODUCTION_ENVS


def fixture_builder_enabled(env: Mapping[str, str] | None = None) -> bool:
    """``CRB_ENABLE_FIXTURE_BUILDER=1`` exactly, and never in production: anything else
    (the switch unset, ``0`` or ``true``; ``CRB_ENV`` unset, empty or naming production)
    keeps the builder unregistered and the probe reporting it absent — the switch is
    deliberately narrow, and production is the default it must be switched out of."""
    e = env if env is not None else os.environ
    if is_production(e):
        return False
    return e.get(ENABLE_ENV, "").strip() == "1"
