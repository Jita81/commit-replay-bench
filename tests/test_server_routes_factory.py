"""``/factory/{repo}/*`` — phase P6 stubs: a real 501 code the UI can key on, RBAC in force."""

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
