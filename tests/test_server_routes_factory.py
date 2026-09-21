"""``/factory/{repo}/*`` — the forward-mode factory's API over its file-backed state.

Navigation
----------
What it is:   Route tests for the factory API (backlog registration, task view, gap
              sign-offs, evidence chain) against the seeded app and a temporary CRB_HOME.
What it does: Pins that a backlog registers frozen and hashed with the freeze in the
              evidence chain, that the RBAC ladder holds (viewer/operator/approver), that
              invalid items and value-slot sign-offs are refused, that a structural gap
              sign-off lands in both the gap ledger and the evidence, that the task view
              reads "pending" before any run, folds every refusal's reason and the build's
              ids (J-FAC-4 / F15), folds ``pr_url`` from a rework's ``delivery.updated``
              as from ``delivery.opened`` — whichever is newest on the chain (DL-045) —
              folds an ``oracle_needs_strengthening`` stop with its reason (DL-045 rule 3),
              that the backlog carries the delivery pre-flight the worker's credentials
              rule implies (J-FAC-3), and that registration is refused while a factory run
              is queued or running.
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

from crb.core.version import APPARATUS_VERSION
from crb.factory.evidence import (
    EV_BACKLOG_FROZEN,
    EV_DELIVERY,
    EV_DELIVERY_UPDATED,
    EV_GAP_SIGNOFF,
    EV_ITEM_OUTCOME,
)
from crb.factory.loop import STATUS_ORACLE_NEEDS_STRENGTHENING
from crb.factory.readiness import ROUTE_HUMAN
from crb.server.app import API_PREFIX
from crb.server.factory_state import FactoryHome
from crb.server.settings import GitHubAppSettings
from crb.store.models import GitHubInstallation, Repo, Run
from fixtures.server_seed import ALPHA, Env, envelope, login, logout, make_env
from fixtures.signoff_seed import clear_policy

PATHS: list[tuple[str, str, str]] = [
    ("GET", f"/factory/{ALPHA}/backlog", "viewer"),
    ("POST", f"/factory/{ALPHA}/backlog", "operator"),
    ("GET", f"/factory/{ALPHA}/tasks", "viewer"),
    ("POST", f"/factory/{ALPHA}/tasks/I-1/signoff-gap", "approver"),
    ("GET", f"/factory/{ALPHA}/evidence", "viewer"),
]

#: What the loop writes when it refuses a rebuild against an unchanged oracle (DL-045 rule 3).
REASON = (
    "the reviewer found the oracle weak (statement deleted) and this deployment has no test "
    "author: strengthen the test and register a superseding item"
)

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
    assert [t["outcome_reason"] for t in tasks] == ["", ""]
    # F28 — the cell's route BEFORE any run: bug.fix × XS is not measured on ALPHA, so the
    # gate would withhold delivery, and the task says so now rather than after a paid build
    assert tasks[0]["cell_route"] == {
        "route": "",
        "reason_code": "",
        "reason": "",
        "n": 0,
        "point": 0.0,
        "ci_low": 0.0,
        "ci_high": 0.0,
        "apparatus_versions": [],
        "deliverable": False,
    }
    e = env.get(f"/factory/{ALPHA}/evidence").json()
    assert e["total"] == 1 and e["verified"] is True and e["items"][0]["kind"] == EV_BACKLOG_FROZEN


def test_task_view_folds_the_pull_request_from_an_updated_delivery(env: Env) -> None:
    """A rework's re-delivery is a ``delivery.updated`` event carrying the SAME pull request
    the first delivery opened (DL-045): the task view shows that PR — and keeps showing it
    when the update is the item's newest delivery event — with ``last_event`` honest."""
    assert _register(env, [ITEM]).status_code == 201
    home = FactoryHome(env.settings.home, ALPHA)
    ev = home.evidence(actor="worker")
    opened = {
        "item_id": "I-1",
        "branch": "crb/I-1-add-multiply-to-calc",
        "base": "main",
        "commit_sha": "a" * 40,
        "pr_url": "https://github.invalid/acme/calc/pull/7",
        "pr_number": 7,
        "pack_hash": "p" * 64,
        "body_sha256": "b" * 64,
        "created": "2026-09-19T00:00:00+00:00",
        "previous_commit_sha": "",
        "updated": False,
    }
    ev.record_delivery(opened)
    (t,) = env.get(f"/factory/{ALPHA}/tasks").json()
    assert t["pr_url"] == opened["pr_url"] and t["last_event"] == EV_DELIVERY
    ev.record_delivery_updated(
        {**opened, "commit_sha": "c" * 40, "previous_commit_sha": "a" * 40, "updated": True},
        rework=1,
        after_verdict="accept_with_edit",
    )
    (t,) = env.get(f"/factory/{ALPHA}/tasks").json()
    assert t["pr_url"] == opened["pr_url"] and t["last_event"] == EV_DELIVERY_UPDATED
    items = env.get(f"/factory/{ALPHA}/evidence").json()["items"]
    up = items[-1]
    assert up["kind"] == EV_DELIVERY_UPDATED and up["payload"]["rework"] == 1
    assert up["payload"]["after_verdict"] == "accept_with_edit"
    assert up["payload"]["previous_commit_sha"] == "a" * 40 and up["payload"]["pr_number"] == 7
    assert env.get(f"/factory/{ALPHA}/evidence").json()["verified"] is True


