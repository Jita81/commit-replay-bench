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
              rule implies (J-FAC-3), that registration is refused while a factory run
              is queued or running, that an evolution chains onto the frozen record and
              the task view shows the supersession chain (F32), and that the outcome sync
              records each delivered pull request's fate at most closed then merged — a
              closed-only delivery is read again and its later merge lands; a merged-only
              one mints no token — task view, backlog summary and capability-map counts
              agree (B-9 / F30); and that two registrations at once — two evolutions, or the
              intake listener freezing twice on an empty backlog — both land on the active
              backlog in the chain's order (EI-7), and that every server function deciding
              between freeze and evolve does so inside the registration lock (a ratchet,
              P-213).
How:          FastAPI TestClient over the seeded SQLite app (``fixtures.server_seed``);
              the factory state is read back through ``FactoryHome`` to check the files; the
              races are staged with a barrier inside the registration that times out when
              the code under test serialises it.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0002-append-only-hash-chained-ledger.md
Works with:   src/crb/server/routes/factory.py (under test), src/crb/server/factory_state.py
              (the state it writes), src/crb/factory/backlog.py (validation),
              src/crb/factory/readiness.py (slots), tests/fixtures/server_seed.py (the app),
              tests/fixtures/concurrency.py (the staged races),
              tests/test_server_github_app.py (``FakeGitHub`` plays the pulls API)
Tested by:    tests/test_server_routes_factory.py
Touch when:   never for a new repository; a factory route or a field of the task view changes
              (docs/API.md first).
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
    EV_CALIBRATION_FUNDED,
    EV_DELIVERY,
    EV_DELIVERY_UPDATED,
    EV_GAP_SIGNOFF,
    EV_ITEM_OUTCOME,
    EV_PROBE_WAIVED,
)
from crb.factory.loop import STATUS_ORACLE_NEEDS_STRENGTHENING
from crb.factory.readiness import ROUTE_HUMAN
from crb.server.app import API_PREFIX
from crb.server.factory_state import FactoryHome
from crb.server.settings import GitHubAppSettings
from crb.store.models import GitHubInstallation, Repo, Run
from fixtures.concurrency import at_once, pause_after
from fixtures.proven import add_rows, add_tasks
from fixtures.proven_cells import every_cell_proven
from fixtures.server_seed import ALPHA, THIN_CELL, Env, envelope, login, logout, make_env
from fixtures.signoff_seed import clear_policy

