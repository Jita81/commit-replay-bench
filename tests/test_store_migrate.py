"""crb.store.migrate — Alembic parity with ``init_db``, adoption, idempotence, the CLI.

The load-bearing test is :func:`test_upgrade_head_equals_init_db`: the initial revision and
``Base.metadata.create_all`` must produce the same schema (autogenerate diff empty; every
table/column/index/constraint identical through the inspector; on SQLite the
``sqlite_master`` rows byte-identical), and both must carry the append-only triggers.

Parametrised over SQLite and (when ``CRB_TEST_POSTGRES_URL`` is set) PostgreSQL.
"""

from __future__ import annotations

import io
import sqlite3
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import Engine, inspect, text
from sqlalchemy.exc import DBAPIError

from crb.store import migrate
from crb.store.db import init_db, make_engine, make_session_factory
from crb.store.ledger import DbLedger, assert_append_only
from crb.store.models import APPEND_ONLY_TABLES, Base

try:
    from tests.conftest_store import Backend, backend, grade_row, pg_schema
except ImportError:  # pragma: no cover — rootdir-relative import (pytest default)
    from conftest_store import Backend, backend, grade_row, pg_schema  # noqa: F401

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _snapshot(engine: Engine) -> dict[str, Any]:
    """A dialect-neutral, order-insensitive picture of the schema (tables, columns,
    constraints, indexes) plus the trigger names. ``alembic_version`` excluded."""
    insp = inspect(engine)
    snap: dict[str, Any] = {}
    for table in sorted(insp.get_table_names()):
        if table == "alembic_version":
            continue
        cols = [(c["name"], str(c["type"]), bool(c["nullable"])) for c in insp.get_columns(table)]
        pk = tuple(insp.get_pk_constraint(table)["constrained_columns"])
        uniques = sorted(tuple(u["column_names"]) for u in insp.get_unique_constraints(table))
        indexes = sorted(
            (str(i["name"]), tuple(i["column_names"]), bool(i["unique"]))
            for i in insp.get_indexes(table)
        )
        fks = sorted(
            (tuple(f["constrained_columns"]), f["referred_table"], tuple(f["referred_columns"]))
            for f in insp.get_foreign_keys(table)
        )
        snap[table] = {
            "columns": cols,
            "pk": pk,
            "uniques": uniques,
            "indexes": indexes,
            "fks": fks,
        }
    with engine.connect() as c:
        if engine.dialect.name == "sqlite":
            q = "SELECT name FROM sqlite_master WHERE type = 'trigger'"
        else:
            q = (
                "SELECT t.tgname FROM pg_trigger t "
                "JOIN pg_class c ON c.oid = t.tgrelid "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE NOT t.tgisinternal AND n.nspname = current_schema()"
            )
        snap["__triggers__"] = sorted(str(r[0]) for r in c.execute(text(q)))
    return snap


def _sqlite_master(path: Path) -> list[tuple[str, ...]]:
    conn = sqlite3.connect(path)
    try:
        return sorted(
            conn.execute(
                "SELECT type, name, tbl_name, sql FROM sqlite_master "
                "WHERE name NOT LIKE 'sqlite_%' AND name != 'alembic_version'"
            ).fetchall()
        )
    finally:
        conn.close()


def _autogen_diff(engine: Engine) -> list[Any]:
    with engine.connect() as c:
        return compare_metadata(MigrationContext.configure(c), Base.metadata)


def _reset(backend: Backend) -> Engine:
    """Drop everything (including alembic_version) and return a fresh engine."""
    if backend.dialect == "sqlite":
        path = backend.url.removeprefix("sqlite:///")
        backend.engine.dispose()
        for suffix in ("", "-wal", "-shm"):
            Path(path + suffix).unlink(missing_ok=True)
        return make_engine(backend.url)
    with backend.engine.begin() as c:
        for table in [*reversed(list(Base.metadata.sorted_tables)), "alembic_version"]:
            name = table if isinstance(table, str) else table.name
            c.execute(text(f"DROP TABLE IF EXISTS {name} CASCADE"))
        c.execute(text("DROP FUNCTION IF EXISTS crb_append_only() CASCADE"))
    return backend.engine


# ---------------------------------------------------------------------------
# parity: alembic upgrade head == Base.metadata.create_all
# ---------------------------------------------------------------------------