def test_task_view_shows_the_newest_delivery_when_a_fresh_pull_request_follows_an_update(
    env: Env,
) -> None:
    """The fold picks the delivery event that is LATEST in chain order, not the `updated`
    kind by preference: an earlier run's reworked delivery (opened + updated) followed by a
    later run that opens a FRESH pull request (the branch was deleted after the first PR
    closed) must show the fresh PR, not the stale run's."""
    assert _register(env, [ITEM]).status_code == 201
    home = FactoryHome(env.settings.home, ALPHA)
    ev = home.evidence(actor="worker")
    opened = {
        "item_id": "I-1",
        "branch": "crb/I-1-add-multiply-to-calc",
        "base": "main",
        "commit_sha": "a" * 40,
        "pr_url": "https://github.invalid/acme/calc/pull/7",
        "pr_number": 7,
        "pack_hash": "p" * 64,
        "body_sha256": "b" * 64,
        "created": "2026-09-19T00:00:00+00:00",
        "previous_commit_sha": "",
        "updated": False,
        "comment_error": "",
    }
    ev.record_delivery(opened)
    ev.record_delivery_updated(
        {**opened, "commit_sha": "c" * 40, "previous_commit_sha": "a" * 40, "updated": True},
        rework=1,
        after_verdict="accept_with_edit",
    )
    (t,) = env.get(f"/factory/{ALPHA}/tasks").json()
    assert t["pr_url"] == opened["pr_url"]
    fresh = {**opened, "commit_sha": "d" * 40, "pr_url": "https://github.invalid/acme/calc/pull/9"}
    fresh["pr_number"] = 9
    ev.record_delivery(fresh)
    (t,) = env.get(f"/factory/{ALPHA}/tasks").json()
    assert t["pr_url"] == fresh["pr_url"] and t["last_event"] == EV_DELIVERY
    assert env.get(f"/factory/{ALPHA}/evidence").json()["verified"] is True


def test_task_view_folds_an_oracle_needs_strengthening_stop_with_its_reason(env: Env) -> None:
    """DL-045 rule 3: the loop stops an item ``oracle_needs_strengthening`` (routed human,
    no rebuild) when the reviewer found the oracle weak and no changed oracle can be had.
    The task view folds it like every other stop — the status from ``item.outcome`` — and
    carries the reason (the finding and the way forward) as ``outcome_reason``."""
    assert _register(env, [ITEM]).status_code == 201
    home = FactoryHome(env.settings.home, ALPHA)
    ev = home.evidence(actor="worker")
    ev.record_route(
        "I-1",
        ROUTE_HUMAN,
        REASON,
        after_verdict="accept_with_edit",
        finding="weak_oracle",
        oracle_sha256="o" * 64,
    )
    ev.record_item_outcome(
        "I-1",
        status=STATUS_ORACLE_NEEDS_STRENGTHENING,
        builds=1,
        verdict="accept_with_edit",
        delivered=True,
        reworks=0,
        error=REASON,
    )
    (t,) = env.get(f"/factory/{ALPHA}/tasks").json()
    assert t["status"] == STATUS_ORACLE_NEEDS_STRENGTHENING and t["outcome_reason"] == REASON
    assert t["route_hint"] == ROUTE_HUMAN and t["last_event"] == EV_ITEM_OUTCOME
    # J-FAC-4 meets rule 3: the stop's `route.decided` to human carries `after_verdict`, so
    # it folds as a REVIEW-step refusal — never as a refusal at readiness (the item was built)
    assert t["refusal"] == {
        "step": "review",
        "reason": REASON,
        "reason_code": "",
        "measured_route": "",
    }
    assert t["error"] == REASON
    assert env.get(f"/factory/{ALPHA}/evidence").json()["verified"] is True


