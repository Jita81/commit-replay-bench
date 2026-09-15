"""``/factory/{repo}/*`` — phase P6 stubs: a real 501 code the UI can key on, RBAC in force.

Navigation
----------
What it is:   ``/factory/{repo}/*``'s test suite — phase P6 stubs: a real 501 code the UI can key
              on, RBAC in force.
What it does: Pins that every factory route answers the 501 envelope with its code, and that
              RBAC (401 / 403) precedes the 501 so a stub never leaks whether it exists to an
              unauthorised caller.
How:          Parametrised over method, path and minimum role against ``make_env``.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         none
Works with:   src/crb/server/routes/factory.py (under test), tests/fixtures/server_seed.py
              (``assert_rbac``), docs/API.md (factory, phase P6), src/crb/factory/loop.py (what
              the routes will front)
Tested by:    tests/test_server_routes_factory.py
Touch when:   a factory route is implemented (replace its 501 case with real ones — keep the
              RBAC-precedes case).
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from crb.server.app import API_PREFIX
from fixtures.server_seed import ALPHA, Env, envelope, login, logout, make_env

PATHS: list[tuple[str, str, str]] = [
    ("GET", f"/factory/{ALPHA}/backlog", "viewer"),
    ("POST", f"/factory/{ALPHA}/backlog", "operator"),
    ("GET", f"/factory/{ALPHA}/tasks", "viewer"),
    ("POST", f"/factory/{ALPHA}/tasks/t1/signoff-gap", "approver"),
    ("GET", f"/factory/{ALPHA}/evidence", "viewer"),
]


@pytest.fixture(autouse=True)
def _no_ambient_crb_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        if key.startswith("CRB_"):
            monkeypatch.delenv(key, raising=False)


@pytest.fixture
def env(tmp_path: Path) -> Iterator[Env]:
    """The seeded environment, logged in as admin, torn down after the test."""
    with make_env(tmp_path) as e:
        yield e


@pytest.mark.parametrize(("method", "path", "min_role"), PATHS)
def test_501_envelope(env: Env, method: str, path: str, min_role: str) -> None:
    r = env.client.request(method, f"{API_PREFIX}{path}")
    assert r.status_code == 501, r.text
    e = envelope(r)
    assert e["code"] == "not_implemented"
    assert e["detail"] == {"phase": "P6", "path": path}
    assert "P6" in e["message"]


@pytest.mark.parametrize(("method", "path", "min_role"), PATHS)
def test_rbac_precedes_501(env: Env, method: str, path: str, min_role: str) -> None:
    logout(env.client)
    r = env.client.request(method, f"{API_PREFIX}{path}")
    assert r.status_code == 401 and envelope(r)["code"] == "unauthenticated"
    ladder = ["viewer", "operator", "approver", "admin"]
    for role in ladder[: ladder.index(min_role)]:
        login(env.client, role)
        r = env.client.request(method, f"{API_PREFIX}{path}")
        assert r.status_code == 403, (role, path)
        logout(env.client)
    login(env.client, min_role)
    assert env.client.request(method, f"{API_PREFIX}{path}").status_code == 501
