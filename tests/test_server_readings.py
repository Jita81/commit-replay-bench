"""``/readings``, and the map, ``/routes``, ``/value`` and the export serving per-arm readings.

Navigation
----------
What it is:   Server tests of registered readings (ADR-0026 items 2 to 5) and of the surfaces
              that read them (ADR-0025 items 1 and 8 as ADR-0026 item 6 amends them).
What it does: Registers a reading through ``POST /readings`` (operator; refused ``pool_seen``,
              an unsealed posture and a viewer), reads it back with every arm's state and the
              cell's budget spent; shows the map and ``/routes`` delivering only on the cell's
              standard arm — the ``S3`` ceiling calibrates, a cell with no reading reads "no
              proven standard" — and serving per-arm readings; shows the loop on and off as two
              arms on the map and on ``/value`` with the playbook digests as provenance; refuses
              every pooled view with 422; carries the arm, builder and model in the CSV export;
              and answers ``standard_for`` for the factory's gate.
How:          ``make_env`` with ``tests.fixtures.proven`` adding tasks, sealed rows, scores and a
              controls report; no model, no docker.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0025-routing-v2.md, docs/adr/0026-the-context-standard.md
Works with:   src/crb/server/routes/readings.py (``POST`` and ``GET /readings``, ``standard_for``),
              src/crb/server/routes/capability.py (the map and ``/routes`` per arm),
              src/crb/server/routes/value.py (per-arm cells and the readings on ``/value``),
              src/crb/server/routes/ledger.py (the CSV export's arm and class-set columns),
              tests/fixtures/proven.py (a proven cell in the seeded store)
Tested by:    this file
Touch when:   a served field of the readings or the map changes.
"""

from __future__ import annotations

import csv
import io
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from crb.server.routes.readings import standard_for
from fixtures.proven import (
    AUTHOR,
    CELL,
    S1,
    add_oracle_and_controls,
    add_rows,
    add_tasks,
    commit,
    register_via_api,
)
from fixtures.readings import SEALED
from fixtures.server_seed import ALPHA, Env, login, logout, make_env


@pytest.fixture(autouse=True)
def _no_ambient_crb_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        if key.startswith("CRB_"):
            monkeypatch.delenv(key, raising=False)


@pytest.fixture
def env(tmp_path: Path) -> Iterator[Env]:
    with make_env(tmp_path) as e:
        yield e


def _cells(env: Env, query: str = "") -> list[dict[str, Any]]:
    r = env.get(f"/capability-map?repo={ALPHA}&posture={SEALED}&by=class,size{query}")
    assert r.status_code == 200, r.text
    return [c for c in r.json()["cells"] if (c["capability_class"], c["size"]) == ("bug.fix", "XS")]


def _proven(env: Env) -> dict[str, Any]:
    add_tasks(env.factory)
    r = register_via_api(env)
    assert r.status_code == 201, r.text
    reading = r.json()
    first = reading["pool"][:20]
    add_rows(env.factory, first, arm="S3")
    add_rows(env.factory, first, arm=S1)
    add_oracle_and_controls(env.factory, first)
    return dict(reading)


def test_a_registered_reading_delivers_only_on_the_cells_standard_arm(env: Env) -> None:
    reading = _proven(env)
    assert reading["hierarchy"] == ["S3", S1] and len(reading["pool"]) == 40
    assert reading["spend"] == pytest.approx(0.02096, abs=1e-4)
    # the map's default reads each cell on its standard arm
    (cell,) = _cells(env)
    assert cell["context_arm"] == S1 and cell["route"] == "deliver", cell["reason"]
    assert cell["standard"]["standard"] == S1 and cell["standard"]["label"] == f"standard {S1}"
    assert cell["standard"]["spent"] == pytest.approx(0.02096, abs=1e-4)
    arms = {a["arm"]: a for a in cell["reading"]["arms"]}
    assert arms["S3"]["state"] == "deliver" and arms[S1]["state"] == "deliver"
    assert arms[S1]["counted"] == 20 and arms[S1]["clean"] == 20
    assert arms[S1]["ci_low"] == pytest.approx(0.8389, abs=1e-3)
    # the S3 ceiling licenses nothing
    (ceiling,) = _cells(env, "&arm=S3")
    assert ceiling["route"] == "calibrate" and ceiling["reason_code"] == "ceiling"
    # /routes reads the same, per full cell
    r = env.get(f"/routes?repo={ALPHA}&posture={SEALED}")
    assert r.status_code == 200, r.text
    (d,) = [x for x in r.json()["decisions"] if x["cell"]["size"] == "XS"]
    assert d["route"] == "deliver" and d["context_arm"] == S1 and d["standard"] == S1
    assert d["look_state"] == "deliver" and d["counted"] == 20 and d["shortfalls"] == []
    # the readings, read back, with the cell's budget spent
    got = env.get(f"/readings?repo={ALPHA}").json()
    assert got["budget"] == 0.05 and got["readings"][0]["standard"] == S1
    assert got["budgets"][0]["spent"] == pytest.approx(0.02096, abs=1e-4)
    # the factory's gate reads the same standard
    std = standard_for(env.factory, ALPHA, CELL)
    assert std is not None and std.arm == S1 and not std.ceiling
    assert std.reading_id == reading["reading_id"]


def test_a_cell_with_no_reading_reads_no_proven_standard_and_names_the_next_measurement(
    env: Env,
) -> None:
    add_tasks(env.factory)
    add_rows(env.factory, [commit(i) for i in range(5)], arm="S3")
    (cell,) = _cells(env)
    assert cell["route"] == "calibrate" and cell["reason_code"] == "reading_unregistered"
    assert cell["standard"]["standard"] is None
    assert cell["standard"]["label"] == "no proven standard"
    assert cell["standard"]["next"] == "register"
    assert standard_for(env.factory, ALPHA, CELL) is None


