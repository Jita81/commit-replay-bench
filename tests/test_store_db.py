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
              next start re-creates where the application owns the tables, and only the
              owner's ``crb migrate`` where it does not) and on an accepted REPLACE, and never
              claims an UPDATE it did not try on an empty ledger, that a PostgreSQL
              application role that does not own the tables starts with no DDL and cannot
              remove the protection nor issue table DDL nor write ``alembic_version``, under
              DEPLOYMENT §3.3's grants run as written, that a system event holds its
              trace's ``seq`` until it commits (EI-1) and the events write lock holds a second
              writer until the first commits (P-196), and that the ``users`` lock is never
              taken after the ``events`` lock, so an organisation sign-in and an admin act at
              once never deadlock (P-227), that the decisions clock joins a concurrent
              first stamp in both dialects (P-357), and that a link's withdrawal and an admin's
              password set wait for an acceptance under the ``users`` lock, with a ratchet on
              every route that withdraws or spends a link (P-785).
How:          ``conftest_store.backend`` gives an EMPTY database per dialect; one valid ORM row
              per append-only table is inserted and then attacked.
Layer:        tests — docs/ARCHITECTURE.md#73-data-model-store-p4
ADRs:         docs/adr/0002-append-only-hash-chained-ledger.md
Works with:   src/crb/store/db.py (under test), src/crb/store/models.py (``APPEND_ONLY_TABLES``
              and the rows), tests/conftest_store.py (the backends), tests/test_store_migrate.py
              (the same triggers through Alembic), docs/SECURITY.md (evidence integrity, §3.5),
              src/crb/server/routes/invitations.py and src/crb/server/routes/admin.py (P-785)
Tested by:    tests/test_store_db.py
Touch when:   never for a new repository; a table is added (decide whether it is
              append-only — if so, add it to ``APPEND_ONLY_TABLES`` and ``_one_row`` here, and a
              migration); a pragma changes.
