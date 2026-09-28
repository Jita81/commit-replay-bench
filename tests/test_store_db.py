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
              the ordinary tables (``repos`` / ``runs`` / ``users``) stay mutable. Also that no
              statement short of DDL rewrites an append-only row (SQLite's REPLACE,
              PostgreSQL's TRUNCATE and upsert — EI-4, EI-5), that the ``append_only`` probe
              goes down on a disabled, moved, missing or ``WHEN``-neutered trigger (which the
              next start re-creates) and on an accepted REPLACE, and never claims an UPDATE it
              did not try on an empty ledger, that a PostgreSQL application role that does
              not own the tables starts with no DDL and cannot remove the protection nor
              issue table DDL, and that a system event holds its trace's ``seq`` until it
              commits (EI-1) and the events write lock holds a second writer until the first
              commits (P-196).
How:          ``conftest_store.backend`` gives an EMPTY database per dialect; one valid ORM row
              per append-only table is inserted and then attacked.
Layer:        tests — docs/ARCHITECTURE.md#73-data-model-store-p4
ADRs:         docs/adr/0002-append-only-hash-chained-ledger.md
Works with:   src/crb/store/db.py (under test), src/crb/store/models.py (``APPEND_ONLY_TABLES``
              and the rows), tests/conftest_store.py (the backends), tests/test_store_migrate.py
              (the same triggers through Alembic), docs/SECURITY.md (evidence integrity, §3.5)
Tested by:    tests/test_store_db.py
Touch when:   never for a new repository; a table is added (decide whether it is
              append-only — if so, add it to ``APPEND_ONLY_TABLES`` and ``_one_row`` here, and a
              migration); a pragma changes.
"""

from __future__ import annotations

import contextlib
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


def _expected_triggers(dialect: str) -> set[str]:
    """The dialect's expected trigger names — PostgreSQL adds a statement-level
    ``_no_truncate`` per table (EI-4)."""
    return {name for _, name in store_db.expected_triggers(dialect)}


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
            # REPLACE's implicit delete must fire the append-only delete trigger (EI-5)
            assert c.execute(text("PRAGMA recursive_triggers")).scalar_one() == 1
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
    assert backend.trigger_names() == _expected_triggers(backend.dialect)

    store_db.init_db(backend.engine)  # second call: no error, nothing new
    assert set(inspect(backend.engine).get_table_names()) == first
    assert backend.trigger_names() == _expected_triggers(backend.dialect)


def test_install_triggers_is_idempotent_on_its_own(backend: Backend) -> None:
    store_db.init_db(backend.engine)
    store_db.install_append_only_triggers(backend.engine)
    store_db.install_append_only_triggers(backend.engine)
    assert backend.trigger_names() == _expected_triggers(backend.dialect)


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


def test_the_events_seq_lock_holds_a_second_writer_until_the_first_commits(
    backend: Backend,
) -> None:
    """``lock_event_writes`` (P-196): a writer that reads a trace's last ``seq`` itself — the
    server's audited commit — takes the events lock first, so a second writer to the same
    trace reads only after the first committed, on both dialects (SQLite's write lock,
    PostgreSQL's advisory lock), and neither insert breaks ``uq_events_trace_seq``. The
    first writer holds its lock across a barrier the second cannot reach while held."""
    import threading

    from sqlalchemy import func, select

    from crb.server.routes.runs import append_system_event
    from crb.store.events import lock_event_writes

    store_db.init_db(backend.engine)
    held = threading.Barrier(2, timeout=1.5)
    seen: dict[str, int] = {}
    errors: list[BaseException] = []

    def writer(name: str) -> None:
        try:
            with backend.factory() as s:
                lock_event_writes(s)
                lock_event_writes(s)  # re-entrant: a second call in one transaction is a no-op
                seen[name] = int(
                    s.execute(
                        select(func.coalesce(func.max(Event.seq), 0)).where(
                            Event.trace_id == "t-lock"
                        )
                    ).scalar_one()
                )
                with contextlib.suppress(threading.BrokenBarrierError):
                    held.wait()
                append_system_event(s, trace_id="t-lock", action="user.login_failed")
                s.commit()
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=writer, args=(n,)) for n in ("a", "b")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert sorted(seen.values()) == [0, 1]  # the second read saw the first commit
    assert _count(backend, "events") == 2


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


# ---------------------------------------------------------------------------
# no statement short of trigger DDL rewrites an append-only row (EI-4, EI-5)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("table", APPEND_ONLY_TABLES)
def test_append_only_table_refuses_truncate(backend: Backend, table: str) -> None:
    """PostgreSQL's ``TRUNCATE`` is a STATEMENT event: a ``FOR EACH ROW`` trigger never sees
    it, so the application's own role emptied the whole ledger with ``/health`` still green
    (EI-4). Every append-only table carries a statement-level trigger that refuses it. SQLite
    has no ``TRUNCATE``; its truncate is ``DELETE`` without ``WHERE``, which the row trigger
    refuses (and which turns SQLite's truncate optimisation off)."""
    store_db.init_db(backend.engine)
    with backend.factory() as s:
        s.add(_one_row(table))
        s.commit()
    stmt = (
        f"TRUNCATE {table} CASCADE" if backend.dialect == "postgresql" else f"DELETE FROM {table}"
    )
    with pytest.raises(DBAPIError, match="append-only"), backend.engine.begin() as c:
        c.execute(text(stmt))
    assert _count(backend, table) == 1


@pytest.mark.parametrize("table", APPEND_ONLY_TABLES)
@pytest.mark.parametrize("verb", ["INSERT OR REPLACE INTO", "REPLACE INTO"])
def test_replace_cannot_rewrite_an_append_only_row(backend: Backend, table: str, verb: str) -> None:
    """EI-5: SQLite's ``REPLACE`` deletes the conflicting row and inserts the new one, and its
    implicit delete fired no ``BEFORE DELETE`` trigger unless ``recursive_triggers`` is on —
    so a rewritten row (re-hashed) verified clean. The product's engine turns it on for
    every connection, so the delete trigger refuses the rewrite. PostgreSQL has no
    ``REPLACE``; its upsert is ``ON CONFLICT DO UPDATE``, an UPDATE the row trigger refuses."""
    store_db.init_db(backend.engine)
    with backend.factory() as s:
        s.add(_one_row(table))
        s.commit()
    if backend.dialect == "postgresql":
        del verb  # one statement stands for both spellings
        stmt = (
            f"INSERT INTO {table} SELECT * FROM {table} "
            f"ON CONFLICT ({_pk(table)}) DO UPDATE SET repo = 'tampered'"
        )
    else:
        stmt = f"{verb} {table} SELECT * FROM {table}"
    with pytest.raises(DBAPIError, match="append-only"), backend.engine.begin() as c:
        c.execute(text(stmt))
    with backend.engine.connect() as c:
        assert (
            c.execute(text(f"SELECT COUNT(*) FROM {table} WHERE repo = 'tampered'")).scalar_one()
            == 0
        )
    assert _count(backend, table) == 1


def test_the_append_only_probe_is_ok_on_an_intact_store(backend: Backend) -> None:
    """Every expected trigger present, enabled and on its own table: the probe is ``ok`` and
    counts exactly the dialect's expected set."""
    from crb.observability.probes import OK
    from crb.server.routes.system import probe_append_only

    store_db.init_db(backend.engine)
    with backend.factory() as s:
        s.add(_one_row("grades"))
        s.commit()
    expected = len(store_db.expected_triggers(backend.dialect))
    res = probe_append_only(backend.factory)
    assert res.status == OK, res.detail
    assert res.data == {"triggers": expected, "expected": expected}


def test_the_append_only_probe_goes_down_when_a_trigger_is_disabled_or_moved(
    backend: Backend,
) -> None:
    """EI-4: the probe counted trigger NAMES, so a trigger the table's owner had disabled
    (``ALTER TABLE … DISABLE TRIGGER``) — or one of that name hung on another table — still
    read "append-only proven" while rows were deleted. It now counts only triggers that are
    on their own table, enabled, and call the append-only function."""
    from crb.observability.probes import DOWN
    from crb.server.routes.system import probe_append_only

    store_db.init_db(backend.engine)
    with backend.factory() as s:
        s.add(_one_row("grades"))
        s.commit()
    expected = len(store_db.expected_triggers(backend.dialect))
    with backend.engine.begin() as c:
        if backend.dialect == "postgresql":
            c.execute(text("ALTER TABLE events DISABLE TRIGGER events_no_delete"))
        else:  # SQLite cannot disable a trigger: the name moved onto an ordinary table
            c.execute(text("DROP TRIGGER events_no_delete"))
            c.execute(
                text(
                    "CREATE TRIGGER events_no_delete BEFORE DELETE ON repos "
                    "BEGIN SELECT RAISE(ABORT, 'events is append-only'); END;"
                )
            )
    res = probe_append_only(backend.factory)
    assert res.status == DOWN, res.detail
    assert res.data["triggers"] == expected - 1 and res.data["expected"] == expected
    assert res.data["missing"] == ["events_no_delete"]
    assert f"{expected - 1}/{expected} append-only triggers present" in res.detail


def test_a_trigger_neutered_by_a_when_clause_is_not_live_and_a_restart_heals_it(
    backend: Backend,
) -> None:
    """The skeptic on EI-4: liveness was read by name, table, event and function (or the
    RAISE text), not by the whole definition, so ``events_no_delete`` re-created with a
    never-true ``WHEN`` counted as live while every ``DELETE FROM events`` went through —
    and because the installer skips a live trigger, a restart no longer healed it. A
    trigger is now live only when its whole definition is the installer's own: the neutered
    one is ``down`` by name, and ``install_append_only_triggers`` re-creates it."""
    from crb.observability.probes import DOWN, OK
    from crb.server.routes.system import probe_append_only

    store_db.init_db(backend.engine)
    with backend.factory() as s:
        s.add(_one_row("grades"))
        s.add(_one_row("events"))
        s.commit()
    with backend.engine.begin() as c:
        if backend.dialect == "postgresql":
            c.execute(text("DROP TRIGGER events_no_delete ON events"))
            c.execute(
                text(
                    "CREATE TRIGGER events_no_delete BEFORE DELETE ON events FOR EACH ROW "
                    "WHEN (false) EXECUTE FUNCTION crb_append_only()"
                )
            )
        else:
            c.execute(text("DROP TRIGGER events_no_delete"))
            c.execute(
                text(
                    "CREATE TRIGGER events_no_delete BEFORE DELETE ON events WHEN 0 "
                    "BEGIN SELECT RAISE(ABORT, 'events is append-only'); END;"
                )
            )
    with backend.engine.connect() as c:
        assert "events_no_delete" not in store_db.live_triggers(c)
    res = probe_append_only(backend.factory)
    assert res.status == DOWN and res.data["missing"] == ["events_no_delete"], res.detail
    store_db.install_append_only_triggers(backend.engine)  # a restart's init_db
    assert probe_append_only(backend.factory).status == OK
    with pytest.raises(DBAPIError, match="append-only"), backend.engine.begin() as c:
        c.execute(text("DELETE FROM events"))
    assert _count(backend, "events") == 1


def test_the_append_only_probe_never_claims_an_update_it_did_not_try(backend: Backend) -> None:
    """The skeptic on EI-4: ``assert_append_only`` returns without writing anything when
    ``grades`` is empty, yet ``/health`` said "UPDATE on grades refused" on every fresh
    store. On an empty ledger the detail now says no UPDATE was tried (the live-trigger count
    still decides the status); once a row exists it says the UPDATE was refused."""
    from crb.observability.probes import OK
    from crb.server.routes.system import (
        APPEND_ONLY_OK_DETAIL,
        APPEND_ONLY_UNTRIED_DETAIL,
        probe_append_only,
    )
    from crb.store.ledger import assert_append_only

    store_db.init_db(backend.engine)
    assert assert_append_only(backend.factory) is False  # nothing to try
    res = probe_append_only(backend.factory)
    assert res.status == OK
    assert res.detail == APPEND_ONLY_UNTRIED_DETAIL, res.detail
    with backend.factory() as s:
        s.add(_one_row("grades"))
        s.commit()
    assert assert_append_only(backend.factory) is True  # tried, and refused
    res = probe_append_only(backend.factory)
    assert (res.status, res.detail) == (OK, APPEND_ONLY_OK_DETAIL)


def test_the_append_only_probe_counts_the_truncate_trigger(backend: Backend) -> None:
    """EI-4: on PostgreSQL the statement-level ``TRUNCATE`` trigger is part of the expected
    set, so a store that lacks it (one created before it existed, or one whose owner dropped
    it) is ``down`` until ``crb migrate`` or a restart re-installs it."""
    from crb.observability.probes import DOWN, OK
    from crb.server.routes.system import probe_append_only

    store_db.init_db(backend.engine)
    names = {name for _, name in store_db.expected_triggers(backend.dialect)}
    if backend.dialect != "postgresql":
        assert not any(n.endswith("_no_truncate") for n in names)
        return
    assert {f"{t}_no_truncate" for t in APPEND_ONLY_TABLES} <= names
    with backend.engine.begin() as c:
        c.execute(text("DROP TRIGGER grades_no_truncate ON grades"))
    assert probe_append_only(backend.factory).status == DOWN
    store_db.install_append_only_triggers(backend.engine)
    assert probe_append_only(backend.factory).status == OK


def test_the_append_only_probe_goes_down_when_replace_is_not_refused(tmp_path: Path) -> None:
    """EI-5: a SQLite connection without ``recursive_triggers`` lets ``REPLACE`` rewrite a row,
    and the probe (which tried only an UPDATE) said ``ok``. It now tries a ``REPLACE`` of the
    first ``grades`` row too, so a connection that would accept one is ``down``."""
    from sqlalchemy import create_engine

    from crb.observability.probes import DOWN
    from crb.server.routes.system import probe_append_only
    from crb.store.db import make_session_factory

    url = f"sqlite:///{tmp_path / 'crb.db'}"
    engine = store_db.make_engine(url)
    store_db.init_db(engine)
    with make_session_factory(engine)() as s:
        s.add(_one_row("grades"))
        s.commit()
    engine.dispose()
    bare = create_engine(url)  # no product pragmas: recursive_triggers is off
    try:
        res = probe_append_only(make_session_factory(bare))
        assert res.status == DOWN, res.detail
        assert "REPLACE" in res.detail
        with bare.connect() as c:
            assert c.execute(text("SELECT COUNT(*) FROM grades")).scalar_one() == 1
    finally:
        bare.dispose()


# ---------------------------------------------------------------------------
# an out-of-band event holds its trace's seq until it commits (EI-1)
# ---------------------------------------------------------------------------


def test_a_system_event_holds_its_trace_until_it_commits(backend: Backend) -> None:
    """EI-1: ``append_system_event`` read the trace's last ``seq`` and added the next one
    WITHOUT the write lock ``append_event`` takes, so a worker's event landing before the
    route committed took the same ``seq`` and the route answered a 500 after its side effect
    (a queue spent, a corpus line written). It now allocates under the same lock: the
    worker's event waits for the route's commit and takes the next ``seq``."""
    import threading

    from crb.server.routes.runs import append_system_event
    from crb.store.events import append_event

    store_db.init_db(backend.engine)
    trace = "l" * 32
    worker_out: dict[str, object] = {}

    def _worker() -> None:
        worker_out["event"] = append_event(
            backend.factory,
            trace_id=trace,
            stage="system",
            action="learn.prevention.recorded",
            repo="r",
        )

    with backend.factory() as s:
        mine = append_system_event(s, trace_id=trace, action="learn.remeasure.queued", repo="r")
        worker = threading.Thread(target=_worker)
        worker.start()
        worker.join(timeout=1.0)  # on the old code the worker commits here, with our seq
        s.commit()
    worker.join(timeout=30)
    assert not worker.is_alive()
    theirs = worker_out["event"]
    assert theirs is not None, "the worker's event was dropped"
    with backend.engine.connect() as c:
        seqs = [
            int(r[0])
            for r in c.execute(
                text("SELECT seq FROM events WHERE trace_id = :t ORDER BY seq"), {"t": trace}
            )
        ]
    assert mine.seq == 1 and getattr(theirs, "seq", None) == 2 and seqs == [1, 2]


def test_an_application_role_that_does_not_own_the_tables_cannot_remove_the_protection(
    backend: Backend,
) -> None:
    """EI-4, the root of it: on PostgreSQL the role that OWNS a table may disable, drop or
    re-create its triggers, so a deployment whose API and worker connect as the owner holds
    append-only only against its own good behaviour. Migrated by the owner, the store serves
    an application role granted ``SELECT``/``INSERT`` on the append-only tables: that role
    starts the API and the worker (``init_db`` issues no DDL on a store whose triggers are
    live), the migration job at head passes, the probe is ``ok`` — and TRUNCATE, disabling a
    trigger, dropping one, rewriting the trigger function and DDL on the table itself
    (retyping a column with ``USING``, dropping a column, dropping the table — each rewrites
    or removes rows with no trigger firing) are each refused to it."""
    import secrets

    from sqlalchemy.engine import make_url

    from crb.observability.probes import OK
    from crb.server.routes.system import probe_append_only
    from crb.store import migrate

    if backend.dialect != "postgresql":
        pytest.skip("SQLite has no roles: access to the file is the boundary (DEPLOYMENT §3.3)")
    migrate.upgrade(backend.url)  # the owner: the migration job's own role
    with backend.factory() as s:
        for table in APPEND_ONLY_TABLES:
            s.add(_one_row(table))
        s.commit()
    role, password = f"crb_app_{secrets.token_hex(4)}", secrets.token_hex(16)
    with backend.engine.begin() as c:
        schema = c.execute(text("SELECT current_schema()")).scalar_one()
        others = sorted(set(inspect(backend.engine).get_table_names()) - set(APPEND_ONLY_TABLES))
        c.execute(text(f"CREATE ROLE {role} LOGIN PASSWORD '{password}'"))
        c.execute(text(f"GRANT USAGE ON SCHEMA {schema} TO {role}"))
        c.execute(text(f"GRANT SELECT, INSERT ON {', '.join(APPEND_ONLY_TABLES)} TO {role}"))
        c.execute(text(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {', '.join(others)} TO {role}"))
        c.execute(text(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA {schema} TO {role}"))
    app_url = (
        make_url(backend.url)
        .set(username=role, password=password)
        .render_as_string(hide_password=False)
    )
    app = store_db.make_engine(app_url)
    try:
        store_db.init_db(app)  # the API's and the worker's own start
        migrate.upgrade(app_url)  # the chart's migration hook, at head
        assert probe_append_only(store_db.make_session_factory(app)).status == OK
        for stmt in (
            "TRUNCATE grades CASCADE",
            "ALTER TABLE grades DISABLE TRIGGER grades_no_delete",
            "DROP TRIGGER grades_no_delete ON grades",
            "CREATE OR REPLACE FUNCTION crb_append_only() RETURNS trigger AS "
            "$$ BEGIN RETURN NULL; END; $$ LANGUAGE plpgsql",
            # table DDL rewrites or removes rows with no trigger firing (the skeptic on
            # DL-081): only the owner may issue it, so the application role is refused
            "ALTER TABLE grades ALTER COLUMN model TYPE text USING 'a-model-that-never-ran'",
            "ALTER TABLE grades DROP COLUMN model",
            "DROP TABLE grades CASCADE",
            "DELETE FROM grades",
            "UPDATE events SET repo = 'tampered'",
        ):
            with (
                pytest.raises(DBAPIError, match=r"permission denied|must be owner|append-only"),
                app.begin() as c,
            ):
                c.execute(text(stmt))
        with store_db.make_session_factory(app)() as s:  # and it still appends
            s.add(Repo(name="app-role", language="python", runner="pytest", config_json={}))
            s.commit()
        assert _count(backend, "grades") == 1 and _count(backend, "events") == 1
    finally:
        app.dispose()
        with backend.engine.begin() as c:
            c.execute(text(f"DROP OWNED BY {role}"))
            c.execute(text(f"DROP ROLE {role}"))


def test_the_pg_function_raises_the_one_append_only_text() -> None:
    """The Wave 2 integration's merge spliced stream I's f-string body into feat/ns1's plain
    string, so PostgreSQL's ``crb_append_only()`` would have raised the literal
    ``{APPEND_ONLY_SUFFIX}`` and the probe, which takes only the trigger's own words as proof,
    would have read every refusal as another error. The function raises exactly the text the
    probe matches, on both dialects."""
    assert "{" not in store_db._PG_FUNCTION_SRC
    assert f"'%{store_db.APPEND_ONLY_SUFFIX}'" in store_db._PG_FUNCTION_SRC
    assert store_db.append_only_error_text("grades") in store_db._sqlite_trigger_sql(
        "grades", "grades_no_update"
    )
