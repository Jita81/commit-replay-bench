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
              answers ``standard_for`` for the factory's gate; shows a reading licensing only
              the checks arm and posture class it counted on (P-319), a pool picked on
              outcomes refused ``pool_not_blind``, the rule's pool over a cell already looked
              at refused ``pool_seen`` under reserved.v1 — the only attempt rule the route
              registers (P-792) — and a date cut accepted (P-320), imported
              rows never counted (P-321), an S3-only standard read as a ceiling, an unsealed
              row of the standard arm served as a ``scope_fault`` that stops it (P-795), a reading
              naming an unknown campaign refused ``campaign_unknown``, and a reading on the
              factory's cell — the forward reading included — naming any campaign refused
              ``campaign_unsupported_reading`` by both routes (DL-382); a retried
              registration and a retried forward reading — the same second or later, the same
              operator or another, two racing on SQLite and PostgreSQL — refused 409
              ``reading_exists`` naming the first, nothing written, and a store already
              holding a reading twice listing and spending it once (P-793); both routes
              refusing 409 ``lint_disabled`` while the repository's lint is off, and a
              reserved.v1 id hashing the repository's lint config while a legacy id does not
              (P-796); both routes refusing 409 ``reading_checks_overlay`` (``{overlay_arm,
              repo_arm}``, nothing written) while the loop's ``format_step`` change moves the
              checks arm off the repository block's own, on SQLite and PostgreSQL, and
              registering on the block's own arm once the block sets the key (RT2B-2).
How:          ``make_env`` with ``tests.fixtures.proven`` adding qualified tasks, sealed rows
              (each reserved for its commit first, as the worker reserves it), scores and a
              controls report; a legacy reading written as a store holds one; the race on each
              store backend (``tests.conftest_store``); no model, no docker.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0025-routing-v2.md, docs/adr/0026-the-context-standard.md
