"""``/learn/register`` and the operator acts on the prevention loop, over the seeded store.

Navigation
----------
What it is:   The prevention routes' test suite (ADR-0020 §3, §4, §9, §10).
What it does: Pins that the register is viewer-readable and 404s an unknown repository; that
              the switch is operator-only, needs a reason, forbids a body-supplied decider and
              names the signed-in session; that a revert removes the change from the next run
              and sets a veto; that a filed item registers in one act — freezing the first,
              evolving the rest, superseding itself as ``-v2`` — and is refused while a factory
              run holds the backlog; that a product-scoped item never reaches a customer's
              backlog; that a link is prospective; that a tick is idempotent; that the events
              store round-trips and refuses a forged record; and that a concurrent append
              re-chains rather than forking the chain.
How:          ``make_env`` over the seed; rows appended through ``DbLedger``; the chain read
              back through ``EventsPreventionStore``.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0020-a-bug-is-closed-by-prevention.md
Works with:   src/crb/server/routes/prevention.py (under test), src/crb/server/prevention_state.py
              (the store and the tick), src/crb/core/prevention.py (the records),
              tests/fixtures/server_seed.py (the seeded store and the four roles)
Tested by:    tests/test_server_routes_prevention.py
Touch when:   a route or a record kind of the loop is added.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from crb.core.ledger import FAILURE_PROTOCOL, LABEL_FAILURE_KIND, GradeRow, LedgerIntegrityError
from crb.core.prevention import PreventionRecord, changes, vetoes
from crb.server import prevention_state
from crb.server.factory_state import FactoryHome
from crb.server.prevention_state import (
    ACTION,
    EventsPreventionStore,
    learn_trace_id,
    learning_snapshot,
)
from crb.server.routes.runs import append_system_event
from crb.store.ledger import DbLedger
from crb.store.models import Event, Run
from fixtures.server_seed import ALPHA, Env, assert_rbac, envelope, make_env, user_id

NET = (
    "protocol violation: network: 'go' is not allowed (no network access) (attempted: go mod tidy)"
)
SIG = "protocol:network:go mod"


@pytest.fixture(autouse=True)
def _no_ambient_crb_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        if key.startswith("CRB_"):
            monkeypatch.delenv(key, raising=False)


@pytest.fixture
def env(tmp_path: Path) -> Iterator[Env]:
    with make_env(tmp_path) as e:
        yield e


def _add_blind_rows(env: Env, n: int = 12, protocol: tuple[int, ...] = (0, 3, 6, 9)) -> None:
    """``n`` blind first attempts on ``alpha``; the positions in ``protocol`` refuse
    ``go mod tidy``, each on its own task."""
    ledger = DbLedger(env.factory)
    template = next(r for r in ledger.rows(repo=ALPHA) if r.clean)
    for i in range(n):
        d = template.to_dict()
        for k in ("failure_kind", "cost_known", "row_hash", "prev_hash"):
            d.pop(k, None)
        d.update(
            row_id="",
            task_id=f"{i + 1:02x}" * 20,
            mode="blind",
            trial="r1",
            run_id="blind-run",
            created=f"2026-09-20T00:{i:02d}:00+00:00",
        )
        if i in protocol:
            d.update(
                clean=False,
                target_green=False,
                source_changed=False,
                no_new_failures=None,
                repo_lint_clean=None,
                evidence_pack_hash="",
                error=NET,
                labels={LABEL_FAILURE_KIND: FAILURE_PROTOCOL},
            )
        ledger.append(GradeRow.from_dict(d))


def _seed(env: Env, *records: PreventionRecord) -> list[PreventionRecord]:
    with env.factory() as s:
        store = EventsPreventionStore(s, ALPHA)
        out = [store.append(r) for r in records]
        s.commit()
    return out


def _records(env: Env) -> list[PreventionRecord]:
    with env.factory() as s:
        return EventsPreventionStore(s, ALPHA).records()


def _rec(kind: str, payload: dict[str, Any], *, i: int = 0) -> PreventionRecord:
    return PreventionRecord(
        kind,
        ALPHA,
        payload,
        actor="loop",
        on_behalf_of="op",
        reason="fixture",
        created=f"2026-09-21T00:00:{i:02d}+00:00",
    )


def _proposal(item: str, scope: str, *, i: int = 1) -> PreventionRecord:
    return _rec(
        "proposed",
        {
            "item_id": item,
            "targets": [SIG],
            "lever_id": "item:offline-deps" if scope == "infra" else "item:refused-call",
            "level": "construction",
            "scope": scope,
            "kind": scope,
            "title": "Provision the sandbox so dependency commands resolve without the network",
            "description": "go mod tidy recurred on 4 first attempts",
            "expected_effect": "the installer answers offline",
            "evidence_refs": ["a" * 64],
            "evidence_total": 4,
        },
        i=i,
    )


# ---------------------------------------------------------------------------


def test_register_is_viewer_readable_and_404s_an_unknown_repo(env: Env) -> None:
    assert_rbac(env, "GET", f"/learn/register?repo={ALPHA}", min_role="viewer")
    r = env.get("/learn/register?repo=nope")
    assert r.status_code == 404 and envelope(r)["code"] == "not_found"
    _add_blind_rows(env)
    body = env.get(f"/learn/register?repo={ALPHA}").json()
    assert body["schema"] == "crb.prevention.register.v1" and body["repo"] == ALPHA
    assert body["switch"]["auto_apply"] == "off" and body["decisions_verified"] == []
    entry = next(e for e in body["entries"] if e["signature"] == SIG)
    assert (entry["first_attempts"], entry["tasks"], entry["status"]) == (4, 4, "open")
    # this build ships W's finish gate: a process lever outranks the advisory line
    assert (entry["recommendation"]["lever_id"], entry["recommendation"]["level"]) == (
        "finish_gate",
        "mistake-proofing",
    )
    assert set(body["counts"]) == {"open", "applied", "closed", "retired", "escalated"}


def test_the_switch_is_operator_only_needs_a_reason_and_names_the_session(env: Env) -> None:
    good = {"auto_apply": "context", "reason": "try the lines on alpha"}
    assert_rbac(env, "PUT", f"/learn/switch?repo={ALPHA}", min_role="operator", json=good)
    r = env.put(f"/learn/switch?repo={ALPHA}", json={"auto_apply": "context"})
    assert r.status_code == 422
    r = env.put(f"/learn/switch?repo={ALPHA}", json={**good, "reason": ""})
    assert r.status_code == 422
    r = env.put(f"/learn/switch?repo={ALPHA}", json={**good, "decided_by": "somebody-else"})
    assert r.status_code == 422  # the decider is the session, never the body
    r = env.put(f"/learn/switch?repo={ALPHA}", json={"auto_apply": "always", "reason": "x"})
    assert r.status_code == 422
    body = env.put(
        f"/learn/switch?repo={ALPHA}", json={"auto_apply": "config", "reason": "go"}
    ).json()
    assert body["switch"]["auto_apply"] == "config"
    assert body["record"]["actor"] == user_id("op1") == body["switch"]["switched_by"]
    assert body["record"]["reason"] == "go"
    recs = _records(env)
    assert [r.kind for r in recs] == ["switched", "switched"] and recs[-1].actor == user_id("op1")
    with env.factory() as s:
        ev = s.query(Event).filter(Event.trace_id == learn_trace_id(ALPHA)).all()
    assert [e.action for e in ev] == [ACTION, ACTION] and ev[-1].stage == "system"


GATE = {"section": "checks", "key": "finish_gate", "value": True}


def _applied(cid: str, *, i: int = 2) -> PreventionRecord:
    return _rec(
        "applied",
        {
            "change_id": cid,
            "lever_id": "finish_gate",
            "family": "config",
            "level": "mistake-proofing",
            "targets": [SIG],
            "stratum": {"mode": "blind"},
            "key": "2.2|fake|m|crb.prevention.sig.v1",
            "what": GATE,
            "before": {SIG: {"k0": 4, "n0": 12, "decisive_n": 13}},
        },
        i=i,
    )


def test_revert_removes_the_change_from_the_next_run_and_sets_a_veto(env: Env) -> None:
    _seed(env, _rec("switched", {"auto_apply": "config"}, i=1), _applied("c1"))
    assert [c.change_id for c in learning_snapshot(env.factory, ALPHA).changes] == ["c1"]
    r = env.post(f"/learn/changes/c1/revert?repo={ALPHA}", json={})
    assert r.status_code == 422  # a reason is required
    login_as = env.post(
        f"/learn/changes/c1/revert?repo={ALPHA}", json={"reason": "it slowed review"}
    )
    assert login_as.status_code == 200, login_as.text
    body = login_as.json()
    assert (body["lever_id"], body["targets"]) == ("finish_gate", [SIG])
    assert body["record"]["payload"] == {"change_id": "c1", "by": "person", "veto": True}
    recs = _records(env)
    assert changes(recs)["c1"].state == "reverted" and (SIG, "finish_gate") in vetoes(recs)
    assert learning_snapshot(env.factory, ALPHA).changes == ()
    again = env.post(f"/learn/changes/c1/revert?repo={ALPHA}", json={"reason": "again"})
    assert again.status_code == 404
    assert (
        env.post(f"/learn/changes/nope/revert?repo={ALPHA}", json={"reason": "x"}).status_code
        == 404
    )


def test_register_item_freezes_or_evolves_and_409s_while_a_run_holds_the_backlog(env: Env) -> None:
    _seed(
        env,
        _proposal("prevent-aaaaaaaaaaaa", "infra"),
        _proposal("prevent-bbbbbbbbbbbb", "operator", i=2),
    )
    r = env.post(f"/learn/items/prevent-aaaaaaaaaaaa/register?repo={ALPHA}")
    assert r.status_code == 201, r.text
    assert (r.json()["how"], r.json()["registered_id"]) == ("frozen", "prevent-aaaaaaaaaaaa")
    r = env.post(f"/learn/items/prevent-bbbbbbbbbbbb/register?repo={ALPHA}")
    assert r.status_code == 201 and r.json()["how"] == "evolved"
    r = env.post(f"/learn/items/prevent-aaaaaaaaaaaa/register?repo={ALPHA}")
    assert r.status_code == 201
    assert (r.json()["registered_id"], r.json()["supersedes"]) == (
        "prevent-aaaaaaaaaaaa-v2",
        "prevent-aaaaaaaaaaaa",
    )
    backlog = FactoryHome(env.settings.home, ALPHA).load_backlog()
    assert backlog is not None
    kinds = {i.id: i.kind for i in backlog.all_items()}
    assert kinds["prevent-aaaaaaaaaaaa"] == "infra" and kinds["prevent-bbbbbbbbbbbb"] == "operator"
    registered = [x for x in _records(env) if x.kind == "registered"]
    assert len(registered) == 3 and all(x.actor == user_id("root") for x in registered)
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
    r = env.post(f"/learn/items/prevent-bbbbbbbbbbbb/register?repo={ALPHA}")
    assert r.status_code == 409 and envelope(r)["code"] == "factory_run_active"
    assert env.post(f"/learn/items/prevent-000000000000/register?repo={ALPHA}").status_code == 404


def test_a_product_item_is_never_registered_on_a_customers_backlog(env: Env) -> None:
    _seed(env, _proposal("prevent-cccccccccccc", "product"))
    r = env.post(f"/learn/items/prevent-cccccccccccc/register?repo={ALPHA}")
    assert r.status_code == 422 and envelope(r)["code"] == "product_item"
    assert FactoryHome(env.settings.home, ALPHA).load_backlog() is None
    assert [x.kind for x in _records(env)] == ["proposed"]


def test_links_are_prospective(env: Env) -> None:
    _add_blind_rows(env)
    r = env.post(
        f"/learn/links?repo={ALPHA}", json={"signatures": ["protocol:network:nope"], "ref": "PR #1"}
    )
    assert r.status_code == 422 and envelope(r)["code"] == "unknown_class"
    r = env.post(f"/learn/links?repo={ALPHA}", json={"signatures": ["NOT A SIG"], "ref": "PR #1"})
    assert r.status_code == 422
    r = env.post(
        f"/learn/links?repo={ALPHA}",
        json={"signatures": [SIG], "ref": "docs/PREVENTION.md P-005", "note": "offline go proxy"},
    )
    assert r.status_code == 201, r.text
    rec = r.json()["record"]
    assert rec["kind"] == "linked" and rec["actor"] == user_id("root")
    assert rec["payload"]["before"][SIG]["k0"] == 4 and rec["payload"]["before"][SIG]["n0"] == 12
    entry = next(
        e
        for e in env.get(f"/learn/register?repo={ALPHA}").json()["entries"]
        if e["signature"] == SIG
    )
    assert entry["measurement"]["exposed"]["n"] == 0  # nothing before the link is exposure
    assert entry["status"] == "applied" and entry["lever_kind"] == "process"


def test_tick_is_idempotent(env: Env) -> None:
    _add_blind_rows(env)
    assert env.post(f"/learn/tick?repo={ALPHA}").json()["appended"] == []  # the switch is off
    env.put(f"/learn/switch?repo={ALPHA}", json={"auto_apply": "context", "reason": "lines"})
    first = env.post(f"/learn/tick?repo={ALPHA}").json()["appended"]
    kinds = [(x["kind"], x["payload"].get("lever_id")) for x in first]
    assert ("applied", "line:T-NET") in kinds and ("proposed", "item:refused-call") in kinds
    assert all(x["actor"] == "loop" and x["on_behalf_of"] == user_id("root") for x in first)
    assert env.post(f"/learn/tick?repo={ALPHA}").json()["appended"] == []
    snap = learning_snapshot(env.factory, ALPHA)
    assert [ln.template_id for ln in snap.lines] == ["T-NET"]


def test_events_store_round_trips_and_verifies(env: Env) -> None:
    written = _seed(env, _rec("switched", {"auto_apply": "context"}, i=1), _applied("c1"))
    back = _records(env)
    assert [r.row_hash for r in back] == [r.row_hash for r in written]
    assert back[1].prev_hash == back[0].row_hash
    # a forged record appended around the store (its prev_hash does not follow the head)
    forged = _rec("switched", {"auto_apply": "config"}, i=9).chained("f" * 64)
    with env.factory() as s:
        append_system_event(
            s, trace_id=learn_trace_id(ALPHA), action=ACTION, repo=ALPHA, payload=forged.to_dict()
        )
        s.commit()
    with pytest.raises(LedgerIntegrityError):
        _records(env)
    r = env.get(f"/learn/register?repo={ALPHA}")
    assert r.status_code == 409 and envelope(r)["code"] == "prevention_chain_broken"
    r = env.put(f"/learn/switch?repo={ALPHA}", json={"auto_apply": "off", "reason": "x"})
    assert r.status_code == 409 and envelope(r)["code"] == "prevention_chain_broken"


def test_a_concurrent_append_rechains(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    _seed(env, _rec("switched", {"auto_apply": "off"}, i=1))
    real = prevention_state.append_system_event
    raced = {"done": False}

    def racing(session: Any, **kw: Any) -> Any:
        if not raced["done"]:
            raced["done"] = True
            # another writer commits a record between this store's read of the head and its
            # insert — the insert would otherwise chain on a stale head
            _seed(env, _rec("switched", {"auto_apply": "context"}, i=2))
        return real(session, **kw)

    monkeypatch.setattr(prevention_state, "append_system_event", racing)
    r = env.put(f"/learn/switch?repo={ALPHA}", json={"auto_apply": "config", "reason": "race"})
    assert r.status_code == 200, r.text
    recs = _records(env)  # verifies the chain: one line, no fork
    assert [x.payload["auto_apply"] for x in recs] == ["off", "context", "config"]
    assert recs[2].prev_hash == recs[1].row_hash