def test_packaged_migration_files_exist() -> None:
    """The ini, the template and the revision chain ship inside the package (the
    container installs crb non-editable; a missing file here breaks ``migrate``)."""
    assert migrate.INI_PATH.is_file()
    assert (migrate.MIGRATIONS_DIR / "env.py").is_file()
    assert (migrate.MIGRATIONS_DIR / "script.py.mako").is_file()
    assert migrate.head_revision() == migrate.INITIAL_REVISION or migrate.head_revision()


def test_upgrade_head_equals_init_db(backend: Backend, tmp_path: Path) -> None:
    # --- migrated ---
    migrate.upgrade(backend.url)
    assert migrate.current(backend.url) == migrate.head_revision()
    assert _autogen_diff(backend.engine) == [], "models drifted from the migration chain"
    migrated = _snapshot(backend.engine)

    # create_all on the migrated DB is a no-op (checkfirst): nothing changes
    Base.metadata.create_all(backend.engine)
    assert _snapshot(backend.engine) == migrated
    if backend.dialect == "sqlite":
        path = Path(backend.url.removeprefix("sqlite:///"))
        migrated_master = _sqlite_master(path)
        Base.metadata.create_all(backend.engine)
        assert _sqlite_master(path) == migrated_master

    # --- created ---
    if backend.dialect == "sqlite":
        other = make_engine(f"sqlite:///{tmp_path / 'created.db'}")
        try:
            init_db(other)
            created = _snapshot(other)
            created_master = _sqlite_master(tmp_path / "created.db")
        finally:
            other.dispose()
        assert created_master == migrated_master, "sqlite_master differs: migration != init_db"
    else:
        engine = _reset(backend)
        init_db(engine)
        created = _snapshot(engine)

    assert created == migrated
    assert created["__triggers__"] == sorted(
        f"{t}_{k}" for t in APPEND_ONLY_TABLES for k in ("no_update", "no_delete")
    )


def test_migration_defines_every_model_table(backend: Backend) -> None:
    migrate.upgrade(backend.url)
    tables = set(inspect(backend.engine).get_table_names()) - {"alembic_version"}
    assert tables == set(Base.metadata.tables)


# ---------------------------------------------------------------------------
# upgrade / current / check semantics
# ---------------------------------------------------------------------------


def test_current_and_check_on_a_fresh_database(backend: Backend) -> None:
    assert migrate.current(backend.url) is None
    assert migrate.check(backend.url) is False


def test_upgrade_is_idempotent(backend: Backend) -> None:
    migrate.upgrade(backend.url)
    before = _snapshot(backend.engine)
    migrate.upgrade(backend.url)
    migrate.upgrade(backend.url, revision="head")
    assert _snapshot(backend.engine) == before
    assert migrate.check(backend.url) is True
    assert migrate.current(backend.url) == migrate.INITIAL_REVISION


def test_migrated_database_is_append_only_and_chains(backend: Backend) -> None:
    """A database that only ever saw ``migrate.upgrade`` carries the full protection."""
    migrate.upgrade(backend.url)
    ledger = DbLedger(backend.factory)
    ledger.append(grade_row(trial="1"))
    ledger.append(grade_row(trial="2"))
    assert ledger.verify() == 2
    assert_append_only(backend.factory)
    with pytest.raises(DBAPIError, match="append-only"), backend.engine.begin() as c:
        c.execute(text("DELETE FROM grades"))
    assert ledger.count() == 2


def test_upgrade_adopts_an_init_db_database_and_keeps_its_rows(backend: Backend) -> None:
    init_db(backend.engine)
    ledger = DbLedger(backend.factory)
    ledger.append(grade_row(trial="pre-adoption"))
    assert migrate.current(backend.url) is None
    assert migrate.check(backend.url) is False

    migrate.upgrade(backend.url)  # stamps 0001, then upgrades (no-op) — never re-creates

    assert migrate.current(backend.url) == migrate.INITIAL_REVISION
    assert migrate.check(backend.url) is True
    assert ledger.verify() == 1
    assert next(iter(ledger.rows())).trial == "pre-adoption"
    assert_append_only(backend.factory)
    assert _autogen_diff(backend.engine) == []


def test_upgrade_refuses_a_partial_schema(backend: Backend) -> None:
    Base.metadata.tables["repos"].create(backend.engine)
    with pytest.raises(migrate.SchemaStateError, match="missing"):
        migrate.upgrade(backend.url)
    assert migrate.current(backend.url) is None
    assert "grades" not in inspect(backend.engine).get_table_names()


