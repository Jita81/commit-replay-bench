"""The forward reading, end to end: a ceiling, a calibration build, a second person, an S2 row.

The walk ADR-0026 item 8 describes, on the API's own store with fake models (nothing costs
money): a cell whose standard is only a ceiling (``S3`` delivered, ``S1`` did not); a forward
reading registered on it through ``POST /readings/forward``; an approver funding a calibration
build; a second person writing held-out acceptance tests through the API from the ticket
alone; the factory loop, bound as the worker binds it, building the ticket — its first attempt
graded on those tests and stamped ``S2``, no pull request; and the reading's state read back
with its n, on ``GET /readings`` and on the work type's page. Then twenty passes promote the
ceiling to an ``S2`` standard — the only thing that can.

Navigation
----------
What it is:   The end-to-end test of the forward reading (``product.truth.215``, G-679).
What it does: Seeds a ceiling on the fixture's ``bug.fix`` XS and S cells (the size rule reads
              both), registers the forward reading, funds a calibration build, writes the held-
              out tests as a second person, runs the loop with the store-bound gate readers and
              held-out reader into the store's ledger, and asserts the row, the chain, the
              absent pull request, ``GET /readings`` and ``/library``; then enrols nineteen more
              graded tickets and asserts the promotion.
How:          ``fixtures.server_seed.make_env`` → ``test_governed_delivery_e2e._prove`` (the
              ceiling) → the API routes → ``FactoryLoop`` over ``fixtures.pyrepo`` with
              ``test_factory_loop``'s fake builder and ``crb.server.acceptance.held_out_reader``.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0026-the-context-standard.md (items 2, 4, 5 and 8)
Works with:   src/crb/server/routes/acceptance.py (the second person's write),
              src/crb/server/routes/readings.py (``/readings/forward``), src/crb/factory/loop.py
              (the calibration build), src/crb/server/factory_standard.py (the gate's readers
              and ``forward_states``), tests/test_governed_delivery_e2e.py (the ceiling's rows)
Tested by:    this file
Touch when:   never for a new repository; a step of the forward reading changes.
"""

from __future__ import annotations

import dataclasses
import datetime as _dt
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from crb.builders.adapter import as_run_ledger
from crb.builders.base import Rung
from crb.core import reading as reading_mod
from crb.core.acceptance import (
    ACCEPTANCE_HELD_OUT,
    EVENT_ACTION,
    LABEL_ACCEPTANCE,
    LABEL_ACCEPTANCE_RESULT,
    RESULT_PASS,
    HeldOutTests,
    held_out_labels,
    trace_for,
)
from crb.core.execution import LocalExecutor
from crb.core.library import CALIBRATION_NEEDS
from crb.core.runners.pytest_runner import PytestRunner
from crb.factory import evidence as fe
from crb.factory import loop as fl
from crb.factory import readiness as rd
from crb.factory import review as rv
from crb.factory.standard import CellRef
from crb.observability.events import Emitter
from crb.server.acceptance import held_out_reader, write_held_out
from crb.server.factory_state import FactoryHome
from crb.store.events import DbEventSink, append_event_checked
from crb.store.ledger import DbLedger
from fixtures import pyrepo as pr
from fixtures.posture import posture_row
from fixtures.server_seed import ALPHA, BUILDER, MODEL, PROVIDER, Env, envelope, login, make_env
from test_factory_loop import MultiBuilder, _creds
from test_governed_delivery_e2e import CELL_S, CELL_XS, FIRST_LOOK, Forge, _prove, _readers

