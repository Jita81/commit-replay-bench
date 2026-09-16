"""``/factory/{repo}/*`` — the forward-mode factory's API over its file-backed state.

Navigation
----------
What it is:   Route tests for the factory API (backlog registration, task view, gap
              sign-offs, evidence chain) against the seeded app and a temporary CRB_HOME.
What it does: Pins that a backlog registers frozen and hashed with the freeze in the
              evidence chain, that the RBAC ladder holds (viewer/operator/approver), that
              invalid items and value-slot sign-offs are refused, that a structural gap
              sign-off lands in both the gap ledger and the evidence, that the task view
              reads "pending" before any run, and that registration is refused while a
              factory run is queued or running.
How:          FastAPI TestClient over the seeded SQLite app (``fixtures.server_seed``);
              the factory state is read back through ``FactoryHome`` to check the files.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0002-append-only-hash-chained-ledger.md
Works with:   src/crb/server/routes/factory.py (under test), src/crb/server/factory_state.py
              (the state it writes), src/crb/factory/backlog.py (validation),
              src/crb/factory/readiness.py (slots), tests/fixtures/server_seed.py (the app)
Tested by:    tests/test_server_routes_factory.py
Touch when:   a factory route or a field of the task view changes (docs/API.md first).
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from crb.factory.evidence import EV_BACKLOG_FROZEN, EV_GAP_SIGNOFF
from crb.server.app import API_PREFIX
from crb.server.factory_state import FactoryHome
from crb.store.models import Run
from fixtures.server_seed import ALPHA, Env, envelope, login, logout, make_env

PATHS: list[tuple[str, str, str]] = [
    ("GET", f"/factory/{ALPHA}/backlog", "viewer"),
    ("POST", f"/factory/{ALPHA}/backlog", "operator"),
    ("GET", f"/factory/{ALPHA}/tasks", "viewer"),
    ("POST", f"/factory/{ALPHA}/tasks/I-1/signoff-gap", "approver"),
    ("GET", f"/factory/{ALPHA}/evidence", "viewer"),
]

ITEM: dict[str, Any] = {
    "id": "I-1",
    "title": "Add multiply to calc",
    "kind": "code",
    "description": "calc needs a multiply(a, b) function.",
    "acceptance_criteria": ["multiply(3, 4) == 12"],
    "capability_class": "bug.fix",
    "size_estimate": "XS",
    "structural_facts": [
        "reproduction: `from calc import multiply` raises ImportError",
        "expected_behaviour: calc exposes multiply(a: int, b: int) -> int",
    ],
}
ITEM2: dict[str, Any] = {**ITEM, "id": "I-2", "title": "Divide", "depends_on": ["I-1"]}


@pytest.fixture(autouse=True)
def _no_ambient_crb_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        if key.startswith("CRB_"):
            monkeypatch.delenv(key, raising=False)


@pytest.fixture
def env(tmp_path: Path) -> Iterator[Env]:
    with make_env(tmp_path) as e:
        yield e


def _register(env: Env, items: list[dict[str, Any]], **extra: Any) -> Any:
    login(env.client, "operator")
    return env.post(f"/factory/{ALPHA}/backlog", json={"items": items, **extra})


@pytest.mark.parametrize(("method", "path", "min_role"), PATHS)
def test_rbac_ladder(env: Env, method: str, path: str, min_role: str) -> None:
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
    r = env.client.request(method, f"{API_PREFIX}{path}")
    assert r.status_code != 403 and r.status_code != 401, (min_role, path, r.status_code)


def test_register_freezes_hashes_and_records(env: Env) -> None:
    assert env.get(f"/factory/{ALPHA}/backlog").status_code == 404
    assert env.get(f"/factory/{ALPHA}/tasks").json() == []
    r = _register(
        env,
        [ITEM, ITEM2],
        authored={
            "I-1": {"path": "tests/test_multiply.py", "content": "def test_m():\n    assert 1\n"}
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["repo"] == ALPHA and len(body["hash"]) == 64 and body["frozen_at"]
    assert [i["id"] for i in body["items"]] == ["I-1", "I-2"]  # dependency order
    assert body["items"][0]["has_authored_test"] is True
    assert body["items"][1]["has_authored_test"] is False
    # on disk: the active backlog, its history copy, the authored test, the freeze event
    home = FactoryHome(env.settings.home, ALPHA)
    backlog = home.load_backlog()
    assert backlog is not None and backlog.frozen and backlog.verify(body["hash"])
    assert (home.dir / f"backlog-{body['hash'][:16]}.json").exists()
    assert home.authored()["I-1"].author.startswith("operator:")
    ev = home.events()
    assert [e.kind for e in ev] == [EV_BACKLOG_FROZEN]
    assert ev[0].payload["backlog_hash"] == body["hash"]
    # served back, and the task view is honest about "nothing has run"
    assert env.get(f"/factory/{ALPHA}/backlog").json()["hash"] == body["hash"]
    tasks = env.get(f"/factory/{ALPHA}/tasks").json()
    assert [(t["id"], t["status"], t["build_status"], t["red_proof"]) for t in tasks] == [
        ("I-1", "pending", "not_built", None),
        ("I-2", "pending", "not_built", None),
    ]
    e = env.get(f"/factory/{ALPHA}/evidence").json()
    assert e["total"] == 1 and e["verified"] is True and e["items"][0]["kind"] == EV_BACKLOG_FROZEN


def test_register_refuses_invalid_items_and_unknown_authored(env: Env) -> None:
    r = _register(env, [{**ITEM, "kind": "wish"}])
    assert r.status_code == 422 and "kind must be one of" in envelope(r)["message"]
    r = _register(env, [{**ITEM, "depends_on": ["ghost"]}])
    assert r.status_code == 422
    r = _register(env, [ITEM], authored={"nope": {"path": "t.py", "content": "x"}})
    assert r.status_code == 422 and "unknown items" in envelope(r)["message"]
    assert env.get(f"/factory/{ALPHA}/backlog").status_code == 404  # nothing was written


def test_register_refused_while_a_factory_run_is_active(env: Env) -> None:
    assert _register(env, [ITEM]).status_code == 201
    with env.factory() as s:
        s.add(
            Run(
                id="fac" + "0" * 29,
                repo=ALPHA,
                kind="factory",
                status="queued",
                params_json={},
                actor="x",
            )
        )
        s.commit()
    r = _register(env, [ITEM2 | {"depends_on": []}])
    assert r.status_code == 409 and envelope(r)["code"] == "factory_run_active"


def test_gap_signoff_lands_in_ledger_and_evidence_value_slots_refused(env: Env) -> None:
    assert _register(env, [ITEM]).status_code == 201
    login(env.client, "approver")
    r = env.post(
        f"/factory/{ALPHA}/tasks/I-1/signoff-gap",
        json={"slot": "reproduction", "answer": "from calc import multiply → ImportError"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert (
        body["item_id"] == "I-1" and body["slot"] == "reproduction" and body["kind"] == "structural"
    )
    assert body["verifier"] and len(body["row_hash"]) == 64
    home = FactoryHome(env.settings.home, ALPHA)
    assert [g.slot for g in home.gap_ledger().records()] == ["reproduction"]
    assert [e.kind for e in home.events()] == [EV_BACKLOG_FROZEN, EV_GAP_SIGNOFF]
    # a VALUE slot can never be signed into readiness; an unknown slot / item is 4xx
    r = env.post(
        f"/factory/{ALPHA}/tasks/I-1/signoff-gap", json={"slot": "exact_value", "answer": "12"}
    )
    assert r.status_code == 422 and envelope(r)["code"] == "value_slot_unsignable"
    r = env.post(f"/factory/{ALPHA}/tasks/I-1/signoff-gap", json={"slot": "nope", "answer": "x"})
    assert r.status_code == 422
    r = env.post(
        f"/factory/{ALPHA}/tasks/I-9/signoff-gap", json={"slot": "reproduction", "answer": "x"}
    )
    assert r.status_code == 404


def test_factory_run_pins_the_active_backlog_hash_at_enqueue(env: Env) -> None:
    """The API stamps ``params.backlog_hash`` when a factory run is queued and refuses a
    run that names a different (stale) backlog; the worker re-verifies the stamp on
    claim (CodeRabbit on PR #4, 2026-09-15 — closes the register/enqueue window)."""
    login(env.client, "operator")
    body = {"repo": ALPHA, "kind": "factory", "builder": "editblock", "model": "m"}
    r = env.post("/runs", json=body)
    assert r.status_code == 409 and envelope(r)["code"] == "no_frozen_backlog"
    assert _register(env, [ITEM]).status_code == 201
    active = env.get(f"/factory/{ALPHA}/backlog").json()["hash"]
    r = env.post("/runs", json={**body, "backlog_hash": "0" * 64})
    assert r.status_code == 409 and envelope(r)["code"] == "backlog_hash_mismatch"
    assert envelope(r)["detail"]["active"] == active
    r = env.post("/runs", json=body)
    assert r.status_code == 201, r.text
    with env.factory() as s:
        run = s.get(Run, r.json()["id"])
        assert run is not None and run.params_json["backlog_hash"] == active
    # the pin is a factory-only field
    r = env.post("/runs", json={"repo": ALPHA, "kind": "mine", "backlog_hash": active})
    assert r.status_code == 422 and "factory runs only" in envelope(r)["message"]


def test_factory_delivery_fields_and_the_approver_only_override(env: Env) -> None:
    """`deliver` / `max_rework` are stored on the run; `deliver_override` needs an approver
    and stamps the caller's identity into `params.deliver_override_by` (the route gate's
    override is an approver's act, on the evidence chain — DL-038); none of them apply to
    a non-factory run."""
    login(env.client, "operator")
    assert _register(env, [ITEM]).status_code == 201
    body = {"repo": ALPHA, "kind": "factory", "builder": "editblock", "model": "m"}
    r = env.post("/runs", json={**body, "deliver": True, "max_rework": 2})
    assert r.status_code == 201, r.text
    with env.factory() as s:
        run = s.get(Run, r.json()["id"])
        assert run is not None
        assert run.params_json["deliver"] is True and run.params_json["max_rework"] == 2
        assert "deliver_override_by" not in run.params_json
    # an operator may not override the route gate
    r = env.post("/runs", json={**body, "deliver": True, "deliver_override": True})
    assert r.status_code == 403 and envelope(r)["code"] == "forbidden"
    # an approver may — and is named for it
    login(env.client, "approver")
    r = env.post("/runs", json={**body, "deliver": True, "deliver_override": True})
    assert r.status_code == 201, r.text
    with env.factory() as s:
        run = s.get(Run, r.json()["id"])
        assert run is not None and run.params_json["deliver_override_by"]
        assert run.params_json["deliver_override_by"] == run.actor
    # factory-only fields on another kind are refused, naming them
    login(env.client, "operator")
    r = env.post("/runs", json={"repo": ALPHA, "kind": "mine", "deliver": True, "max_rework": 1})
    assert (
        r.status_code == 422
        and "['deliver', 'max_rework'] apply to factory runs only" in envelope(r)["message"]
    )
