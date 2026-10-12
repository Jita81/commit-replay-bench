"""P-797: a reserved.v1 reading's pool is pinned to the qualification records that admitted it.

docs/PREVENTION.md P-797 records the finding: the Wave 3 red team (F2, C14, C18), by code
reading on c5b9e5ec, found a reserved.v1 reading's pool read from live, editable ``Task``
fields — a pool task relabelled after registration still counted, a commit the miner called
``gold_clean`` entered the pool whatever its qualification record said, and ``pool_seen`` read
only the reading's own hierarchy, so a commit already graded under another arm or test author
could be registered as unseen. Each test reproduces one probe of that enumeration and failed
before the fix.

Navigation
----------
What it is:   The P-797 suite: the reserved.v1 pool read from qualification records and pinned
              by id, its drift refused wherever a run of it is read or claimed, and the widened
              ``pool_seen``.
What it does: Relabels a pool task after registration (the CLI's ``tasks label`` and a direct
              ``Task`` edit) and proves ``GET /readings`` serves the reading ``undecided`` with
              its drift, ``POST /runs`` answers 409 ``pool_drift`` and the claim refuses
              ``run.refused`` ``pool_drift`` before any reservation; proves a 2.4 replay row
              under any arm or test author makes a commit seen for a reserved.v1 registration
              (and not for a legacy one); proves a mined ``gold_clean`` commit enters a
              reserved.v1 pool only through a ``qualified`` record in force; proves the pool
              hash and the id pin the posture and the record ids; proves a requalification is
              not drift, a revoked record in force leaves its commit pending, and a posture
              move halts the run before anything is qualified or reserved.
How:          The core tests register in memory (``fixtures.readings``). The route tests run
              the app on the ``backend`` fixture's store (SQLite and PostgreSQL), qualifying
              tasks through the store's writer (``qualify_pool``); the drift test reuses the
              Wave 3 rehearsal's stack (``_r_stack``). The claim tests reuse P-792's worker rig
              (``_w_rig``: the pyrepo fixture's two commits, the fake builder, a sealed
              worker's labels) and read ``GET /readings`` over its store (``_w_served``).
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0019-qualification-is-posture-relative.md,
              docs/adr/0026-the-context-standard.md
Works with:   src/crb/core/reading.py (the pins, ``reserved_pool_digest`` and ``pool_seen``,
              under test), src/crb/server/reading_book.py (``pool_drift``, under test),
              src/crb/server/routes/readings.py (the pool from records; the served drift),
              src/crb/server/routes/runs.py (the 409 ``pool_drift``),
              src/crb/server/worker.py (the claim refusal and the posture check, under test),
              src/crb/store/qualifications.py (the records a pool is read from and pinned to),
              tests/test_p792_reserved.py (the worker rig and the submit-gate stack reused),
              tests/fixtures/readings.py (``qualify_pool``, the rows and the registrations)
Tested by:    tests/test_p792_pool.py
Touch when:   never for a new repository; what pins a reserved.v1 pool, what counts as its
              drift, or what makes a commit seen for it changes (its test here, failing first).
"""

from __future__ import annotations

import contextlib
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

import crb.core.reading as core_reading
import crb.server.reading_book as reading_book
from crb.cli.main import main as crb_main
from crb.core.qualify import QUAL_ENV_WITNESS_RED, QUAL_GOLD_NOT_GREEN, STATE_UNQUALIFIED
from crb.core.reading import (
    ATTEMPT_RULE_RESERVED,
    OUTCOME_UNDECIDED,
    REFUSAL_INVALID,
    REFUSAL_POOL_SEEN,
    Reading,
    ReadingRefused,
    pool_digest,
)
from crb.core.spend import PROFILE_DEFAULT
from crb.server.app import create_app
from crb.store import qualifications as store_q
from crb.store.db import init_db
from crb.store.jobs import STATUS_CANCELLED, STATUS_FAILED
from crb.store.models import Task, TaskQualification
from fixtures import pyrepo as pr
from fixtures.proven import add_rows, add_tasks, register_via_api
from fixtures.readings import (
    POSTURE_ID,
    SEALED_SETTINGS,
    commits,
    qualify_pool,
    register_reading,
    sealed_row,
)
from fixtures.server_seed import ALPHA, Env, add_users, envelope, login, make_settings, seed
from test_p792_reserved import _r_admit, _r_refused, _r_stack, _w_rig, _w_served, _WRig
from test_wave3_registration_rehearsal import _a0, _served_readings

