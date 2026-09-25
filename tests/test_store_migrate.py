"""crb.store.migrate — Alembic parity with ``init_db``, adoption, idempotence, the CLI.

The load-bearing test is :func:`test_upgrade_head_equals_init_db`: the migration chain at
head and ``Base.metadata.create_all`` must produce the same schema (autogenerate diff
empty; every table/column/index/constraint identical — and in the same order — through the
inspector; on SQLite the ``sqlite_master`` rows identical definition-for-definition), and
both must carry the append-only triggers. Since revision 0002 (belt 5, ADR-0011) the chain
has an ``ADD COLUMN`` step, and SQLite records that by splicing the definition into the
stored ``CREATE TABLE`` text — so the SQLite comparison is by definition set, not by byte
(the inspector comparison keeps the order strict).

Adoption of an unversioned ``create_all`` database is revision-aware
(:data:`crb.store.migrate.REVISION_MARKERS`): a database created by an older release is
stamped at the revision it is at and receives the missing revisions; one created by this
release is stamped at head.

Parametrised over SQLite and (when ``CRB_TEST_POSTGRES_URL`` is set) PostgreSQL.

Navigation
----------
What it is:   The migrations' test suite — Alembic parity with ``init_db``, adoption of
              unversioned databases, idempotence and the CLI, on SQLite and PostgreSQL.
What it does: Pins the load-bearing parity — the chain at head and ``create_all`` produce the
              same schema (inspector-identical in order; on SQLite definition-for-definition,
              since revision 0002's ``ADD COLUMN`` is spliced into the stored ``CREATE TABLE``) —
              both carrying the triggers; that the migration files ship in the package; that
              ``current`` / ``check`` answer on a fresh database; ``head_status`` — the one
              head check ``/health`` and ``crb doctor`` read — on an empty, a ``create_all``,
              an older release's, a migrated and a behind store; idempotent upgrade; that a
              migrated database is append-only and chains; adoption of an ``init_db`` database
              from this release (stamped at head) and from before belt 5 (stamped at 0001 and
              upgraded) while a schema matching no release or a partial one is refused; triggers
              re-asserted; downgrade refused while the ledger holds rows (0002 while a v5 row
              exists) and dropping the schema otherwise; the URL from the environment; offline
              SQL including triggers; and the CLI's ``upgrade`` / ``current`` / ``check``.
How:          ``conftest_store`` backends; ``_snapshot`` compares schemas through the inspector;
              ``_drop_column`` fakes an older release's schema.
Layer:        tests — docs/ARCHITECTURE.md#73-data-model-store-p4
ADRs:         docs/adr/0002-append-only-hash-chained-ledger.md, docs/adr/0011-repo-lint-belt.md
Works with:   src/crb/store/migrate.py (under test), src/crb/store/migrations/env.py and
              src/crb/store/migrations/versions/v0002_belt5_repo_lint_clean.py (the chain),
              src/crb/store/db.py (``init_db``), tests/conftest_store.py, docs/DEPLOYMENT.md
              (upgrade, §6)
Tested by:    tests/test_store_migrate.py
Touch when:   a model changes (write the revision, add its marker to ``REVISION_MARKERS``, and
              let the parity case prove head == ``create_all``); never edit a shipped revision.
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


def _canonical_sql(sql: str | None) -> tuple[str, frozenset[str]]:
    """``CREATE TABLE t (a, b, PRIMARY KEY (a))`` → ``("CREATE TABLE t", {"a", "b",
    "PRIMARY KEY (a)"})``: the head before the parenthesis, whitespace-collapsed, and the
    set of depth-0 comma-separated definitions. ``ALTER TABLE … ADD COLUMN`` on SQLite
    splices ``, col TYPE`` before the closing parenthesis of the stored text, so byte
    equality with ``create_all`` is unattainable past the initial revision; definition
    equality is what the schema actually says (column order is checked by the inspector)."""
    if not sql:
        return ("", frozenset())
    open_at = sql.find("(")
    if open_at < 0:
        return (" ".join(sql.split()), frozenset())
    head = " ".join(sql[:open_at].split())
    body = sql[open_at + 1 : sql.rfind(")")]
    defs: list[str] = []
    depth = 0
    cur: list[str] = []
    for ch in body:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            defs.append(" ".join("".join(cur).split()))
            cur = []
        else:
            cur.append(ch)
    if cur:
        defs.append(" ".join("".join(cur).split()))
    return (head, frozenset(d for d in defs if d))


def _sqlite_master(path: Path) -> list[tuple[str, str, str, tuple[str, frozenset[str]]]]:
    conn = sqlite3.connect(path)
    try:
        return sorted(
            (str(t), str(n), str(tn), _canonical_sql(sql))
            for t, n, tn, sql in conn.execute(
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
    # the single head is a packaged revision file (not a number that drifts per branch)
    head = migrate.head_revision()
    assert head.isdigit() and len(head) == 4
    assert list((migrate.MIGRATIONS_DIR / "versions").glob(f"v{head}_*.py")), head


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


def test_head_status_reads_empty_created_migrated_and_behind_stores(backend: Backend) -> None:
    """``head_status`` (the ``migrations`` probe's and ``crb doctor``'s reading): an empty
    store is not at head and has no schema; a ``create_all`` store is unversioned at head and
    matches the models (``upgrade`` would only stamp it); a migrated store is at head; a store
    stamped behind names both revisions; an older release's ``create_all`` schema is
    unversioned at ITS revision and does not match the models."""
    head = migrate.head_revision()
    empty = migrate.head_status(backend.url)
    assert empty == migrate.HeadStatus(None, head, False)
    assert empty.to_dict() == {
        "database": None,
        "head": head,
        "at_head": False,
        "unversioned_at": None,
        "matches_models": False,
    }

    init_db(backend.engine)
    created = migrate.head_status(backend.url)
    assert created.database is None and created.at_head is False
    assert created.unversioned_at == head and created.matches_models is True

    migrate.upgrade(backend.url)
    assert migrate.head_status(backend.url) == migrate.HeadStatus(head, head, True)
    with backend.factory() as s:  # the connection form /health uses (a session's)
        assert migrate.head_status_on(s.connection()).at_head is True

    command.stamp(migrate.alembic_config(backend.url), migrate.INITIAL_REVISION)
    behind = migrate.head_status(backend.url)
    assert behind == migrate.HeadStatus(migrate.INITIAL_REVISION, head, False)
    assert migrate.check(backend.url) is False  # ``check`` is ``head_status().at_head``


def test_head_status_of_an_older_release_create_all_schema(backend: Backend) -> None:
    init_db(backend.engine)
    _drop_column(backend, "grades", "repo_lint_clean")  # a pre-belt-5 release's create_all
    st = migrate.head_status(backend.url)
    assert st.database is None and st.at_head is False
    assert st.unversioned_at == migrate.INITIAL_REVISION and st.matches_models is False


def test_upgrade_is_idempotent(backend: Backend) -> None:
    migrate.upgrade(backend.url)
    before = _snapshot(backend.engine)
    migrate.upgrade(backend.url)
    migrate.upgrade(backend.url, revision="head")
    assert _snapshot(backend.engine) == before
    assert migrate.check(backend.url) is True
    assert migrate.current(backend.url) == migrate.head_revision()


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

    migrate.upgrade(backend.url)  # stamps head (create_all == the models), never re-creates

    assert migrate.current(backend.url) == migrate.head_revision()
    assert migrate.check(backend.url) is True
    assert ledger.verify() == 1
    assert next(iter(ledger.rows())).trial == "pre-adoption"
    assert_append_only(backend.factory)
    assert _autogen_diff(backend.engine) == []


def _drop_column(backend: Backend, table: str, column: str) -> None:
    """Turn this release's ``create_all`` schema into an older release's (no ``column``)."""
    if backend.dialect == "sqlite" and sqlite3.sqlite_version_info < (3, 35):
        pytest.skip("SQLite < 3.35 cannot DROP COLUMN")
    with backend.engine.begin() as c:
        c.execute(text(f"ALTER TABLE {table} DROP COLUMN {column}"))


def test_upgrade_adopts_an_older_release_init_db_database_and_adds_belt_five(
    backend: Backend,
) -> None:
    """A database created by ``init_db`` BEFORE belt 5 existed (no ``repo_lint_clean``
    column) holding four-belt rows: adoption stamps it at 0001, 0002 adds the nullable
    column in place, every existing row still verifies (belt 5 is unrecorded for ``v4``,
    not hashed), and five-belt rows can be appended after it."""
    init_db(backend.engine)
    ledger = DbLedger(backend.factory)
    ledger.append(grade_row(trial="four-belt", belt_set="v4"))
    _drop_column(backend, "grades", "repo_lint_clean")
    assert "repo_lint_clean" not in {
        c["name"] for c in inspect(backend.engine).get_columns("grades")
    }
    assert migrate.current(backend.url) is None
    assert _autogen_diff(backend.engine) != []  # an older release's schema

    migrate.upgrade(backend.url)  # stamps 0001, applies 0002 (and every later revision)

    assert migrate.current(backend.url) == migrate.head_revision() == "0011"
    assert migrate.check(backend.url) is True
    assert _autogen_diff(backend.engine) == []
    assert "repo_lint_clean" in {c["name"] for c in inspect(backend.engine).get_columns("grades")}
    assert_append_only(backend.factory)
    old = next(iter(ledger.rows()))
    assert old.trial == "four-belt" and old.belt_set == "v4" and old.repo_lint_clean is None
    assert old.verify_hash() and ledger.verify() == 1
    ledger.append(grade_row(trial="five-belt", repo_lint_clean=True))
    # ≤ 16 characters: ``grades.trial`` is VARCHAR(16), which PostgreSQL enforces at INSERT
    # (an 18-character label failed the store suite on PostgreSQL 16, CI 2026-09-15) and
    # the row now refuses on every dialect
    ledger.append(grade_row(trial="five-belt-rej", clean=False, repo_lint_clean=False))
    with pytest.raises(ValueError, match="trial longer than 16"):
        grade_row(trial="five-belt-rejected")
    rows = list(ledger.rows())
    assert [r.repo_lint_clean for r in rows] == [None, True, False]
    assert [r.belt_set for r in rows] == ["v4", "v5", "v5"]
    assert rows[2].failure_kind == "lint"
    assert ledger.verify() == 3


def test_upgrade_refuses_an_unversioned_schema_that_matches_no_release(
    backend: Backend,
) -> None:
    """Every table present, the belt-5 marker present, but a column nobody shipped: not a
    known ``create_all`` — refused rather than stamped at head."""
    init_db(backend.engine)
    with backend.engine.begin() as c:
        c.execute(text("ALTER TABLE repos ADD COLUMN bogus TEXT"))
    with pytest.raises(migrate.SchemaStateError, match="neither a known release"):
        migrate.upgrade(backend.url)
    assert migrate.current(backend.url) is None


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
    assert migrate.current(backend.url) == migrate.head_revision()


def test_downgrade_0002_refuses_while_a_v5_row_exists_and_drops_the_column_otherwise(
    backend: Backend,
) -> None:
    """Revision 0002's downgrade is real: refused while any row records belt 5 (the
    column IS evidence then); with only pre-belt-5 rows the empty column may go, and the
    append-only triggers survive the drop."""
    migrate.upgrade(backend.url)
    ledger = DbLedger(backend.factory)
    ledger.append(grade_row(trial="v4", belt_set="v4"))
    ledger.append(grade_row(trial="v5", repo_lint_clean=True))
    cfg = migrate.alembic_config(backend.url)
    with (
        pytest.raises(RuntimeError, match="refusing to downgrade 0002"),
        backend.engine.begin() as connection,
    ):
        cfg.attributes["connection"] = connection
        command.downgrade(cfg, "0001")
    # the refusal rolls the whole downgrade back — 0008's column, 0007's and 0005's tables, 0006's
    # column, 0004's index swap and 0003's drop of the (empty) reviews table included — so the database stays
    # exactly where it was
    assert migrate.current(backend.url) == "0011"

    fresh = _reset(backend)
    migrate.upgrade(backend.url)
    DbLedger(make_session_factory(fresh)).append(grade_row(trial="v4-only", belt_set="v4"))
    cfg = migrate.alembic_config(backend.url)
    with fresh.begin() as connection:
        cfg.attributes["connection"] = connection
        command.downgrade(cfg, "0001")
    assert migrate.current(backend.url) == "0001"
    assert "repo_lint_clean" not in {c["name"] for c in inspect(fresh).get_columns("grades")}
    assert {"grades_no_update", "grades_no_delete"} <= backend.trigger_names()
    with pytest.raises(DBAPIError, match="append-only"), fresh.begin() as c:
        c.execute(text("DELETE FROM grades"))
    migrate.upgrade(backend.url)  # and back up again
    assert migrate.current(backend.url) == "0011" and _autogen_diff(fresh) == []


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
    # 0006 offline is the whole revision, IN ORDER: the column, then the SQL backfill, then
    # the unique index — an index before the backfill would fail on a duplicate legacy link
    col = sql.find("github_full_name VARCHAR(256)")
    backfill = sql.find("UPDATE repos SET github_full_name = lower(trim(")
    index = sql.find("CREATE UNIQUE INDEX uq_repos_github_full_name")
    assert col >= 0 and backfill >= 0 and index >= 0, sql[-2000:]
    assert col < backfill < index
    # 0007 offline emits the whole workers table after 0006 (J-TEL-2)
    workers = sql.find("CREATE TABLE workers")
    assert workers > index, sql[-2000:]
    assert "heartbeat_s FLOAT NOT NULL" in sql and "current_run_id VARCHAR(32) NOT NULL" in sql
    # 0008 offline adds the reaper count to that table after it exists
    count = sql.find("ADD COLUMN unconfirmed_containers INTEGER DEFAULT '0' NOT NULL")
    assert count > workers, sql[-2000:]
    assert migrate.current(backend.url) is None  # offline mode touched nothing


def test_cli_upgrade_current_check(backend: Backend, capsys: pytest.CaptureFixture[str]) -> None:
    assert migrate.main(["current", "--url", backend.url]) == 0
    assert capsys.readouterr().out.strip() == "(unversioned)"
    assert migrate.main(["check", "--url", backend.url]) == 1
    assert "pending" in capsys.readouterr().out
    assert migrate.main(["upgrade", "--url", backend.url]) == 0
    assert capsys.readouterr().out.strip() == f"ok: database at {migrate.head_revision()}"
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
    import os
    import subprocess
    import sys

    # The child must import the SAME ``crb`` this test did (pytest's ``pythonpath = ["src"]``
    # does not reach a subprocess): with an editable install of another checkout in the
    # venv, ``python -m`` would migrate to THAT tree's head and this test would fail — or
    # pass — for a tree it never ran. Point it at the src this module came from.
    src_dir = str(Path(migrate.__file__).resolve().parents[2])
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join([src_dir, os.environ.get("PYTHONPATH", "")]).rstrip(
            os.pathsep
        ),
    }
    r = subprocess.run(
        [sys.executable, "-m", "crb.store.migrate", "check", "--url", backend.url],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
        env=env,
    )
    assert r.returncode == 1 and "pending" in r.stdout, r.stderr
    r = subprocess.run(
        [sys.executable, "-m", "crb.store.migrate", "upgrade", "--url", backend.url],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
        env=env,
    )
    assert r.returncode == 0, r.stderr
    assert migrate.check(backend.url) is True
    make_session_factory(backend.engine)  # engine still usable after the subprocess migrated


def test_0004_refuses_a_database_holding_duplicate_trace_seq_pairs(backend: Backend) -> None:
    """Revision 0004 adds the unique ``(trace_id, seq)`` index. Rows are append-only, so a
    database that already holds a duplicate pair cannot be repaired by the migration: it
    refuses with the offending traces instead of guessing (CodeRabbit on PR #4)."""
    migrate.upgrade(backend.url, revision="0003")
    assert migrate.current(backend.url) == "0003"
    cols = (
        "event_id, trace_id, seq, timestamp, stage, action, status, step_id, parent_step_id, "
        "actor, repo, task_id, input_ref, output_ref, error_code, error_message, payload_json"
    )
    with backend.engine.begin() as c:
        for eid in ("e1", "e2"):
            c.execute(
                text(
                    f"INSERT INTO events ({cols}) VALUES (:eid, 'trace-a', 7, 'ts', 'system', "
                    "'a', 'ok', '', '', '', '', '', '', '', '', '', '{}')"
                ),
                {"eid": eid},
            )
    with pytest.raises(RuntimeError, match=r"refusing to upgrade 0004.*trace-a.*#7 x2"):
        migrate.upgrade(backend.url)
    assert migrate.current(backend.url) == "0003"  # nothing moved
    # a clean pre-0004 database takes the index and lands at head
    fresh = _reset(backend)
    migrate.upgrade(backend.url, revision="0003")
    migrate.upgrade(backend.url)
    assert migrate.current(backend.url) == "0011" and _autogen_diff(fresh) == []
    assert "uq_events_trace_seq" in {ix["name"] for ix in inspect(fresh).get_indexes("events")}


def test_0006_backfills_the_github_identity_and_refuses_duplicate_legacy_links(
    backend: Backend,
) -> None:
    """Revision 0006 makes ``repos.github_full_name`` unique. A pre-0006 database holds
    the link only in ``config_json``; the backfill copies it (lower-cased) and creates the
    index LAST. Two legacy rows linked to the same GitHub repository cannot be judged by a
    migration: it refuses with both names and moves nothing (the pattern 0004 set)."""
    migrate.upgrade(backend.url, revision="0005")
    cols = "name, language, runner, clone_path, url, config_json, probo, probe_detail, created, updated"
    cols = cols.replace("probo", "probe_status")
    row = (
        f"INSERT INTO repos ({cols}) VALUES (:name, 'go', 'go', '', 'https://github.com/acme/calc.git', "
        ":cfg, 'unknown', '', 'ts', 'ts')"
    )
    linked = '{"language": "go", "github": {"installation_id": 77, "full_name": "Acme/Calc"}}'
    with backend.engine.begin() as c:
        c.execute(text(row), {"name": "calc", "cfg": linked})
        c.execute(text(row), {"name": "by-url", "cfg": '{"language": "go"}'})
    migrate.upgrade(backend.url)
    assert migrate.current(backend.url) == "0011"
    with backend.engine.connect() as c:
        got = dict(c.execute(text("SELECT name, github_full_name FROM repos")).all())
    assert got == {"calc": "acme/calc", "by-url": None}
    assert "uq_repos_github_full_name" in {
        ix["name"] for ix in inspect(backend.engine).get_indexes("repos")
    }
    # a second row linked to the same repository: refused by name, nothing moved
    fresh = _reset(backend)
    migrate.upgrade(backend.url, revision="0005")
    with fresh.begin() as c:
        c.execute(text(row), {"name": "calc", "cfg": linked})
        c.execute(
            text(row), {"name": "calc-again", "cfg": linked.replace("Acme/Calc", "acme/calc")}
        )
    with pytest.raises(
        RuntimeError, match=r"refusing to upgrade 0006.*acme/calc ← calc, calc-again"
    ):
        migrate.upgrade(backend.url)
    assert migrate.current(backend.url) == "0005"
    assert "github_full_name" not in {c["name"] for c in inspect(fresh).get_columns("repos")}


def test_0007_adds_the_workers_table_and_adoption_tolerates_its_absence(backend: Backend) -> None:
    """Revision 0007 adds ``workers`` — the liveness rows the worker loop upserts even when
    idle (J-TEL-2). Mutable state, no triggers. An ``init_db`` schema from the release
    before it (every table but ``workers``) is a complete schema for that release:
    adoption stamps it at 0006 and 0007 creates the table."""
    migrate.upgrade(backend.url, revision="0006")
    assert "workers" not in set(inspect(backend.engine).get_table_names())
    migrate.upgrade(backend.url, revision="0007")
    assert migrate.current(backend.url) == "0007"
    cols = {c["name"] for c in inspect(backend.engine).get_columns("workers")}
    assert cols == {
        "worker_id",
        "hostname",
        "executor",
        "kinds",
        "started",
        "heartbeat",
        "heartbeat_s",
        "current_run_id",
        "version",
        "stopped",
    }
    assert not {t for t in backend.trigger_names() if t.startswith("workers_")}
    # a pre-0007 create_all database (no alembic_version, no workers table) adopts at 0006
    fresh = _reset(backend)
    init_db(fresh)
    with fresh.begin() as c:
        c.execute(text("DROP TABLE workers"))
    assert migrate.current(backend.url) is None
    migrate.upgrade(backend.url)
    assert migrate.current(backend.url) == "0011" and _autogen_diff(fresh) == []
    assert "workers" in set(inspect(fresh).get_table_names())


def test_0008_adds_the_unconfirmed_containers_count_and_adoption_reads_its_absence(
    backend: Backend,
) -> None:
    """Revision 0008 adds ``workers.unconfirmed_containers`` — the reaper queue's size the
    worker stamps on check-in so ``/health`` can report a killed-but-unconfirmed container.
    ``NOT NULL DEFAULT 0``: every existing row reads 0. A ``create_all`` schema from the
    release before it (``workers`` without the column) adopts at 0007 and 0008 adds it; a
    downgrade drops the column and the table stays."""
    migrate.upgrade(backend.url, revision="0007")
    with backend.engine.begin() as c:
        c.execute(
            text(
                "INSERT INTO workers (worker_id, hostname, executor, kinds, started, heartbeat, "
                "heartbeat_s, current_run_id, version, stopped) VALUES "
                "('w-old', 'h', 'docker', '[]', '', '', 10.0, '', '0', '')"
            )
        )
    migrate.upgrade(backend.url)
    assert migrate.current(backend.url) == "0011"
    cols = {c["name"] for c in inspect(backend.engine).get_columns("workers")}
    assert "unconfirmed_containers" in cols
    with backend.engine.connect() as c:
        got = c.execute(text("SELECT unconfirmed_containers FROM workers")).scalar_one()
    assert got == 0
    assert not {t for t in backend.trigger_names() if t.startswith("workers_")}
    # downgrade drops the column only
    cfg = migrate.alembic_config(backend.url)
    with backend.engine.begin() as connection:
        cfg.attributes["connection"] = connection
        command.downgrade(cfg, "0007")
    assert migrate.current(backend.url) == "0007"
    assert "unconfirmed_containers" not in {
        c["name"] for c in inspect(backend.engine).get_columns("workers")
    }
    assert "workers" in set(inspect(backend.engine).get_table_names())
    # a pre-0008 create_all database (workers without the column) adopts at 0007
    fresh = _reset(backend)
    init_db(fresh)
    with fresh.begin() as c:
        c.execute(text("ALTER TABLE workers DROP COLUMN unconfirmed_containers"))
    assert migrate.current(backend.url) is None
    migrate.upgrade(backend.url)
    assert migrate.current(backend.url) == "0011" and _autogen_diff(fresh) == []


def test_0011_adds_task_qualifications_backfills_one_legacy_row_per_task(
    backend: Backend,
) -> None:
    """Revision 0011 (ADR-0019) adds the append-only ``task_qualifications`` and writes one
    ``legacy`` record per existing task, for the record. A legacy record is never selected
    by a gate; the downgrade drops the table."""
    from crb.core.spec import TaskSpec
    from crb.store import qualifications as sq
    from crb.store.models import Repo, Task

    migrate.upgrade(backend.url, revision="0008")
    factory = make_session_factory(backend.engine)
    specs = [
        TaskSpec(
            task_id=sha * 40,
            repo="calc",
            subject="s",
            authored="2026-01-01T00:00:00Z",
            test_files=("t_test.go",),
            src_files=("s.go",),
            target_tests=("./",),
            belt_scope=("./",),
            baseline_failing=("calc::TestDeadcode",),
            red_checked=True,
            gold_clean=True,
        )
        for sha in ("a", "b")
    ]
    with factory() as s:
        s.add(Repo(name="calc", language="go", runner="go", config_json={"language": "go"}))
        for t in specs:
            s.add(Task(repo="calc", task_id=t.task_id, spec_json=t.to_dict(), authored=t.authored))
        s.commit()
    migrate.upgrade(backend.url)
    assert migrate.current(backend.url) == migrate.head_revision() == "0011"
    with backend.engine.connect() as c:
        n = c.execute(text("SELECT COUNT(*) FROM task_qualifications")).scalar_one()
        states = {r[0] for r in c.execute(text("SELECT state FROM task_qualifications"))}
        posture = {r[0] for r in c.execute(text("SELECT posture_id FROM task_qualifications"))}
    assert n == len(specs) and states == {"legacy"} and posture == {"pst_legacy"}
    with factory() as s:
        legacy = sq.latest(s, "calc", specs[0].task_id, "pst_legacy")
        assert legacy is not None and not legacy.is_qualified
        assert legacy.baseline_failing == ("calc::TestDeadcode",)
        # a legacy row is never selected — in its own posture or any other
        assert sq.qualified_specs(s, "calc", "pst_legacy") == []
    assert {"task_qualifications_no_update", "task_qualifications_no_delete"} <= (
        backend.trigger_names()
    )
    with pytest.raises(DBAPIError, match="append-only"), backend.engine.begin() as c:
        c.execute(text("UPDATE task_qualifications SET state = 'qualified'"))
    # the downgrade drops the table and its triggers
    cfg = migrate.alembic_config(backend.url)
    with backend.engine.begin() as connection:
        cfg.attributes["connection"] = connection
        command.downgrade(cfg, "0008")
    assert migrate.current(backend.url) == "0008"
    assert "task_qualifications" not in set(inspect(backend.engine).get_table_names())
    migrate.upgrade(backend.url)  # and back up at head, equal to init_db
    assert migrate.current(backend.url) == "0011" and _autogen_diff(backend.engine) == []