def test_catalogue_serves_the_classes_their_slots_and_the_vocabularies(env: Env) -> None:
    """F24: the freeze form asks the readiness catalogue's questions, so the API serves it."""
    login(env.client, "viewer")
    d = env.get("/factory/catalogue").json()
    assert d["sizes"] == ["XS", "S", "M", "L", "XL"]
    assert d["kinds"] == ["code", "infra", "operator"] and d["levels"] == ["L1", "L2", "L3"]
    by_class = {c["capability_class"]: c["slots"] for c in d["classes"]}
    assert "backend.route.add" in by_class and "bug.fix" in by_class
    route_add = {sl["name"]: sl for sl in by_class["backend.route.add"]}
    assert route_add["method_path"]["kind"] == "structural"
    assert route_add["method_path"]["question"].startswith("What HTTP method and path")
    assert route_add["example_payload"]["kind"] == "value"
    logout(env.client)
    assert env.get("/factory/catalogue").status_code == 401


def test_tasks_carry_the_cell_route_the_delivery_gate_will_read(env: Env) -> None:
    """F28: the (class × size) route from the same signed map the worker's gate uses —
    sighted rows, current apparatus, the repo's controls verdict — on every task, before a
    run spends anything: the seeded deliver cell reads deliverable, the thin cell does not."""
    deliver = {**ITEM, "id": "D-1", "capability_class": "bug.fix", "size_estimate": "S"}
    thin = {**ITEM, "id": "T-1", "capability_class": "backend.route.add", "size_estimate": "M"}
    assert _register(env, [deliver, thin]).status_code == 201
    # before the controls gate passes and the oracle is scored, even the strong cell routes
    # to a human — and the task says so
    by_id = {t["id"]: t["cell_route"] for t in env.get(f"/factory/{ALPHA}/tasks").json()}
    assert by_id["D-1"]["route"] == "human" and by_id["D-1"]["deliverable"] is False
    clear_policy(env)
    by_id = {t["id"]: t["cell_route"] for t in env.get(f"/factory/{ALPHA}/tasks").json()}
    assert by_id["D-1"]["route"] == "deliver" and by_id["D-1"]["deliverable"] is True
    assert by_id["D-1"]["n"] >= 10 and by_id["D-1"]["reason_code"] == "deliver"
    # the provenance behind the route: the rate, its interval and the apparatus
    d1 = by_id["D-1"]
    assert d1["point"] >= 0.9 and d1["ci_low"] >= 0.8 and d1["ci_high"] >= d1["point"]
    assert d1["apparatus_versions"] == [APPARATUS_VERSION]
    assert by_id["T-1"]["route"] != "deliver" and by_id["T-1"]["deliverable"] is False
    assert by_id["T-1"]["reason_code"] and by_id["T-1"]["n"] > 0


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