def test_upgrade_reasserts_triggers_that_were_dropped(backend: Backend) -> None:
    migrate.upgrade(backend.url)
    backend.drop_grades_triggers()
    assert "grades_no_update" not in backend.trigger_names()
    migrate.upgrade(backend.url)  # already at head — still re-installs the protection
    assert {"grades_no_update", "grades_no_delete"} <= backend.trigger_names()


# ---------------------------------------------------------------------------
# downgrade safety
# ---------------------------------------------------------------------------


def _downgrade_to_base(backend: Backend) -> None:
    cfg = migrate.alembic_config(backend.url)
    with backend.engine.begin() as connection:
        cfg.attributes["connection"] = connection
        command.downgrade(cfg, "base")


def test_downgrade_refuses_while_the_ledger_holds_rows(backend: Backend) -> None:
    migrate.upgrade(backend.url)
    DbLedger(backend.factory).append(grade_row())
    with pytest.raises(RuntimeError, match="refusing to downgrade"):
        _downgrade_to_base(backend)
    assert "grades" in inspect(backend.engine).get_table_names()
    assert migrate.current(backend.url) == migrate.INITIAL_REVISION


def test_downgrade_of_an_empty_database_drops_the_schema(backend: Backend) -> None:
    migrate.upgrade(backend.url)
    _downgrade_to_base(backend)
    assert set(inspect(backend.engine).get_table_names()) <= {"alembic_version"}
    assert migrate.current(backend.url) is None


# ---------------------------------------------------------------------------
# env.py URL resolution + offline SQL + the CLI
# ---------------------------------------------------------------------------


def test_env_resolves_url_from_environment_when_no_connection_is_supplied(
    backend: Backend, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The developer path: ``alembic -c src/crb/store/alembic.ini upgrade head`` with
    ``CRB_DATABASE_URL`` exported and nothing in the ini."""
    monkeypatch.setenv("CRB_DATABASE_URL", backend.url)
    cfg = migrate.alembic_config()  # no url, no connection attribute
    assert cfg.get_main_option("sqlalchemy.url") in (None, "")
    command.upgrade(cfg, "head")
    assert migrate.check(backend.url) is True
    assert set(inspect(backend.engine).get_table_names()) >= set(Base.metadata.tables)


def test_offline_sql_includes_tables_and_triggers(backend: Backend) -> None:
    """``alembic upgrade head --sql`` emits reviewable DDL for the target dialect —
    including the trigger statements, because the migration installs them itself."""
    buf = io.StringIO()
    cfg = migrate.alembic_config(backend.url)
    with redirect_stdout(buf):
        command.upgrade(cfg, "head", sql=True)
    sql = buf.getvalue()
    assert "CREATE TABLE grades" in sql
    assert "grades_no_update" in sql and "signoffs_no_delete" in sql
    assert "alembic_version" in sql
    assert migrate.current(backend.url) is None  # offline mode touched nothing


def test_cli_upgrade_current_check(backend: Backend, capsys: pytest.CaptureFixture[str]) -> None:
    assert migrate.main(["current", "--url", backend.url]) == 0
    assert capsys.readouterr().out.strip() == "(unversioned)"
    assert migrate.main(["check", "--url", backend.url]) == 1
    assert "pending" in capsys.readouterr().out
    assert migrate.main(["upgrade", "--url", backend.url]) == 0
    assert capsys.readouterr().out.strip() == f"ok: database at {migrate.INITIAL_REVISION}"
    assert migrate.main(["check", "--url", backend.url]) == 0
    assert capsys.readouterr().out.strip() == "ok: at head"
    assert migrate.main(["--url", backend.url]) == 0  # default action is upgrade; idempotent


def test_cli_default_url_comes_from_environment(
    backend: Backend, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("CRB_DATABASE_URL", backend.url)
    assert migrate.main(["upgrade", "-v"]) == 0
    assert migrate.check(backend.url) is True
    capsys.readouterr()


def test_module_is_runnable_as_main(backend: Backend) -> None:
    import subprocess
    import sys

    r = subprocess.run(
        [sys.executable, "-m", "crb.store.migrate", "check", "--url", backend.url],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert r.returncode == 1 and "pending" in r.stdout, r.stderr
    r = subprocess.run(
        [sys.executable, "-m", "crb.store.migrate", "upgrade", "--url", backend.url],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert r.returncode == 0, r.stderr
    assert migrate.check(backend.url) is True
    make_session_factory(backend.engine)  # engine still usable after the subprocess migrated