PATHS: list[tuple[str, str, str]] = [
    ("GET", f"/factory/{ALPHA}/backlog", "viewer"),
    ("POST", f"/factory/{ALPHA}/backlog", "operator"),
    ("GET", f"/factory/{ALPHA}/tasks", "viewer"),
    ("POST", f"/factory/{ALPHA}/tasks/I-1/signoff-gap", "approver"),
    ("GET", f"/factory/{ALPHA}/evidence", "viewer"),
    ("POST", f"/factory/{ALPHA}/backlog/evolutions", "operator"),
    ("POST", f"/factory/{ALPHA}/outcomes/sync", "operator"),
    ("POST", f"/factory/{ALPHA}/items/I-1/probe-waiver", "approver"),
    ("POST", f"/factory/{ALPHA}/items/I-1/calibration", "approver"),
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
    # POST /runs refuses a builder whose key variable is unset (P-003): the OpenAI-compatible
    # builders' key is PRESENT here — a placeholder, never a real key
    monkeypatch.setenv("CEREBRAS_API_KEY", "csk-test-placeholder-not-a-key")


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
        "verification_tier": "",
        "signed": False,
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
    # the API serves the link the stop's sentence points at: the evolutions route,
    # superseding this item (a documented route the response never named was not a
    # served link — verifier on feat/shippable, 2026-09-22)
    wf = t["way_forward"]
    assert wf["action"] == "register_evolution"
    assert wf["route"] == f"/factory/{ALPHA}/backlog/evolutions"
    assert wf["supersedes"] == "I-1"
    assert env.get(f"/factory/{ALPHA}/evidence").json()["verified"] is True


def test_a_weak_oracle_stop_serves_the_superseding_item_pre_filled(env: Env) -> None:
    """G-904: the way forward is not only a route — it is the superseding item already
    drafted from the item that stopped and from the reviewer's own finding, so the person
    strengthening the test reads what was too weak where they will fix it. Nothing is
    decided: the operator edits the draft and posts it, or does not."""
    assert _register(env, [ITEM]).status_code == 201
    ev = FactoryHome(env.settings.home, ALPHA).evidence(actor="worker")
    ev.record_route(
        "I-1", ROUTE_HUMAN, REASON, after_verdict="accept_with_edit", finding="weak_oracle"
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
    wf = t["way_forward"]
    # the POST should carry a stronger oracle: this stop was about the test itself
    assert wf["needs_authored_test"] is True
    assert wf["what_to_change"].startswith("Strengthen the test")
    pre = wf["prefill"]
    # a NEW id the register route will accept, superseding the one that stopped
    assert pre["id"] == "I-1-v2" and pre["supersedes"] == "I-1"
    # everything the product already knows is carried, not retyped
    assert pre["title"] == ITEM["title"] and pre["kind"] == ITEM["kind"]
    assert pre["capability_class"] == ITEM["capability_class"]
    assert pre["size_estimate"] == ITEM["size_estimate"]
    assert pre["structural_facts"] == ITEM["structural_facts"]
    assert pre["acceptance_criteria"] == ITEM["acceptance_criteria"]
    assert pre["level"] == "L1" and pre["depends_on"] == []
    # and the reviewer's finding is in the description, under the item's own words
    assert pre["description"].startswith(ITEM["description"])
    assert "Why the last attempt stopped:" in pre["description"] and REASON in pre["description"]
    # and it stays a body the register route accepts: the description is inside its own limit
    assert len(pre["description"]) <= 8000
    # the draft is a body the evolutions route accepts, unedited
    login(env.client, "operator")
    assert env.client.post(f"/api/v1{wf['route']}", json={"item": pre}).status_code == 201
    # once it is superseded the item no longer offers a way forward, and the next draft's
    # id steps past the one just registered
    by_id = {x["id"]: x for x in env.get(f"/factory/{ALPHA}/tasks").json()}
    assert by_id["I-1"]["way_forward"] is None
    assert by_id["I-1"]["superseded_by"] == "I-1-v2"


def test_a_stop_about_the_facts_asks_for_a_fact_not_a_test(env: Env) -> None:
    """The pre-filled draft says what to change, and that differs by stop: a readiness
    refusal needs a structural fact, not an oracle."""
    assert _register(env, [ITEM]).status_code == 201
    ev = FactoryHome(env.settings.home, ALPHA).evidence(actor="worker")
    ev.record_route("I-1", ROUTE_HUMAN, "unsigned structural gap: expected_behaviour")
    ev.record_item_outcome("I-1", status="not_ready", builds=0, error="")
    (t,) = env.get(f"/factory/{ALPHA}/tasks").json()
    wf = t["way_forward"]
    assert wf["needs_authored_test"] is False
    assert "structural fact" in wf["what_to_change"]
    assert "unsigned structural gap" in wf["prefill"]["description"]


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
    # before a reading proves the cell, the controls gate passes and the oracle is scored,
    # even the strong cell routes calibrate (routing.v2: unmeasured is never deliver) — and
    # the task says so
    by_id = {t["id"]: t["cell_route"] for t in env.get(f"/factory/{ALPHA}/tasks").json()}
    assert by_id["D-1"]["route"] == "calibrate" and by_id["D-1"]["deliverable"] is False
    clear_policy(env)
    # the deployment now grades in the sealed posture, so the thin cell is measured there
    # too: four sealed first attempts and no registered reading
    add_rows(
        env.factory,
        add_tasks(env.factory, 4, prefix="thin", cell=THIN_CELL),
        arm="S3",
        cell=THIN_CELL,
    )
    by_id = {t["id"]: t["cell_route"] for t in env.get(f"/factory/{ALPHA}/tasks").json()}
    # ADR-0018 — the route now says deliver and the prediction still says withheld: this
    # deployment needs a signed cell too, and nobody has signed it
    assert by_id["D-1"]["route"] == "deliver" and by_id["D-1"]["deliverable"] is False
    assert by_id["D-1"]["signed"] is False and by_id["D-1"]["verification_tier"] == "automated-pass"
    assert by_id["D-1"]["n"] >= 10 and by_id["D-1"]["reason_code"] == "deliver"
    # the provenance behind the route: the rate, its interval and the apparatus
    d1 = by_id["D-1"]
    assert d1["point"] >= 0.9 and d1["ci_low"] >= 0.8 and d1["ci_high"] >= d1["point"]
    assert d1["apparatus_versions"] == [APPARATUS_VERSION]
    assert by_id["T-1"]["route"] != "deliver" and by_id["T-1"]["deliverable"] is False
    assert by_id["T-1"]["reason_code"] == "reading_unregistered" and by_id["T-1"]["n"] == 4


def test_the_prediction_reads_the_sign_off_on_the_cells_proven_standard(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0018 as amended by ADR-0026 item 8: ``signed`` is the entry gate's own reading —
    the cell's proven standard carries an active sign-off (``standard_for``) — never the
    map's verification tier, so the screen's prediction and the gate cannot disagree. A
    ceiling is never signed; an unsigned standard is not deliverable."""
    from crb.factory.standard import Readers, Standard
    from crb.server import factory_standard

    assert _register(env, [{**ITEM, "id": "D-1", "size_estimate": "S"}]).status_code == 201
    clear_policy(env)

    def cell() -> dict[str, Any]:
        (route,) = [t["cell_route"] for t in env.get(f"/factory/{ALPHA}/tasks").json()]
        return dict(route)

    assert cell()["route"] == "deliver" and cell()["signed"] is False  # no proven standard
    every_cell_proven(monkeypatch, "S2")
    signed = cell()
    assert signed["signed"] is True and signed["deliverable"] is True
    assert signed["verification_tier"] == "automated-pass"  # the map's tier licenses nothing
    for std in (Standard("S2", signed=False), Standard("S3", signed=True)):
        readers = Readers(standard_for=lambda _c, s=std: s)
        monkeypatch.setattr(factory_standard, "readers_in", lambda *_a, r=readers, **_k: r)
        got = cell()
        assert got["signed"] is False and got["deliverable"] is False, std


def test_the_prediction_follows_the_deployments_delivery_licence_posture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A deployment that has set ``CRB_FACTORY__REQUIRE_SIGNED_CELL=false`` (ADR-0018 §5)
    predicts what ITS gate would do: the measured route alone makes the cell deliverable,
    with `signed` still saying the truth — nobody attested it."""
    monkeypatch.setenv("CRB_FACTORY__REQUIRE_SIGNED_CELL", "false")
    with make_env(tmp_path / "route-alone") as env:
        login(env.client, "operator")
        assert _register(env, [{**ITEM, "id": "D-1", "size_estimate": "S"}]).status_code == 201
        clear_policy(env)
        (route,) = [t["cell_route"] for t in env.get(f"/factory/{ALPHA}/tasks").json()]
        assert route["route"] == "deliver" and route["signed"] is False
        assert route["deliverable"] is True


def test_register_refuses_invalid_items_and_unknown_authored(env: Env) -> None:
    r = _register(env, [{**ITEM, "kind": "wish"}])
    assert r.status_code == 422 and "kind must be one of" in envelope(r)["message"]
    r = _register(env, [{**ITEM, "depends_on": ["ghost"]}])
    assert r.status_code == 422
    r = _register(env, [ITEM], authored={"nope": {"path": "t.py", "content": "x"}})
    assert r.status_code == 422 and "unknown items" in envelope(r)["message"]
    assert env.get(f"/factory/{ALPHA}/backlog").status_code == 404  # nothing was written


def test_an_item_registered_without_a_size_is_unsized_and_stops_before_any_spend(
    env: Env,
) -> None:
    """P-297: the operator API froze an item with no estimate as ``S``, a cell it never
    claimed, and refused ``unsized`` outright (seven characters, four allowed). An item
    with no size is ``unsized``: registered as such, and told now that the next run's
    pre-build check stops it ``unsized`` — to a person, before any spend."""
    bare = {k: v for k, v in ITEM.items() if k != "size_estimate"}
    r = _register(env, [bare, {**ITEM, "id": "I-3", "size_estimate": "unsized"}])
    assert r.status_code == 201, r.text
    backlog = FactoryHome(env.settings.home, ALPHA).load_backlog()
    assert backlog is not None
    assert [i.size_estimate for i in backlog.items] == ["unsized", "unsized"]
    tasks = {t["id"]: t for t in env.get(f"/factory/{ALPHA}/tasks").json()}
    assert tasks["I-1"]["entry"]["code"] == "unsized"
    assert tasks["I-3"]["entry"]["code"] == "unsized"
    # a size outside the ladder is refused, never truncated or defaulted
    r = _register(env, [{**ITEM, "id": "I-4", "size_estimate": "XXL"}])
    assert r.status_code == 422, r.text


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


def test_a_probe_waiver_is_an_approvers_act_bound_to_the_red_proofs_bytes(env: Env) -> None:
    """ADR-0025 item 12: the waiver names the test the item's latest RED proof carries —
    another sha256 is refused 409 ``probe_waiver_stale`` — and lands on the chain as
    ``review.probe_waived`` naming the approver, the reason and the bytes."""
    assert _register(env, [ITEM]).status_code == 201
    home = FactoryHome(env.settings.home, ALPHA)
    home.evidence(actor="worker").record_red_proof({"item_id": "I-1", "test_sha256": "a" * 64})
    login(env.client, "approver")
    url = f"/factory/{ALPHA}/items/I-1/probe-waiver"
    r = env.post(url, json={"reason": "a constant table", "test_sha256": "b" * 64})
    assert r.status_code == 409 and envelope(r)["code"] == "probe_waiver_stale"
    r = env.post(url, json={"reason": "a constant table", "test_sha256": "a" * 64})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["approver"] and body["test_sha256"] == "a" * 64
    (waived,) = home.evidence().events_for("I-1", EV_PROBE_WAIVED)
    assert waived.payload["reason"] == "a constant table"
    assert waived.payload["approver"] == body["approver"]
    assert (
        env.post(
            f"/factory/{ALPHA}/items/I-9/probe-waiver",
            json={"reason": "x", "test_sha256": "a" * 64},
        ).status_code
        == 404
    )


def test_the_approver_who_queued_a_factory_run_cannot_waive_its_strength_probe(
    env: Env,
) -> None:
    """P-339 (GOV-4 applied to the waiver): the probe waiver lifts a REQUIRED gate, so it is a
    second person's act, as the route-gate override and the sign-off are. An approver with a
    factory run on the repository still queued or running is refused 409 ``same_actor``;
    another approver may waive it."""
    assert _register(env, [ITEM]).status_code == 201
    home = FactoryHome(env.settings.home, ALPHA)
    home.evidence(actor="worker").record_red_proof({"item_id": "I-1", "test_sha256": "a" * 64})
    login(env.client, "approver")
    body = {"repo": ALPHA, "kind": "factory", "builder": "editblock", "model": "m"}
    r = env.post("/runs", json={**body, "deliver": True})
    assert r.status_code == 201, r.text
    url = f"/factory/{ALPHA}/items/I-1/probe-waiver"
    waiver = {"reason": "a constant table", "test_sha256": "a" * 64}
    r = env.post(url, json=waiver)
    assert r.status_code == 409 and envelope(r)["code"] == "same_actor", r.text
    assert not home.evidence().events_for("I-1", EV_PROBE_WAIVED)
    login(env.client, "admin")  # an admin holds the approver role and queued nothing
    r = env.post(url, json=waiver)
    assert r.status_code == 201, r.text


def test_a_calibration_build_is_an_approvers_evented_act_for_an_entry_stop_only(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0026 item 8: an item whose cell has no proven standard is told so before any run
    (the gate the next run's pre-build check makes) and after one (the chain's stop), with
    the calibration route as its way forward; an approver funds ONE calibration build (the
    chain names them); a second grant while one waits is refused, and so is a grant for an
    item the gate would let in."""

    assert _register(env, [ITEM]).status_code == 201
    home = FactoryHome(env.settings.home, ALPHA)
    url = f"/factory/{ALPHA}/items/I-1/calibration"
    login(env.client, "approver")
    # a proven cell whose standard the item carries: nothing to calibrate
    every_cell_proven(monkeypatch, "S1@m")
    r = env.post(url, json={"reason": "measure the cell"})
    assert r.status_code == 409 and envelope(r)["code"] == "calibration_not_answering"
    (t,) = env.get(f"/factory/{ALPHA}/tasks").json()
    assert t["entry"] is None and t["way_forward"] is None
    monkeypatch.undo()
    # before any run: the gate as the next run will read it (no reading is registered)
    (t,) = env.get(f"/factory/{ALPHA}/tasks").json()
    assert t["status"] == "pending" and t["entry"]["code"] == "no_proven_standard"
    assert t["way_forward"]["action"] == "fund_calibration"
    # after a run: the chain's stop
    ev = home.evidence(actor="worker")
    ev.record_readiness({"item_id": "I-1", "gaps": [], "route_hint": "build"})
    reason = "no context standard is proven for the bug.fix XS cell: it is not built"
    ev.record_entry_refused("I-1", "no_proven_standard", reason, reason_code="none", needs=[])
    ev.record_route("I-1", "human", reason, reason_code="no_proven_standard", needs=[])
    ev.record_item_outcome("I-1", status="no_proven_standard", builds=0, error=reason)
    (t,) = env.get(f"/factory/{ALPHA}/tasks").json()
    assert t["status"] == "no_proven_standard"
    assert t["entry"] == {
        "code": "no_proven_standard",
        "reason": reason,
        "reason_code": "none",
        "needs": [],
    }
    assert t["refusal"]["step"] == "entry" and t["refusal"]["reason_code"] == "no_proven_standard"
    assert t["way_forward"]["action"] == "fund_calibration"
    assert t["way_forward"]["route"] == f"/factory/{ALPHA}/items/I-1/calibration"
    r = env.post(url, json={"reason": "measure the cell"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["approver"] and body["answers"] == "no_proven_standard"
    (funded,) = home.evidence().events_for("I-1", EV_CALIBRATION_FUNDED)
    assert funded.payload["approver"] == body["approver"]
    (t,) = env.get(f"/factory/{ALPHA}/tasks").json()
    assert t["calibration"]["approver"] == body["approver"] and t["way_forward"] is None
    r = env.post(url, json={"reason": "again"})
    assert r.status_code == 409 and envelope(r)["code"] == "calibration_pending"


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
        # the evolutions chain is pinned too (empty: nothing evolved yet) — an evolution
        # in the enqueue window moves it without moving the frozen hash
        assert run.params_json["evolutions_hash"] == ""
    # the pin is a factory-only field
    r = env.post("/runs", json={"repo": ALPHA, "kind": "mine", "backlog_hash": active})
    assert r.status_code == 422 and "factory runs only" in envelope(r)["message"]


def test_factory_delivery_fields_and_the_second_approver_override(env: Env) -> None:
    """`deliver` / `max_rework` are stored on the run. The route gate's override licenses a
    delivery the map refused, so it is a SECOND approver's evented act (GOV-4, ADR-0016's
    two-person rule): nobody overrides at enqueue — an operator is 403, an approver 409
    ``same_actor`` and nothing is queued — and on a queued or running factory run that
    delivers, ``POST /runs/{id}/deliver-override`` is refused to the run's own actor and to
    a role below approver, and granted to another approver, named on the run and on a
    ``system/run.deliver_override`` event; factory fields on another kind are refused."""
    import hashlib

    from sqlalchemy import func, select

    from crb.store.models import Event

    login(env.client, "operator")
    assert _register(env, [ITEM]).status_code == 201
    body = {"repo": ALPHA, "kind": "factory", "builder": "editblock", "model": "m"}
    r = env.post("/runs", json={**body, "deliver": True, "max_rework": 2})
    assert r.status_code == 201, r.text
    operators_run = r.json()["id"]
    with env.factory() as s:
        run = s.get(Run, operators_run)
        assert run is not None
        assert run.params_json["deliver"] is True and run.params_json["max_rework"] == 2
        assert "deliver_override_by" not in run.params_json
    # nobody overrides at enqueue: an operator is refused the role, an approver the act
    r = env.post("/runs", json={**body, "deliver": True, "deliver_override": True})
    assert r.status_code == 403 and envelope(r)["code"] == "forbidden"
    login(env.client, "approver")
    with env.factory() as s:
        before = s.execute(select(func.count()).select_from(Run)).scalar_one()
    r = env.post("/runs", json={**body, "deliver": True, "deliver_override": True})
    assert r.status_code == 409 and envelope(r)["code"] == "same_actor", r.text
    assert "deliver-override" in envelope(r)["message"]
    with env.factory() as s:
        assert s.execute(select(func.count()).select_from(Run)).scalar_one() == before
    # the approver queues a run that delivers, and cannot override its own run's gate
    r = env.post("/runs", json={**body, "deliver": True})
    assert r.status_code == 201, r.text
    approvers_run = r.json()["id"]
    r = env.post(f"/runs/{approvers_run}/deliver-override")
    assert r.status_code == 409 and envelope(r)["code"] == "same_actor"
    # an operator may never grant it
    login(env.client, "operator")
    r = env.post(f"/runs/{approvers_run}/deliver-override")
    assert r.status_code == 403
    # a second approver (here the admin, who outranks one) grants it — named, evented
    login(env.client, "admin")
    root = hashlib.sha256(b"root").hexdigest()[:32]
    r = env.post(f"/runs/{approvers_run}/deliver-override")
    assert r.status_code == 200, r.text
    assert r.json()["factory"]["deliver_override_by"] == root
    with env.factory() as s:
        run = s.get(Run, approvers_run)
        assert run is not None and run.params_json["deliver_override_by"] == root != run.actor
        events = (
            s.execute(
                select(Event).where(
                    Event.trace_id == approvers_run, Event.action == "run.deliver_override"
                )
            )
            .scalars()
            .all()
        )
    assert [(e.actor, e.stage) for e in events] == [(root, "system")]
    assert events[0].payload_json["run_actor"] != root
    # once granted it stands for the run; a second grant is refused
    r = env.post(f"/runs/{approvers_run}/deliver-override")
    assert r.status_code == 409 and envelope(r)["code"] == "override_already_granted"
    # a run that does not deliver has no gate to override; an unknown run is 404
    login(env.client, "operator")
    r = env.post("/runs", json={**body, "deliver": False})
    quiet = r.json()["id"]
    login(env.client, "admin")
    r = env.post(f"/runs/{quiet}/deliver-override")
    assert r.status_code == 409 and envelope(r)["code"] == "delivery_off"
    assert env.post("/runs/nope/deliver-override").status_code == 404
    # a finished run is past its gates
    with env.factory() as s:
        done = s.get(Run, operators_run)
        assert done is not None
        done.status = "succeeded"
        s.commit()
    r = env.post(f"/runs/{operators_run}/deliver-override")
    assert r.status_code == 409 and envelope(r)["code"] == "run_terminal"
    # factory-only fields on another kind are refused, naming them
    login(env.client, "operator")
    r = env.post("/runs", json={"repo": ALPHA, "kind": "mine", "deliver": True, "max_rework": 1})
    assert (
        r.status_code == 422
        and "['deliver', 'max_rework'] apply to factory runs only" in envelope(r)["message"]
    )
    r = env.post("/runs", json={"repo": ALPHA, "kind": "mine"})
    assert r.status_code == 201
    login(env.client, "admin")
    r = env.post(f"/runs/{r.json()['id']}/deliver-override")
    assert r.status_code == 409 and envelope(r)["code"] == "not_a_factory_run"


def test_two_approvers_granting_one_override_at_once_grant_it_once(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """P-228: ``POST /runs/{id}/deliver-override`` read ``deliver_override_by`` with no lock
    and wrote it later, so two approvers granting at the same moment both passed the
    ``override_already_granted`` check: the trace recorded two grants while the run named
    one (the last commit won). The check and the grant are now one step under the events
    write lock, re-read under it: exactly one grant, one event, and the other approver is
    refused naming the one who granted it."""
    from fastapi.testclient import TestClient
    from sqlalchemy import select

    import crb.server.routes.runs as runs_routes
    from crb.store.models import Event
    from fixtures.server_seed import user_id

    assert _register(env, [ITEM]).status_code == 201
    body = {"repo": ALPHA, "kind": "factory", "builder": "editblock", "model": "m"}
    r = env.post("/runs", json={**body, "deliver": True})
    assert r.status_code == 201, r.text
    run_id = r.json()["id"]
    login(env.client, "approver")
    with TestClient(env.client.app) as other:
        login(other, "admin")
        pause_after(monkeypatch, runs_routes, "_get_run")
        results = at_once(
            lambda: env.post(f"/runs/{run_id}/deliver-override"),
            lambda: other.post(f"{API_PREFIX}/runs/{run_id}/deliver-override"),
        )
    codes = sorted(getattr(r, "status_code", type(r).__name__) for r in results)
    assert codes == [200, 409], [getattr(r, "text", r) for r in results]
    won = next(r for r in results if r.status_code == 200)
    lost = next(r for r in results if r.status_code == 409)
    grantor = won.json()["factory"]["deliver_override_by"]
    assert grantor in {user_id("appr1"), user_id("root")}
    assert envelope(lost)["code"] == "override_already_granted"
    assert envelope(lost)["detail"]["deliver_override_by"] == grantor
    with env.factory() as s:
        run = s.get(Run, run_id)
        assert run is not None and run.params_json["deliver_override_by"] == grantor
        grants = list(
            s.execute(
                select(Event).where(
                    Event.trace_id == run_id, Event.action == "run.deliver_override"
                )
            ).scalars()
        )
    assert [e.actor for e in grants] == [grantor]


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
    # a readiness stop and a red stop serve the evolutions route as the way forward; a
    # delivery refusal does not (the item was built and is reviewed — nothing to revise)
    assert by_id["I-2"]["way_forward"]["supersedes"] == "I-2"
    assert by_id["I-3"]["way_forward"]["route"] == f"/factory/{ALPHA}/backlog/evolutions"
    assert by_id["I-1"]["way_forward"] is None
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
    # a dependency block is not a stop a revised item answers: no way forward is served;
    # I-2's status is still the last outcome's (not_ready), so its link stands until a run
    # records a new outcome
    assert by_id["I-3"]["way_forward"] is None
    assert by_id["I-2"]["way_forward"]["supersedes"] == "I-2"


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


# --- evolutions (F32) ------------------------------------------------------------------


def test_evolution_registers_onto_the_frozen_backlog_and_shows_the_chain(env: Env) -> None:
    """F32: an evolution is a NEW item chained onto the frozen hash — optionally superseding
    one — with the same authored-oracle handling as registration; the frozen record never
    changes. ``GET /backlog`` lists the evolutions and the chain hash; the task view shows
    the superseded item as ``superseded`` above the item that replaced it; the loop works
    the evolution (``ordered()``)."""
    assert (
        _register(
            env,
            [ITEM],
            authored={
                "I-1": {"path": "tests/test_m.py", "content": "def test_m():\n    assert 0\n"}
            },
        ).status_code
        == 201
    )
    frozen = env.get(f"/factory/{ALPHA}/backlog").json()
    assert frozen["evolutions"] == [] and frozen["evolutions_hash"] == ""
    login(env.client, "operator")
    v2 = {**ITEM, "id": "I-1-v2", "title": "Add multiply to calc (44 tests)", "supersedes": "I-1"}
    r = env.post(
        f"/factory/{ALPHA}/backlog/evolutions",
        json={
            "item": v2,
            "authored": {"path": "tests/test_m2.py", "content": "def test_m2():\n    assert 0\n"},
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["hash"] == frozen["hash"], "the frozen hash never moves"
    assert len(body["evolutions_hash"]) == 64
    assert [(i["id"], i["supersedes"], i["superseded_by"]) for i in body["items"]] == [
        ("I-1-v2", "I-1", "")
    ]
    assert [(e["id"], e["supersedes"], e["has_authored_test"]) for e in body["evolutions"]] == [
        ("I-1-v2", "I-1", True)
    ]
    home = FactoryHome(env.settings.home, ALPHA)
    active = home.load_backlog()
    assert active is not None and active.verify(frozen["hash"]) and active.evolutions_hash
    assert (home.dir / f"backlog-{active.evolutions_hash[:16]}.json").exists()
    assert sorted(home.authored()) == ["I-1", "I-1-v2"], "the superseded oracle stays on record"
    assert [e.kind for e in home.events()] == [EV_BACKLOG_FROZEN, "backlog.evolved"]
    assert home.events()[-1].payload["supersedes"] == "I-1"
    tasks = env.get(f"/factory/{ALPHA}/tasks").json()
    assert [(t["id"], t["status"], t["supersedes"], t["superseded_by"]) for t in tasks] == [
        ("I-1", "superseded", "", "I-1-v2"),
        ("I-1-v2", "pending", "I-1", ""),
    ]
    ev = env.get(f"/factory/{ALPHA}/evidence").json()
    assert ev["verified"] is True and ev["items"][-1]["kind"] == "backlog.evolved"
    # a pure amendment (no supersedes) is an evolution too; a chain of three supersedes the latest
    r = env.post(f"/factory/{ALPHA}/backlog/evolutions", json={"item": {**ITEM, "id": "I-7"}})
    assert r.status_code == 201 and [e["id"] for e in r.json()["evolutions"]] == ["I-1-v2", "I-7"]
    r = env.post(
        f"/factory/{ALPHA}/backlog/evolutions",
        json={"item": {**v2, "id": "I-1-v3", "supersedes": "I-1-v2"}},
    )
    assert r.status_code == 201
    # active items keep registration order (I-7 before I-1-v3); a chain reads oldest first
    ids = [(t["id"], t["status"]) for t in env.get(f"/factory/{ALPHA}/tasks").json()]
    assert ids == [
        ("I-7", "pending"),
        ("I-1", "superseded"),
        ("I-1-v2", "superseded"),
        ("I-1-v3", "pending"),
    ]


def test_evolution_refusals(env: Env) -> None:
    """The frozen record never mutates: an existing id (409 ``item_exists``), superseding an
    item already superseded (409 ``already_superseded``), an unknown ``supersedes`` or a
    malformed item (422), no backlog (404), and never under an active run (409)."""
    login(env.client, "operator")
    r = env.post(f"/factory/{ALPHA}/backlog/evolutions", json={"item": {**ITEM, "id": "I-9"}})
    assert r.status_code == 404
    assert _register(env, [ITEM]).status_code == 201
    r = env.post(f"/factory/{ALPHA}/backlog/evolutions", json={"item": {**ITEM, "title": "edit"}})
    assert r.status_code == 409 and envelope(r)["code"] == "item_exists"
    r = env.post(
        f"/factory/{ALPHA}/backlog/evolutions",
        json={"item": {**ITEM, "id": "I-x", "supersedes": "ghost"}},
    )
    assert r.status_code == 422 and "unknown item" in envelope(r)["message"]
    r = env.post(
        f"/factory/{ALPHA}/backlog/evolutions", json={"item": {**ITEM, "id": "I-x", "kind": "wish"}}
    )
    assert r.status_code == 422
    r = env.post(
        f"/factory/{ALPHA}/backlog/evolutions", json={"item": {**ITEM, "id": "I-x"}, "extra": 1}
    )
    assert r.status_code == 422
    # a malformed authored oracle is refused BEFORE the evolution is written: a path that
    # escapes the repository (or blank content, which passes the schema's min_length) is a
    # 422, the chain gains nothing and the same id can be registered again with a good one
    # (verifier on feat/shippable, 2026-09-22: it used to be a 500 with the evolution
    # already persisted without its oracle)
    for bad in (
        {"path": "../../escape.py", "content": "def test_x():\n    assert 0\n"},
        {"path": "tests/test_x.py", "content": "   "},
    ):
        r = env.post(
            f"/factory/{ALPHA}/backlog/evolutions",
            json={"item": {**ITEM, "id": "I-1x", "supersedes": "I-1"}, "authored": bad},
        )
        assert r.status_code == 422 and envelope(r)["code"] == "validation_error", r.text
        assert env.get(f"/factory/{ALPHA}/backlog").json()["evolutions"] == []
    assert (
        env.post(
            f"/factory/{ALPHA}/backlog/evolutions",
            json={"item": {**ITEM, "id": "I-1b", "supersedes": "I-1"}},
        ).status_code
        == 201
    )
    r = env.post(
        f"/factory/{ALPHA}/backlog/evolutions",
        json={"item": {**ITEM, "id": "I-1c", "supersedes": "I-1"}},
    )
    assert r.status_code == 409 and envelope(r)["code"] == "already_superseded"
    with env.factory() as s:
        s.add(
            Run(
                id="fac" + "1" * 29,
                repo=ALPHA,
                kind="factory",
                status="running",
                params_json={},
                actor="x",
            )
        )
        s.commit()
    r = env.post(
        f"/factory/{ALPHA}/backlog/evolutions",
        json={"item": {**ITEM, "id": "I-1c", "supersedes": "I-1b"}},
    )
    assert r.status_code == 409 and envelope(r)["code"] == "factory_run_active"
    home = FactoryHome(env.settings.home, ALPHA)
    assert [e["id"] for e in env.get(f"/factory/{ALPHA}/backlog").json()["evolutions"]] == ["I-1b"]
    assert home.evidence().verify() == 2


# --- the merge outcome as evidence (B-9 / F30) -------------------------------------------


def _delivered(env: Env, item_id: str, number: int, *, pr_host: str = "github.com") -> None:
    FactoryHome(env.settings.home, ALPHA).evidence(actor="worker").record_delivery(
        {
            "item_id": item_id,
            "branch": f"crb/{item_id}",
            "base": "trunk",
            "commit_sha": "a" * 40,
            "pr_url": f"https://{pr_host}/acme/alpha/pull/{number}",
            "pr_number": number,
            "pack_hash": "p" * 64,
            "body_sha256": "b" * 64,
            "created": "2026-09-19T00:00:00+00:00",
            "previous_commit_sha": "",
            "updated": False,
            "comment_error": "",
        }
    )


def test_outcome_sync_is_refused_until_the_repository_is_linked(env: Env) -> None:
    login(env.client, "operator")
    assert env.post(f"/factory/{ALPHA}/outcomes/sync").status_code == 404
    assert _register(env, [ITEM]).status_code == 201
    r = env.post(f"/factory/{ALPHA}/outcomes/sync")
    assert r.status_code == 409 and envelope(r)["code"] == "outcome_sync_unavailable"
    assert "not through the GitHub App" in envelope(r)["message"]
    _link(env)
    r = env.post(f"/factory/{ALPHA}/outcomes/sync")
    assert r.status_code == 409 and "not configured" in envelope(r)["message"]
    # linked + configured + read-only: reading is allowed (an installation that delivered
    # once had write; a narrowed one can still read) — with nothing delivered, nothing is read
    env.settings.github = GitHubAppSettings(app_id="4242", app_slug="crb", private_key="pem")
    _installation(env, {"contents": "read", "pull_requests": "read"})
    r = env.post(f"/factory/{ALPHA}/outcomes/sync")
    assert r.status_code == 200, r.text
    assert r.json() == {
        "checked": 0,
        "merged": 0,
        "closed": 0,
        "open": 0,
        "errors": [],
        "outcomes": {"delivered": 0, "merged": 0, "closed": 0, "open": 0, "last_synced": ""},
    }


def _fake_github(env: Env, monkeypatch: pytest.MonkeyPatch, pulls: dict[int, str]) -> Any:
    """A linked, configured, writable installation whose pulls API is a ``FakeGitHub``
    serving ``{number: state}`` for ``acme/alpha``; the route's client is routed to it.
    Returns the fake (``calls``, ``tokens_minted``, ``pulls`` to mutate)."""
    import httpx
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    from crb.server.routes import factory as factory_routes
    from test_server_github_app import FakeGitHub, pull_request_api

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    gh = FakeGitHub(key.public_key())
    gh.pulls = {
        ("acme/alpha", n): pull_request_api(n, state, full_name="acme/alpha")
        for n, state in pulls.items()
    }
    monkeypatch.setattr(
        factory_routes, "_github_client", lambda: httpx.Client(transport=gh.transport())
    )
    _link(env)
    env.settings.github = GitHubAppSettings(app_id="4242", app_slug="crb", private_key=pem)
    _installation(env, {"contents": "write", "pull_requests": "write"})
    return gh


def test_outcome_sync_records_each_pull_requests_fate_once(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """B-9 / F30 end to end over the API: three delivered pull requests, read through the
    installation token from a fake GitHub — one merged, one closed, one open — recorded
    ONCE each on the item's chain; the task view carries ``outcome``, the backlog the
    summary (task 8's fact), the capability map's cell ``n_delivered`` / ``n_merged``;
    a second sync reads only what is still open and appends nothing."""
    import httpx

    from crb.server.routes import factory as factory_routes
    from test_server_github_app import pull_request_api

    deliver = {**ITEM, "id": "D-1", "capability_class": "bug.fix", "size_estimate": "S"}
    other = {**ITEM, "id": "D-2", "capability_class": "bug.fix", "size_estimate": "S"}
    third = {**ITEM, "id": "D-3", "capability_class": "backend.route.add", "size_estimate": "M"}
    assert _register(env, [deliver, other, third]).status_code == 201
    gh = _fake_github(env, monkeypatch, {7: "merged", 8: "closed", 9: "open"})
    _delivered(env, "D-1", 7)
    _delivered(env, "D-2", 8)
    _delivered(env, "D-3", 9)
    by_id = {t["id"]: t for t in env.get(f"/factory/{ALPHA}/tasks").json()}
    assert by_id["D-1"]["outcome"]["state"] == "open" and by_id["D-1"]["outcome"]["pr_number"] == 7
    login(env.client, "operator")
    r = env.post(f"/factory/{ALPHA}/outcomes/sync")
    assert r.status_code == 200, r.text
    assert r.json() == {
        "checked": 3,
        "merged": 1,
        "closed": 1,
        "open": 1,
        "errors": [],
        "outcomes": {
            "delivered": 3,
            "merged": 1,
            "closed": 1,
            "open": 1,
            "last_synced": r.json()["outcomes"]["last_synced"],
        },
    }
    assert r.json()["outcomes"]["last_synced"]
    reads = [c[1] for c in gh.calls if "/pulls/" in c[1]]
    assert reads == [
        "/repos/acme/alpha/pulls/7",
        "/repos/acme/alpha/pulls/8",
        "/repos/acme/alpha/pulls/9",
    ]
    assert gh.tokens_minted == 1
    by_id = {t["id"]: t for t in env.get(f"/factory/{ALPHA}/tasks").json()}
    merged = by_id["D-1"]["outcome"]
    assert merged["state"] == "merged" and merged["merged_by"] == "paul"
    assert merged["merged_at"] == "2026-09-19T17:02:11Z" and merged["merge_sha"].startswith(
        "e0fefb2"
    )
    assert merged["synced_at"] and merged["pr_url"].endswith("/pull/7")
    closed = by_id["D-2"]["outcome"]
    assert closed["state"] == "closed" and closed["closed_at"] == "2026-09-20T09:00:00Z"
    assert closed["merged_by"] == "" and closed["merge_sha"] == ""
    assert by_id["D-3"]["outcome"]["state"] == "open" and by_id["D-3"]["outcome"]["synced_at"] == ""
    # the chain: one outcome per PR, as the ledger records it; the backlog summary agrees
    kinds = [
        (e["kind"], e["item_id"]) for e in env.get(f"/factory/{ALPHA}/evidence").json()["items"]
    ]
    assert kinds[-2:] == [("delivery.merged", "D-1"), ("delivery.closed", "D-2")]
    summary = env.get(f"/factory/{ALPHA}/backlog").json()["outcomes"]
    assert (summary["delivered"], summary["merged"], summary["closed"], summary["open"]) == (
        3,
        1,
        1,
        1,
    )
    # the capability map's cell: COUNTS beside n, no interval — bug.fix × S delivered two
    # pull requests, one merged; the projection by class sums over sizes
    cells = {
        (c["capability_class"], c["size"]): c
        for c in env.get(f"/capability-map?repo={ALPHA}").json()["cells"]
    }
    assert (cells["bug.fix", "S"]["n_delivered"], cells["bug.fix", "S"]["n_merged"]) == (2, 1)
    by_class = {
        c["capability_class"]: c
        for c in env.get(f"/capability-map?repo={ALPHA}&by=class").json()["cells"]
    }
    assert (by_class["bug.fix"]["n_delivered"], by_class["bug.fix"]["n_merged"]) == (2, 1)
    # a second sync: #7 (merged) is never read again; #8 (closed — a person can reopen and
    # merge it) and #9 (still open) are; nothing appended while neither has moved
    gh.calls.clear()
    n_events = env.get(f"/factory/{ALPHA}/evidence").json()["total"]
    r = env.post(f"/factory/{ALPHA}/outcomes/sync")
    assert r.status_code == 200 and (r.json()["checked"], r.json()["open"]) == (2, 1)
    assert [c[1] for c in gh.calls if "/pulls/" in c[1]] == [
        "/repos/acme/alpha/pulls/8",
        "/repos/acme/alpha/pulls/9",
    ]
    assert env.get(f"/factory/{ALPHA}/evidence").json()["total"] == n_events
    # #9 merges later — recorded once; a PR GitHub cannot find is an error entry, not a 5xx
    gh.pulls[("acme/alpha", 9)] = pull_request_api(
        9, "merged", full_name="acme/alpha", merged_by="ada"
    )
    _delivered(env, "D-3", 10)
    r = env.post(f"/factory/{ALPHA}/outcomes/sync")
    assert r.status_code == 200 and r.json()["merged"] == 1
    assert r.json()["errors"] == ["PR #10 (D-3): GitHub 404: Not Found"]
    assert r.json()["outcomes"]["merged"] == 2 and r.json()["outcomes"]["open"] == 1
    # the newest delivery of D-3 is #10, still open: the task says so, the chain keeps #9's merge
    by_id = {t["id"]: t for t in env.get(f"/factory/{ALPHA}/tasks").json()}
    assert (by_id["D-3"]["outcome"]["state"], by_id["D-3"]["outcome"]["pr_number"]) == ("open", 10)
    assert env.get(f"/factory/{ALPHA}/evidence").json()["verified"] is True
    # a dead credential is ONE 502, never a run of per-PR errors
    monkeypatch.setattr(
        factory_routes,
        "_github_client",
        lambda: httpx.Client(
            transport=httpx.MockTransport(
                lambda req: httpx.Response(401, json={"message": "Bad credentials"})
            )
        ),
    )
    r = env.post(f"/factory/{ALPHA}/outcomes/sync")
    assert r.status_code == 502 and envelope(r)["code"] == "github_error"
    assert "Bad credentials" in envelope(r)["message"]


def test_outcome_sync_reads_a_closed_only_delivery_again_and_records_its_merge(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The closed-then-merged rule at the route's own gate: when the ONLY delivered pull
    request is already recorded ``delivery.closed``, the sync still reads it (a person
    can reopen and merge it — ``outcomes_pending``), mints the token, and appends
    ``delivery.merged`` once GitHub says so; when the only delivery is ``merged``, nothing
    is pending — no token, no read, nothing appended, ``checked: 0``."""
    from test_server_github_app import pull_request_api

    assert _register(env, [{**ITEM, "id": "D-1"}]).status_code == 201
    gh = _fake_github(env, monkeypatch, {7: "closed"})
    _delivered(env, "D-1", 7)
    login(env.client, "operator")
    r = env.post(f"/factory/{ALPHA}/outcomes/sync")
    assert r.status_code == 200 and (r.json()["checked"], r.json()["closed"]) == (1, 1)
    kinds = [e["kind"] for e in env.get(f"/factory/{ALPHA}/evidence").json()["items"]]
    assert kinds[-1] == "delivery.closed"
    # every delivery has an outcome — and the closed one is still pending: read again,
    # still closed, nothing appended
    gh.calls.clear()
    r = env.post(f"/factory/{ALPHA}/outcomes/sync")
    assert r.status_code == 200 and (r.json()["checked"], r.json()["closed"]) == (1, 0)
    assert [c[1] for c in gh.calls if "/pulls/" in c[1]] == ["/repos/acme/alpha/pulls/7"]
    assert gh.tokens_minted == 2  # one per sync: a closed-only sync still mints and reads
    n_events = env.get(f"/factory/{ALPHA}/evidence").json()["total"]
    # a person reopens and merges #7: the next sync appends delivery.merged
    gh.pulls[("acme/alpha", 7)] = pull_request_api(7, "merged", full_name="acme/alpha")
    r = env.post(f"/factory/{ALPHA}/outcomes/sync")
    assert r.status_code == 200 and (r.json()["checked"], r.json()["merged"]) == (1, 1)
    assert gh.tokens_minted == 3
    items = env.get(f"/factory/{ALPHA}/evidence").json()
    assert items["total"] == n_events + 1 and items["items"][-1]["kind"] == "delivery.merged"
    assert items["verified"] is True
    outcome = {t["id"]: t for t in env.get(f"/factory/{ALPHA}/tasks").json()}["D-1"]["outcome"]
    assert outcome["state"] == "merged" and outcome["merged_by"] == "paul"
    assert r.json()["outcomes"] == {
        "delivered": 1,
        "merged": 1,
        "closed": 0,
        "open": 0,
        "last_synced": r.json()["outcomes"]["last_synced"],
    }
    # merged-only: nothing pending — the route neither mints a token nor reads a PR
    monkeypatch.setattr(
        "crb.server.routes.factory._github_client",
        lambda: (_ for _ in ()).throw(AssertionError("no token is minted for an empty sync")),
    )
    r = env.post(f"/factory/{ALPHA}/outcomes/sync")
    assert r.status_code == 200, r.text
    assert (r.json()["checked"], r.json()["merged"], r.json()["errors"]) == (0, 0, [])
    assert env.get(f"/factory/{ALPHA}/evidence").json()["total"] == n_events + 1


# ---------------------------------------------------------------------------
# EI-7: registration is one locked read-modify-write of the active backlog
# ---------------------------------------------------------------------------


def test_two_simultaneous_evolutions_both_land_on_the_active_backlog(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """EI-7: two evolutions registered at once both loaded the same active backlog, both
    appended ``backlog.evolved`` to the (locked) evidence chain and both answered 201 — and
    the second write of ``backlog.json`` dropped the first, so an item the chain records as
    registered never builds (10 of 20 unstaged runs on the audit). Registration now holds
    one lock from the load to the active pointer: both evolutions are on the backlog, in
    the order the chain records them, and the task view serves both."""
    from crb.factory.backlog import Backlog

    assert _register(env, [ITEM]).status_code == 201
    pause_after(monkeypatch, Backlog, "evolve")

    def evolve(item_id: str) -> Any:
        return lambda: env.post(
            f"/factory/{ALPHA}/backlog/evolutions", json={"item": {**ITEM, "id": item_id}}
        )

    results = at_once(evolve("E-A"), evolve("E-B"))
    assert [getattr(r, "status_code", type(r).__name__) for r in results] == [201, 201], [
        getattr(r, "text", r) for r in results
    ]
    home = FactoryHome(env.settings.home, ALPHA)
    active = home.load_backlog()
    assert active is not None
    chained = [e.item_id for e in home.events() if e.kind == "backlog.evolved"]
    assert sorted(chained) == ["E-A", "E-B"]
    assert [i.id for i in active.evolutions] == chained
    tasks = {t["id"] for t in env.get(f"/factory/{ALPHA}/tasks").json()}
    assert {"I-1", "E-A", "E-B"} <= tasks
    assert env.get(f"/factory/{ALPHA}/evidence").json()["verified"] is True


def test_the_intake_listener_racing_itself_on_an_empty_backlog_keeps_both_items(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """EI-7, the intake path: two tickets registered at once on a repository with no backlog
    both saw none and both FROZE, so the second freeze replaced the first. The listener's
    freeze-or-evolve now runs under the same registration lock."""
    from crb.factory.backlog import BacklogItem
    from crb.server.intake import _register as intake_register

    home = FactoryHome(env.settings.home, ALPHA)
    pause_after(monkeypatch, FactoryHome, "load_backlog")
    a = BacklogItem.from_dict({**ITEM, "id": "T-1"})
    b = BacklogItem.from_dict({**ITEM, "id": "T-2"})
    results = at_once(
        lambda: intake_register(home, a, actor="intake"),
        lambda: intake_register(home, b, actor="intake"),
    )
    assert sorted(map(str, results)) == ["evolved", "frozen"], results
    active = home.load_backlog()
    assert active is not None and {"T-1", "T-2"} <= {i.id for i in active.all_items()}


#: callers that load the backlog outside ``registration()`` and then register, each with the
#: reason the load cannot go stale into a lost item
_UNLOCKED_LOAD_EXEMPT = {
    ("routes/factory.py", "register_evolution"): (
        "a 404 peek only: FactoryHome.register_evolution loads again under the lock and "
        "evolves what it loaded there, and a registered backlog is never removed"
    ),
}


def test_every_freeze_or_evolve_decision_holds_the_registration_lock() -> None:
    """EI-7's class, as a ratchet: a function that loads the active backlog and then freezes
    or evolves it is a read-modify-write of ``backlog.json``. Three callers made that
    decision (Learn, intake and the prevention route); the first fix locked two, and the
    third still froze twice on an empty backlog. Every function in the server that calls
    ``.load_backlog()`` and ``.register_backlog(`` / ``.register_evolution(`` must make every
    one of those calls inside a ``with <home>.registration():`` block, or be named in
    ``_UNLOCKED_LOAD_EXEMPT`` with the reason it cannot lose an item."""
    import ast

    import crb.server as server_pkg

    writes = {"register_backlog", "register_evolution"}
    root = Path(server_pkg.__file__).parent

    def attr_calls(fn: ast.AST, names: set[str]) -> list[ast.Call]:
        return [
            n
            for n in ast.walk(fn)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr in names
        ]

    def locked_spans(fn: ast.AST) -> list[tuple[int, int]]:
        spans = []
        for node in ast.walk(fn):
            if isinstance(node, ast.With | ast.AsyncWith) and any(
                isinstance(item.context_expr, ast.Call)
                and isinstance(item.context_expr.func, ast.Attribute)
                and item.context_expr.func.attr == "registration"
                for item in node.items
            ):
                spans.append((node.lineno, node.end_lineno or node.lineno))
        return spans

    seen: set[tuple[str, str]] = set()
    unlocked: list[str] = []
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for fn in ast.walk(tree):
            if not isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            loads = attr_calls(fn, {"load_backlog"})
            registers = attr_calls(fn, writes)
            if not loads or not registers:
                continue
            seen.add((rel, fn.name))
            spans = locked_spans(fn)
            last_write = max(c.lineno for c in registers)
            outside = [
                c.lineno
                for c in [*loads, *registers]
                if c.lineno <= last_write and not any(a <= c.lineno <= b for a, b in spans)
            ]
            if outside and (rel, fn.name) not in _UNLOCKED_LOAD_EXEMPT:
                unlocked.append(f"{rel}::{fn.name} (lines {outside})")
    assert unlocked == [], f"a freeze-or-evolve decision outside registration(): {unlocked}"
    # every caller that decides was found, and every exemption still names a real one
    assert {
        ("intake.py", "_register"),
        ("routes/learn.py", "register_strengthening"),
        ("routes/prevention.py", "learn_register_item"),
    } <= seen
    assert set(_UNLOCKED_LOAD_EXEMPT) <= seen
    assert all(why.strip() for why in _UNLOCKED_LOAD_EXEMPT.values())