def test_task_view_folds_the_refusal_reason_and_the_build_ids(env: Env) -> None:
    """J-FAC-4 / F15: every refusal the loop records (readiness → route human, red.refused,
    delivery.refused, a blocked outcome) reaches the task view as ``refusal {step, reason,
    reason_code, measured_route}``; the outcome's ``error`` is served; the newest build's
    ``task_id`` / ``pack_hash`` / ``row_hash`` and the ledger row's ``run_id`` let the row
    open its evidence. A new readiness pass clears the previous pass's refusal."""
    assert (
        _register(env, [ITEM, ITEM2, {**ITEM, "id": "I-3", "title": "Modulo"}]).status_code == 201
    )
    home = FactoryHome(env.settings.home, ALPHA)
    ev = home.evidence(actor="worker")
    row = env.info.succeeded_rows[0]
    # I-1: assessed, built (the row is a seeded ledger row so run_id resolves), withheld
    ev.record_readiness({"item_id": "I-1", "ready": True, "gaps": [], "route_hint": "build"})
    ev.record_route("I-1", "build", "ready")
    ev.record_red_proof({"item_id": "I-1", "test_sha256": "t" * 64})
    ev.record_build(
        "I-1",
        pack_hash="p" * 64,
        row_id=row.row_id,
        row_hash=row.row_hash,
        clean=True,
        belts={},
        rung="fake:m0",
        trial="r1",
        oracle_commit="c" * 40,
        test_sha256="t" * 64,
    )
    ev.record_delivery_refused(
        "I-1",
        "route gate: the cell routes calibrate (n_below_min)",
        pack_hash="p" * 64,
        measured_route="calibrate",
        reason_code="n_below_min",
        policy_version="routing.v1",
    )
    ev.record_verdict({"item_id": "I-1", "verdict": "accept", "pack_hash": "p" * 64})
    ev.record_item_outcome("I-1", status="accepted", error="")
    # I-2: an unsigned structural gap routes it to a person; the value gap beside it is
    # NOT a gap a person signs (the DoR gate refuses value slots) — it only routes
    ev.record_readiness(
        {
            "item_id": "I-2",
            "ready": False,
            "gaps": [
                {"slot": "method_path", "kind": "structural", "question": "Which method and path?"},
                {
                    "slot": "example_payload",
                    "kind": "value",
                    "question": "A representative payload.",
                },
            ],
            "route_hint": "human",
        }
    )
    ev.record_route("I-2", "human", "structural gap method_path unsigned", blocking=["method_path"])
    ev.record_item_outcome("I-2", status="not_ready", error="")
    # I-3: no oracle, then an error on the outcome
    ev.record_readiness({"item_id": "I-3", "ready": True, "gaps": [], "route_hint": "build"})
    ev.record_route("I-3", "build", "ready")
    ev.record_red_refused("I-3", "no authored test and no test author configured", route="build")
    ev.record_item_outcome("I-3", status="error", error="RuntimeError: boom")
    by_id = {t["id"]: t for t in env.get(f"/factory/{ALPHA}/tasks").json()}
    assert by_id["I-1"]["refusal"] == {
        "step": "delivery",
        "reason": "route gate: the cell routes calibrate (n_below_min)",
        "reason_code": "n_below_min",
        "measured_route": "calibrate",
    }
    assert by_id["I-1"]["task_id"] == "c" * 40 and by_id["I-1"]["pack_hash"] == "p" * 64
    assert by_id["I-1"]["row_hash"] == row.row_hash and by_id["I-1"]["run_id"] == row.run_id
    assert by_id["I-1"]["error"] == ""
    assert by_id["I-2"]["refusal"] == {
        "step": "readiness",
        "reason": "structural gap method_path unsigned",
        "reason_code": "",
        "measured_route": "",
    }
    assert by_id["I-2"]["task_id"] == "" and by_id["I-2"]["run_id"] == ""
    # dor_gaps are the STRUCTURAL gaps (what blocks and what an approver can sign);
    # value gaps are served apart, never offered for signing
    assert by_id["I-2"]["dor_gaps"] == ["method_path"]
    assert by_id["I-2"]["value_gaps"] == ["example_payload"]
    assert by_id["I-3"]["refusal"]["step"] == "red"
    assert by_id["I-3"]["refusal"]["reason"].startswith("no authored test")
    assert by_id["I-3"]["error"] == "RuntimeError: boom"
    # a second pass: I-2's gap was signed, readiness now passes and the old refusal goes;
    # I-3 is blocked on a dependency this time, which is a refusal with its own step
    ev.record_readiness({"item_id": "I-2", "ready": True, "gaps": [], "route_hint": "build"})
    ev.record_route("I-2", "build", "ready")
    ev.record_item_outcome("I-3", status="blocked_on_dependency", blocked_on=["I-2"])
    by_id = {t["id"]: t for t in env.get(f"/factory/{ALPHA}/tasks").json()}
    assert by_id["I-2"]["refusal"] is None and by_id["I-2"]["dor_gaps"] == []
    assert by_id["I-3"]["refusal"] == {
        "step": "dependency",
        "reason": "waiting on I-2",
        "reason_code": "",
        "measured_route": "",
    }