Works with:   src/crb/server/routes/readings.py (``POST`` and ``GET /readings``, ``standard_for``),
              src/crb/server/routes/capability.py (the map and ``/routes`` per arm),
              src/crb/server/routes/value.py (per-arm cells and the readings on ``/value``),
              src/crb/server/routes/ledger.py (the CSV export's arm and class-set columns),
              src/crb/server/prevention_state.py (``checks_arm_in``, ``own_checks_arm_in``),
              tests/fixtures/proven.py (a proven cell in the seeded store),
              tests/fixtures/readings.py (``format_step_in_force``, the loop's overlay)
Tested by:    this file
Touch when:   never for a new repository; a served field of the readings or the map changes.
"""

from __future__ import annotations

import contextlib
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
from fixtures.readings import (
    HYPOTHESIS,
    SEALED,
    SEALED_SETTINGS,
    SMALLEST_EFFECT,
    format_step_in_force,
    qualify_pool,
)
from fixtures.server_seed import ALPHA, Env, envelope, login, logout, make_env

try:  # the store backends: SQLite always, PostgreSQL when CRB_TEST_POSTGRES_URL is set
    from tests.conftest_store import Backend, backend, pg_schema
except ImportError:  # pragma: no cover — rootdir-relative import (pytest default)
    from conftest_store import Backend, backend, pg_schema  # noqa: F401


@pytest.fixture(autouse=True)
def _no_ambient_crb_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        if key.startswith("CRB_"):
            monkeypatch.delenv(key, raising=False)


@pytest.fixture
def env(tmp_path: Path) -> Iterator[Env]:
    # a sealed deployment: a replayed reading registers only there (P-789)
    with make_env(tmp_path, **SEALED_SETTINGS) as e:
        yield e


def _cells(env: Env, query: str = "") -> list[dict[str, Any]]:
    r = env.get(f"/capability-map?repo={ALPHA}&posture={SEALED}&by=class,size{query}")
    assert r.status_code == 200, r.text
    return [c for c in r.json()["cells"] if (c["capability_class"], c["size"]) == ("bug.fix", "XS")]


def _proven(env: Env) -> dict[str, Any]:
    add_tasks(env.factory, qualify=True)
    r = register_via_api(env)
    assert r.status_code == 201, r.text
    reading = r.json()
    assert reading["attempt_rule"] == "reserved.v1", reading
    first = reading["pool"][:20]
    add_rows(env.factory, first, arm="S3", reading=reading)
    add_rows(env.factory, first, arm=S1, reading=reading)
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
    std = standard_for(env.factory, ALPHA, CELL, checks_arm="off", posture_class=SEALED)
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
    assert standard_for(env.factory, ALPHA, CELL, checks_arm="off", posture_class=SEALED) is None


def test_registering_is_an_operators_act_and_refuses_what_the_rules_forbid(env: Env) -> None:
    _proven(env)
    # the same commits again, a second question: already graded under an arm of the hierarchy
    again = register_via_api(env, hypothesis=f"{HYPOTHESIS}, the same commits again")
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


# --- a reading licenses only the checks arm and posture class it counted on (P-319) ----------


def test_a_reading_on_the_off_checks_arm_never_licenses_the_fmt_arm(env: Env) -> None:
    """ADR-0024 (arms never pool) and ADR-0026 item 2: a reading registered on the ``off``
    checks arm counts ``off`` rows only, so it never speaks for the same cell read on ``fmt``
    — the map, /routes and the factory's gate alike."""
    _proven(env)
    add_rows(env.factory, [commit(30)], arm=S1, clean=False, labels={"checks": "fmt=1"})
    (fmt,) = _cells(env, "&checks=fmt")
    assert fmt["checks_arm"] == "fmt" and fmt["n"] == 1
    assert fmt["route"] != "deliver" and fmt["reason_code"] == "reading_unregistered", fmt
    r = env.get(f"/routes?repo={ALPHA}&posture={SEALED}&checks=fmt")
    assert r.status_code == 200, r.text
    fmt_routes = [x for x in r.json()["decisions"] if x["cell"]["size"] == "XS"]
    assert fmt_routes and all(x["route"] != "deliver" for x in fmt_routes)
    assert standard_for(env.factory, ALPHA, CELL, checks_arm="fmt", posture_class=SEALED) is None
    std = standard_for(env.factory, ALPHA, CELL, checks_arm="off", posture_class=SEALED)
    assert std is not None and std.arm == S1


def test_a_repository_switched_to_fmt_reads_its_default_map_on_fmt_unlicensed(env: Env) -> None:
    """The repository's own arm (``checks=current``) moving to ``fmt`` after an ``off``
    reading delivered leaves the default view with no proven standard on the new arm."""
    _proven(env)
    add_rows(env.factory, [commit(30)], arm=S1, clean=False, labels={"checks": "fmt=1"})
    r = env.put(f"/repos/{ALPHA}", json={"checks": {"format_step": True}})
    assert r.status_code == 200, r.text
    (cell,) = _cells(env)
    assert cell["checks_arm"] == "fmt" and cell["route"] != "deliver", cell


def test_a_reading_of_one_sealed_class_never_licenses_another(env: Env) -> None:
    """A reading counted on ``docker/copy/sealed`` never speaks for the cell read on
    ``docker/worktree/sealed``: the posture class is part of what the evidence was counted on."""
    _proven(env)
    other = "docker/worktree/sealed"
    add_rows(env.factory, [commit(30)], arm=S1, clean=False, posture_class=other)
    r = env.get(f"/capability-map?repo={ALPHA}&posture={other}&by=class,size")
    assert r.status_code == 200, r.text
    (cell,) = [
        c for c in r.json()["cells"] if (c["capability_class"], c["size"]) == ("bug.fix", "XS")
    ]
    assert cell["n"] == 1 and cell["route"] != "deliver", cell
    assert cell["reason_code"] == "reading_unregistered"
    assert standard_for(env.factory, ALPHA, CELL, checks_arm="off", posture_class=other) is None


# --- the pool is frozen by rule, never picked on outcomes (P-320) ------------------------------


def test_a_pool_chosen_on_outcomes_is_refused(env: Env) -> None:
    """ADR-0026 item 2 (DL-097): the pool is every qualified commit of the cell, or every one
    authored since a date the operator names — never a list. Grading the commits under the
    descriptive ``A0`` arm first and registering only the ones that passed is refused
    ``pool_not_blind``. Nor can the look be laundered through the rule: every reading
    ``POST /readings`` registers is reserved.v1 (P-792), which refuses ``pool_seen`` for a
    pool commit with any 2.4 row, the ``A0`` look included, so the rule's own pool here is
    refused as well, and nothing is written. On a cell nothing has looked at, the rule's own
    pool is accepted and recorded (:func:`test_registering_on_a_sealed_deployment_succeeds`)."""
    ids = add_tasks(env.factory, qualify=True)
    add_rows(env.factory, ids[:20], arm="A0", mode="blind")
    add_rows(env.factory, ids[20:], arm="A0", mode="blind", clean=False)
    picked = register_via_api(env, pool=ids[:20])
    assert picked.status_code == 422, picked.text
    assert picked.json()["error"]["code"] == "pool_not_blind"
    whole = register_via_api(env)
    assert whole.status_code == 409, whole.text
    err = envelope(whole)
    assert err["code"] == "pool_seen" and err["detail"]["n"] == len(ids), err
    assert set(err["detail"]["commits"]) <= set(ids)
    assert _registered_events(env) == 0


def test_a_pool_may_start_at_a_date_the_operator_names(env: Env) -> None:
    """A date cut is blind to outcomes (ADR-0026's held-out rule: "commits made since that
    measurement"): the pool is every qualified commit authored at or after it."""
    old = add_tasks(env.factory, 5, prefix="old", qualify=True)
    new = add_tasks(
        env.factory, 25, prefix="new", authored="2026-09-01T00:00:00+00:00", qualify=True
    )
    r = register_via_api(env, since="2026-08-15T00:00:00+00:00")
    assert r.status_code == 201, r.text
    assert sorted(r.json()["pool"]) == sorted(new) and not set(old) & set(r.json()["pool"])
    assert r.json()["pool_rule"] == "qualified-since:2026-08-15T00:00:00+00:00"
    bad = register_via_api(env, since="last tuesday")
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "invalid_reading"


# --- imported rows are history: a reading counts only what this deployment graded (P-321) -----


def test_rows_imported_through_the_ledger_never_count_toward_a_reading(env: Env) -> None:
    """ADR-0026 item 2: a reading counts first attempts GRADED after its registration in the
    sealed posture. A row an admin imports keeps every label it was exported with — posture,
    builder executor, context arm, a ``created`` time after the registration — so it is
    stamped ``imported`` on the way in and a reading never counts it, whether or not it
    carried a source hash."""
    import json

    from fixtures.readings import sealed_row

    add_tasks(env.factory, qualify=True)
    r = register_via_api(env)
    assert r.status_code == 201, r.text
    first = r.json()["pool"][:20]
    forged = [
        sealed_row(c, arm=arm, created="2099-01-01T00:00:00+00:00", repo=ALPHA, cell=dict(CELL))
        for arm in ("S3", S1)
        for c in first
    ]
    body = "".join(json.dumps(x.to_dict(), sort_keys=True) + "\n" for x in forged).encode()
    got = env.post("/ledger/import", files={"file": ("forged.jsonl", body)})
    assert got.status_code == 200 and got.json()["imported"] == 40, got.text
    add_oracle_and_controls(env.factory, first)
    # the licensing reading (``apparatus=current``) counts measured rows only (EI-2): a cell
    # of imported rows is not measured here at all, so it cannot route deliver
    assert _cells(env) == []
    # read as history, under its named version, the cell is shown — and the reading counts
    # none of the imported rows either (P-321)
    (cell,) = _cells(env, "&apparatus=2.4")
    assert cell["route"] != "deliver", cell
    assert cell["reason_code"] == "look_pending"
    arms = {a["arm"]: a for a in cell["reading"]["arms"]}
    assert arms["S3"]["counted"] == 0


def test_a_standard_found_on_s3_alone_reads_ceiling_forward_unvalidated(env: Env) -> None:
    """product.value.111: S3 delivers and S1 misses three — the cell's only proven arm is the
    ceiling, shown as ``ceiling S3, forward-unvalidated`` and never as a standard."""
    add_tasks(env.factory, qualify=True)
    r = register_via_api(env)
    assert r.status_code == 201, r.text
    reading = r.json()
    first = reading["pool"][:20]
    add_rows(env.factory, first, arm="S3", reading=reading)
    add_rows(env.factory, first[:3], arm=S1, clean=False, reading=reading)
    add_rows(env.factory, first[3:], arm=S1, reading=reading)
    add_oracle_and_controls(env.factory, first)
    (cell,) = _cells(env)
    assert cell["standard"]["label"] == "ceiling S3, forward-unvalidated"
    assert cell["standard"]["ceiling"] is True and cell["standard"]["standard"] == "S3"
    assert cell["route"] != "deliver"


def test_an_unsealed_row_of_the_standard_arm_is_served_as_a_scope_fault(env: Env) -> None:
    """P-795: a row of the reading's ``S1`` arm that records ``builder_executor`` ``host`` in
    the sealed posture class is no other reading's row — its writer failed to label it. The
    reading dropped it in silence, a later clean row stood in for the commit, and the cell
    delivered on a miss it never read. Now the map serves the arm ``undecided`` with the
    commit in ``scope_faults``, and the cell's only proven arm is the ``S3`` ceiling. Under
    reserved.v1 the unsealed row is the commit's reserved attempt, and the stand-in — a
    later clean row of a run that reserved nothing — is invisible to the reading (P-792)."""
    add_tasks(env.factory, qualify=True)
    r = register_via_api(env)
    assert r.status_code == 201, r.text
    reading = r.json()
    first = reading["pool"][:20]
    add_rows(env.factory, first, arm="S3", reading=reading)
    add_rows(env.factory, first[:1], arm=S1, clean=False, builder_executor="host", reading=reading)
    add_rows(env.factory, first[:1], arm=S1, run_id="stand-in")  # the stand-in
    add_rows(env.factory, first[1:], arm=S1, reading=reading)  # the other nineteen
    add_oracle_and_controls(env.factory, first)
    (cell,) = _cells(env)
    arms = {a["arm"]: a for a in cell["reading"]["arms"]}
    assert arms[S1]["state"] == "undecided", arms[S1]
    assert (arms[S1]["scope_faults"], arms[S1]["unsealed_dropped"]) == ([first[0]], 1)
    assert (arms["S3"]["scope_faults"], arms["S3"]["unsealed_dropped"]) == ([], 0)
    assert cell["standard"]["ceiling"] is True and cell["standard"]["standard"] == "S3"
    assert cell["route"] != "deliver"


def test_a_reserved_row_off_the_checks_arm_is_served_as_a_scope_fault(env: Env) -> None:
    """RT2B-1 (round 6): a reserved row built on ``fmt`` for a reading frozen ``off`` carries
    the reading's reservation, so it is no other reading's row and no miss. ``GET /readings``
    serves each such commit ``reason`` ``scope_fault`` with ``scope`` ``checks_arm``, names it
    in the arm's ``scope_faults`` (none counted unsealed), and the arm and the reading read
    ``undecided``: no standard, no ceiling, and the cell does not deliver."""
    add_tasks(env.factory, qualify=True)
    r = register_via_api(env)
    assert r.status_code == 201, r.text
    reading = r.json()
    assert reading["checks_arm"] == "off"
    first = reading["pool"][:20]
    off = [first[i] for i in (2, 9, 15)]
    add_rows(env.factory, [c for c in first if c not in off], arm="S3", reading=reading)
    add_rows(env.factory, off, arm="S3", labels={"checks": "fmt=1"}, reading=reading)
    add_oracle_and_controls(env.factory, first)
    (served,) = env.get(f"/readings?repo={ALPHA}").json()["readings"]
    s3 = {a["arm"]: a for a in served["arms"]}["S3"]
    assert s3["state"] == "undecided" and served["state"] == "undecided", s3
    assert (sorted(s3["scope_faults"]), s3["unsealed_dropped"]) == (sorted(off), 0)
    faulted = {c["commit"]: (c["reason"], c["scope"]) for c in s3["commits"] if c["scope"]}
    assert faulted == dict.fromkeys(off, ("scope_fault", "checks_arm"))
    assert served["standard"] is None and served["ceiling"] is False
    (cell,) = _cells(env)
    assert cell["route"] != "deliver", cell


# --- a reading states its hypothesis and smallest effect before any row (P-787) --------------


def _registered_events(env: Env) -> int:
    from sqlalchemy import func, select

    from crb.core.reading import READING_EVENT_ACTION
    from crb.store.models import Event

    with env.factory() as s:
        return int(
            s.execute(
                select(func.count()).select_from(Event).where(Event.action == READING_EVENT_ACTION)
            ).scalar_one()
        )


@pytest.mark.parametrize(
    "question",
    [
        {"smallest_effect": SMALLEST_EFFECT},  # no hypothesis
        {"hypothesis": "   ", "smallest_effect": SMALLEST_EFFECT},  # a blank one
        {"hypothesis": HYPOTHESIS},  # no smallest effect
        {"hypothesis": HYPOTHESIS, "smallest_effect": 0},
        {"hypothesis": HYPOTHESIS, "smallest_effect": 1.5},
    ],
    ids=["missing", "blank", "missing-effect", "effect-0", "effect-1.5"],
)
def test_a_reading_without_its_hypothesis_or_smallest_effect_is_refused_422(
    env: Env, question: dict[str, Any]
) -> None:
    """Wave 3 pre-run (Q-24): a reading says what it tests and the smallest effect that would
    matter before its first attempt — a registration without either, with a blank hypothesis
    or with an effect outside (0, 1] is refused 422 and writes no event."""
    from fixtures.proven import add_tasks as _add

    _add(env.factory)
    body = {
        "repo": ALPHA,
        "cell": CELL,
        "hierarchy": ["S3", S1],
        "posture_class": SEALED,
        "author_model": AUTHOR,
        **question,
    }
    r = env.post("/readings", json=body)
    assert r.status_code == 422, r.text
    assert envelope(r)["code"] == "validation_error"
    assert _registered_events(env) == 0


def test_hypothesis_and_smallest_effect_are_stored_and_served(env: Env) -> None:
    add_tasks(env.factory, qualify=True)
    r = register_via_api(env, hypothesis=f"  {HYPOTHESIS}  ", smallest_effect=0.05)
    assert r.status_code == 201, r.text
    assert (r.json()["hypothesis"], r.json()["smallest_effect"]) == (HYPOTHESIS, 0.05)
    (served,) = env.get(f"/readings?repo={ALPHA}").json()["readings"]
    assert served["reading_id"] == r.json()["reading_id"]
    assert (served["hypothesis"], served["smallest_effect"]) == (HYPOTHESIS, 0.05)


def test_a_legacy_reading_without_the_fields_still_verifies_and_is_served(env: Env) -> None:
    """A reading registered before P-787 carries neither field: its body omits both, so its
    id re-hashes as it always did and it is served with an empty hypothesis."""
    from crb.core.reading import Reading
    from fixtures.proven import write_reading

    ids = add_tasks(env.factory)
    legacy = write_reading(env.factory, ids, hierarchy=("S3", S1))
    assert "hypothesis" not in legacy.body() and "smallest_effect" not in legacy.body()
    assert Reading.from_dict(legacy.to_dict()).verify()
    (served,) = env.get(f"/readings?repo={ALPHA}").json()["readings"]
    assert served["reading_id"] == legacy.reading_id
    assert (served["hypothesis"], served["smallest_effect"]) == ("", None)


def test_the_hypothesis_is_inside_the_hash(env: Env) -> None:
    """A stored reading whose hypothesis was edited after registration no longer re-hashes:
    ``verify`` fails and ``load_readings`` leaves it out — the question cannot move after
    the answer is read."""
    from crb.core.reading import READING_EVENT_ACTION, Reading
    from crb.server.routes.readings import load_readings
    from crb.store.events import append_event

    add_tasks(env.factory, qualify=True)
    r = register_via_api(env)
    assert r.status_code == 201, r.text
    edited = {**r.json(), "hypothesis": "the richer arm is no better than the leaner one"}
    assert not Reading.from_dict(edited).verify()
    moved = {**r.json(), "smallest_effect": 0.5}
    assert not Reading.from_dict(moved).verify()
    with env.factory() as s:
        assert [x.reading_id for x in load_readings(s, ALPHA)] == [r.json()["reading_id"]]
    for payload in (edited, moved):
        append_event(
            env.factory,
            trace_id=f"readings:{ALPHA}",
            stage="system",
            action=READING_EVENT_ACTION,
            repo=ALPHA,
            payload=payload,
        )
    with env.factory() as s:
        kept = load_readings(s, ALPHA)
    assert [x.reading_id for x in kept] == [r.json()["reading_id"]]
    assert kept[0].hypothesis == HYPOTHESIS


def test_a_forward_reading_without_them_is_refused_422(env: Env) -> None:
    body = {"repo": ALPHA, "promotes": "rdg_" + "0" * 24, "builder": "b", "model": "m"}
    for question in ({}, {"hypothesis": HYPOTHESIS}, {"smallest_effect": SMALLEST_EFFECT}):
        r = env.post("/readings/forward", json={**body, **question})
        assert r.status_code == 422, r.text
        assert envelope(r)["code"] == "validation_error"
    # with both, the request reaches the route: an unknown ceiling is 404
    r = env.post(
        "/readings/forward", json={**body, "hypothesis": HYPOTHESIS, "smallest_effect": 0.1}
    )
    assert r.status_code == 404, r.text
    assert _registered_events(env) == 0


# --- a replayed reading registers only on a sealed deployment (P-789) -----------------------


def test_registering_on_a_host_builder_is_refused(tmp_path: Path) -> None:
    """The posture class reads the sandbox alone, so a docker sandbox with a host builder
    still names a sealed class; the deployment itself must be sealed — the builder too."""
    with make_env(tmp_path, sandbox={"executor": "docker"}) as e:
        assert e.settings.posture()["builder_executor"] == "host"
        add_tasks(e.factory)
        r = register_via_api(e)
        assert r.status_code == 422, r.text
        err = envelope(r)
        assert err["code"] == "invalid_reading"
        assert "sealed deployment" in err["message"]
        assert err["detail"] == {"sandbox_executor": "docker", "builder_executor": "host"}
        assert _registered_events(e) == 0


def test_registering_on_a_sealed_deployment_succeeds(env: Env) -> None:
    """On a sealed deployment a cell nothing has looked at registers: the pool is the rule's
    own (every qualified commit of the cell), recorded with its rule, under ``reserved.v1``
    — the only attempt rule ``POST /readings`` registers (P-792, DL-385)."""
    assert env.settings.posture()["sealed"] is True
    ids = add_tasks(env.factory, qualify=True)
    r = register_via_api(env)
    assert r.status_code == 201, r.text
    assert sorted(r.json()["pool"]) == sorted(ids)
    assert r.json()["pool_rule"] == "all-qualified"
    assert (r.json()["attempt_rule"], r.json()["max_reruns"]) == ("reserved.v1", 0)
    assert _registered_events(env) == 1


# --- a reading names, from birth, the campaign its runs spend under (DL-382) ----------------

#: The Wave 3 campaign as ``POST /campaigns`` takes it (G-957).
WAVE3 = {
    "name": "wave-3",
    "ceiling_gbp": 80,
    "released_gbp": 40,
    "rate_usd_per_gbp": 1.35,
    "decision": "DECISION 8 (2026-10-11): stage 1 £40 yes",
}


def _campaign(env: Env, **kw: Any) -> str:
    r = env.post("/campaigns", json={**WAVE3, **kw})
    assert r.status_code == 201, r.text
    return str(r.json()["campaign_id"])


def test_a_reading_names_its_campaign_inside_its_hash(env: Env) -> None:
    """A reading is immutable from birth, so the campaign its runs spend under is named at
    registration and hashed into its id: served back on ``POST`` and ``GET``, and a stored
    record whose campaign was edited or dropped no longer re-hashes."""
    from crb.core.reading import Reading

    add_tasks(env.factory, qualify=True)
    cid = _campaign(env)
    r = register_via_api(env, campaign_id=cid)
    assert r.status_code == 201, r.text
    assert r.json()["campaign_id"] == cid
    (served,) = env.get(f"/readings?repo={ALPHA}").json()["readings"]
    assert (served["reading_id"], served["campaign_id"]) == (r.json()["reading_id"], cid)
    assert Reading.from_dict(r.json()).verify()
    moved = {**r.json(), "campaign_id": "cmp_" + "e" * 24}
    assert not Reading.from_dict(moved).verify()
    dropped = {k: v for k, v in r.json().items() if k != "campaign_id"}
    assert not Reading.from_dict(dropped).verify()


def test_a_legacy_reading_under_no_campaign_keeps_its_id_and_verifies(env: Env) -> None:
    from crb.core.reading import Reading
    from fixtures.proven import write_reading

    ids = add_tasks(env.factory)
    legacy = write_reading(env.factory, ids, hierarchy=("S3", S1))
    assert "campaign_id" not in legacy.body() and legacy.campaign_id == ""
    assert Reading.from_dict(legacy.to_dict()).verify()
    named = write_reading(env.factory, ids, hierarchy=("S3", S1), campaign_id="cmp_" + "c" * 24)
    assert named.body()["campaign_id"] == "cmp_" + "c" * 24
    assert named.reading_id != legacy.reading_id
    (served, _) = env.get(f"/readings?repo={ALPHA}").json()["readings"]
    assert (served["reading_id"], served["campaign_id"]) == (legacy.reading_id, "")


def test_a_reading_naming_an_unknown_campaign_is_refused_with_no_event(env: Env) -> None:
    """``campaign_unknown`` — the code ``POST /runs`` answers for an unknown campaign — before
    anything is written: a reading whose runs could never be admitted is never registered."""
    add_tasks(env.factory)
    unknown = "cmp_" + "a" * 24
    r = register_via_api(env, campaign_id=unknown)
    assert r.status_code == 404, r.text
    err = envelope(r)
    assert err["code"] == "campaign_unknown" and err["detail"] == {"campaign_id": unknown}
    bad = register_via_api(env, campaign_id="wave-3")
    assert bad.status_code == 422 and envelope(bad)["code"] == "validation_error"
    assert _registered_events(env) == 0


#: The refusal both routes answer for a reading on the factory's cell that names a campaign.
UNSUPPORTED = "campaign_unsupported_reading"


def test_a_forward_reading_naming_a_campaign_is_refused_422_with_no_event(env: Env) -> None:
    """DL-382: a forward reading counts calibration builds — factory runs, which carry no
    ``reading_id``, so nothing ties them to the reading and no submit gate requires them to
    be filed under its campaign. Naming a campaign, known or not, is refused 422
    ``campaign_unsupported_reading`` before anything is read or written; without one, the
    same body is answered on its merits (here, 404 for a reading the repository does not
    have)."""
    add_tasks(env.factory)
    body = {
        "repo": ALPHA,
        "promotes": "rdg_" + "0" * 24,
        "builder": "b",
        "model": "m",
        "hypothesis": HYPOTHESIS,
        "smallest_effect": SMALLEST_EFFECT,
    }
    for cid in (_campaign(env), "cmp_" + "a" * 24):
        fwd = env.post("/readings/forward", json={**body, "campaign_id": cid})
        assert fwd.status_code == 422, fwd.text
        err = envelope(fwd)
        assert err["code"] == UNSUPPORTED, err
        assert err["detail"] == {"campaign_id": cid, "process_step": "factory"}
    assert _registered_events(env) == 0
    plain = env.post("/readings/forward", json=body)
    assert plain.status_code == 404 and envelope(plain)["code"] == "not_found", plain.text


def test_a_reading_on_the_factorys_cell_naming_a_campaign_is_refused_422_with_no_event(
    env: Env,
) -> None:
    """DL-382, one rule for both routes: a reading on the factory's cell may name no campaign.
    Its runs are factory runs, which carry no ``reading_id``, so nothing ties them to the
    reading and no submit gate requires them to be filed under its campaign; ``POST /readings``
    refuses its ``campaign_id`` with the forward route's 422 — same code, same reason —
    before anything is written; without one, the same reading registers."""
    add_tasks(env.factory, qualify=True)
    cid = _campaign(env)
    fcell = {**CELL, "process_step": "factory"}
    r = register_via_api(env, hierarchy=("S2",), cell=fcell, campaign_id=cid)
    assert r.status_code == 422, r.text
    err = envelope(r)
    assert err["code"] == UNSUPPORTED, err
    assert err["detail"] == {"campaign_id": cid, "process_step": "factory"}
    assert _registered_events(env) == 0
    fwd = {"repo": ALPHA, "promotes": "rdg_" + "0" * 24, "builder": "b", "model": "m"}
    fwd |= {"hypothesis": HYPOTHESIS, "smallest_effect": SMALLEST_EFFECT, "campaign_id": cid}
    assert envelope(env.post("/readings/forward", json=fwd))["message"] == err["message"]
    plain = register_via_api(env, hierarchy=("S2",), cell=fcell)
    assert plain.status_code == 201, plain.text
    assert _registered_events(env) == 1


# --- a retried registration is the same reading once (P-793) ---------------------------------

#: The first registration's second, and a retry's seven seconds later: ``registered_at`` is in
#: the reading's hash at whole seconds, so only a retry in the same second re-hashes to the
#: first reading's id — the refusal reads the reading's content, not its id alone.
FIRST_AT = "2026-10-11T12:00:00+00:00"
RETRY_AT = "2026-10-11T12:00:07+00:00"


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """The registration's clock (``crb.core.reading.utc_now_iso``), set by the test."""
    now = {"at": FIRST_AT}
    monkeypatch.setattr("crb.core.reading.utc_now_iso", lambda: now["at"])
    return now


RETRIES = [
    pytest.param(FIRST_AT, "", id="same-second"),
    pytest.param(RETRY_AT, "", id="seconds-later"),
    pytest.param(FIRST_AT, "operator", id="another-operator"),
]


@pytest.mark.parametrize(("retry_at", "role"), RETRIES)
def test_a_retried_registration_is_refused_reading_exists_and_writes_nothing(
    env: Env, clock: dict[str, str], retry_at: str, role: str
) -> None:
    """The same body sent again — a retried request, by the same operator or another, in the
    same second or later — is refused 409 ``reading_exists`` naming the reading already
    registered, and writes nothing: ``GET /readings`` lists the reading once and the cell's
    budget reads one reading's spend. Another question on the same cell is not a retry."""
    add_tasks(env.factory, qualify=True)
    first = register_via_api(env)
    assert first.status_code == 201, first.text
    rid = first.json()["reading_id"]
    clock["at"] = retry_at
    if role:
        logout(env.client)
        login(env.client, role)
    retry = register_via_api(env)
    assert retry.status_code == 409, retry.text
    err = envelope(retry)
    assert err["code"] == "reading_exists", err
    assert err["detail"] == {"reading_id": rid}
    assert _registered_events(env) == 1
    served = env.get(f"/readings?repo={ALPHA}").json()
    assert [o["reading_id"] for o in served["readings"]] == [rid]
    (cell,) = served["budgets"]
    assert cell["readings"] == 1
    assert cell["spent"] == pytest.approx(first.json()["spend"], abs=1e-6)
    other = register_via_api(env, hypothesis=f"{HYPOTHESIS}, a second question")
    assert other.status_code == 201, other.text
    assert _registered_events(env) == 2


@pytest.mark.parametrize("retry_at", ["2026-10-11T12:01:00+00:00", "2026-10-11T12:01:07+00:00"])
def test_a_retried_forward_registration_is_refused_reading_exists(
    env: Env, clock: dict[str, str], retry_at: str
) -> None:
    """``POST /readings/forward`` sent twice with the same body is refused 409
    ``reading_exists`` naming the forward reading, before the ceiling's budget is read: the
    retry is the same reading, never a second one that would overspend the cell."""
    from fixtures.server_seed import BUILDER, MODEL, PROVIDER

    add_tasks(env.factory, qualify=True)
    r = register_via_api(env)
    assert r.status_code == 201, r.text
    first = r.json()["pool"][:20]
    add_rows(env.factory, first, arm="S3", reading=r.json())
    add_rows(env.factory, first[:3], arm=S1, clean=False, reading=r.json())
    add_rows(env.factory, first[3:], arm=S1, reading=r.json())
    add_oracle_and_controls(env.factory, first)
    body = {
        "repo": ALPHA,
        "promotes": r.json()["reading_id"],
        "builder": BUILDER,
        "model": MODEL,
        "provider": PROVIDER,
        "hypothesis": HYPOTHESIS,
        "smallest_effect": SMALLEST_EFFECT,
    }
    clock["at"] = "2026-10-11T12:01:00+00:00"
    fwd = env.post("/readings/forward", json=body)
    assert fwd.status_code == 201, fwd.text
    clock["at"] = retry_at
    retry = env.post("/readings/forward", json=body)
    assert retry.status_code == 409, retry.text
    err = envelope(retry)
    assert err["code"] == "reading_exists", err
    assert err["detail"] == {"reading_id": fwd.json()["reading_id"]}
    assert _registered_events(env) == 2
    served = env.get(f"/readings?repo={ALPHA}").json()["readings"]
    assert [o["reading_id"] for o in served] == [r.json()["reading_id"], fwd.json()["reading_id"]]


def test_a_store_holding_a_duplicate_registration_counts_it_once(env: Env) -> None:
    """A store written before P-793 may hold one reading's event twice (a retried request
    answered 201): every reader keeps the first per ``reading_id``, so ``GET /readings`` lists
    it once, the cell's budget reads one reading's spend, and a second question still fits
    beside it."""
    from crb.core.reading import READING_EVENT_ACTION
    from crb.store.events import append_event

    add_tasks(env.factory, qualify=True)
    r = register_via_api(env)
    assert r.status_code == 201, r.text
    payload = r.json()
    for _ in range(2):
        append_event(
            env.factory,
            trace_id=f"readings:{ALPHA}",
            stage="system",
            action=READING_EVENT_ACTION,
            repo=ALPHA,
            payload=payload,
        )
    assert _registered_events(env) == 3
    served = env.get(f"/readings?repo={ALPHA}").json()
    assert [o["reading_id"] for o in served["readings"]] == [payload["reading_id"]]
    (cell,) = served["budgets"]
    assert cell["readings"] == 1
    assert f"{cell['spent']:.2%}" == "2.10%"
    assert cell["spent"] == pytest.approx(payload["spend"], abs=1e-6)
    other = register_via_api(env, hypothesis=f"{HYPOTHESIS}, a second question")
    assert other.status_code == 201, other.text


def test_two_racing_retries_register_one_reading_on_each_store(
    backend: Backend, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The refusal reads the readings already registered under the events store's write
    lock — SQLite's ``BEGIN IMMEDIATE`` and PostgreSQL's advisory lock alike — so two copies
    of one registration sent at once write one reading: one answers 201, the other 409
    ``reading_exists`` naming it."""
    import threading

    from fastapi.testclient import TestClient

    from crb.server.app import create_app
    from crb.server.deps import ApiError, Principal
    from crb.server.routes.readings import ReadingIn, register_reading
    from crb.store.db import init_db
    from fixtures.server_seed import add_users, make_settings, seed

    monkeypatch.setattr("crb.core.reading.utc_now_iso", lambda: FIRST_AT)
    init_db(backend.engine)
    seed(backend.factory)
    add_users(backend.factory)
    add_tasks(backend.factory, qualify=True)
    settings = make_settings(tmp_path, **SEALED_SETTINGS)
    body = ReadingIn.model_validate(
        {
            "repo": ALPHA,
            "cell": CELL,
            "hierarchy": ["S3", S1],
            "posture_class": SEALED,
            "author_model": AUTHOR,
            "hypothesis": HYPOTHESIS,
            "smallest_effect": SMALLEST_EFFECT,
        }
    )
    barrier = threading.Barrier(2)
    outcomes: list[tuple[str, str]] = []
    lock = threading.Lock()

    def send(actor: str) -> None:
        who = Principal(id=actor, display_name=actor, email="", role="operator", issuer="local")
        barrier.wait()
        with backend.factory() as db:
            try:
                got = (
                    "201",
                    str(register_reading(body, who, db, backend.factory, settings)["reading_id"]),
                )
            except ApiError as exc:
                got = (exc.code, str(exc.detail.get("reading_id", "")))
        with lock:
            outcomes.append(got)

    threads = [threading.Thread(target=send, args=(a,)) for a in ("op-a", "op-b")]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert sorted(code for code, _ in outcomes) == ["201", "reading_exists"], outcomes
    assert len({rid for _, rid in outcomes}) == 1, outcomes
    with TestClient(create_app(settings, backend.factory)) as client:
        login(client, "operator")
        served = client.get(f"/api/v1/readings?repo={ALPHA}").json()
    assert [o["reading_id"] for o in served["readings"]] == [outcomes[0][1]]
    (cell,) = served["budgets"]
    assert cell["readings"] == 1


# --- an operator's lint switch never reshapes what a reading counts (P-796) ------------------


def _set_lint(env: Env, lint: dict[str, Any]) -> None:
    """Store ``lint`` as the repository's ``RepoConfig.lint`` — what an operator's config edit
    writes and the next registration, submit and claim read."""
    from crb.store.models import Repo

    with env.factory() as s:
        repo = s.get(Repo, ALPHA)
        assert repo is not None
        repo.config_json = {**dict(repo.config_json or {}), "lint": dict(lint)}
        s.commit()


def test_registering_with_lint_disabled_is_refused_409(env: Env, clock: dict[str, str]) -> None:
    """P-796, the Wave 3 red team's F7 by code reading: a commit whose row was graded with belt
    5 switched off leaves a legacy reading's pool ``lint_disabled``, and the operator's switch
    can be thrown after outcomes are seen, so it chose which commits leave. Now a repository
    whose lint is disabled (``RepoConfig.lint = {"disabled": true}``) registers no reading:
    ``POST /readings`` (its reserved.v1 default and the rule named outright alike) and ``POST
    /readings/forward`` are refused 409 ``lint_disabled`` naming the repository and the
    reason, and nothing is written (each answered 201 before the change)."""
    from fixtures.server_seed import BUILDER, MODEL, PROVIDER

    add_tasks(env.factory, qualify=True)
    off = {"repo": ALPHA, "reason": "disabled_by_config"}
    _set_lint(env, {"disabled": True})
    for rule in ({}, {"attempt_rule": "reserved.v1"}):
        r = register_via_api(env, **rule)
        assert r.status_code == 409, (rule, r.text)
        err = envelope(r)
        assert (err["code"], err["detail"]) == ("lint_disabled", off), err
    assert _registered_events(env) == 0

    _set_lint(env, {})
    r = register_via_api(env)
    assert r.status_code == 201, r.text
    first = r.json()["pool"][:20]
    add_rows(env.factory, first, arm="S3", reading=r.json())
    add_rows(env.factory, first[:3], arm=S1, clean=False, reading=r.json())
    add_rows(env.factory, first[3:], arm=S1, reading=r.json())
    add_oracle_and_controls(env.factory, first)
    body = {
        "repo": ALPHA,
        "promotes": r.json()["reading_id"],
        "builder": BUILDER,
        "model": MODEL,
        "provider": PROVIDER,
        "hypothesis": HYPOTHESIS,
        "smallest_effect": SMALLEST_EFFECT,
    }
    _set_lint(env, {"disabled": True})
    fwd = env.post("/readings/forward", json=body)
    assert fwd.status_code == 409, fwd.text
    err = envelope(fwd)
    assert (err["code"], err["detail"]) == ("lint_disabled", off), err
    assert _registered_events(env) == 1
    _set_lint(env, {})
    assert env.post("/readings/forward", json=body).status_code == 201
    assert _registered_events(env) == 2


def test_a_reserved_reading_id_hashes_the_lint_config(
    tmp_path: Path, clock: dict[str, str]
) -> None:
    """A reserved.v1 reading names the lint configuration it was registered under (P-796): the
    same registration on two stores whose repository lints differently gets two ids, the
    stored ``lint_digest`` is the sha256 of the canonical lint block, and a record whose
    digest was edited no longer re-hashes. A legacy reading (written as a store holds one;
    ``POST /readings`` registers reserved.v1 only, P-792) hashes no lint: its id is the same
    on both stores and its record carries no ``lint_digest``."""
    from crb.core.evidence import canonical_json, sha256_text
    from crb.core.reading import Reading
    from fixtures.proven import write_reading

    lints: dict[str, dict[str, Any]] = {"plain": {}, "ruff": {"command": ["ruff", "check"]}}
    got: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    for name, lint in lints.items():
        (tmp_path / name).mkdir()
        with make_env(tmp_path / name, **SEALED_SETTINGS) as store:
            _set_lint(store, lint)
            ids = add_tasks(store.factory)
            qualify_pool(store.factory, ALPHA, ids)
            legacy = write_reading(store.factory, ids, hierarchy=("S3", S1))
            reserved = register_via_api(store, attempt_rule="reserved.v1")
            assert reserved.status_code == 201, reserved.text
            got[name] = (legacy.to_dict(), reserved.json())
    (legacy_a, reserved_a), (legacy_b, reserved_b) = got["plain"], got["ruff"]
    assert legacy_a["reading_id"] == legacy_b["reading_id"]
    assert "lint_digest" not in legacy_a and "lint_digest" not in legacy_b
    assert reserved_a["reading_id"] != reserved_b["reading_id"]
    for name, (_, reserved) in got.items():
        assert reserved["lint_digest"] == sha256_text(canonical_json(lints[name])), name
        assert Reading.from_dict(reserved).verify()
        moved = {**reserved, "lint_digest": sha256_text(canonical_json({"disabled": True}))}
        assert not Reading.from_dict(moved).verify()
        dropped = {k: v for k, v in reserved.items() if k != "lint_digest"}
        assert not Reading.from_dict(dropped).verify()


# --- a reading is never frozen through the loop's overlay (RT2B-2, round 6) ------------------


@contextlib.contextmanager
def _api_on(backend: Backend, home: Path) -> Iterator[Env]:
    """The app on ``backend``'s store: sealed (P-789), seeded, an operator logged in."""
    from fastapi.testclient import TestClient

    from crb.server.app import create_app
    from crb.store.db import init_db
    from fixtures.server_seed import add_users, make_settings, seed

    home.mkdir(exist_ok=True)
    init_db(backend.engine)
    info = seed(backend.factory)
    add_users(backend.factory)
    settings = make_settings(home, **SEALED_SETTINGS)
    with TestClient(create_app(settings, backend.factory)) as client:
        login(client, "operator")
        yield Env(client=client, factory=backend.factory, info=info, settings=settings)


def _set_checks(env: Env, checks: dict[str, Any]) -> None:
    """ALPHA's own ``checks`` block set through ``PUT /repos/{name}`` (operator) — DL-410's
    config edit before step 4: a key the team sets wins over the loop's overlay."""
    r = env.put(f"/repos/{ALPHA}", json={"checks": dict(checks)})
    assert r.status_code == 200, r.text


OVERLAY_MOVED = {"overlay_arm": "fmt", "repo_arm": "off"}


def test_post_readings_refuses_when_the_loop_overlay_moves_the_checks_arm(
    backend: Backend, tmp_path: Path
) -> None:
    """RT2B-2 (round 6): with the learning switch at config, the loop's ``format_step`` change
    in force and the repository's ``checks`` block silent on the key, the arm a run that
    learns resolves is ``fmt`` while the re-measurement plan's runs (``learning: off``)
    resolve the block's own ``off``. ``POST /readings`` froze the overlay's ``fmt`` (201), so
    every S3, A0 and S1 run of the plan would halt ``reading_checks_arm_mismatch``. It is now
    refused 409 ``reading_checks_overlay`` naming both arms, and nothing is written — on
    SQLite and PostgreSQL alike."""
    with _api_on(backend, tmp_path / "home") as env:
        add_tasks(env.factory, qualify=True)
        format_step_in_force(env.factory, ALPHA)
        r = register_via_api(env)
        assert r.status_code == 409, r.text
        err = envelope(r)
        assert (err["code"], err["detail"]) == ("reading_checks_overlay", OVERLAY_MOVED), err
        assert _registered_events(env) == 0
        assert env.get(f"/readings?repo={ALPHA}").json()["readings"] == []


def test_a_reading_registers_on_the_blocks_own_arm_when_the_overlay_does_not_move_it(
    backend: Backend, tmp_path: Path
) -> None:
    """The pins beside RT2B-2: with no loop change in force the reading freezes the block's
    own arm, ``off`` by default and ``fmt`` when the team's block sets ``format_step`` (the
    refusal reads a difference, never an arm); and with the loop's change in force, the team's
    block setting ``format_step: false`` (DL-410) wins over the overlay, so the two arms agree
    and the reading registers on ``off``."""
    with _api_on(backend, tmp_path / "home") as env:
        add_tasks(env.factory, qualify=True)
        _set_checks(env, {"format_step": True})
        r = register_via_api(env)
        assert r.status_code == 201, r.text
        assert r.json()["checks_arm"] == "fmt"
        _set_checks(env, {"format_step": False})
        format_step_in_force(env.factory, ALPHA)
        r = register_via_api(env, hypothesis=f"{HYPOTHESIS}, on the block's off arm")
        assert r.status_code == 201, r.text
        assert r.json()["checks_arm"] == "off"
        assert _registered_events(env) == 2


def test_a_forward_reading_is_refused_while_the_loop_overlay_moves_the_checks_arm(
    backend: Backend, tmp_path: Path
) -> None:
    """``POST /readings/forward`` freezes the ceiling's checks arm, and the factory runs it
    counts resolve the overlay's: it is refused 409 ``reading_checks_overlay`` while the loop's
    change moves the arm, nothing written, and registers once the team's block sets the key."""
    from fixtures.server_seed import BUILDER, MODEL, PROVIDER

    with _api_on(backend, tmp_path / "home") as env:
        add_tasks(env.factory, qualify=True)
        r = register_via_api(env)
        assert r.status_code == 201, r.text
        assert r.json()["checks_arm"] == "off"
        first = r.json()["pool"][:20]
        add_rows(env.factory, first, arm="S3", reading=r.json())
        add_rows(env.factory, first[:3], arm=S1, clean=False, reading=r.json())
        add_rows(env.factory, first[3:], arm=S1, reading=r.json())
        add_oracle_and_controls(env.factory, first)
        body = {
            "repo": ALPHA,
            "promotes": r.json()["reading_id"],
            "builder": BUILDER,
            "model": MODEL,
            "provider": PROVIDER,
            "hypothesis": HYPOTHESIS,
            "smallest_effect": SMALLEST_EFFECT,
        }
        format_step_in_force(env.factory, ALPHA)
        fwd = env.post("/readings/forward", json=body)
        assert fwd.status_code == 409, fwd.text
        err = envelope(fwd)
        assert (err["code"], err["detail"]) == ("reading_checks_overlay", OVERLAY_MOVED), err
        assert _registered_events(env) == 1
        _set_checks(env, {"format_step": False})
        fwd = env.post("/readings/forward", json=body)
        assert fwd.status_code == 201, fwd.text
        assert fwd.json()["checks_arm"] == "off"
        assert _registered_events(env) == 2