try:  # tests/ is a package only if the conftest owner made it one
    from tests.conftest_store import Backend, backend, pg_schema
except ImportError:  # pragma: no cover — rootdir-relative import (pytest default)
    from conftest_store import Backend, backend, pg_schema  # noqa: F401


@pytest.fixture(autouse=True)
def _no_ambient_crb_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        if key.startswith("CRB_"):
            monkeypatch.delenv(key, raising=False)


def _pins(pool: list[str]) -> dict[str, str]:
    """One stand-in qualification id per pool commit."""
    return {c: f"{i:032x}" for i, c in enumerate(pool, start=1)}


def _reserved(pins: dict[str, str], posture_id: str = POSTURE_ID) -> dict[str, Any]:
    """``register`` options of a reserved.v1 reading pinned to ``pins`` in ``posture_id``."""
    return {
        "attempt_rule": ATTEMPT_RULE_RESERVED,
        "max_reruns": 0,
        "budget_profile": PROFILE_DEFAULT,
        "pool_posture_id": posture_id,
        "pool_qualifications": pins,
    }


@contextlib.contextmanager
def _api(backend: Backend, home: Path) -> Iterator[Env]:
    """The app on ``backend``'s store: sealed (P-789), seeded, an operator logged in."""
    home.mkdir(exist_ok=True)
    init_db(backend.engine)
    info = seed(backend.factory)
    add_users(backend.factory)
    settings = make_settings(home, **SEALED_SETTINGS)
    with TestClient(create_app(settings, backend.factory)) as client:
        login(client, "operator")
        yield Env(client=client, factory=backend.factory, info=info, settings=settings)


def _label(url: str, repo: str, commit: str, cls: str) -> None:
    """``crb tasks label`` — a human relabels ``commit``'s class in the store at ``url``."""
    argv = ["tasks", "label", repo, commit, "--class", cls, "--by", "op-1"]
    assert crb_main([*argv, "--database-url", url, "--json"]) == 0


def _set_size(rig: _WRig, commit: str, size: str) -> None:
    """A direct edit of ``commit``'s ``Task`` size column (what a re-mine writes)."""
    with rig.h.factory() as s:
        task = s.execute(
            select(Task).where(Task.repo == pr.REPO_NAME, Task.task_id == commit)
        ).scalar_one()
        task.size = size
        s.commit()


def _records(rig: _WRig) -> int:
    with rig.h.factory() as s:
        return int(s.execute(select(func.count()).select_from(TaskQualification)).scalar_one())