def _link(
    env: Env, *, installation_id: int = 77, url: str = "https://github.com/acme/alpha.git"
) -> None:
    with env.factory() as s:
        repo = s.get(Repo, ALPHA)
        assert repo is not None
        repo.url = url
        repo.config_json = {
            **dict(repo.config_json or {}),
            "url": url,
            "github": {
                "installation_id": installation_id,
                "full_name": "acme/alpha",
                "default_branch": "trunk",
            },
        }
        s.commit()


def _installation(env: Env, permissions: dict[str, str], *, suspended: bool = False) -> None:
    with env.factory() as s:
        row = s.get(GitHubInstallation, 77) or GitHubInstallation(installation_id=77)
        row.account_login = "acme"
        row.permissions_json = permissions
        row.suspended = suspended
        s.add(row)
        s.commit()


def test_backlog_carries_the_delivery_preflight(env: Env) -> None:
    """J-FAC-3: the backlog says BEFORE a run whether delivery is possible, by the same
    rule the worker's credentials follow (linked through the app, on the app's host,
    installation on record, not suspended, Contents: write + Pull requests: write) — so
    a paid build never ends ``delivery_failed`` for a reason known before the run."""
    assert _register(env, [ITEM]).status_code == 201
    d = env.get(f"/factory/{ALPHA}/backlog").json()["delivery"]
    assert d["can_deliver"] is False and d["reason_code"] == "not_linked"
    assert "not through the GitHub App" in d["reason"] and d["full_name"] == ""
    # linked, but the app is not configured on this deployment
    _link(env)
    d = env.get(f"/factory/{ALPHA}/backlog").json()["delivery"]
    assert (d["can_deliver"], d["reason_code"]) == (False, "app_not_configured")
    env.settings.github = GitHubAppSettings(app_id="4242", app_slug="crb", private_key="pem")
    d = env.get(f"/factory/{ALPHA}/backlog").json()["delivery"]
    assert (d["can_deliver"], d["reason_code"]) == (False, "installation_missing")
    _installation(env, {"contents": "read", "metadata": "read"})
    d = env.get(f"/factory/{ALPHA}/backlog").json()["delivery"]
    assert (d["can_deliver"], d["reason_code"]) == (False, "read_only")
    assert "contents: read" in d["reason"] and "acme" in d["reason"]
    _installation(env, {"contents": "write", "pull_requests": "write"}, suspended=True)
    d = env.get(f"/factory/{ALPHA}/backlog").json()["delivery"]
    assert (d["can_deliver"], d["reason_code"]) == (False, "installation_suspended")
    _installation(env, {"contents": "write", "pull_requests": "write"})
    d = env.get(f"/factory/{ALPHA}/backlog").json()["delivery"]
    assert d == {
        "can_deliver": True,
        "reason_code": "ok",
        "reason": "",
        "full_name": "acme/alpha",
        "default_branch": "trunk",
        "installation_id": 77,
        "account_login": "acme",
    }
    # a URL edited to another host gets no token (CWE-201) — the pre-flight says so too
    _link(env, url="https://example.invalid/acme/alpha.git")
    d = env.get(f"/factory/{ALPHA}/backlog").json()["delivery"]
    assert (d["can_deliver"], d["reason_code"]) == (False, "host_mismatch")
    # the POST answers the same shape
    r = _register(env, [ITEM])
    assert r.status_code == 201 and r.json()["delivery"]["reason_code"] == "host_mismatch"
    assert r.json()["items"][0]["description"] == ITEM["description"]
