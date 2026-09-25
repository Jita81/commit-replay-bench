"""crb.store.qualifications — append-only, latest wins, a revocation is a row (ADR-0019).

Navigation
----------
What it is:   The store tests for ``task_qualifications`` on both dialects (SQLite always;
              PostgreSQL in CI's ``test-postgres`` job).
What it does: Pins that an UPDATE or DELETE is refused by the database, that the latest row
              for a task and posture is the one in force and a revocation is a new row, that
              ``qualified_specs`` returns projected specs of qualified tasks only, and the
              counts and fingerprints the gate and the map read.
How:          ``init_db`` on the parametrised backend; records built with
              ``crb.core.qualify.Qualification``; raw SQL for the tamper attempts.
Layer:        tests — docs/ARCHITECTURE.md#73-data-model-store-p4
ADRs:         docs/adr/0019-qualification-is-posture-relative.md
Works with:   src/crb/store/qualifications.py (under test), src/crb/store/models.py
              (``TaskQualification``), src/crb/core/qualify.py (the record),
              tests/conftest_store.py (the backends)
Tested by:    tests/test_store_qualifications.py
Touch when:   a new reading of the records is added to the store module.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from crb.core.qualify import STATE_QUALIFIED, STATE_UNQUALIFIED, Qualification
from crb.core.spec import TaskSpec
from crb.store import qualifications as sq
from crb.store.db import init_db
from crb.store.models import Repo, Task

try:  # tests/ is a package only if the conftest owner made it one
    from tests.conftest_store import Backend, backend, pg_schema
except ImportError:  # pragma: no cover — rootdir-relative import (pytest default)
    from conftest_store import Backend, backend, pg_schema  # noqa: F401

P1, P2 = "pst_" + "1" * 24, "pst_" + "2" * 24
T1, T2 = "a" * 40, "b" * 40


def _q(task_id: str = T1, posture_id: str = P1, **kw: Any) -> Qualification:
    base: dict[str, Any] = {
        "qualification_id": "",
        "repo": "calc",
        "task_id": task_id,
        "posture_id": posture_id,
        "posture": {
            "executor": "docker",
            "image_ref": "crb-sandbox-go:t",
            "posture_class": "docker/copy/sealed" if posture_id == P1 else "local/inplace/host-env",
        },
        "state": STATE_QUALIFIED,
        "baseline_failing": ("calc::TestOnlyHere",) if posture_id == P1 else (),
        "gold": {"clean": True, "lint": None},
    }
    base.update(kw)
    return Qualification(**base)


def _seed(backend: Backend) -> None:
    init_db(backend.engine)
    with backend.factory() as s:
        s.add(Repo(name="calc", language="go", runner="go", config_json={"language": "go"}))
        for tid, authored in ((T1, "2026-01-01"), (T2, "2026-01-02")):
            spec = TaskSpec(
                task_id=tid,
                repo="calc",
                subject="s",
                authored=authored,
                test_files=("calc_test.go",),
                src_files=("calc.go",),
                target_tests=("./",),
                belt_scope=("./",),
                baseline_failing=("calc::HostOnly",),
            )
            s.add(Task(repo="calc", task_id=tid, spec_json=spec.to_dict(), authored=authored))
        s.commit()


def test_qualifications_are_append_only(backend: Backend) -> None:
    _seed(backend)
    with backend.factory() as s:
        sq.append(s, _q())
    for stmt in (
        "UPDATE task_qualifications SET state = 'legacy'",
        "DELETE FROM task_qualifications",
    ):
        with pytest.raises(DBAPIError, match="append-only"), backend.engine.begin() as c:
            c.execute(text(stmt))
    with backend.factory() as s:
        got = sq.latest(s, "calc", T1, P1)
        assert got is not None and got.is_qualified


def test_latest_row_wins_and_revocation_is_a_row(backend: Backend) -> None:
    _seed(backend)
    with backend.factory() as s:
        first = sq.append(s, _q(state=STATE_UNQUALIFIED, code="QUAL_ENV_UNLOADABLE"))
        second = sq.append(s, _q())
        assert sq.latest(s, "calc", T1, P1) == second
        revoked = sq.revoke(s, second, "QUAL_ENV_WITNESS_RED", "worker", "gold control red")
        now = sq.latest(s, "calc", T1, P1)
        assert now is not None and now.state == "revoked" and now.code == "QUAL_ENV_WITNESS_RED"
        assert now.qualification_id == revoked.qualification_id != second.qualification_id
        assert "gold control red" in now.message and not now.is_qualified
        # every row is still there: three records, nothing rewritten
        n = s.execute(text("SELECT COUNT(*) FROM task_qualifications")).scalar_one()
        assert n == 3 and first.code == "QUAL_ENV_UNLOADABLE"
        # a record in another posture does not answer for this one
        assert sq.latest(s, "calc", T1, P2) is None


def test_qualified_specs_are_projected(backend: Backend) -> None:
    _seed(backend)
    with backend.factory() as s:
        q1 = sq.append(s, _q(T1))
        sq.append(s, _q(T2, state=STATE_UNQUALIFIED, code="QUAL_NOT_RED"))
        sq.append(s, _q(T2, posture_id=P2))  # qualified — but in another posture
        specs = sq.qualified_specs(s, "calc", P1)
        assert [t.task_id for t in specs] == [T1]
        (spec,) = specs
        assert spec.posture_id == P1 and spec.qualification_ref == q1.qualification_id
        assert spec.baseline_failing == ("calc::TestOnlyHere",)  # never the host's
        assert [t.task_id for t in sq.qualified_specs(s, "calc", P2)] == [T2]
        assert sq.qualified_specs(s, "calc", P1, task_ids=[T2]) == []
        assert sq.counts_by_code(s, "calc", P1) == {"": 1, "QUAL_NOT_RED": 1}
        assert sq.latest_posture_for(s, "calc", executor="docker") == P2
        fps = sq.latest_fingerprints(s, "calc", ["docker/copy/sealed", "local/inplace/host-env"])
        assert fps["docker/copy/sealed"] == {T1: q1.fingerprint}
        assert set(fps["local/inplace/host-env"]) == {T2}