def test_registering_is_an_operators_act_and_refuses_what_the_rules_forbid(env: Env) -> None:
    reading = _proven(env)
    # the same commits again: already graded under an arm of the hierarchy
    again = register_via_api(env, pool=reading["pool"][:25])
    assert again.status_code == 409 and again.json()["error"]["code"] == "pool_seen"
    # a replayed arm on an unsealed posture class
    host = register_via_api(env, posture_class="local/inplace/host-env")
    assert host.status_code == 422 and host.json()["error"]["code"] == "invalid_reading"
    # a pool commit that is not a qualified task of the cell
    stray = register_via_api(env, pool=["f" * 40])
    assert stray.status_code == 422
    # a viewer reads readings but cannot register one
    logout(env.client)
    login(env.client, "viewer")
    assert env.get(f"/readings?repo={ALPHA}").status_code == 200
    assert register_via_api(env).status_code == 403


def test_the_loop_on_and_off_are_two_arms_on_the_map_and_value(env: Env) -> None:
    add_tasks(env.factory)
    off = [commit(i) for i in range(4)]
    on = [commit(i) for i in range(4, 10)]
    add_rows(env.factory, off, arm="S3", labels={"learn": "off"})
    add_rows(env.factory, on[:3], arm="S3+L", labels={"learn": "context", "learn_playbook": "p1"})
    add_rows(env.factory, on[3:], arm="S3+L", labels={"learn": "context", "learn_playbook": "p2"})
    body = env.get(f"/capability-map?repo={ALPHA}&posture={SEALED}&by=class,size").json()
    assert set(body["arms"]) >= {"S3", "S3+L"}
    (loop_off,) = _cells(env)
    assert loop_off["context_arm"] == "S3" and loop_off["n"] == 4
    (loop_on,) = _cells(env, "&arm=S3%2BL")
    assert loop_on["context_arm"] == "S3+L" and loop_on["n"] == 6
    # the playbook digests are provenance: two of them, one cell
    assert loop_on["provenance"]["learn_playbook"] == ["p1", "p2"]
    value = env.get(f"/value?repo={ALPHA}&checks=off").json()
    xs = [c for c in value["cells"] if (c["capability_class"], c["size"]) == ("bug.fix", "XS")]
    assert sorted((c["context_arm"], c["attempts"]) for c in xs) == [("S3", 4), ("S3+L", 6)]
    assert all(c["first_attempts"]["n"] == c["attempts"] for c in xs)


def test_a_pooled_view_is_refused_for_every_axis(env: Env) -> None:
    for query, code in (
        ("apparatus=all", "apparatus_pooling_refused"),
        ("arm=all", "context_arm_pooling_refused"),
        ("taxonomy=all", "class_set_pooling_refused"),
    ):
        for path in ("/capability-map", "/routes"):
            r = env.get(f"{path}?repo={ALPHA}&{query}")
            assert r.status_code == 422, (path, query, r.text)
            assert r.json()["error"]["code"] == code
    assert env.get(f"/capability-map?repo={ALPHA}&arm=S9").status_code == 422
    assert env.get(f"/capability-map?repo={ALPHA}&taxonomy=classes").status_code == 422


def test_the_ledger_export_carries_the_arm_builder_and_model_beside_each_row(env: Env) -> None:
    add_tasks(env.factory)
    add_rows(env.factory, [commit(0)], arm=f"S1@{AUTHOR}")
    r = env.get(f"/ledger/export?repo={ALPHA}&format=csv")
    assert r.status_code == 200, r.text
    rows = list(csv.DictReader(io.StringIO(r.text)))
    mine = [x for x in rows if x["task_id"] == commit(0)]
    assert mine and mine[0]["context_arm"] == f"S1@{AUTHOR}"
    assert mine[0]["taxonomy"] == "global/classes@v1"
    assert (mine[0]["builder"], mine[0]["model"]) == (CELL["builder"], CELL["model"])


def test_the_delivery_gate_reads_one_class_set_version(env: Env) -> None:
    """The map the delivery gate reads (``signed_map``) keeps one class-set version: rows an
    organisation's set classified never pool with the global vocabulary's, and a sign-off or
    a route read on one lifts nothing on the other (ADR-0026 item 9)."""
    from crb.core.capability import PROJECTION_CLASS_SIZE
    from crb.server.routes.capability import signed_map
    from crb.store.ledger import DbLedger

    add_tasks(env.factory)
    add_rows(env.factory, [commit(i) for i in range(3)], arm="S3")
    add_rows(
        env.factory,
        [commit(i) for i in range(3, 7)],
        arm="S3",
        labels={"taxonomy": "acme/classes@v1"},
    )
    rows = [r for r in DbLedger(env.factory).rows(repo=ALPHA) if r.size == "XS" and r.context_arm]
    with env.factory() as s:
        cmap, _ = signed_map(rows, PROJECTION_CLASS_SIZE, s, ALPHA)
        org, _ = signed_map(rows, PROJECTION_CLASS_SIZE, s, ALPHA, taxonomy="acme/classes@v1")
    (glob,) = [c for c in cmap.cells if c.stats is not None]
    assert glob.stats is not None and glob.stats.taxonomy == "global/classes@v1" and glob.n == 3
    (own,) = [c for c in org.cells if c.stats is not None]
    assert own.stats is not None and own.stats.taxonomy == "acme/classes@v1" and own.n == 4
    body = env.get(f"/capability-map?repo={ALPHA}&posture={SEALED}&taxonomy=acme/classes@v1")
    assert body.status_code == 200 and body.json()["taxonomies"] == [
        "acme/classes@v1",
        "global/classes@v1",
    ]