def test_p792_relabelling_a_pool_task_after_registration_is_pool_drift(
    backend: Backend, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F2 (the red team's probe): a reserved.v1 reading registered, one of its pool tasks is
    relabelled out of the cell. Before P-797 the reading kept counting it and a run of the
    reading was queued and claimed as if nothing moved. Now ``GET /readings`` serves the
    reading ``undecided`` with no standard and names the drift, ``POST /runs`` refuses 409
    ``pool_drift`` with nothing queued or admitted, and a run that reached the queue is
    refused at claim — ``run.refused`` ``pool_drift``, failed before any build, nothing
    reserved, every commit still pending. The reading's other cells do not drift, and
    restoring the label restores admission."""
    (tmp_path / "submit").mkdir()
    with _r_stack(backend, tmp_path / "submit", monkeypatch) as w:
        key = ("cobra", "XS")
        reading_id = w.readings[key]["reading_id"]
        body = _a0(w, key)
        commit = body["task_ids"][0]
        before = _served_readings(w, "cobra")[reading_id]
        assert before["pool_drift"] == [] and before["state"] != OUTCOME_UNDECIDED

        _label(backend.url, "cobra", commit, "perf")
        drift = [
            {
                "task_id": commit,
                "field": "capability_class",
                "registered": "bug.fix",
                "now": "perf",
            }
        ]
        served = _served_readings(w, "cobra")
        got = served[reading_id]
        assert (got["state"], got["standard"], got["ceiling"]) == (OUTCOME_UNDECIDED, None, False)
        assert got["pool_drift"] == drift
        assert served[w.readings[("cobra", "S")]["reading_id"]]["pool_drift"] == []
        err = _r_refused(w, body, 409, "pool_drift")
        assert err["detail"] == {"reading_id": reading_id, "drift": drift}

        _label(backend.url, "cobra", commit, "bug.fix")
        assert _served_readings(w, "cobra")[reading_id]["pool_drift"] == []
        assert _r_admit(w, body).status == STATUS_CANCELLED

    (tmp_path / "claim").mkdir()
    rig = _w_rig(tmp_path / "claim", monkeypatch)
    reading = rig.register()
    _set_size(rig, rig.second, "S")
    drift = [{"task_id": rig.second, "field": "size", "registered": "XS", "now": "S"}]
    with rig.h.factory() as s:
        assert reading_book.pool_drift(s, reading) == drift
    run = rig.enqueue(reading)
    done = rig.h.run_one()
    assert done.status == STATUS_FAILED and done.error.startswith("pool_drift"), done.error
    (refused,) = rig.payloads(run.id, "run.refused")
    assert (refused["code"], refused["reading_id"]) == ("pool_drift", reading.reading_id)
    assert refused["drift"] == drift
    assert "build.start" not in rig.actions(run.id)
    assert rig.rows(run.id) == [] and rig.reservations(reading) == []
    pending = {rig.first: (None, "pending"), rig.second: (None, "pending")}
    assert rig.verdicts(reading, "A0") == pending
    served_rig = _w_served(rig, tmp_path / "claim" / "api")[reading.reading_id]
    assert (served_rig["state"], served_rig["pool_drift"]) == (OUTCOME_UNDECIDED, drift)

    _set_size(rig, rig.second, "XS")
    rig.enqueue(reading)
    rig.h.run_one()
    assert len(rig.reservations(reading)) == 1
    assert rig.verdicts(reading, "A0")[rig.first] == (True, "")


def test_p792_a_commit_with_a_24_a0_row_is_pool_seen(backend: Backend, tmp_path: Path) -> None:
    """C14 (the red team's probe): a commit already graded at apparatus 2.4 under an arm the
    reading does not name — ``A0``, or ``S1`` under another test author, or a later
    apparatus — was registered as unseen, because ``pool_seen`` read only the hierarchy's
    arms at the reading's apparatus. A reserved.v1 registration now refuses ``pool_seen`` on
    any replay row at 2.4 or later, under any arm or author, on a pool commit or another
    commit of its change; a legacy registration over the same rows is admitted as before."""
    pool = commits(4, "seen")
    changes = {c: f"change-{c}" for c in pool}
    twin = commits(1, "twin")[0]
    cases = [
        ([sealed_row(pool[0], arm="A0")], [pool[0]]),
        ([sealed_row(twin, arm="S1@gpt-oss-120b", change=changes[pool[1]])], [twin]),
        ([sealed_row(pool[2], arm="S3", apparatus_version="2.5")], [pool[2]]),
    ]
    for rows, seen in cases:
        assert register_reading(pool, rows=rows, changes=changes).pool == tuple(
            register_reading(pool, changes=changes).pool
        )
        with pytest.raises(ReadingRefused) as exc:
            register_reading(pool, rows=rows, changes=changes, **_reserved(_pins(pool)))
        assert exc.value.code == REFUSAL_POOL_SEEN, exc.value
        assert exc.value.detail == {"commits": seen, "n": 1}
    unseen = [sealed_row(pool[3], arm="S2", process_step="factory"), sealed_row(pool[3], repo="x")]
    assert register_reading(pool, rows=unseen, changes=changes, **_reserved(_pins(pool)))

    with _api(backend, tmp_path / "api") as env:
        ids = add_tasks(env.factory)
        qualify_pool(env.factory, ALPHA, ids)
        add_rows(env.factory, [ids[0]], arm="A0")
        refused = register_via_api(env, attempt_rule=ATTEMPT_RULE_RESERVED)
        assert refused.status_code == 409, refused.text
        err = envelope(refused)
        assert (err["code"], err["detail"]) == (REFUSAL_POOL_SEEN, {"commits": [ids[0]], "n": 1})
        legacy = register_via_api(env)
        assert legacy.status_code == 201, legacy.text


def test_p792_a_mine_gold_clean_commit_with_a_failing_qualification_is_not_in_the_pool(
    backend: Backend, tmp_path: Path
) -> None:
    """C18 (the red team's probe): a reserved.v1 pool read the miner's ``gold_clean``, so a
    commit whose qualification in the posture failed — or was revoked, or never ran — was
    frozen into the pool all the same. Every task here is mined ``gold_clean``. With no
    record at all a reserved.v1 registration now has no pool (422 ``invalid_reading``,
    nothing written); once records exist, its pool is exactly the commits whose record in
    force in the latest posture of the reading's class is ``qualified``, each pinned by its
    record id — the unqualified, the revoked and the unrecorded commit are left out — while
    a legacy registration still freezes every mined commit."""
    with _api(backend, tmp_path / "api") as env:
        ids = add_tasks(env.factory)
        empty = register_via_api(env, attempt_rule=ATTEMPT_RULE_RESERVED)
        assert empty.status_code == 422, empty.text
        assert envelope(empty)["code"] == REFUSAL_INVALID

        unqualified, unrecorded, revoked, *qualified = ids
        pins = qualify_pool(env.factory, ALPHA, [revoked, *qualified])
        qualify_pool(
            env.factory, ALPHA, [unqualified], state=STATE_UNQUALIFIED, code=QUAL_GOLD_NOT_GREEN
        )
        with env.factory() as s:
            in_force = store_q.latest(s, ALPHA, revoked, POSTURE_ID)
            assert in_force is not None
            store_q.revoke(s, in_force, QUAL_ENV_WITNESS_RED, "op-1", "gold control red")

        reserved = register_via_api(env, attempt_rule=ATTEMPT_RULE_RESERVED)
        assert reserved.status_code == 201, reserved.text
        got = reserved.json()
        assert sorted(got["pool"]) == sorted(qualified)
        assert not {unqualified, unrecorded, revoked} & set(got["pool"])
        assert got["pool_posture_id"] == POSTURE_ID
        assert got["pool_qualifications"] == {c: pins[c] for c in sorted(qualified)}

        legacy = register_via_api(env)
        assert legacy.status_code == 201, legacy.text
        assert sorted(legacy.json()["pool"]) == sorted(ids)
        assert "pool_qualifications" not in legacy.json()


def test_p792_reserved_pool_sha256_pins_the_qualification_ids(
    backend: Backend, tmp_path: Path
) -> None:
    """F2's hash (the red team's probe): a reserved.v1 reading's ``pool_sha256`` hashed the
    commit list alone, so the records that admitted its commits could change under it with
    the reading still verifying. The hash and the id now pin the posture and each commit's
    record id: another record or posture is another pool and another reading; a stored body
    whose pins were edited no longer verifies; pins that miss a commit or name no posture are
    refused; a legacy reading pins nothing and its hash and id do not move. ``POST /readings``
    pins the records the store holds and ``GET /readings`` serves the same hash."""
    pool = commits(3, "pin")
    pins = _pins(pool)
    reading = register_reading(pool, **_reserved(pins))
    body = reading.to_dict()
    assert (body["pool_posture_id"], body["pool_qualifications"]) == (POSTURE_ID, pins)
    digest = core_reading.reserved_pool_digest(reading.pool, POSTURE_ID, pins)
    assert reading.pool_sha256 == digest != pool_digest(reading.pool)
    assert reading.verify() and Reading.from_dict(body).verify()
    for edit in (
        {"pool_qualifications": {**pins, pool[0]: "e" * 32}},
        {"pool_posture_id": "pst_" + "e" * 24},
    ):
        other = register_reading(pool, **{**_reserved(pins), **edit})
        assert other.pool_sha256 != reading.pool_sha256, edit
        assert other.reading_id != reading.reading_id, edit
        assert not Reading.from_dict({**body, **edit}).verify(), edit
    for edit in (
        {"pool_qualifications": {c: pins[c] for c in pool[1:]}},
        {"pool_posture_id": ""},
    ):
        with pytest.raises(ReadingRefused) as exc:
            register_reading(pool, **{**_reserved(pins), **edit})
        assert exc.value.code == REFUSAL_INVALID, edit

    legacy = register_reading(pool)
    assert legacy.pool_sha256 == pool_digest(legacy.pool)
    assert not {"pool_posture_id", "pool_qualifications"} & set(legacy.to_dict())
    ignored = register_reading(pool, pool_posture_id=POSTURE_ID, pool_qualifications=pins)
    assert ignored.reading_id == legacy.reading_id

    with _api(backend, tmp_path / "api") as env:
        records = qualify_pool(env.factory, ALPHA, add_tasks(env.factory))
        r = register_via_api(env, attempt_rule=ATTEMPT_RULE_RESERVED)
        assert r.status_code == 201, r.text
        got = r.json()
        assert got["pool_posture_id"] == POSTURE_ID
        assert got["pool_qualifications"] == {c: records[c] for c in sorted(got["pool"])}
        assert got["pool_sha256"] == core_reading.reserved_pool_digest(
            got["pool"], POSTURE_ID, records
        )
        served = env.get(f"/readings?repo={ALPHA}")
        assert served.status_code == 200, served.text
        (one,) = [o for o in served.json()["readings"] if o["reading_id"] == got["reading_id"]]
        assert (one["pool_sha256"], one["pool_drift"]) == (got["pool_sha256"], [])


def test_p792_a_requalified_commit_is_not_drift_and_a_revoked_one_stays_pending(
    backend: Backend, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C18 at claim: the records a pool pinned are append-only, so a NEWER record for the
    pinned posture is never drift. A requalification (a second ``qualify`` run) leaves the
    reading undrifted and its run reserves and grades; a revocation of the record in force
    leaves it undrifted too, and admission refuses the revoked commit (the run's
    ``qualify_first`` off) — ``run.posture_refused`` before any build, nothing reserved, the
    commit still pending: a stall, never a skip."""
    rig = _w_rig(tmp_path, monkeypatch, backend)
    reading = rig.register()
    pinned = dict(reading.pool_qualifications)
    before = _w_served(rig, tmp_path / "api")[reading.reading_id]
    rig.qualify()
    with rig.h.factory() as s:
        now = store_q.latest_by_task(s, pr.REPO_NAME, reading.pool_posture_id)
        assert all(now[c].qualification_id != pinned[c] for c in pinned), (now, pinned)
        assert reading_book.pool_drift(s, reading) == []
    served = _w_served(rig, tmp_path / "api")[reading.reading_id]
    assert served["pool_drift"] == [] and served == before
    rig.enqueue(reading)
    rig.h.run_one()
    (res,) = rig.reservations(reading)
    assert rig.verdicts(reading, "A0")[rig.first] == (True, "")

    with rig.h.factory() as s:
        store_q.revoke(s, now[rig.second], QUAL_ENV_WITNESS_RED, "op-1", "gold control red")
        assert reading_book.pool_drift(s, reading) == []
    run = rig.enqueue(reading, rig.second, params={"qualify_first": False})
    done = rig.h.run_one()
    assert done.status == STATUS_FAILED, done.error
    (refused,) = rig.payloads(run.id, "run.posture_refused")
    assert [r["code"] for r in refused["refusals"]] == [QUAL_ENV_WITNESS_RED], refused
    assert rig.payloads(run.id, "run.refused") == []
    assert "build.start" not in rig.actions(run.id)
    assert [e.event_id for e in rig.reservations(reading)] == [res.event_id]
    assert rig.verdicts(reading, "A0") == {rig.first: (True, ""), rig.second: (None, "pending")}


def test_p792_a_posture_move_halts_a_pinned_pool_before_any_reservation(
    backend: Backend, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The pinned posture at build: a reserved.v1 pool qualified in one posture, run where the
    live posture is another, was admitted on the live posture's own records. The run is now
    refused ``run.refused`` ``pool_drift`` naming both postures — before the gate qualifies
    anything (no record is written) and before any reservation, every commit still pending —
    though the pinned records themselves still stand (no drift on ``GET /readings``)."""
    rig = _w_rig(tmp_path, monkeypatch, backend)
    moved = "pst_" + "e" * 24
    pins = qualify_pool(
        rig.h.factory,
        pr.REPO_NAME,
        [rig.first, rig.second],
        posture_class=rig.posture,
        posture_id=moved,
    )
    monkeypatch.setattr(
        rig, "qualify", lambda: {"pool_posture_id": moved, "pool_qualifications": pins}
    )
    reading = rig.register()
    assert reading.pool_posture_id == moved
    with rig.h.factory() as s:
        assert reading_book.pool_drift(s, reading) == []
    records = _records(rig)
    run = rig.enqueue(reading)
    done = rig.h.run_one()
    assert done.status == STATUS_FAILED and done.error.startswith("pool_drift"), done.error
    (refused,) = rig.payloads(run.id, "run.refused")
    assert refused["code"] == "pool_drift" and refused["reading_id"] == reading.reading_id
    ((drift,),) = [refused["drift"]]
    assert (drift["field"], drift["registered"]) == ("pool_posture_id", moved)
    assert drift["now"].startswith("pst_") and drift["now"] != moved
    assert "build.start" not in rig.actions(run.id)
    assert _records(rig) == records
    assert rig.rows(run.id) == [] and rig.reservations(reading) == []
    assert rig.verdicts(reading, "A0") == {
        rig.first: (None, "pending"),
        rig.second: (None, "pending"),
    }
