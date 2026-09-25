"""crb.store.db — engine construction, ``init_db`` idempotence, the append-only triggers.

Parametrised over SQLite and (when ``CRB_TEST_POSTGRES_URL`` is set) PostgreSQL.

Navigation
----------
What it is:   The store engine's test suite — engine construction, ``init_db`` idempotence and
              the append-only triggers, on SQLite and PostgreSQL.
What it does: Pins the database-URL precedence, that a SQLite engine creates the parent
              directory and sets the pragmas (WAL, foreign keys), that ``init_db`` creates every
              model table and is idempotent (as is installing the triggers alone), that foreign
              keys are enforced, that ``session_scope`` commits and rolls back, and that every
              append-only table refuses UPDATE and DELETE while still accepting INSERT — and that
              the ordinary tables (``repos`` / ``runs`` / ``users``) stay mutable.
How:          ``conftest_store.backend`` gives an EMPTY database per dialect; one valid ORM row
              per append-only table is inserted and then attacked.
Layer:        tests — docs/ARCHITECTURE.md#73-data-model-store-p4
ADRs:         docs/adr/0002-append-only-hash-chained-ledger.md
Works with:   src/crb/store/db.py (under test), src/crb/store/models.py (``APPEND_ONLY_TABLES``
              and the rows), tests/conftest_store.py (the backends), tests/test_store_migrate.py
              (the same triggers through Alembic), docs/SECURITY.md (evidence integrity, §3.5)
Tested by:    tests/test_store_db.py
Touch when:   a table is added (decide whether it is append-only — if so, add it to
              ``APPEND_ONLY_TABLES`` and ``_one_row`` here, and a migration); a pragma changes.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from crb.core.ledger import GENESIS_HASH
from crb.store import db as store_db
from crb.store.ledger import _to_model
from crb.store.models import (
    APPEND_ONLY_TABLES,
    Base,
    Event,
    EvidencePackRow,
    Repo,
    Review,
    Run,
    Signoff,
    TaskQualification,
)

try:
    from tests.conftest_store import Backend, backend, grade_row, pg_schema
except ImportError:  # pragma: no cover — rootdir-relative import (pytest default)
    from conftest_store import Backend, backend, grade_row, pg_schema  # noqa: F401

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _one_row(table: str) -> object:
    """One valid ORM row for each append-only table."""
    if table == "grades":
        return _to_model(grade_row().chained(GENESIS_HASH))
    if table == "events":
        return Event(
            event_id="e" * 32,
            trace_id="t" * 32,
            seq=1,
            timestamp="2026-09-13T12:00:00+00:00",
            stage="grade",
            action="grade.belt",
            status="ok",
        )
    if table == "signoffs":
        return Signoff(
            signoff_id="s" * 32,
            repo="r",
            cell_json={"process_step": "replay"},
            verifier="approver@example.org",
            prev_hash=GENESIS_HASH,
            row_hash="a" * 64,
        )
    if table == "evidence":
        return EvidencePackRow(pack_hash="p" * 64, repo="r", task_id="x" * 40, body_json={"k": 1})
    if table == "reviews":
        return Review(
            review_id="v" * 32,
            schema="crb.review.v1",
            grade_row_hash="g" * 64,
            repo="r",
            task_id="x" * 40,
            reviewer="reviewer@example.org",
            verdict="ok",
            findings_json=[],
            statement="read it",
            patch_sha256_reviewed="d" * 64,
            apparatus_version="2.2",
            created="2026-09-14T12:00:00+00:00",
            prev_hash=GENESIS_HASH,
            row_hash="b" * 64,
        )
    if table == "task_qualifications":
        return TaskQualification(
            qualification_id="q" * 32,
            repo="r",
            task_id="x" * 40,
            posture_id="pst_" + "1" * 24,
            state="qualified",
            body_json={"state": "qualified"},
            created="2026-09-25T12:00:00+00:00",
        )
    raise AssertionError(table)


def _pk(table: str) -> str:
    return {
        "grades": "seq",
        "events": "id",
        "signoffs": "seq",
        "evidence": "pack_hash",
        "reviews": "seq",
        "task_qualifications": "seq",
    }[table]


def _count(b: Backend, table: str) -> int:
    with b.engine.connect() as c:
        return int(c.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one())


def _expected_triggers() -> set[str]:
    return {f"{t}_{kind}" for t in APPEND_ONLY_TABLES for kind in ("no_update", "no_delete")}


# ---------------------------------------------------------------------------
# database_url / make_engine
# ---------------------------------------------------------------------------


def test_database_url_precedence(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("CRB_DATABASE_URL", raising=False)
    monkeypatch.setenv("CRB_HOME", str(tmp_path / "home"))
    assert store_db.database_url() == f"sqlite:///{tmp_path / 'home' / 'crb.db'}"
    monkeypatch.setenv("CRB_DATABASE_URL", "postgresql+psycopg://u@h/db")
    assert store_db.database_url() == "postgresql+psycopg://u@h/db"
    assert store_db.database_url("sqlite:///explicit.db") == "sqlite:///explicit.db"


def test_sqlite_engine_creates_parent_dir_and_sets_pragmas(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "dir" / "crb.db"
    engine = store_db.make_engine(f"sqlite:///{path}")
    try:
        with engine.connect() as c:
            assert c.execute(text("PRAGMA journal_mode")).scalar_one() == "wal"
            assert c.execute(text("PRAGMA foreign_keys")).scalar_one() == 1
            assert c.execute(text("PRAGMA synchronous")).scalar_one() == 2  # FULL
        assert path.parent.is_dir()
    finally:
        engine.dispose()


# ---------------------------------------------------------------------------
# init_db
# ---------------------------------------------------------------------------


def test_init_db_creates_every_model_table_and_is_idempotent(backend: Backend) -> None:
    store_db.init_db(backend.engine)
    first = set(inspect(backend.engine).get_table_names())
    assert first == set(Base.metadata.tables)
    assert backend.trigger_names() == _expected_triggers()

    store_db.init_db(backend.engine)  # second call: no error, nothing new
    assert set(inspect(backend.engine).get_table_names()) == first
    assert backend.trigger_names() == _expected_triggers()


def test_install_triggers_is_idempotent_on_its_own(backend: Backend) -> None:
    store_db.init_db(backend.engine)
    store_db.install_append_only_triggers(backend.engine)
    store_db.install_append_only_triggers(backend.engine)
    assert backend.trigger_names() == _expected_triggers()


def test_foreign_keys_are_enforced(backend: Backend) -> None:
    """``runs.repo`` → ``repos.name``: SQLite needs ``PRAGMA foreign_keys=ON`` for this."""
    store_db.init_db(backend.engine)
    with pytest.raises(IntegrityError), backend.factory() as s:
        s.add(Run(id="r1", repo="does-not-exist"))
        s.commit()
    with backend.factory() as s:
        s.add(Repo(name="exists", language="python", runner="pytest", config_json={}))
        s.add(Run(id="r2", repo="exists"))
        s.commit()
    assert _count(backend, "runs") == 1


def test_session_scope_commits_and_rolls_back(backend: Backend) -> None:
    store_db.init_db(backend.engine)
    with store_db.session_scope(backend.factory) as s:
        s.add(Repo(name="a", language="python", runner="pytest", config_json={}))
    assert _count(backend, "repos") == 1
    with pytest.raises(RuntimeError, match="boom"), store_db.session_scope(backend.factory) as s:
        s.add(Repo(name="b", language="python", runner="pytest", config_json={}))
        raise RuntimeError("boom")
    assert _count(backend, "repos") == 1


# ---------------------------------------------------------------------------
# append-only triggers — one test per table, UPDATE and DELETE each
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("table", APPEND_ONLY_TABLES)
def test_append_only_table_refuses_update(backend: Backend, table: str) -> None:
    store_db.init_db(backend.engine)
    with backend.factory() as s:
        s.add(_one_row(table))
        s.commit()
    with pytest.raises(DBAPIError, match="append-only"), backend.engine.begin() as c:
        c.execute(text(f"UPDATE {table} SET repo = 'tampered'"))
    with backend.engine.connect() as c:
        assert (
            c.execute(text(f"SELECT COUNT(*) FROM {table} WHERE repo = 'tampered'")).scalar_one()
            == 0
        )
    assert _count(backend, table) == 1


@pytest.mark.parametrize("table", APPEND_ONLY_TABLES)
def test_append_only_table_refuses_delete(backend: Backend, table: str) -> None:
    store_db.init_db(backend.engine)
    with backend.factory() as s:
        s.add(_one_row(table))
        s.commit()
    with pytest.raises(DBAPIError, match="append-only"), backend.engine.begin() as c:
        c.execute(text(f"DELETE FROM {table}"))
    assert _count(backend, table) == 1
    # ...and a targeted delete by primary key is refused just the same
    with pytest.raises(DBAPIError, match="append-only"), backend.engine.begin() as c:
        c.execute(text(f"DELETE FROM {table} WHERE {_pk(table)} IS NOT NULL"))
    assert _count(backend, table) == 1


def test_non_append_only_tables_stay_mutable(backend: Backend) -> None:
    """The triggers are scoped: ``repos`` / ``runs`` / ``users`` are ordinary tables."""
    store_db.init_db(backend.engine)
    with backend.factory() as s:
        s.add(Repo(name="a", language="python", runner="pytest", config_json={}))
        s.commit()
    with backend.engine.begin() as c:
        c.execute(text("UPDATE repos SET probe_status = 'green'"))
        c.execute(text("DELETE FROM repos"))
    assert _count(backend, "repos") == 0


def test_append_only_tables_still_accept_inserts(backend: Backend) -> None:
    store_db.init_db(backend.engine)
    for table in APPEND_ONLY_TABLES:
        with backend.factory() as s:
            s.add(_one_row(table))
            s.commit()
        assert _count(backend, table) == 1