"""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from crb.core.ledger import GENESIS_HASH
from crb.store import db as store_db
from crb.store.ledger import _to_model
from crb.store.models import (
    APPEND_ONLY_TABLES,
    Base,
    ClassLabelRow,
    ClassSetActRow,
    Event,
    EvidencePackRow,
    LibraryActRow,
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

#: DEPLOYMENT §3.3, whose SQL block the split-role tests run as written, so the guide's
#: grants and the proof cannot drift apart.
DEPLOYMENT = Path(__file__).resolve().parents[1] / "docs" / "DEPLOYMENT.md"


def _deployment_grants() -> str:
    """The ``sql`` block in DEPLOYMENT §3.3 that creates and grants ``crb_app``."""
    blocks = DEPLOYMENT.read_text(encoding="utf-8").split("```sql\n")[1:]
    found = [b.split("```", 1)[0] for b in blocks if "CREATE ROLE crb_app" in b]
    assert len(found) == 1, "DEPLOYMENT §3.3 holds one crb_app grant block"
    return found[0]


#: A table grant in the guide's SQL: its privileges, then the tables it names.
_TABLE_GRANT = r"GRANT ([A-Z, ]+?) ON (?!ALL |SCHEMA |DATABASE |TABLES |SEQUENCES )([\w, ]+?) TO"


def _grant_as_the_guide_says(
    c: Any,
    *,
    role: str,
    password: str = "",
    schema: str,
    sql: str = "",
    without: frozenset[str] = frozenset(),
) -> None:
    """Run DEPLOYMENT §3.3's grants (or ``sql``, another of the guide's blocks) on
    connection ``c`` (the owner's) for ``role``, with the test's database and schema in
    place of ``crb`` and ``public``. ``without`` drops tables from each table grant: the
    block as it read before a revision added them."""
    import re

    def drop(m: re.Match[str]) -> str:
        kept = [t.strip() for t in m.group(2).split(",") if t.strip() not in without]
        return f"GRANT {m.group(1)} ON {', '.join(kept)} TO"

    database = c.execute(text("SELECT current_database()")).scalar_one()
    sql = sql or _deployment_grants()
    sql = re.sub(r"\bcrb_app\b", role, sql).replace("'<secret>'", f"'{password}'")
    sql = sql.replace("DATABASE crb ", f"DATABASE {database} ")
    sql = sql.replace("SCHEMA public", f"SCHEMA {schema}")
    lines = [ln for ln in sql.splitlines() if not ln.lstrip().startswith("--")]
    joined = re.sub(_TABLE_GRANT, drop, " ".join(lines))
    for stmt in joined.split(";"):
        if stmt.strip():
            c.execute(text(stmt))


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
    if table == "library_acts":
        return LibraryActRow(
            act_id="l" * 32,
            schema="crb.library.v1",
            repo="r",
            entry_id="convention/snake-case",
            version="c" * 64,
            act="propose",
            actor="operator@example.org",
            body_json={"entry": {}},
            created="2026-09-27T12:00:00+00:00",
            prev_hash=GENESIS_HASH,
            row_hash="e" * 64,
        )
    if table == "class_set_acts":
        return ClassSetActRow(
            act_id="k" * 32,
            schema="crb.class_set.v1",
            org="acme",
            version_id="acme/classes@v1",
            digest="d" * 64,
            act="propose",
            actor="operator@example.org",
            body_json={"version": {}},
            created="2026-09-28T12:00:00+00:00",
            prev_hash=GENESIS_HASH,
            row_hash="f" * 64,
        )
    if table == "class_labels":
        return ClassLabelRow(
            label_id="m" * 32,
            taxonomy="acme/classes@v1",
            repo="r",
            task_id="x" * 40,
            capability_class="parser-fix",
            source="person",
            labeller="operator@example.org",
            created="2026-09-28T12:00:00+00:00",
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
        "library_acts": "seq",
        "class_set_acts": "seq",
        "class_labels": "seq",
    }[table]


def _col(table: str) -> str:
    """The text column a tampering UPDATE rewrites: the repository, or — for the class sets'
    acts, which belong to an organisation — the organisation."""
    return "org" if table == "class_set_acts" else "repo"


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


def test_the_events_lock_is_held_even_inside_a_transaction_already_open(
    backend: Backend,
) -> None:
    """P-429's rule for the events lock: ``BEGIN IMMEDIATE`` cannot run inside an open
    transaction, and a caller's deferred ``BEGIN`` holds no write lock, so the helper takes
    it explicitly (a zero-row write) instead of swallowing the refused ``BEGIN IMMEDIATE``.
    After it returns, a second connection must not be able to take SQLite's write lock.
    PostgreSQL's advisory lock has no such case (the concurrency test above covers it)."""
    import sqlite3

    from crb.store.events import lock_event_writes

    if backend.dialect != "sqlite":
        pytest.skip("SQLite's BEGIN IMMEDIATE only; PostgreSQL takes an advisory lock")
    store_db.init_db(backend.engine)
    database = backend.engine.url.database
    assert database
    with backend.factory() as s:
        s.execute(text("BEGIN"))  # a transaction, but no write lock
        lock_event_writes(s)
        other = sqlite3.connect(database, timeout=0)
        try:
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                other.execute("BEGIN IMMEDIATE")
        finally:
            other.close()
        s.rollback()


def test_a_refused_begin_immediate_already_took_sqlites_write_lock(tmp_path: Path) -> None:
    """The accident P-429's and P-430's records describe: SQLite compiles ``BEGIN IMMEDIATE``
    to ``OP_Transaction`` (which takes the write lock) BEFORE ``OP_AutoCommit`` (which raises
    "cannot start a transaction within a transaction"), so the old helpers that swallowed
    that error did hold the write lock. The fail-closed helpers no longer depend on that
    order; this test pins it, so the records are corrected if a SQLite release changes it."""
    import sqlite3

    database = tmp_path / "order.db"
    first = sqlite3.connect(database, isolation_level=None)
    other = sqlite3.connect(database, timeout=0, isolation_level=None)
    try:
        first.execute("CREATE TABLE t (x)")
        first.execute("BEGIN")  # deferred: no write lock yet
        with pytest.raises(sqlite3.OperationalError, match="within a transaction"):
            first.execute("BEGIN IMMEDIATE")
        with pytest.raises(sqlite3.OperationalError, match="locked"):
            other.execute("BEGIN IMMEDIATE")
    finally:
        other.close()
        first.close()


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
        c.execute(text(f"UPDATE {table} SET {_col(table)} = 'tampered'"))
    with backend.engine.connect() as c:
        assert (
            c.execute(
                text(f"SELECT COUNT(*) FROM {table} WHERE {_col(table)} = 'tampered'")
            ).scalar_one()
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
            f"ON CONFLICT ({_pk(table)}) DO UPDATE SET {_col(table)} = 'tampered'"
        )
    else:
        stmt = f"{verb} {table} SELECT * FROM {table}"
    with pytest.raises(DBAPIError, match="append-only"), backend.engine.begin() as c:
        c.execute(text(stmt))
    with backend.engine.connect() as c:
        assert (
            c.execute(
                text(f"SELECT COUNT(*) FROM {table} WHERE {_col(table)} = 'tampered'")
            ).scalar_one()
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
        _grant_as_the_guide_says(c, role=role, password=password, schema=schema)
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
            # only the owner migrates: the application reads the schema's version, and
            # writing it would let it hide an unapplied migration (PR #63 review)
            "UPDATE alembic_version SET version_num = 'a-head-that-never-ran'",
            "DELETE FROM alembic_version",
            "INSERT INTO alembic_version VALUES ('a-head-that-never-ran')",
        ):
            with (
                pytest.raises(DBAPIError, match=r"permission denied|must be owner|append-only"),
                app.begin() as c,
            ):
                c.execute(text(stmt))
        with store_db.make_session_factory(app)() as s:  # and it still appends
            s.add(Repo(name="app-role", language="python", runner="pytest", config_json={}))
            s.commit()
        with app.connect() as c:  # and reads the schema's version
            assert c.execute(text("SELECT count(*) FROM alembic_version")).scalar_one() == 1
        assert _count(backend, "grades") == 1 and _count(backend, "events") == 1
        # a table a later release adds gets the guide's default grant, the narrower one:
        # the application may read and append to it, never rewrite it
        with backend.engine.begin() as c:
            c.execute(text("CREATE TABLE a_later_table (id serial PRIMARY KEY, v text)"))
        with app.begin() as c:
            c.execute(text("INSERT INTO a_later_table (v) VALUES ('appended')"))
            assert c.execute(text("SELECT v FROM a_later_table")).scalar_one() == "appended"
        for stmt in ("UPDATE a_later_table SET v = 'x'", "DELETE FROM a_later_table"):
            with pytest.raises(DBAPIError, match="permission denied"), app.begin() as c:
                c.execute(text(stmt))
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


def test_the_guides_grants_name_every_table_and_only_the_owner_writes_the_version() -> None:
    """DEPLOYMENT §3.3's grants, read as text on every run (the split-role tests execute
    them only on PostgreSQL): each model table is granted exactly once, the append-only
    ones ``SELECT, INSERT`` only, ``alembic_version`` ``SELECT`` only (a review of PR #63:
    the guide gave the application DML on it, though only the owner migrates), and the
    owner's later tables and sequences get default grants."""
    import re

    sql = " ".join(
        ln for ln in _deployment_grants().splitlines() if not ln.lstrip().startswith("--")
    )
    grants: dict[str, str] = {}
    for privs, tables in re.findall(_TABLE_GRANT, sql):
        for t in (x.strip() for x in tables.split(",")):
            assert t not in grants, f"{t} is granted twice"
            grants[t] = " ".join(privs.split())
    assert set(grants) == set(Base.metadata.tables) | {"alembic_version"}
    for t in APPEND_ONLY_TABLES:
        assert grants[t] == "SELECT, INSERT", t
    assert grants["alembic_version"] == "SELECT"
    assert "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT ON TABLES" in sql
    assert "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES" in sql


#: The first revision released after DEPLOYMENT §3.3 began giving a later release's tables
#: the default ``SELECT, INSERT`` grant (PR #63, 2026-09-28). A table a revision from here
#: on adds reaches an upgraded split-role store with that grant alone.
_DEFAULT_GRANT_FROM = "0013"


def _later_rewritable_tables() -> list[tuple[str, str]]:
    """``(revision, table)`` for each table §3.3 grants ``UPDATE, DELETE`` that a revision
    from :data:`_DEFAULT_GRANT_FROM` on added: on a store upgraded across that revision it
    holds the default grant alone."""
    import re

    from crb.store.migrate import REVISION_TABLES

    sql = " ".join(
        ln for ln in _deployment_grants().splitlines() if not ln.lstrip().startswith("--")
    )
    rewritable = {
        t.strip()
        for privs, tables in re.findall(_TABLE_GRANT, sql)
        if " ".join(privs.split()) == "SELECT, INSERT, UPDATE, DELETE"
        for t in tables.split(",")
    }
    return [(r, t) for r, t in REVISION_TABLES if r >= _DEFAULT_GRANT_FROM and t in rewritable]


def _upgrade_notes() -> dict[str, str]:
    """DEPLOYMENT §6's "Upgrading to revision" notes, keyed by each revision their heading
    names. A note runs to the next one, so its ``sql`` block is part of it."""
    import re

    page = DEPLOYMENT.read_text(encoding="utf-8")
    upgrade = page.split("\n## 6. Upgrade\n", 1)[1].split("\n## 7. ", 1)[0]
    notes: dict[str, str] = {}
    for note in re.split(r"\n(?=\*\*Upgrading to )", upgrade):
        head = re.match(r"\*\*Upgrading to revisions? ([^*]+)\*\*", note)
        for rev in re.findall(r"`(\d{4})`", head.group(1)) if head else []:
            notes[rev] = notes.get(rev, "") + "\n" + note
    return notes


def test_a_later_table_the_application_rewrites_has_an_upgrade_note_that_grants_it() -> None:
    """A table §3.3 grants ``UPDATE, DELETE`` that a revision after the default grant added
    is only ``SELECT, INSERT`` on a split-role store upgraded across that revision, so the
    application's first rewrite of it is refused with ``permission denied``. Revisions 0014
    and 0015 shipped ``invitations`` and ``decisions_due`` that way with no note (P-754).
    §3.3 says the release's upgrade notes name the grant: §6 must hold an "Upgrading to
    revision" note that names the revision, the table and ``UPDATE, DELETE``."""
    import re

    later, notes = _later_rewritable_tables(), _upgrade_notes()
    assert later, "no later table is rewritable: the check reads nothing"
    missing = [
        f"{t} (revision {r})"
        for r, t in later
        if not re.search(rf"\b{t}\b", notes.get(r, ""))
        or "UPDATE, DELETE" not in " ".join(notes.get(r, "").split())
    ]
    assert not missing, f"DEPLOYMENT §6 has no upgrade note granting UPDATE, DELETE on {missing}"


def test_the_upgrade_notes_grant_lets_the_application_rewrite_each_later_table(
    backend: Backend,
) -> None:
    """P-754 on PostgreSQL: a split-role store granted as §3.3 read before the later tables
    existed, then upgraded to head by the owner, refuses the application ``UPDATE`` and
    ``DELETE`` on each later table it rewrites; the ``sql`` block of that table's §6 note,
    run as the owner, lets it."""
    import re
    import secrets

    from sqlalchemy.engine import make_url

    from crb.store import migrate
    from crb.store.migrate import REVISION_TABLES

    if backend.dialect != "postgresql":
        pytest.skip("SQLite has no roles: there is no grant to miss (DEPLOYMENT §3.3)")
    later, notes = _later_rewritable_tables(), _upgrade_notes()
    added = frozenset(t for r, t in REVISION_TABLES if r >= _DEFAULT_GRANT_FROM)
    migrate.upgrade(backend.url, revision=f"{int(_DEFAULT_GRANT_FROM) - 1:04d}")
    role, password = f"crb_app_{secrets.token_hex(4)}", secrets.token_hex(16)
    with backend.engine.begin() as c:
        schema = c.execute(text("SELECT current_schema()")).scalar_one()
        _grant_as_the_guide_says(c, role=role, password=password, schema=schema, without=added)
    migrate.upgrade(backend.url)  # the owner's migration job, across the later revisions
    app_url = (
        make_url(backend.url)
        .set(username=role, password=password)
        .render_as_string(hide_password=False)
    )
    app = store_db.make_engine(app_url)

    def rewrites(table: str) -> tuple[str, str]:
        col = next(c.name for c in Base.metadata.tables[table].columns if not c.primary_key)
        return f"UPDATE {table} SET {col} = {col}", f"DELETE FROM {table}"

    try:
        for _, table in later:
            for stmt in rewrites(table):
                with pytest.raises(DBAPIError, match="permission denied"), app.begin() as c:
                    c.execute(text(stmt))
        blocks = {re.search(r"```sql\n(.*?)```", notes.get(r, ""), re.S) for r, _ in later}
        assert None not in blocks, "a later table's upgrade note holds no sql block"
        with backend.engine.begin() as c:
            for sql in sorted({b.group(1) for b in blocks if b}):
                _grant_as_the_guide_says(c, role=role, schema=schema, sql=sql)
        for _, table in later:
            for stmt in rewrites(table):
                with app.begin() as c:
                    c.execute(text(stmt))
    finally:
        app.dispose()
        with backend.engine.begin() as c:
            c.execute(text(f"DROP OWNED BY {role}"))
            c.execute(text(f"DROP ROLE {role}"))


def test_a_trigger_missing_on_a_split_role_store_is_restored_by_the_owner_not_the_application(
    backend: Backend,
) -> None:
    """DEPLOYMENT §3.3 said the next start re-creates a trigger that is not live. That holds
    only where the application owns the tables: on a split-role store the owner may drop a
    trigger, the probe goes ``down`` naming it, and the application role's own start
    (``init_db``) is refused — it may not issue trigger DDL — so the guide sends the operator
    to ``crb migrate`` as the owner, which restores it."""
    import secrets

    from sqlalchemy.engine import make_url

    from crb.observability.probes import DOWN, OK
    from crb.server.routes.system import probe_append_only
    from crb.store import migrate

    if backend.dialect != "postgresql":
        pytest.skip("SQLite has no roles: the application and the owner are one (DEPLOYMENT §3.3)")
    migrate.upgrade(backend.url)
    role, password = f"crb_app_{secrets.token_hex(4)}", secrets.token_hex(16)
    with backend.engine.begin() as c:
        schema = c.execute(text("SELECT current_schema()")).scalar_one()
        _grant_as_the_guide_says(c, role=role, password=password, schema=schema)
        c.execute(text("DROP TRIGGER grades_no_delete ON grades"))  # the owner may
    app_url = (
        make_url(backend.url)
        .set(username=role, password=password)
        .render_as_string(hide_password=False)
    )
    app = store_db.make_engine(app_url)
    try:
        probe = probe_append_only(store_db.make_session_factory(app))
        assert probe.status == DOWN and probe.data["missing"] == ["grades_no_delete"]
        with pytest.raises(DBAPIError, match=r"permission denied|must be owner"):
            store_db.init_db(app)  # the API's and the worker's start cannot restore it
        assert probe_append_only(store_db.make_session_factory(app)).status == DOWN
        migrate.upgrade(backend.url)  # `crb migrate` as the owner
        assert probe_append_only(store_db.make_session_factory(app)).status == OK
    finally:
        app.dispose()
        with backend.engine.begin() as c:
            c.execute(text(f"DROP OWNED BY {role}"))
            c.execute(text(f"DROP ROLE {role}"))


def test_the_users_lock_is_never_taken_after_the_events_lock(backend: Backend) -> None:
    """P-227: the organisation sign-in under ``role_from_claims=always`` took the ``events``
    write lock (the audited commit) and then the ``users`` lock, while every admin act takes
    ``users`` and then ``events``; on PostgreSQL the two orders deadlock. The one order is
    ``users`` before ``events`` in a transaction, and taking them the other way round is
    refused at once — on either dialect, so a test on SQLite catches it too. Re-taking a
    lock the transaction already holds is not an inversion."""
    from crb.server.auth import lock_users_table
    from crb.store.events import LockOrderError, lock_event_writes

    store_db.init_db(backend.engine)
    with backend.factory() as s:
        lock_event_writes(s)
        with pytest.raises(LockOrderError, match="users lock"):
            lock_users_table(s)
        s.rollback()
    with backend.factory() as s:  # the order the rule names, and re-entry, both hold
        lock_users_table(s)
        lock_event_writes(s)
        lock_users_table(s)
        s.commit()
    with backend.factory() as s:  # a new transaction starts with no lock held
        lock_event_writes(s)
        s.commit()
        lock_users_table(s)
        s.commit()


def test_an_organisation_sign_in_and_an_admin_act_at_once_never_deadlock(
    backend: Backend, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """P-227, end to end: an ``always`` sign-in held just before it takes the ``users`` lock,
    and an admin deactivating another account held just after it took it, both released at
    once. On PostgreSQL the sign-in once held the ``events`` lock there, the database
    detected the deadlock and the sign-in failed (``DeadlockDetected``, a 500). Now both
    complete: the sign-in takes ``users`` first, so it waits for the admin's commit."""
    import os
    import threading

    from fastapi.testclient import TestClient

    import crb.server.routes.admin as admin_routes
    import crb.server.routes.auth as auth_routes
    from crb.server.app import create_app
    from fixtures.concurrency import at_once, pause_after
    from fixtures.server_seed import API_PREFIX, add_users, login, make_settings, user_id

    try:
        from tests.test_server_auth import OIDC_SETTINGS, FakeOidc, _oidc_login
    except ImportError:  # pragma: no cover — rootdir-relative import (pytest default)
        from test_server_auth import OIDC_SETTINGS, FakeOidc, _oidc_login

    for key in [k for k in os.environ if k.startswith("CRB_")]:
        monkeypatch.delenv(key, raising=False)
    store_db.init_db(backend.engine)
    add_users(backend.factory)
    fake = FakeOidc({"sub": "entra-oid-1", "name": "Ada", "groups": ["grp-crb-admins"]})
    settings = make_settings(tmp_path, oidc={**OIDC_SETTINGS, "role_from_claims": "always"})
    app = create_app(settings, backend.factory, oidc_client=fake)
    with TestClient(app) as admin:
        login(admin, "admin")
        _oidc_login(app, settings).__exit__(None, None, None)  # the account exists
        gate = threading.Barrier(2)
        real_lock = auth_routes.lock_users_table

        def sign_in_waits_before_users(db: object) -> None:
            with contextlib.suppress(threading.BrokenBarrierError):
                gate.wait(timeout=5)
            real_lock(db)  # type: ignore[arg-type]

        monkeypatch.setattr(auth_routes, "lock_users_table", sign_in_waits_before_users)
        pause_after(monkeypatch, admin_routes, "set_user_active", gate, timeout=5)

        def sign_in() -> int:
            c = _oidc_login(app, settings)
            c.__exit__(None, None, None)
            return 302

        viewer = user_id("viewer1")
        results = at_once(
            sign_in,
            lambda: (
                admin.put(f"{API_PREFIX}/users/{viewer}/active", json={"active": False}).status_code
            ),
        )
    assert results == [302, 200], results


# ---------------------------------------------------------------------------
# an invitation's link is spent, withdrawn or superseded one at a time (P-785)
# ---------------------------------------------------------------------------

#: the password the invited person chooses on the link's page, and the one the admin sets
CHOSEN_PW = "the-person-chose-this-one"
ADMIN_PW = "the-admin-set-this-one-instead"


def _invited(
    backend: Backend, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, admin: Any
) -> tuple[dict[str, Any], Any]:
    """``admin`` (a ``TestClient`` on the app :func:`_app` built) signs in as the seed's admin
    and invites ``dana``; the acceptance of that link is then held at the barrier returned,
    after it took the ``users`` lock and read the link as pending and before it writes
    anything. Returns the invitation as created, and the barrier the other request meets."""
    import threading

    import crb.server.routes.invitations as invitation_routes
    from fixtures.concurrency import pause_after
    from fixtures.server_seed import API_PREFIX, login

    login(admin, "admin")
    r = admin.post(f"{API_PREFIX}/invitations", json={"username": "dana"})
    assert r.status_code == 201, r.text
    gate = threading.Barrier(2)
    # ``is_local_account`` is the acceptance's first call after its read of the link
    pause_after(monkeypatch, invitation_routes, "is_local_account", gate, timeout=5)
    return dict(r.json()), gate


def _app(backend: Backend, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    """The application on ``backend`` with the seed's accounts and no ambient settings."""
    import os

    from crb.server.app import create_app
    from fixtures.server_seed import add_users, make_settings

    for key in [k for k in os.environ if k.startswith("CRB_")]:
        monkeypatch.delenv(key, raising=False)
    store_db.init_db(backend.engine)
    add_users(backend.factory)
    return create_app(make_settings(tmp_path), backend.factory)


def _accept(app: Any, token: str) -> Any:
    from fastapi.testclient import TestClient

    from fixtures.server_seed import API_PREFIX

    return TestClient(app).post(
        f"{API_PREFIX}/invitations/accept", json={"token": token, "password": CHOSEN_PW}
    )


def _invite_actions(backend: Backend) -> list[str]:
    """What became of the link: the ``user.invite_*`` events, not the ``user.invited`` one."""
    with backend.factory() as s:
        rows = s.execute(text("SELECT action FROM events WHERE action LIKE 'user.invite%'"))
        return sorted(a for (a,) in rows if a.startswith("user.invite_"))


def test_a_link_withdrawn_while_it_is_being_accepted_is_refused_not_stamped_twice(
    backend: Backend, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CodeRabbit on #81, 2026-10-10: the withdraw route read the invitation before it took
    the ``users`` lock. On both dialects a withdrawal that read ``pending`` while an
    acceptance was in flight stamped ``revoked`` on a link the acceptance then stamped
    ``accepted``: one invitation with both stamps and both events, and an open account the
    list called withdrawn. The acceptance is held after it read the link as pending, with
    the lock held; the withdrawal is let go at that moment. It now waits for the lock, reads
    the spent link and is refused (409 ``already_accepted``), and the link carries one
    stamp."""
    from fastapi.testclient import TestClient

    from crb.store.models import Invitation

    app = _app(backend, tmp_path, monkeypatch)
    with TestClient(app) as admin:
        made, gate = _invited(backend, tmp_path, monkeypatch, admin)
        accepted, withdrawn = _accept_and_withdraw(app, admin, made, gate, monkeypatch)
    codes = [getattr(r, "status_code", r) for r in (accepted, withdrawn)]
    assert codes == [200, 409], codes
    assert withdrawn.json()["error"]["code"] == "already_accepted"
    inv_id = made["invitation"]["id"]
    with backend.factory() as s:
        inv = s.get(Invitation, inv_id)
        assert inv is not None and inv.accepted and not inv.revoked
    assert _invite_actions(backend) == ["user.invite_accepted"]


def _accept_and_withdraw(
    app: Any, admin: Any, made: dict[str, Any], gate: Any, monkeypatch: pytest.MonkeyPatch
) -> list[Any]:
    """The held acceptance and the admin's withdrawal of the same link, at once. The
    withdrawal starts once the acceptance holds the ``users`` lock, and meets it at ``gate``
    just before it asks for that lock itself."""
    import itertools
    import threading

    import crb.server.routes.invitations as invitation_routes
    from fixtures.concurrency import at_once
    from fixtures.server_seed import API_PREFIX

    inv_id = made["invitation"]["id"]
    locked = threading.Event()
    calls = itertools.count()
    real_lock = invitation_routes.lock_users_table

    def lock(db: object) -> None:
        if next(calls) == 0:  # the acceptance's own lock, taken first
            real_lock(db)  # type: ignore[arg-type]
            locked.set()
            return
        # the withdrawal meets the held acceptance here, then asks for the lock
        with contextlib.suppress(threading.BrokenBarrierError):
            gate.wait(timeout=5)
        real_lock(db)  # type: ignore[arg-type]

    monkeypatch.setattr(invitation_routes, "lock_users_table", lock)

    def withdraw() -> Any:
        assert locked.wait(timeout=5), "the acceptance never took the users lock"
        return admin.post(
            f"{API_PREFIX}/invitations/{inv_id}/revoke", json={"reason": "sent to the wrong person"}
        )

    return at_once(lambda: _accept(app, made["token"]), withdraw)


def test_an_admin_password_set_while_the_link_is_being_accepted_waits_its_turn(
    backend: Backend, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CodeRabbit on #81, 2026-10-10: the admin's password route read the account before it
    took the ``users`` lock. On PostgreSQL it set the admin's password and withdrew the link
    while an acceptance that had already read the link as pending went on: it activated the
    account, replaced the admin's password with the person's and stamped the withdrawn link
    accepted. The acceptance is held after its read, with the lock held; the admin's
    request is let go at that moment. It now waits for the lock: the acceptance completes,
    then the admin's password is set over it and withdraws nothing, because nothing is
    pending."""
    import threading

    from fastapi.testclient import TestClient

    import crb.server.routes.admin as admin_routes
    from crb.store.models import Invitation
    from fixtures.concurrency import at_once
    from fixtures.server_seed import API_PREFIX

    app = _app(backend, tmp_path, monkeypatch)
    real_lock = admin_routes.lock_users_table

    def admin_waits_before_users(db: object) -> None:
        with contextlib.suppress(threading.BrokenBarrierError):
            gate.wait(timeout=5)
        real_lock(db)  # type: ignore[arg-type]

    with TestClient(app) as admin:
        made, gate = _invited(backend, tmp_path, monkeypatch, admin)
        uid, inv_id = made["invitation"]["user_id"], made["invitation"]["id"]
        monkeypatch.setattr(admin_routes, "lock_users_table", admin_waits_before_users)
        accepted, set_by_admin = at_once(
            lambda: _accept(app, made["token"]),
            lambda: admin.put(f"{API_PREFIX}/users/{uid}/password", json={"password": ADMIN_PW}),
        )
    codes = [getattr(r, "status_code", r) for r in (accepted, set_by_admin)]
    assert codes == [200, 200], codes
    with backend.factory() as s:
        inv = s.get(Invitation, inv_id)
        assert inv is not None and inv.accepted and not inv.revoked
    assert _invite_actions(backend) == ["user.invite_accepted"]

    assert (_sign_in(app, ADMIN_PW), _sign_in(app, CHOSEN_PW)) == (200, 401)


#: the password the person changes theirs to on their own account page
SELF_PW = "the-person-changed-it-to-this"


def _sign_in(app: Any, password: str) -> int:
    """The status of ``dana``'s sign-in with ``password``, on a client of its own."""
    from fastapi.testclient import TestClient

    from fixtures.server_seed import API_PREFIX

    r = TestClient(app).post(
        f"{API_PREFIX}/auth/login", json={"username": "dana", "password": password}
    )
    return r.status_code


def _dana_signed_in(app: Any, admin: Any) -> tuple[str, Any]:
    """``admin`` signs in as the seed's admin and invites ``dana``, who accepts the link with
    :data:`CHOSEN_PW` and signs in on a client of their own. Returns the account's id and
    that client, its CSRF header set."""
    from fastapi.testclient import TestClient

    from fixtures.server_seed import API_PREFIX, login

    login(admin, "admin")
    r = admin.post(f"{API_PREFIX}/invitations", json={"username": "dana"})
    assert r.status_code == 201, r.text
    made = r.json()
    accepted = _accept(app, made["token"])
    assert accepted.status_code == 200, accepted.text
    dana = TestClient(app)
    r = dana.post(f"{API_PREFIX}/auth/login", json={"username": "dana", "password": CHOSEN_PW})
    assert r.status_code == 200, r.text
    dana.headers["X-CSRF-Token"] = dana.cookies["crb_csrf"]
    return made["invitation"]["user_id"], dana


def _change_own(dana: Any) -> Any:
    from fixtures.server_seed import API_PREFIX

    return dana.put(
        f"{API_PREFIX}/users/me/password",
        json={"current_password": CHOSEN_PW, "new_password": SELF_PW},
    )


#: an admin's act on ``dana`` — method, path under the account, body — with the password the
#: account keeps after it and the code the racing change is refused with
ADMIN_ACTS: dict[str, tuple[str, str, dict[str, Any] | None, str, str]] = {
    "reset": ("put", "/password", {"password": ADMIN_PW}, ADMIN_PW, "session_revoked"),
    "sign_out_everywhere": ("post", "/sessions/revoke", None, CHOSEN_PW, "session_revoked"),
    "disable": ("put", "/active", {"active": False}, CHOSEN_PW, "unauthenticated"),
}


@pytest.mark.parametrize("act", sorted(ADMIN_ACTS))
def test_an_admin_act_while_the_person_changes_their_own_password_holds(
    backend: Backend, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, act: str
) -> None:
    """Found widening #85's ratchet to every route that writes an account, 2026-10-10: the
    self-service password change took no ``users`` lock. A change that had verified the
    current password went on to store its own while an admin's reset committed in between:
    the reset was lost, and the account opened with the person's password, not the admin's.
    A sign-out everywhere or a disable in that gap was lost the same way, and the change set
    a fresh cookie for the session the admin had ended. The change verifies before the lock
    (argon2 is slow) and is held there while the admin acts; under the lock it reads the
    account again, finds its session ended, and writes nothing."""
    import threading

    from fastapi.testclient import TestClient

    import crb.server.routes.admin as admin_routes
    from crb.server.auth import verify_password
    from crb.store.models import User
    from fixtures.concurrency import at_once
    from fixtures.server_seed import API_PREFIX

    method, path, body, kept, refused_with = ADMIN_ACTS[act]
    app = _app(backend, tmp_path, monkeypatch)
    verified, acted = threading.Event(), threading.Event()
    real_verify = admin_routes.verify_password

    def verify_then_wait(stored: str, password: str) -> bool:
        ok = real_verify(stored, password)
        verified.set()
        # a change that verified under the lock would keep the admin waiting: this times out
        acted.wait(timeout=5)
        return ok

    with TestClient(app) as admin:
        uid, dana = _dana_signed_in(app, admin)
        monkeypatch.setattr(admin_routes, "verify_password", verify_then_wait)

        def admin_acts() -> Any:
            assert verified.wait(timeout=5), "the change never verified the password"
            url = f"{API_PREFIX}/users/{uid}{path}"
            r = admin.request(method.upper(), url, json=body)
            acted.set()
            return r

        changed, by_admin = at_once(lambda: _change_own(dana), admin_acts)
    codes = [getattr(r, "status_code", r) for r in (changed, by_admin)]
    assert codes == [401, 200], codes
    assert changed.json()["error"]["code"] == refused_with
    with backend.factory() as s:
        row = s.get(User, uid)
        assert row is not None and row.password_hash is not None
        assert (verify_password(row.password_hash, kept), row.active) == (True, act != "disable")
        assert not verify_password(row.password_hash, SELF_PW)


@pytest.mark.parametrize("by", ["admin", "self"])
def test_a_sign_out_everywhere_while_the_person_changes_their_password_holds(
    backend: Backend, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, by: str
) -> None:
    """Found widening #85's ratchet to every write of a session nonce, 2026-10-10: a sign-out
    everywhere — an admin's, or the person's own logout on another device — rotated the
    nonce without the users lock. One that came while a password change held the lock,
    after the change had found its session current, committed first; the change then set a
    fresh cookie for the session that had just been ended, and it stayed signed in. The
    change is held under the lock until the sign-out has reached the lock; the sign-out
    waits there until the change commits, then reads the account again: an admin's ends
    every session, the change's fresh one too, and the other device's logout finds its
    session already ended by the change and rotates nothing."""
    import threading

    from fastapi.testclient import TestClient

    import crb.server.routes.admin as admin_routes
    import crb.server.routes.auth as auth_routes
    from crb.server.auth import verify_password
    from crb.store.models import User
    from fixtures.concurrency import at_once
    from fixtures.server_seed import API_PREFIX

    app = _app(backend, tmp_path, monkeypatch)
    held, reached = threading.Event(), threading.Event()
    real_refuse, real_lock = admin_routes.refuse_an_ended_session, admin_routes.lock_users_table
    refused: list[bool] = []

    def refuse_then_hold(user: Any, cv: str) -> Any:
        account = real_refuse(user, cv)
        if not refused:
            refused.append(True)
            held.set()  # under the lock, the session found current
            # a sign-out that does not wait for the lock never reaches it: this times out
            reached.wait(timeout=3)
        return account

    def lock_then_note(db: Any) -> None:
        if held.is_set():
            reached.set()
        real_lock(db)

    with TestClient(app) as admin:
        uid, dana = _dana_signed_in(app, admin)
        other = TestClient(app)  # the person's other device
        r = other.post(f"{API_PREFIX}/auth/login", json={"username": "dana", "password": CHOSEN_PW})
        assert r.status_code == 200, r.text
        other.headers["X-CSRF-Token"] = other.cookies["crb_csrf"]
        monkeypatch.setattr(admin_routes, "refuse_an_ended_session", refuse_then_hold)
        monkeypatch.setattr(admin_routes, "lock_users_table", lock_then_note)
        monkeypatch.setattr(auth_routes, "lock_users_table", lock_then_note)

        def signs_out() -> Any:
            assert held.wait(timeout=5), "the change never took the lock"
            try:
                if by == "admin":
                    return admin.post(f"{API_PREFIX}/users/{uid}/sessions/revoke")
                return other.post(f"{API_PREFIX}/auth/logout")
            finally:
                reached.set()

        changed, signed_out = at_once(lambda: _change_own(dana), signs_out)
        me = dana.get(f"{API_PREFIX}/auth/me").status_code
    codes = [getattr(r, "status_code", r) for r in (changed, signed_out)]
    with backend.factory() as s:
        row = s.get(User, uid)
        assert row is not None and row.password_hash is not None
        rows = s.execute(text("SELECT action FROM events WHERE action LIKE 'user.sessions_%'"))
        ended = sorted(a for (a,) in rows)
        kept = verify_password(row.password_hash, SELF_PW)
    if by == "admin":
        # the change committed first; the sign-out everywhere ended its fresh session too
        assert (codes, kept, ended, me) == ([200, 200], True, ["user.sessions_revoked"], 401)
    else:
        # the change committed first and ended the other device's session itself: the
        # logout found it ended and rotated nothing, and this device stays signed in
        assert (codes, kept, ended, me) == ([200, 204], True, [], 200)


def test_a_sign_in_that_straddles_an_admin_reset_is_refused(
    backend: Backend, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Found widening #85's ratchet to every write of a password hash, 2026-10-10: a sign-in
    verified the password, then wrote the account (its last sign-in, and an argon2 upgrade
    of the hash) without the users lock. An admin's reset that committed in between was
    undone by the upgrade, and the old password opened the account again; without an
    upgrade the sign-in still got a session for the password the reset had replaced. The
    sign-in verifies before the lock (argon2 is slow) and is held there while the admin
    resets; under the lock it reads the account again, finds the hash moved, checks the
    password against the new one and is refused."""
    _straddles_a_reset(backend, tmp_path, monkeypatch, rehash=False)


def test_a_sign_in_that_straddles_an_admin_reset_never_upgrades_over_it(
    backend: Backend, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The sign-in of :func:`test_a_sign_in_that_straddles_an_admin_reset_is_refused`, with
    argon2's parameters moved on since the hash was made: the upgrade it hashed before the
    lock is of the old password, and it is never stored over the reset."""
    _straddles_a_reset(backend, tmp_path, monkeypatch, rehash=True)


def _straddles_a_reset(
    backend: Backend, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, rehash: bool
) -> None:
    import threading

    from fastapi.testclient import TestClient
    from sqlalchemy import select

    import crb.server.auth as auth_mod
    from fixtures.concurrency import at_once
    from fixtures.server_seed import API_PREFIX

    app = _app(backend, tmp_path, monkeypatch)
    verified, reset = threading.Event(), threading.Event()
    real_verify, real_hasher = auth_mod.verify_password, auth_mod.hasher
    checked: list[bool] = []

    class _Outdated:
        """argon2's hasher, with every stored hash made under parameters since moved on."""

        def __getattr__(self, name: str) -> Any:
            return getattr(real_hasher, name)

        def check_needs_rehash(self, stored: str) -> bool:
            return True

    def verify_then_wait(stored: str, password: str) -> bool:
        ok = real_verify(stored, password)
        if not checked:
            checked.append(True)
            verified.set()
            # a sign-in that verified under the lock would keep the admin waiting: this
            # times out
            reset.wait(timeout=5)
        return ok

    with TestClient(app) as admin:
        uid, _ = _dana_signed_in(app, admin)
        if rehash:
            monkeypatch.setattr(auth_mod, "hasher", _Outdated())
        monkeypatch.setattr(auth_mod, "verify_password", verify_then_wait)

        def signs_in() -> Any:
            return TestClient(app).post(
                f"{API_PREFIX}/auth/login", json={"username": "dana", "password": CHOSEN_PW}
            )

        def admin_resets() -> Any:
            assert verified.wait(timeout=5), "the sign-in never verified the password"
            try:
                return admin.put(f"{API_PREFIX}/users/{uid}/password", json={"password": ADMIN_PW})
            finally:
                reset.set()

        signed_in, by_admin = at_once(signs_in, admin_resets)
    codes = [getattr(r, "status_code", r) for r in (signed_in, by_admin)]
    assert codes == [401, 200], codes
    assert signed_in.json()["error"]["code"] == "invalid_credentials"
    # a refusal like any other: on the account's trail, and still counted by the limiter
    with app.state.session_factory() as s:
        failed = s.scalars(select(Event).where(Event.action == "user.login_failed")).all()
        assert [(e.payload_json["target"], e.payload_json["reason"]) for e in failed] == [
            (uid, "invalid_credentials")
        ]
    limiter, limit = app.state.login_limiter, app.state.login_limiter.limit
    limiter.limit = 1  # the refused attempt holds the one slot this leaves
    assert _sign_in(app, ADMIN_PW) == 429
    limiter.limit = limit
    assert (_sign_in(app, ADMIN_PW), _sign_in(app, CHOSEN_PW)) == (200, 401)


def test_an_admin_route_reads_the_account_from_the_database_not_the_session(
    backend: Backend,
) -> None:
    """``_get_user`` is the admin routes' read of an account under the ``users`` lock, so it
    reads the row: a copy the same session still holds from before the lock — the identity
    map's, which a plain ``get`` answers from without a query — is refreshed, never
    returned as it was (P-785)."""
    from crb.server.routes.admin import _get_user
    from crb.store.models import User
    from fixtures.server_seed import add_users, user_id

    store_db.init_db(backend.engine)
    add_users(backend.factory)
    uid = user_id("viewer1")
    with backend.factory() as held, backend.factory() as other:
        before = held.get(User, uid)  # held, as a route would hold it across its lock
        assert before is not None
        row = other.get(User, uid)
        assert row is not None
        row.display_name = "changed in another session"
        other.commit()
        assert _get_user(held, uid).display_name == "changed in another session"


#: what writes an account's password hash, session nonce or active flag, or withdraws every
#: pending link — and, beside these, a route's own stamp on an ``Invitation`` and any helper
#: that calls one
USERS_WRITERS = frozenset(
    {
        "supersede_invitations",
        "set_password",
        "set_account_active",
        "set_user_active",
        "rotate_session_nonce",
        "upgrade_password_hash",
    }
)
#: the account's fields that the users lock guards: every assignment of one is in a writer
ACCOUNT_FIELDS = frozenset({"password_hash", "session_nonce", "active"})
LINK_STAMPS = frozenset({"revoked", "accepted"})
ROUTE_VERBS = frozenset({"get", "post", "put", "patch", "delete", "api_route"})
#: a parameter is a session when it is named ``db`` or annotated with one of these
SESSION_TYPES = frozenset({"DbDep", "Session"})
#: what the ratchet finds in the routes package today: a route that leaves it fell out of
#: the class, or out of the ratchet's sight
USERS_WRITING_ROUTES = {
    "admin.py": {
        "set_role",
        "change_own_password",
        "set_user_password",
        "set_active",
        "revoke_user_sessions",
    },
    "auth.py": {"login", "logout"},
    "invitations.py": {"revoke_invitation", "accept_invitation"},
}
#: the routes that check a password before the lock (argon2 is slow) and read the account
#: again under it, each with the race test that proves what it decided from the first
#: reading still holds when an admin acts in between
VERIFIED_FIRST = {
    "admin.py": {
        "change_own_password": "test_an_admin_act_while_the_person_changes_their_own_password_holds"
    },
    "auth.py": {"login": "test_a_sign_in_that_straddles_an_admin_reset_is_refused"},
}


def _users_lock_audit(
    source: str, verified_first: frozenset[str] = frozenset()
) -> dict[str, str | None]:
    """Each route in ``source`` that writes an account or withdraws or spends a link, with
    ``name:line`` of the first call that refuses it, ``name:-`` when nothing does but it
    never takes the lock, else ``None``.

    A route is a function decorated ``router.<verb>(...)``, ``async`` or not. It is in the
    class when it calls one of :data:`USERS_WRITERS`, stamps ``revoked`` or ``accepted`` in
    a module that names ``Invitation`` (an assignment, plain, annotated, augmented or to a
    tuple; ``setattr``; ``.values(...)``), or calls a function of the module that does
    either, at any depth — its own nested functions included. A call goes through the
    session when it is a method of it or takes it as an argument, positional or keyword; a
    route with two sessions is refused at its ``def``, as the ratchet cannot tell which one
    the lock holds.

    The lock is taken where the route's body, at its top level, either calls
    ``lock_users_table`` through the session, or calls ``commit_audited(db, write,
    before=first)`` with ``write`` and ``first`` functions of its own, used nowhere else,
    and ``first`` calling ``lock_users_table`` before anything else. A lock under an ``if``
    or in a function nothing calls is no lock. Every call is placed by the top-level
    statement it is in, and a call in ``write`` or ``first`` is under the lock.

    A route passes when nothing before the lock goes through the session or writes; when
    nothing after ``commit_audited`` does either, and nothing after the first top-level
    ``commit()`` that follows a plain lock writes. A route in ``verified_first`` may read
    before the lock, writing nothing, when its first call through the session under the
    lock reads the account again — ``_get_user(db, …)``, the same call as any it made
    before, or ``db.get(User, …, populate_existing=True)`` — before anything writes: what
    it decided from the first reading is its own race test's to prove."""
    import ast
    from collections import Counter

    tree = ast.parse(source)
    funcs = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    names_invitation = any(
        (isinstance(n, ast.Name) and n.id == "Invitation")
        or (isinstance(n, ast.alias) and (n.asname or n.name) == "Invitation")
        for n in ast.walk(tree)
    )

    def called(c: ast.Call) -> str:
        return c.func.id if isinstance(c.func, ast.Name) else getattr(c.func, "attr", "")

    def body(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.AST]:
        return [n for stmt in fn.body for n in ast.walk(stmt)]  # never the decorators

    def is_stamp(t: ast.AST) -> bool:
        if isinstance(t, (ast.Tuple, ast.List)):
            return any(is_stamp(e) for e in t.elts)
        return isinstance(t, ast.Attribute) and t.attr in LINK_STAMPS

    def stamps(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
        for n in body(fn) if names_invitation else []:
            if isinstance(n, ast.Assign) and any(is_stamp(t) for t in n.targets):
                return True
            if isinstance(n, (ast.AnnAssign, ast.AugAssign)) and is_stamp(n.target):
                return True
            if not isinstance(n, ast.Call):
                continue
            key = n.args[1] if called(n) == "setattr" and len(n.args) > 1 else None
            if isinstance(key, ast.Constant) and key.value in LINK_STAMPS:
                return True
            if called(n) == "values" and any(k.arg in LINK_STAMPS for k in n.keywords):
                return True
        return False

    calls = {fn: [n for n in body(fn) if isinstance(n, ast.Call)] for fn in funcs}
    writers = set(USERS_WRITERS) | {fn.name for fn in funcs if stamps(fn)}
    while (
        more := {fn.name for fn in funcs if any(called(c) in writers for c in calls[fn])} - writers
    ):  # a helper that calls a writer is one
        writers |= more

    def sessions(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
        a = fn.args
        found = []
        for p in [*a.posonlyargs, *a.args, *a.kwonlyargs]:
            ann = [] if p.annotation is None else list(ast.walk(p.annotation))
            types = {n.id for n in ann if isinstance(n, ast.Name)}
            types |= {n.attr for n in ann if isinstance(n, ast.Attribute)}
            if p.arg == "db" or types & SESSION_TYPES:
                found.append(p.arg)
        return found

    def through(c: ast.Call, names: set[str]) -> bool:
        on = c.func.value if isinstance(c.func, ast.Attribute) else None
        if isinstance(on, ast.Name) and on.id in names:
            return True
        given = [*c.args, *(k.value for k in c.keywords)]
        return any(isinstance(v, ast.Name) and v.id in names for v in given)

    def call_of(stmt: ast.stmt) -> ast.Call | None:
        return (
            stmt.value if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call) else None
        )

    def locks(stmt: ast.stmt, names: set[str]) -> bool:
        c = call_of(stmt)
        return c is not None and called(c) == "lock_users_table" and through(c, names)

    def commits(stmt: ast.stmt, names: set[str]) -> bool:
        c = call_of(stmt)
        on = c.func.value if c is not None and isinstance(c.func, ast.Attribute) else None
        return called(c) == "commit" and isinstance(on, ast.Name) and on.id in names if c else False

    def locked_commit(
        stmt: ast.stmt, fn: ast.FunctionDef | ast.AsyncFunctionDef, names: set[str]
    ) -> set[ast.stmt]:
        """``write`` and ``first`` of a ``commit_audited`` that takes the lock, else none."""
        c = call_of(stmt)
        if c is None or called(c) != "commit_audited" or len(c.args) != 2:
            return set()
        db, write = c.args
        first = next((k.value for k in c.keywords if k.arg == "before"), None)
        if not (
            isinstance(db, ast.Name)
            and db.id in names
            and isinstance(write, ast.Name)
            and isinstance(first, ast.Name)
        ):
            return set()
        own = {d.name: d for d in fn.body if isinstance(d, ast.FunctionDef)}
        steps = own.get(write.id), own.get(first.id)
        uses = Counter(n.id for n in body(fn) if isinstance(n, ast.Name))
        if steps[0] is None or steps[1] is None or not steps[1].body:
            return set()
        if not locks(steps[1].body[0], names) or uses[write.id] != 1 or uses[first.id] != 1:
            return set()
        return {steps[0], steps[1]}

    def reads_again(c: ast.Call, names: set[str]) -> bool:
        if called(c) == "_get_user" and isinstance(c.func, ast.Name):
            return bool(c.args) and isinstance(c.args[0], ast.Name) and c.args[0].id in names
        on = c.func.value if isinstance(c.func, ast.Attribute) else None
        return (
            called(c) == "get"
            and isinstance(on, ast.Name)
            and on.id in names
            and bool(c.args)
            and isinstance(c.args[0], ast.Name)
            and c.args[0].id == "User"
            and any(
                k.arg == "populate_existing"
                and isinstance(k.value, ast.Constant)
                and k.value.value is True
                for k in c.keywords
            )
        )

    audit: dict[str, str | None] = {}
    for fn in funcs:
        if fn.name not in writers or not any(
            isinstance(d, ast.Call)
            and isinstance(d.func, ast.Attribute)
            and d.func.attr in ROUTE_VERBS
            for d in fn.decorator_list
        ):
            continue
        found = sessions(fn)
        if len(found) > 1:
            audit[fn.name] = f"{fn.name}:{fn.lineno}"
            continue
        names = set(found)
        point, steps = None, set()
        for i, stmt in enumerate(fn.body):
            steps = locked_commit(stmt, fn, names)
            if locks(stmt, names) or steps:
                point = i
                break
        last = next(
            (
                j
                for j in range(len(fn.body))
                if point is not None and j > point and commits(fn.body[j], names)
            ),
            None,
        )
        placed: list[tuple[str, ast.Call]] = []
        for i, stmt in enumerate(fn.body):
            if i == point:
                continue
            if stmt in steps:
                where = "under"
            elif point is None or i < point:
                where = "before"
            elif steps:
                where = "after"
            elif last is not None and i > last:
                where = "committed"
            else:
                where = "under"
            placed += [(where, n) for n in ast.walk(stmt) if isinstance(n, ast.Call)]
        placed.sort(key=lambda p: (p[1].lineno, p[1].col_offset))

        def via(c: ast.Call) -> bool:
            return through(c, names)  # noqa: B023 — read in this iteration only

        def writes(c: ast.Call) -> bool:
            return called(c) in writers

        if point is None:
            first = next((c for _, c in placed if via(c) and called(c) != "lock_users_table"), None)
            first = first or next((c for _, c in placed if writes(c)), None)
            audit[fn.name] = f"{fn.name}:{first.lineno}" if first else f"{fn.name}:-"
            continue
        before = [c for w, c in placed if w == "before"]
        under = [c for w, c in placed if w == "under"]
        bad = [c for w, c in placed if w == "after" and (via(c) or writes(c))]
        bad += [c for w, c in placed if w == "committed" and writes(c)]
        if fn.name not in verified_first:
            bad += [c for c in before if via(c) or writes(c)]
        else:
            bad += [c for c in before if writes(c)]
            read = [c for c in before if via(c)]
            again = next((c for c in under if via(c) and called(c) != "lock_users_table"), None)
            write = next((c for c in under if writes(c)), None)
            held = (
                again is not None
                and reads_again(again, names)
                and (write is None or under.index(again) < under.index(write))
                and all(ast.dump(c) == ast.dump(again) for c in read if called(c) == "_get_user")
            )
            bad += read[:1] if read and not held else []
        first = min(bad, key=lambda c: (c.lineno, c.col_offset), default=None)
        audit[fn.name] = f"{fn.name}:{first.lineno}" if first else None
    return audit


def _reads_before_the_users_lock(
    source: str, verified_first: frozenset[str] = frozenset()
) -> list[str]:
    """The routes of :func:`_users_lock_audit` that read before the lock and act on it."""
    return sorted(bad for bad in _users_lock_audit(source, verified_first).values() if bad)


def test_a_route_that_writes_an_account_or_a_link_takes_the_users_lock_before_it_reads() -> None:
    """P-785, the class: the acceptance holds the ``users`` lock from before it reads the
    link until it commits, and every other write of an account's password, session nonce
    or active flag holds it too, so a route that writes one of them, or withdraws or spends
    a link, and reads the link or the account before it takes that lock acts on a reading
    the lock's holder is about to make false. #81's two findings and #85's were that shape.
    Every such route in the routes package takes ``lock_users_table`` before its first call
    through its session, or is one of :data:`VERIFIED_FIRST` and reads the account again
    under it before it writes; and the ratchet finds exactly the routes it found when it
    was written."""
    import crb.server.routes as routes_pkg

    for tests in VERIFIED_FIRST.values():
        for name in tests.values():
            assert callable(globals().get(name)), f"{name}: the race test is gone"
    root = Path(routes_pkg.__file__).parent
    audits = {
        path.name: audit
        for path in sorted(root.glob("*.py"))
        if (
            audit := _users_lock_audit(
                path.read_text(), frozenset(VERIFIED_FIRST.get(path.name, {}))
            )
        )
    }
    offenders = {
        name: bad
        for name, audit in audits.items()
        if (bad := sorted(v for v in audit.values() if v))
    }
    assert offenders == {}, offenders
    assert {name: set(audit) for name, audit in audits.items()} == USERS_WRITING_ROUTES


def _account_field_writers(root: Path) -> tuple[set[str], dict[str, set[str]]]:
    """Every function under ``root`` that assigns one of :data:`ACCOUNT_FIELDS` itself, as
    ``path:name``, and every function that does or calls one that does, at any depth, by
    the module it is in. A call is followed by its name: imported ``from crb…``, a module
    imported under an alias, or a function of the same module. A nested function is its
    own function, never a part of the one it is in."""
    import ast

    nested = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)

    def own(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.AST]:
        todo: list[ast.AST] = [s for s in fn.body if not isinstance(s, nested)]
        out: list[ast.AST] = []
        while todo:
            n = todo.pop()
            out.append(n)
            todo.extend(c for c in ast.iter_child_nodes(n) if not isinstance(c, nested))
        return out

    def assigns(n: ast.AST) -> bool:
        targets: list[ast.expr] = []
        if isinstance(n, ast.Assign):
            targets = n.targets
        elif isinstance(n, (ast.AugAssign, ast.AnnAssign)):
            targets = [n.target]
        for t in targets:
            for e in t.elts if isinstance(t, (ast.Tuple, ast.List)) else [t]:
                if isinstance(e, ast.Attribute) and e.attr in ACCOUNT_FIELDS:
                    return True
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "setattr":
            key = n.args[1] if len(n.args) > 1 else None
            return isinstance(key, ast.Constant) and key.value in ACCOUNT_FIELDS
        return False

    def path_of(module: str) -> str | None:
        return module[4:].replace(".", "/") + ".py" if module.startswith("crb.") else None

    mods: dict[str, tuple[dict[str, tuple[str, str]], dict[str, str], list[Any]]] = {}
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root).as_posix()
        names: dict[str, tuple[str, str]] = {}
        aliases: dict[str, str] = {}
        funcs: list[Any] = []
        for n in ast.walk(ast.parse(path.read_text())):
            if isinstance(n, ast.ImportFrom) and n.module and n.level == 0:
                for a in n.names:
                    if src := path_of(n.module):
                        names[a.asname or a.name] = (src, a.name)
                    if sub := path_of(f"{n.module}.{a.name}"):
                        aliases[a.asname or a.name] = sub
            elif isinstance(n, ast.Import):
                for a in n.names:
                    if a.asname and (sub := path_of(a.name)):
                        aliases[a.asname] = sub
            elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                funcs.append((n, own(n)))
        mods[rel] = (names, aliases, funcs)

    def target(rel: str, c: ast.Call) -> tuple[str, str] | None:
        names, aliases, _ = mods[rel]
        if isinstance(c.func, ast.Name):
            return names.get(c.func.id, (rel, c.func.id))
        on = c.func.value if isinstance(c.func, ast.Attribute) else None
        if isinstance(c.func, ast.Attribute) and isinstance(on, ast.Name) and on.id in aliases:
            return aliases[on.id], c.func.attr
        return None

    every = [(rel, fn, nodes) for rel, (_, _, funcs) in mods.items() for fn, nodes in funcs]
    found = {(rel, fn.name) for rel, fn, nodes in every if any(assigns(n) for n in nodes)}
    direct = {f"{rel}:{name}" for rel, name in found}
    while (
        more := {
            (rel, fn.name)
            for rel, fn, nodes in every
            if any(isinstance(n, ast.Call) and target(rel, n) in found for n in nodes)
        }
        - found
    ):
        found |= more
    reach: dict[str, set[str]] = {}
    for rel, name in found:
        reach.setdefault(rel, set()).add(name)
    return direct, reach


def test_every_write_of_an_account_field_is_under_the_users_lock_ratchet() -> None:
    """P-785, widened 2026-10-10: the lock ratchet above follows :data:`USERS_WRITERS` by
    name, so a function that writes an account's password hash, session nonce or active
    flag without being one of them, and a route that reaches one through it, were outside
    its sight — the sign-in upgraded a password hash, and the sign-out and the revocation
    of every session rotated a nonce, without the lock, and the ratchet passed. Every
    assignment of :data:`ACCOUNT_FIELDS` in the package is in a function of the writers
    the ratchet follows, and every function that reaches one is a writer, a route the
    ratchet audits or a step of one, or a command line kept outside the server."""
    import ast

    import crb.server
    import crb.server.routes as routes_pkg
    from crb.cli.commands import users as cli_users

    direct, reach = _account_field_writers(Path(crb.server.__file__).parents[1])  # src/crb
    assert direct == {
        "server/auth.py:rotate_session_nonce",
        "server/auth.py:set_account_active",
        "server/auth.py:set_password",
        "server/auth.py:upgrade_password_hash",
    }
    assert reach.pop("server/auth.py") <= USERS_WRITERS
    # the operator's command line sets a password with nothing else running: a known gap
    assert reach.pop("cli/commands/users.py") == {"_go"}, cli_users.__file__
    root = Path(routes_pkg.__file__).parent
    for rel, names in reach.items():
        assert rel.startswith("server/routes/"), (rel, names)
        tree = ast.parse((root / Path(rel).name).read_text())
        routes = USERS_WRITING_ROUTES.get(Path(rel).name, set())
        steps = {
            d.name
            for fn in ast.walk(tree)
            if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) and fn.name in routes
            for d in fn.body
            if isinstance(d, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        assert names <= routes | steps, (rel, names - routes - steps)


def test_the_lock_ratchet_catches_a_read_before_the_lock() -> None:
    """The shapes #81 and #85 found are refused, with every way of writing them the ratchet
    claims to see — a lock it cannot be sure is taken, a write after the lock ends, an
    audited commit whose first step is not the lock — and the shapes the fixes wrote
    pass."""
    probes = {
        # #81: the withdrawal read the link, then locked
        "read_first": """
@router.post("/invitations/{invitation_id}/revoke")
def revoke(invitation_id, db):
    inv = db.get(Invitation, invitation_id)
    lock_users_table(db)
    inv.revoked = "now"
""",
        # #81: the admin's password route read the account through a helper
        "helper_first": """
@router.put("/users/{user_id}/password")
def set_pw(user_id, db):
    user = _get_user(db, user_id)
    supersede_invitations(db, user, actor="a", how="b")
""",
        # CodeRabbit on #85: the session passed by keyword
        "keyword_first": """
@router.put("/users/{user_id}/password")
def set_pw(user_id, db):
    user = _get_user(db=db, user_id=user_id)
    supersede_invitations(db, user, actor="a", how="b")
""",
        # #85: the self-service change read the account and wrote its password
        "own_password": """
@router.put("/users/me/password")
def change(body, me, db):
    user = _get_user(db, me.id)
    set_password(user, body.new_password)
""",
        "async_route": """
@router.post("/invitations/{invitation_id}/revoke")
async def revoke(invitation_id, db):
    inv = db.get(Invitation, invitation_id)
    inv.revoked = "now"
""",
        "named_session": """
@router.put("/users/{user_id}/active")
def set_active(user_id, session: DbDep):
    user = session.get(User, user_id)
    lock_users_table(session)
    set_user_active(session, user, False, sign_in=None)
""",
        "helper_stamps": """
from crb.store.models import Invitation

def _spend(db, inv):
    inv.accepted = "now"

@router.post("/invitations/accept")
def accept(token, db):
    inv = db.get(Invitation, token)
    lock_users_table(db)
    _spend(db, inv)
""",
        "tuple_stamp": """
@router.post("/invitations/{invitation_id}/revoke")
def revoke(invitation_id, db):
    inv = db.get(Invitation, invitation_id)
    inv.revoked, inv.reason = "now", "r"
""",
        "annotated_stamp": """
@router.post("/invitations/{invitation_id}/revoke")
def revoke(invitation_id, db):
    inv = db.get(Invitation, invitation_id)
    inv.revoked: str = "now"
""",
        "augmented_stamp": """
@router.post("/invitations/{invitation_id}/revoke")
def revoke(invitation_id, db):
    inv = db.get(Invitation, invitation_id)
    inv.accepted += "now"
""",
        "setattr_stamp": """
@router.post("/invitations/{invitation_id}/revoke")
def revoke(invitation_id, db):
    inv = db.get(Invitation, invitation_id)
    setattr(inv, "revoked", "now")
""",
        "values_stamp": """
@router.post("/invitations/revoke-all")
def revoke_all(db):
    db.execute(update(Invitation).values(revoked="now"))
""",
        "never_locks": """
@router.put("/users/{user_id}/password")
def set_pw(user, db):
    set_password(user, "x")
""",
        # the account read before the lock and never again under it
        "no_reread": """
@router.put("/users/me/password")
def change(body, me, db):
    user = _get_user(db, me.id)
    lock_users_table(db)
    set_password(user, body.new_password)
""",
        # read again, but only after the write
        "reread_after_the_write": """
@router.put("/users/me/password")
def change(body, me, db):
    user = _get_user(db, me.id)
    lock_users_table(db)
    set_password(user, body.new_password)
    _get_user(db, me.id)
""",
        # something other than the account read before the lock
        "link_read_then_reread": """
@router.put("/users/{user_id}/password")
def set_pw(user_id, db):
    inv = db.get(Invitation, user_id)
    lock_users_table(db)
    user = _get_user(db, user_id)
    supersede_invitations(db, user, actor="a", how="b")
""",
        # another call through the session comes between the lock and the re-read
        "reread_not_first": """
@router.put("/users/me/password")
def change(body, me, db):
    user = _get_user(db, me.id)
    lock_users_table(db)
    db.flush()
    _get_user(db, me.id)
    set_password(user, body.new_password)
""",
        # a lock that only one branch takes is no lock
        "branch_only_lock": """
@router.put("/users/{user_id}/password")
def set_pw(body, db):
    if body.lock:
        lock_users_table(db)
    user = _get_user(db, body.user_id)
    set_password(user, "x")
""",
        # nor is one in a function nothing calls
        "lock_in_dead_def": """
@router.put("/users/{user_id}/password")
def set_pw(body, db):
    def _never():
        lock_users_table(db)
    user = _get_user(db, body.user_id)
    set_password(user, "x")
""",
        # a write on a way out before the lock
        "early_return_unlocked": """
@router.put("/users/{user_id}/password")
def set_pw(body, db):
    user = body.user
    if body.quick:
        set_password(user, "x")
        return
    lock_users_table(db)
""",
        # a route with two sessions: which one holds the lock?
        "two_sessions": """
@router.put("/users/me/password")
def change(body, me, db, other: Session):
    lock_users_table(db)
    set_password(_get_user(other, me.id), body.new_password)
""",
        # a write after the commit that ended the lock
        "write_after_commit": """
@router.put("/users/{user_id}/password")
def set_pw(user_id, db):
    lock_users_table(db)
    user = _get_user(db, user_id)
    db.commit()
    set_password(user, "x")
""",
        # the sign-out's shape without ``before=``: commit_audited takes the events lock only
        "audited_without_first": """
@router.post("/auth/logout")
def logout(db):
    def _users_first():
        lock_users_table(db)
    def _ended():
        rotate_session_nonce(db.get(User, "u", populate_existing=True))
    commit_audited(db, _ended)
""",
        # a check through the session before the audited commit
        "checked_before_audited": """
@router.post("/auth/logout")
def logout(db):
    if db.get(User, "u") is None:
        return
    def _users_first():
        lock_users_table(db)
    def _ended():
        rotate_session_nonce(db.get(User, "u", populate_existing=True))
    commit_audited(db, _ended, before=_users_first)
""",
        # a first step that is only sometimes given
        "first_sometimes": """
@router.post("/auth/logout")
def logout(db, uid):
    def _users_first():
        lock_users_table(db)
    def _ended():
        rotate_session_nonce(db.get(User, uid, populate_existing=True))
    commit_audited(db, _ended, before=_users_first if uid else None)
""",
        # a first step that goes through the session before it locks
        "first_reads_then_locks": """
@router.post("/auth/logout")
def logout(db):
    def _users_first():
        db.flush()
        lock_users_table(db)
    def _ended():
        rotate_session_nonce(db.get(User, "u", populate_existing=True))
    commit_audited(db, _ended, before=_users_first)
""",
        # the write step also run on its own, outside the lock
        "write_step_run_twice": """
@router.post("/auth/logout")
def logout(db):
    def _users_first():
        lock_users_table(db)
    def _ended():
        rotate_session_nonce(db.get(User, "u", populate_existing=True))
    _ended()
    commit_audited(db, _ended, before=_users_first)
""",
        # a call through the session after the audited commit
        "used_after_audited": """
@router.post("/auth/logout")
def logout(db):
    def _users_first():
        lock_users_table(db)
    def _ended():
        rotate_session_nonce(db.get(User, "u", populate_existing=True))
    commit_audited(db, _ended, before=_users_first)
    rotate_session_nonce(db.get(User, "u"))
""",
    }
    refused = {
        "read_first": ["revoke:4"],
        "helper_first": ["set_pw:4"],
        "keyword_first": ["set_pw:4"],
        "own_password": ["change:4"],
        "async_route": ["revoke:4"],
        "named_session": ["set_active:4"],
        "helper_stamps": ["accept:9"],
        "tuple_stamp": ["revoke:4"],
        "annotated_stamp": ["revoke:4"],
        "augmented_stamp": ["revoke:4"],
        "setattr_stamp": ["revoke:4"],
        "values_stamp": ["revoke_all:4"],
        "never_locks": ["set_pw:4"],
        "no_reread": ["change:4"],
        "reread_after_the_write": ["change:4"],
        "link_read_then_reread": ["set_pw:4"],
        "reread_not_first": ["change:4"],
        "branch_only_lock": ["set_pw:6"],
        "lock_in_dead_def": ["set_pw:6"],
        "early_return_unlocked": ["set_pw:6"],
        "two_sessions": ["change:3"],
        "write_after_commit": ["set_pw:7"],
        "audited_without_first": ["logout:7"],
        "checked_before_audited": ["logout:4"],
        "first_sometimes": ["logout:7"],
        "first_reads_then_locks": ["logout:5"],
        "write_step_run_twice": ["logout:7"],
        "used_after_audited": ["logout:9"],
    }
    assert {k: _reads_before_the_users_lock(src) for k, src in probes.items()} == refused
    # a route allowed to verify first is held to the same shapes: no re-read, one after
    # the write or after another call, another account's or another session's
    verified = frozenset({"change"})
    allowed = {
        k: _reads_before_the_users_lock(probes[k], verified)
        for k in ("own_password", "no_reread", "reread_after_the_write", "reread_not_first")
    }
    assert allowed == {k: ["change:4"] for k in allowed}
    reread_other_account = """
@router.put("/users/me/password")
def change(body, me, db):
    user = _get_user(db, me.id)
    lock_users_table(db)
    user = _get_user(db, body.user_id)
    set_password(user, body.new_password)
"""
    reread_other_session = """
@router.put("/users/me/password")
def change(body, me, db):
    user = _get_user(db, me.id)
    lock_users_table(db)
    with factory() as other:
        user = _get_user(other, me.id)
    set_password(user, body.new_password)
"""
    written_before_the_lock = """
@router.put("/users/me/password")
def change(body, me, db):
    user = _get_user(db, me.id)
    set_password(user, body.new_password)
    lock_users_table(db)
    _get_user(db, me.id)
"""
    for shape in (reread_other_account, reread_other_session):
        assert _reads_before_the_users_lock(shape, verified) == ["change:4"], shape
    assert _reads_before_the_users_lock(written_before_the_lock, verified) == ["change:5"]
    locked_first = """
@router.put("/users/{user_id}/password")
def set_pw(user_id, db):
    lock_users_table(db)
    user = _get_user(db, user_id)
    supersede_invitations(db, user, actor="a", how="b")
"""
    locked_by_keyword = """
@router.put("/users/me/password")
def change(body, me, db):
    lock_users_table(db=db)
    user = _get_user(db, me.id)
    set_password(user, body.new_password)
"""
    no_link = """
@router.put("/users/{user_id}/role")
def set_role(user_id, db):
    user = _get_user(db, user_id)
"""
    # ``accepted`` on a row that is not an invitation, in a module that names none
    not_an_invitation = """
@router.post("/decisions/{decision_id}")
def decide(decision_id, db):
    row = db.get(Decision, decision_id)
    row.accepted = "now"
"""
    # the self-service change's shape: verify before the lock, read the account again under it
    reread_under_the_lock = """
@router.put("/users/me/password")
def change(body, me, db):
    user = _get_user(db, me.id)
    verify_password(user.password_hash, body.current_password)
    lock_users_table(db)
    user = refuse_an_ended_session(_get_user(db, me.id), "cv")
    set_password(user, body.new_password)
"""
    # the sign-in's shape: verify before the lock, read the account again in the write step
    sign_in = """
@router.post("/auth/login")
def login(body, db):
    user = authenticate_local(db, body.username, body.password)
    uid = user.id
    def _users_first():
        lock_users_table(db)
    def _signed_in():
        account = db.get(User, uid, populate_existing=True)
        upgrade_password_hash(account, "verified", "new")
    commit_audited(db, _signed_in, before=_users_first)
"""
    # the sign-out's shape: nothing through the session before the lock
    sign_out = """
@router.post("/auth/logout")
def logout(db):
    def _users_first():
        lock_users_table(db)
    def _ended():
        rotate_session_nonce(db.get(User, "u", populate_existing=True))
    commit_audited(db, _ended, before=_users_first)
"""
    assert _users_lock_audit(locked_first) == {"set_pw": None}
    assert _users_lock_audit(reread_under_the_lock, verified) == {"change": None}
    assert _users_lock_audit(reread_under_the_lock) == {"change": "change:4"}
    assert _users_lock_audit(sign_in, frozenset({"login"})) == {"login": None}
    assert _users_lock_audit(sign_in) == {"login": "login:4"}
    assert _users_lock_audit(sign_out) == {"logout": None}
    assert _users_lock_audit(locked_by_keyword) == {"change": None}
    assert _users_lock_audit(no_link) == {}
    assert _users_lock_audit(not_an_invitation) == {}


# ---------------------------------------------------------------------------
# the decisions clock's first stamp, on both dialects (P-357)
# ---------------------------------------------------------------------------


def test_a_concurrent_first_decision_stamp_is_joined_on_both_dialects(
    backend: Backend, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``record_due`` writes a decision's first stamp with ``INSERT … ON CONFLICT DO
    NOTHING`` in the dialect's own words, then reads the row back. Here the other stamper
    commits the same ``(repo, kind, key)`` between this pass's read and its write: the pass
    joins the earlier row — its ``first_due`` kept, ``last_seen`` moved — on SQLite and on
    PostgreSQL alike, where a plain insert raised ``IntegrityError`` (P-357)."""
    from crb.server import decisions as dec

    store_db.init_db(backend.engine)
    row = dec.DecisionRow(kind="signoff_due", key="bug.fix|S", title="sign it", role="approver")
    original = dec.due_records
    raced: list[bool] = []

    def racing(db: object, repo: str = "") -> object:
        seen = original(db, repo)  # type: ignore[arg-type]
        if not raced:
            raced.append(True)
            with backend.factory() as other:
                dec.record_due(other, "alpha", [row], now="2026-09-01T09:00:00+00:00")
                other.commit()
        return seen

    monkeypatch.setattr(dec, "due_records", racing)
    with backend.factory() as s:
        dec.record_due(s, "alpha", [row], now="2026-09-01T10:00:00+00:00")
        s.commit()
    with backend.factory() as s:
        (rec,) = original(s, "alpha")
        assert raced and rec.first_due == "2026-09-01T09:00:00+00:00"
        assert rec.last_seen == "2026-09-01T10:00:00+00:00" and rec.resolved == ""