TEST_SRC = "from calc import multiply\n\n\ndef test_multiply():\n    assert multiply(3, 4) == 12\n"
HELD_OUT = (
    "from calc import multiply\n\n\n"
    "def test_multiply_held_out_by_a_second_person():\n"
    "    assert multiply(7, 6) == 42\n"
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


@pytest.fixture
def env(tmp_path: Path) -> Iterator[Env]:
    with make_env(tmp_path) as e:
        e.settings.sandbox.executor = "docker"  # the sealed posture: only sealed rows license
        yield e


def _ceilings(env: Env) -> str:
    """``S3`` 20 of 20 and ``S1`` three misses on the XS and S cells: each a ceiling. Returns
    the XS reading's id."""
    from crb.server.routes.readings import load_readings

    misses = [True] * 17 + [False] * 3
    for cell, prefix in ((CELL_XS, "xs"), (CELL_S, "s")):
        _prove(env, cell, s3=[True] * FIRST_LOOK, s1=misses, prefix=prefix)
    with env.factory() as s:
        (xs,) = [r for r in load_readings(s, ALPHA) if r.cell == CELL_XS]
    login(env.client, "viewer")
    readings = env.get("/readings", params={"repo": ALPHA}).json()["readings"]
    assert next(r for r in readings if r["reading_id"] == xs.reading_id)["state"] == "ceiling"
    return xs.reading_id


def _xs_forward(env: Env) -> dict[str, Any]:
    login(env.client, "viewer")
    readings = env.get("/readings", params={"repo": ALPHA}).json()["readings"]
    (fwd,) = [r for r in readings if r["hierarchy"] == ["S2"]]
    return dict(fwd)


def _loop(env: Env, pyrepo: pr.PyRepo, tmp_path: Path, forge: Forge) -> tuple[Any, Any]:
    builder = MultiBuilder(name=BUILDER, model=MODEL, provider=PROVIDER)
    home = FactoryHome(env.settings.home, ALPHA)
    config = dataclasses.replace(pyrepo.config, name=ALPHA)  # the store's repository
    spec = fl.FactorySpec(
        config=config,
        runner=PytestRunner(config),
        executor=LocalExecutor(),
        scratch=tmp_path / "scratch",
        evidence_dir=tmp_path / "packs",
        evidence=home.evidence(actor="run-submitter"),
        ledger=as_run_ledger(DbLedger(env.factory)),
        ladder=(Rung(BUILDER, MODEL, PROVIDER),),
        builder_for=lambda r: builder,
        reviewer=rv.MechanicalReviewer(),
        gap_ledger=rd.JsonlGapSignoffLedger(tmp_path / "gaps.jsonl"),
        deliver=True,
        creds=_creds(),
        push_fn=forge.push,
        open_pr_fn=forge.open_pr,
        comment_pr_fn=lambda **kw: None,
        run_id="fwd-run",
        actor="run-submitter",
        readers=_readers(env),
        held_out=held_out_reader(env.factory, ALPHA),
        require_signed_cell=True,
    )
    loop = fl.FactoryLoop(
        spec, pyrepo.repo, emitter=Emitter(DbEventSink(env.factory), actor="op", repo=ALPHA)
    )
    return loop, spec


def _minute_ago() -> str:
    return (_dt.datetime.now(_dt.UTC) - _dt.timedelta(minutes=1)).replace(microsecond=0).isoformat()


def test_a_calibration_build_on_a_ceiling_is_graded_on_held_out_tests_and_read_forward(
    env: Env, pyrepo: pr.PyRepo, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ceiling_id = _ceilings(env)
    # (1) the operator registers the forward reading of the XS ceiling, before any build —
    # a minute before the rest of the walk: the stamps are whole seconds and a reading counts
    # only what comes strictly after it
    monkeypatch.setattr(reading_mod, "utc_now_iso", lambda: _minute_ago())
    login(env.client, "operator")
    r = env.post(
        "/readings/forward",
        json={
            "repo": ALPHA,
            "promotes": ceiling_id,
            "builder": BUILDER,
            "model": MODEL,
            "provider": PROVIDER,
        },
    )
    assert r.status_code == 201, r.text
    monkeypatch.undo()
    assert r.json()["pool_rule"] == "calibration-builds" and r.json()["promotes"] == ceiling_id
    forward_id = r.json()["reading_id"]
    # the ceiling's page says so, and what a calibration build needs
    login(env.client, "viewer")
    page = env.get(f"/library/{ALPHA}/work-types/bug.fix").json()
    xs = next(s for s in page["sizes"] if s["size"] == "XS")
    assert xs["standard"]["arm"] == "S3" and xs["standard"]["ceiling"] is True
    assert xs["next"] == CALIBRATION_NEEDS and "calibration build" in xs["next"]
    assert xs["standard"]["forward"]["state"] == "look_pending"
    assert xs["standard"]["forward"]["counted"] == 0

    # (2) the ticket, carrying a person's failing test; the gate stops it at the ceiling
    login(env.client, "operator")
    r = env.post(
        f"/factory/{ALPHA}/backlog",
        json={
            "items": [ITEM],
            "authored": {"I-1": {"path": "tests/test_multiply.py", "content": TEST_SRC}},
        },
    )
    assert r.status_code == 201, r.text
    # (3) an approver funds one calibration build
    login(env.client, "approver")
    r = env.post(f"/factory/{ALPHA}/items/I-1/calibration", json={"reason": "forward reading"})
    assert r.status_code == 201, r.text
    # (4) a second person writes the held-out tests from the ticket alone
    login(env.client, "admin")
    r = env.post(
        f"/factory/{ALPHA}/items/I-1/acceptance",
        json={"files": [{"path": "tests/test_multiply_held_out.py", "content": HELD_OUT}]},
    )
    assert r.status_code == 201, r.text
    record_sha = r.json()["sha256"]
    # the second person is told which forward reading will count their tests
    (a,) = env.get(f"/factory/{ALPHA}/acceptance").json()["assignments"]
    assert a["forward_reading"] == forward_id and a["counted_by"] == forward_id

    # (5) the factory builds it: first attempt graded on the held-out tests, stamped S2
    forge = Forge()
    loop, spec = _loop(env, pyrepo, tmp_path, forge)
    home = FactoryHome(env.settings.home, ALPHA)
    backlog = home.load_backlog()
    assert backlog is not None
    out = loop.run_item(backlog.items[0], authored=home.authored()["I-1"])
    assert out.status == fl.STATUS_CALIBRATION_BUILD, out.error
    assert out.delivery is None and not forge.pushes and not forge.prs  # no pull request
    (row,) = [r for r in DbLedger(env.factory).rows(repo=ALPHA) if r.run_id == "fwd-run"]
    assert row.context_arm == "S2" and row.labels[LABEL_ACCEPTANCE] == ACCEPTANCE_HELD_OUT
    assert row.labels["acceptance_sha256"] == record_sha
    assert row.labels[LABEL_ACCEPTANCE_RESULT] == RESULT_PASS
    (graded,) = spec.evidence.events_for("I-1", fe.EV_ACCEPTANCE_GRADED)
    assert graded.payload["row_hash"] == row.row_hash

    # (6) the reading's state, with its n — on /readings and on the work type's page
    fwd = _xs_forward(env)
    (arm,) = fwd["arms"]
    assert arm["arm"] == "S2" and arm["state"] == "look_pending"
    assert arm["counted"] == 1 and arm["clean"] == 1 and arm["needed"] == 19
    page = env.get(f"/library/{ALPHA}/work-types/bug.fix").json()
    xs = next(s for s in page["sizes"] if s["size"] == "XS")
    assert xs["standard"]["ceiling"] is True
    assert xs["standard"]["forward"]["counted"] == 1 and xs["standard"]["forward"]["needed"] == 19
    login(env.client, "admin")
    (a,) = env.get(f"/factory/{ALPHA}/acceptance").json()["assignments"]
    assert a["status"] == "graded" and a["result"] == RESULT_PASS
    # a stored record whose content no longer re-hashes enrols nothing (operations.11)
    forged = HeldOutTests(
        repo=ALPHA,
        item_id="I-99",
        grant="grant-forged",
        files=(("tests/test_forged.py", "def test_it():\n    assert True\n"),),
        author="operator:someone-else",
        written_at=row.created,
        capability_class="bug.fix",
        size="XS",
        language="python",
    )
    append_event_checked(
        env.factory,
        trace_id=trace_for(ALPHA),
        stage="system",
        action=EVENT_ACTION,
        build=lambda _s: {**forged.to_dict(), "files": [["tests/test_forged.py", "x = 1\n"]]},
        actor="someone-else",
        repo=ALPHA,
    )
    login(env.client, "viewer")
    page = env.get(f"/library/{ALPHA}/work-types/bug.fix").json()
    xs = next(s for s in page["sizes"] if s["size"] == "XS")
    assert xs["standard"]["forward"]["enrolled"] == 1

    # (7) nineteen more calibration builds pass their held-out tests: the ceiling is promoted
    rows = []
    for i in range(1, FIRST_LOOK):
        rec = HeldOutTests(
            repo=ALPHA,
            item_id=f"I-{i + 1}",
            grant=f"grant-{i}",
            files=(("tests/test_held.py", f"def test_it():\n    assert {i} == {i}\n"),),
            author="operator:someone-else",
            written_at=row.created,
            capability_class="bug.fix",
            size="XS",
            language="python",
        )
        write_held_out(env.factory, rec)
        rows.append(
            posture_row(
                **{
                    **{k: getattr(row, k) for k in ("repo", "apparatus_version", "mode")},
                    **dict(row.cell.to_dict()),
                    "task_id": f"oracle-{i}",
                    "clean": True,
                    "tests_unmodified": True,
                    "target_green": True,
                    "no_new_failures": True,
                    "source_changed": True,
                    "evidence_pack_hash": "h" * 64,
                    "trial": "r1",
                    "created": "2099-01-01T00:00:00+00:00",
                    "run_id": "fwd-run",
                },
                labels={
                    **{k: v for k, v in row.labels.items() if not k.startswith("acceptance")},
                    "item_id": rec.item_id,
                    **held_out_labels(rec, RESULT_PASS),
                },
            )
        )
    DbLedger(env.factory).append_many(rows)
    fwd = _xs_forward(env)
    assert fwd["state"] == "standard" and fwd["standard"] == "S2"
    std = _readers(env).standard_for(CellRef("bug.fix", "XS"))
    assert std is not None and std.arm == "S2" and not std.ceiling
    login(env.client, "viewer")
    page = env.get(f"/library/{ALPHA}/work-types/bug.fix").json()
    xs = next(s for s in page["sizes"] if s["size"] == "XS")
    assert xs["standard"]["arm"] == "S2" and xs["standard"]["ceiling"] is False
    assert xs["next"] == ""


def test_the_forward_reading_route_refuses_what_it_must(env: Env) -> None:
    """verify_fwd_evidence: the route's refusals were tested nowhere. A viewer may not register
    one (403); an unknown reading is 404; a reading that is not a ceiling is 409
    ``not_a_ceiling``; a second forward reading that would overspend the ceiling's one budget
    is 409 ``budget_spent``."""
    from crb.server.routes.readings import load_readings

    # the XS cell is a ceiling (S1 misses three); the S cell proves S1 outright: a standard
    _prove(env, CELL_XS, s3=[True] * FIRST_LOOK, s1=[True] * 17 + [False] * 3, prefix="xs")
    _prove(env, CELL_S, s3=[True] * FIRST_LOOK, s1=[True] * FIRST_LOOK, prefix="s")
    with env.factory() as s:
        by_cell = {r.cell["size"]: r.reading_id for r in load_readings(s, ALPHA)}
    ceiling_id, standard_id = by_cell["XS"], by_cell["S"]
    body = {"repo": ALPHA, "builder": BUILDER, "model": MODEL, "provider": PROVIDER}
    login(env.client, "viewer")
    r = env.post("/readings/forward", json={**body, "promotes": ceiling_id})
    assert r.status_code == 403, r.text
    login(env.client, "operator")
    r = env.post("/readings/forward", json={**body, "promotes": "rdg_nope"})
    assert r.status_code == 404 and envelope(r)["code"] == "not_found"
    r = env.post("/readings/forward", json={**body, "promotes": standard_id})
    assert r.status_code == 409 and envelope(r)["code"] == "not_a_ceiling", r.text
    assert env.post("/readings/forward", json={**body, "promotes": ceiling_id}).status_code == 201
    r = env.post("/readings/forward", json={**body, "promotes": ceiling_id})
    assert r.status_code == 409 and envelope(r)["code"] == "budget_spent", r.text
