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
Touch when:   never for a new repository; a model changes (write the revision, add its marker to
              ``REVISION_MARKERS``, and let the parity case prove head == ``create_all``); never
              edit a shipped revision.
"""

from __future__ import annotations

import io
import json
import sqlite3
from contextlib import redirect_stdout
from itertools import pairwise
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import Engine, inspect, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from crb.core.ledger import GENESIS_HASH
from crb.core.review import ReviewRecord, verify_review_chain
from crb.store import migrate
from crb.store.db import expected_triggers, init_db, make_engine, make_session_factory
from crb.store.ledger import DbLedger, DbReviewLedger, assert_append_only
from crb.store.models import APPEND_ONLY_TABLES, Base

try:
    from tests.conftest_store import Backend, backend, grade_row, pg_schema
except ImportError:  # pragma: no cover — rootdir-relative import (pytest default)
    from conftest_store import Backend, backend, grade_row, pg_schema  # noqa: F401

#: The packaged head: 0016, the context library's acts (north-star Wave 4, stream L).
HEAD = "0016"

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
    # SQLite stores a table rebuilt by batch mode's rename as ``CREATE TABLE "t"``; the
    # quoted and bare lower-case names are one identifier, so the head drops the quotes
    head = " ".join(sql[:open_at].replace('"', "").split())
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
    assert created["__triggers__"] == sorted(name for _, name in expected_triggers(backend.dialect))


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
        "drift": [],
    }

    init_db(backend.engine)
    created = migrate.head_status(backend.url)
    assert created.database is None and created.at_head is False
    assert created.unversioned_at == head and created.matches_models is True

    migrate.upgrade(backend.url)
    # a migrated store at head is compared with the models too (pilot D7, P-437): its
    # schema matches, and the reading says so rather than a false that means "not checked"
    assert migrate.head_status(backend.url) == migrate.HeadStatus(
        head, head, True, matches_models=True
    )
    with backend.factory() as s:  # the connection form /health uses (a session's)
        assert migrate.head_status_on(s.connection()).at_head is True

    command.stamp(migrate.alembic_config(backend.url), migrate.INITIAL_REVISION)
    behind = migrate.head_status(backend.url)
    assert behind == migrate.HeadStatus(migrate.INITIAL_REVISION, head, False)
    assert migrate.check(backend.url) is False  # ``check`` is ``head_status().at_head``


def test_a_migrated_store_at_head_reads_that_its_schema_matches_the_models(
    backend: Backend,
) -> None:
    """Pilot D7 (P-437): the ``migrations`` probe read ``matches_models: false`` on a store
    migrated to head whose schema equals the models — the field was computed for an
    unversioned store only and left ``False`` for every versioned one, so the truth ("it
    matches") and the unknown ("never compared") read the same. A versioned store at head is
    now compared, by the same ``compare_metadata`` adoption uses, and reads ``True``."""
    migrate.upgrade(backend.url)
    st = migrate.head_status(backend.url)
    assert st.at_head is True
    assert st.matches_models is True and st.drift == ()
    assert st.to_dict()["matches_models"] is True and st.to_dict()["drift"] == []


def test_a_store_at_head_whose_schema_drifted_names_the_drift(backend: Backend) -> None:
    """The class D7 belongs to — a reading that cannot tell a matching schema from one that
    was never compared — is closed only if a real difference reads ``False``: an index
    dropped outside the migrations leaves the store stamped at head, and the reading names
    the difference instead of passing it."""
    migrate.upgrade(backend.url)
    with backend.engine.begin() as c:
        c.execute(text("DROP INDEX ix_runs_status"))
    st = migrate.head_status(backend.url)
    assert st.at_head is True and st.matches_models is False
    assert any("ix_runs_status" in d for d in st.drift), st.drift


def test_the_health_reading_compares_again_after_an_out_of_band_change(backend: Backend) -> None:
    """Why ``/health`` compares the schema on every read and never caches it by revision: an
    out-of-band change (an index dropped by hand) leaves the revision where it was, so a
    cache keyed on the revision would keep answering "matches" — the very reading pilot D7
    closed. The same process reads the store twice, before and after the change."""
    migrate.upgrade(backend.url)
    with backend.engine.connect() as c:
        assert migrate.head_status_on(c).matches_models is True
    with backend.engine.begin() as c:
        c.execute(text("DROP INDEX ix_runs_status"))
    with backend.engine.connect() as c:
        st = migrate.head_status_on(c)
    assert st.at_head is True and st.matches_models is False


def test_a_dropped_server_default_is_drift_on_postgresql(backend: Backend) -> None:
    """Q1's review: the probe compared with alembic's defaults, so a server default dropped
    outside the migrations on PostgreSQL read ``matches_models: True``. PostgreSQL reflects
    defaults faithfully, so the comparison includes them there (on SQLite the reflection
    reads a false difference at head, and the DDL parity test guards migrations instead)."""
    if backend.dialect != "postgresql":
        pytest.skip(
            "server defaults are compared on PostgreSQL only (SQLite reflects them loosely)"
        )
    migrate.upgrade(backend.url)
    assert migrate.head_status(backend.url).matches_models is True  # no false positive at head
    with backend.engine.begin() as c:
        c.execute(text("ALTER TABLE users ALTER COLUMN session_nonce DROP DEFAULT"))
    st = migrate.head_status(backend.url)
    assert st.at_head is True and st.matches_models is False
    assert any("session_nonce" in d for d in st.drift), st.drift


def test_a_constraint_difference_names_its_table_and_columns() -> None:
    """An unnamed constraint (a column's ``unique=True``) has no name to print: the drift line
    names the table and the columns instead of a bare ``add_constraint``."""
    from sqlalchemy import Column, Integer, MetaData, String, Table, UniqueConstraint

    table = Table("users", MetaData(), Column("id", Integer), Column("email", String))
    unnamed = UniqueConstraint(table.c.email)
    assert migrate._describe_difference(("add_constraint", unnamed)) == (
        "add_constraint users unique(email)"
    )
    named = UniqueConstraint(table.c.email, name="uq_users_email")
    assert migrate._describe_difference(("remove_constraint", named)) == (
        "remove_constraint users uq_users_email unique(email)"
    )


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

    assert migrate.current(backend.url) == migrate.head_revision() == HEAD
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
    # the refusal rolls the whole downgrade back — 0015's and 0014's tables, 0008's column,
    # 0007's and 0005's tables, 0006's column, 0004's index swap and 0003's drop of the
    # (empty) reviews table included — so the database stays exactly where it was
    assert migrate.current(backend.url) == HEAD

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
    assert migrate.current(backend.url) == HEAD and _autogen_diff(fresh) == []


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
    # 0013 offline refuses an unchained row too (P-254): the CHECK after the back-fill
    check = sql.find("ck_events_chain_hashes")
    assert check > sql.find("ADD COLUMN row_hash"), sql[-2000:]
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
    assert migrate.current(backend.url) == HEAD and _autogen_diff(fresh) == []
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
    assert migrate.current(backend.url) == HEAD
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
    assert migrate.current(backend.url) == HEAD and _autogen_diff(fresh) == []
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
    assert migrate.current(backend.url) == HEAD
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
    assert migrate.current(backend.url) == HEAD and _autogen_diff(fresh) == []


def test_0009_adds_the_session_nonce_and_keeps_every_account_signed_in(
    backend: Backend,
) -> None:
    """Revision 0009 adds ``users.session_nonce`` — rotated to end every session of an
    account (logout, sign out everywhere). ``NOT NULL DEFAULT ''``: every existing account
    reads the empty nonce, whose credential version is the one it had before, so the
    upgrade signs nobody out. A ``create_all`` schema from the release before it adopts at
    0008 and 0009 adds the column; a downgrade drops it."""
    migrate.upgrade(backend.url, revision="0008")
    with backend.engine.begin() as c:
        c.execute(
            text(
                "INSERT INTO users (id, subject, issuer, email, display_name, role, "
                "password_hash, active, created, last_login) VALUES "
                "('u-old', 'local:old', 'local', '', 'old', 'viewer', '$argon2id$x', "
                ":active, '', '')"
            ),
            {"active": True},
        )
    migrate.upgrade(backend.url)
    assert migrate.current(backend.url) == migrate.head_revision() == HEAD
    with backend.engine.connect() as c:
        got = c.execute(text("SELECT session_nonce FROM users")).scalar_one()
    assert got == ""
    assert not {t for t in backend.trigger_names() if t.startswith("users_")}
    cfg = migrate.alembic_config(backend.url)
    with backend.engine.begin() as connection:
        cfg.attributes["connection"] = connection
        command.downgrade(cfg, "0008")
    assert migrate.current(backend.url) == "0008"
    assert "session_nonce" not in {c["name"] for c in inspect(backend.engine).get_columns("users")}
    # a pre-0009 create_all database (users without the column) adopts at 0008
    fresh = _reset(backend)
    init_db(fresh)
    with fresh.begin() as c:
        c.execute(text("ALTER TABLE users DROP COLUMN session_nonce"))
    assert migrate.current(backend.url) is None
    migrate.upgrade(backend.url)
    assert migrate.current(backend.url) == HEAD and _autogen_diff(fresh) == []


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
    assert migrate.current(backend.url) == migrate.head_revision() == HEAD
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
    assert migrate.current(backend.url) == HEAD and _autogen_diff(backend.engine) == []


def test_0011_downgrade_refuses_while_a_measured_qualification_exists(backend: Backend) -> None:
    """From apparatus 2.3 every measured grade row cites its ``qualification_id``: a
    downgrade that dropped a measured record would leave evidence citing nothing, and an
    append-only table's rows are never dropped. So 0011's downgrade refuses while any record
    but the back-fill's ``legacy`` ones exists (0002's pattern), and drops a table that holds
    only the back-fill (CodeRabbit on PR #56)."""
    from crb.core.qualify import Qualification
    from crb.store import qualifications as sq

    migrate.upgrade(backend.url)
    factory = make_session_factory(backend.engine)
    with factory() as s:
        sq.append(
            s,
            Qualification(
                qualification_id="",
                repo="calc",
                task_id="a" * 40,
                posture_id="pst_" + "1" * 24,
                posture={"posture_class": "docker/copy/sealed"},
                state="qualified",
            ),
        )
    cfg = migrate.alembic_config(backend.url)
    with (
        pytest.raises(RuntimeError, match="refusing to downgrade 0011"),
        backend.engine.begin() as connection,
    ):
        cfg.attributes["connection"] = connection
        command.downgrade(cfg, "0008")
    assert "task_qualifications" in set(inspect(backend.engine).get_table_names())
    assert migrate.current(backend.url) == HEAD


def test_no_released_revision_imports_the_application_runtime() -> None:
    """A released revision is immutable, so what it writes must not move when the product's
    code does: a revision imports nothing of ``crb`` but the store's one trigger helper
    (``crb.store.migrate``) — never ``crb.core`` records, rules or version strings, whose
    later changes would change (or break) what an old revision writes (CodeRabbit on PR
    #56, revision 0011's back-fill)."""
    import ast

    allowed = {"crb.store.migrate"}
    versions = Path(migrate.__file__).parent / "migrations" / "versions"
    offenders: list[str] = []
    for path in sorted(versions.glob("v*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names: list[str] = []
            if isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            elif isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            offenders += [
                f"{path.name}: {n}" for n in names if n.split(".")[0] == "crb" and n not in allowed
            ]
    assert offenders == []


#: Released before the rule (docs/PREVENTION.md P-403) and immutable: 0002's downgrade copies
#: ``grades`` on SQLite. It stays refused while any ``v5`` row exists; nothing newer may add to
#: this set.
_FROZEN_BEFORE_P403 = frozenset({"v0002_belt5_repo_lint_clean.py"})


def test_no_downgrade_copies_the_rows_of_an_append_only_table_on_sqlite() -> None:
    """docs/PREVENTION.md P-403: SQLite drops a column only by copying every row into a new
    table (``batch_alter_table``'s move-and-copy), and a migration never rewrites the rows of
    an append-only table. A revision that batch-alters one must refuse on SQLite while the
    table holds any row — a dialect check and an unfiltered ``COUNT(*)`` of that table."""
    import re

    versions = Path(migrate.__file__).parent / "migrations" / "versions"
    offenders: list[str] = []
    for path in sorted(versions.glob("v*.py")):
        src = path.read_text(encoding="utf-8")
        consts = dict(re.findall(r'^([A-Z_]+) = "(\w+)"', src, re.M))
        for ref in re.findall(r"batch_alter_table\(([^)]+)\)", src):
            table = consts.get(ref.strip(), ref.strip().strip("\"'"))
            if table not in APPEND_ONLY_TABLES or path.name in _FROZEN_BEFORE_P403:
                continue
            refuses = 'dialect.name == "sqlite"' in src and f'COUNT(*) FROM {table}")' in src
            if not refuses:
                offenders.append(f"{path.name}: {table}")
    assert offenders == []


def test_0011_backfills_the_legacy_record_the_runtime_reads() -> None:
    """The back-fill's frozen body is a record the product reads back unchanged, and its
    fingerprint is the product's own rule applied to the same facts (a copy that drifted
    would make a legacy record look like a different oracle)."""
    import importlib

    from crb.core.qualify import Qualification, fingerprint_of

    m = importlib.import_module("crb.store.migrations.versions.v0011_task_qualifications")
    body = m.legacy_body(
        "calc", "a" * 40, {"baseline_failing": ["b", "a", "a"], "gold_clean": True}, "q1", "t"
    )
    q = Qualification.from_dict(body)
    assert q.state == "legacy" and q.posture_id == "pst_legacy" and not q.is_qualified
    assert q.baseline_failing == ("a", "b") and q.gold == {"clean": True, "note": "", "lint": None}
    assert body["fingerprint"] == fingerprint_of(q) == q.fingerprint
    assert body["provenance"] == "migrated_unverified" and body["apparatus_version"] == "2.3"


def _insert_review(conn: Any, *, n: int, minutes: int | None = None) -> None:
    """One review chained the ledger's way (``ReviewRecord.chained`` on the stored head) and
    stored with raw SQL, because the ORM model declares ``minutes`` and a 0011 schema has no
    such column (``minutes`` is written only when the schema has it)."""
    head = conn.execute(
        text("SELECT row_hash FROM reviews ORDER BY seq DESC LIMIT 1")
    ).scalar_one_or_none()
    rec = ReviewRecord(
        grade_row_hash=f"{n:064x}",
        repo="calc",
        task_id=f"{n:040x}",
        reviewer="u1",
        statement="looked",
        verdict="not_reviewed",
        minutes=minutes,
        apparatus_version="2.3",
        created="2026-09-26T10:00:00+00:00",
    ).chained(head or GENESIS_HASH)
    params = rec.to_dict()
    assert params.pop("findings") == []  # a not_reviewed record carries none: '[]' below
    params.setdefault("mergeable", None)
    cols = [k for k in params if k != "minutes" or minutes is not None]
    conn.execute(
        text(
            f"INSERT INTO reviews (findings_json, {', '.join(cols)}) "
            f"VALUES ('[]', {', '.join(':' + k for k in cols)})"
        ),
        {k: params[k] for k in cols},
    )


def _verify_reviews(engine: Engine) -> int:
    """Walk the stored review chain at whatever revision the schema is at; raises
    ``LedgerIntegrityError`` on a record whose hash or link no longer verifies."""
    with engine.connect() as c:
        stored = c.execute(text("SELECT * FROM reviews ORDER BY seq")).mappings().all()
    records = []
    for m in stored:
        d = dict(m)
        raw = d.pop("findings_json")
        d["findings"] = json.loads(raw) if isinstance(raw, str) else raw
        records.append(ReviewRecord.from_dict(d))
    return verify_review_chain(records)


def test_0012_adds_the_reviewers_minutes_nullable_and_keeps_reviews_append_only(
    backend: Backend,
) -> None:
    """Revision 0012 (DL-067) adds ``reviews.minutes`` — the reviewer's own time on a review.
    Every existing review reads NULL (not stated), and its chain still verifies after the
    upgrade; the append-only triggers still refuse an UPDATE; a downgrade is refused while
    any review states its minutes, and on SQLite while any review exists at all (dropping a
    column there copies every row into a new table); an empty table's column may go. A
    ``create_all`` schema from the release before it adopts at 0011 and 0012 adds the
    column."""
    migrate.upgrade(backend.url, revision="0011")
    with backend.engine.begin() as c:
        _insert_review(c, n=1)
    assert _verify_reviews(backend.engine) == 1
    migrate.upgrade(backend.url)
    assert migrate.current(backend.url) == migrate.head_revision() == HEAD
    with backend.engine.connect() as c:
        assert c.execute(text("SELECT minutes FROM reviews")).scalar_one() is None
    assert _verify_reviews(backend.engine) == 1
    assert {"reviews_no_update", "reviews_no_delete"} <= backend.trigger_names()
    with pytest.raises(DBAPIError, match="append-only"), backend.engine.begin() as c:
        c.execute(text("UPDATE reviews SET minutes = 5"))
    with backend.engine.begin() as c:
        _insert_review(c, n=2, minutes=7)
    assert _verify_reviews(backend.engine) == 2
    assert DbReviewLedger(backend.factory).verify() == 2
    cfg = migrate.alembic_config(backend.url)
    with (
        pytest.raises(RuntimeError, match="state their minutes"),
        backend.engine.begin() as connection,
    ):
        cfg.attributes["connection"] = connection
        command.downgrade(cfg, "0011")
    assert migrate.current(backend.url) == HEAD
    # with no minutes stated, SQLite still refuses while a review exists; PostgreSQL drops
    # the column in place, and the chain still verifies
    fresh = _reset(backend)
    migrate.upgrade(backend.url)
    with fresh.begin() as c:
        _insert_review(c, n=3)
    cfg = migrate.alembic_config(backend.url)
    if backend.dialect == "sqlite":
        with (
            pytest.raises(RuntimeError, match="reviews is append-only"),
            fresh.begin() as connection,
        ):
            cfg.attributes["connection"] = connection
            command.downgrade(cfg, "0011")
        assert migrate.current(backend.url) == HEAD
        # an empty table's column may go
        fresh = _reset(backend)
        migrate.upgrade(backend.url)
    with fresh.begin() as connection:
        cfg.attributes["connection"] = connection
        command.downgrade(cfg, "0011")
    assert migrate.current(backend.url) == "0011"
    assert "minutes" not in {c["name"] for c in inspect(fresh).get_columns("reviews")}
    assert _verify_reviews(fresh) == (0 if backend.dialect == "sqlite" else 1)
    assert {"reviews_no_update", "reviews_no_delete"} <= backend.trigger_names()
    # a pre-0012 create_all database (reviews without the column) adopts at 0011
    fresh = _reset(backend)
    init_db(fresh)
    with fresh.begin() as c:
        c.execute(text("ALTER TABLE reviews DROP COLUMN minutes"))
    assert migrate.current(backend.url) is None
    migrate.upgrade(backend.url)
    assert migrate.current(backend.url) == HEAD and _autogen_diff(fresh) == []


def _insert_event(conn: Any, *, n: int, payload: str = '{"k": [1, 2]}') -> None:
    """One stored ``events`` row as a pre-0013 schema holds it (no chain columns)."""
    conn.execute(
        text(
            "INSERT INTO events (event_id, trace_id, seq, timestamp, stage, action, status, "
            "step_id, parent_step_id, actor, repo, task_id, input_ref, output_ref, error_code, "
            "error_message, duration_ms, cost_usd, payload_json) VALUES (:e, :t, :s, "
            "'2026-09-26T10:00:00+00:00', 'system', 'user.login', 'ok', '', '', 'u1', '', '', "
            "'', '', '', '', :d, :c, :p)"
        ),
        {
            "e": f"{n:032x}",
            "t": "t" * 32,
            "s": n,
            "d": n * 10,
            "c": 1 if n % 2 else None,
            "p": payload,
        },
    )


def _chain_of(engine: Engine) -> list[tuple[int, str, str]]:
    with engine.connect() as c:
        return [
            (int(i), str(p), str(h))
            for i, p, h in c.execute(text("SELECT id, prev_hash, row_hash FROM events ORDER BY id"))
        ]


def test_0013_chains_the_existing_events_deterministically_and_verifies(backend: Backend) -> None:
    """Revision 0013 (ADR-0029, F51) adds the chain columns and chains every event that was
    already there, from genesis, in id order — the same rows give the same hashes on every
    run — so the runtime verifier reads the migrated audit trail as intact, and the next
    event written chains onto it. The triggers are back afterwards."""
    from crb.observability.events import StepEvent
    from crb.store.events import DbEventSink, verify_events

    migrate.upgrade(backend.url, revision="0012")
    with backend.engine.begin() as c:
        for n in range(1, 6):
            _insert_event(c, n=n)
    migrate.upgrade(backend.url)
    assert migrate.current(backend.url) == migrate.head_revision() == HEAD
    first = _chain_of(backend.engine)
    assert first[0][1] == "0" * 64 and len({h for _i, _p, h in first}) == 5
    assert all(b[1] == a[2] for a, b in pairwise(first))
    report = verify_events(backend.factory)
    assert report.ok and report.rows == 5 and report.head == first[-1][2], report.detail
    assert _autogen_diff(backend.engine) == []
    assert {"events_no_update", "events_no_delete"} <= backend.trigger_names()
    with pytest.raises(DBAPIError, match="append-only"), backend.engine.begin() as c:
        c.execute(text("UPDATE events SET prev_hash = row_hash"))
    DbEventSink(backend.factory).emit(StepEvent(trace_id="x", stage="system", action="a", seq=1))
    assert verify_events(backend.factory).rows == 6 and verify_events(backend.factory).ok
    # deterministic: the same rows migrated again give the same chain
    fresh = _reset(backend)
    migrate.upgrade(backend.url, revision="0012")
    with fresh.begin() as c:
        for n in range(1, 6):
            _insert_event(c, n=n)
    migrate.upgrade(backend.url)
    assert _chain_of(fresh) == first
    # and the downgrade drops the chain, never the events
    cfg = migrate.alembic_config(backend.url)
    with fresh.begin() as connection:
        cfg.attributes["connection"] = connection
        command.downgrade(cfg, "0012")
    cols = {c["name"] for c in inspect(fresh).get_columns("events")}
    assert "row_hash" not in cols and "prev_hash" not in cols
    with fresh.connect() as c:
        assert c.execute(text("SELECT COUNT(*) FROM events")).scalar_one() == 5
    assert {"events_no_update", "events_no_delete"} <= backend.trigger_names()


def _events_as_text(engine: Engine, columns: list[str]) -> list[tuple[str | None, ...]]:
    """Every ``events`` row, each named column cast to text by the database, not read by a
    driver (a JSON column stays its stored text). It compares text, not the stored bytes:
    a change of storage type that renders the same text is not seen here."""
    cast = ", ".join(f"CAST({c} AS TEXT)" for c in columns)
    with engine.connect() as c:
        return [tuple(r) for r in c.execute(text(f"SELECT {cast} FROM events ORDER BY id"))]


def test_0013_leaves_every_existing_events_field_as_it_was(backend: Backend) -> None:
    """ADR-0029 §3's recorded exception to the store rule: 0013 writes the two NEW chain
    columns of rows that were already there (and SQLite rebuilds the table to add the
    CHECK), so it must leave every column those rows held before — every hashed field and
    the id — as it was. A back-fill or rebuild that changed one (a JSON re-serialised, a
    float re-rounded, an id renumbered, a column retyped) would alter the audit trail it
    claims to protect (DL-350). The test reads each column's declared type and its value
    as text; it does not read the stored bytes."""
    migrate.upgrade(backend.url, revision="0012")
    before_types = {
        c["name"]: str(c["type"]) for c in inspect(backend.engine).get_columns("events")
    }
    before_cols = list(before_types)
    assert "row_hash" not in before_cols and "prev_hash" not in before_cols
    with backend.engine.begin() as c:
        for n in range(1, 6):
            _insert_event(c, n=n, payload='{"k" : [1,2.50], "é": "\\u00e9 x"}')
    before = _events_as_text(backend.engine, before_cols)
    migrate.upgrade(backend.url)
    assert migrate.current(backend.url) == HEAD
    assert _events_as_text(backend.engine, before_cols) == before
    after_types = {c["name"]: str(c["type"]) for c in inspect(backend.engine).get_columns("events")}
    assert {k: after_types.get(k) for k in before_cols} == before_types
    assert {"events_no_update", "events_no_delete"} <= backend.trigger_names()


def test_0013_adopts_a_create_all_schema_from_the_release_before(backend: Backend) -> None:
    """A pre-0013 ``create_all`` database (events without the chain) is at 0012 by its
    markers; 0013 adds the columns, chains the rows it holds and leaves no drift."""
    from crb.store.events import verify_events

    fresh = _reset(backend)
    # the release before's schema is 0012's (test_upgrade_head_equals_init_db holds every
    # revision to create_all); drop the version table and it is that release's create_all
    migrate.upgrade(backend.url, revision="0012")
    with fresh.begin() as c:
        c.execute(text("DROP TABLE alembic_version"))
        _insert_event(c, n=1)
    assert migrate.current(backend.url) is None
    migrate.upgrade(backend.url)
    assert migrate.current(backend.url) == HEAD and _autogen_diff(fresh) == []
    assert verify_events(make_session_factory(fresh)).rows == 1


def test_0013_frozen_rule_is_the_runtime_rule() -> None:
    """The revision carries its own copy of the chain rule (a released revision imports
    nothing of the runtime); a copy that drifted would chain the migrated rows under a rule
    the verifier does not read."""
    import importlib

    from crb.core.event_chain import GENESIS_HASH, event_row_hash

    m = importlib.import_module("crb.store.migrations.versions.v0013_events_hash_chain")
    row = {
        "event_id": "e" * 32,
        "trace_id": "t" * 32,
        "seq": 3,
        "timestamp": "2026-09-26T10:00:00+00:00",
        "stage": "system",
        "action": "user.login",
        "status": "ok",
        "step_id": "",
        "parent_step_id": "",
        "actor": "u1",
        "repo": "r",
        "task_id": "",
        "input_ref": "",
        "output_ref": "",
        "error_code": "",
        "error_message": "é ✓",
        "duration_ms": 5,
        "cost_usd": 1,
        "payload_json": {"b": (1, 2), "a": {"z": None}},
    }
    assert m.GENESIS_HASH == GENESIS_HASH
    for prev in (GENESIS_HASH, "a" * 64):
        assert m._row_hash(row, prev) == event_row_hash(row, prev)


def test_0013_refuses_a_row_from_the_release_before_it_and_keeps_recording(
    backend: Backend,
) -> None:
    """P-254: during a rolling upgrade the release before 0013 keeps writing events, and a
    rollback runs it against the migrated schema. Its INSERT names no chain column. The
    migrated table must refuse that row outright — if it stored ``''`` it would become a
    head no later write can chain onto, and the audit trail (sign-in included) would stop
    for good."""
    from crb.observability.events import StepEvent
    from crb.store.events import DbEventSink, verify_events

    migrate.upgrade(backend.url, revision="0012")
    with backend.engine.begin() as c:
        _insert_event(c, n=1)
    migrate.upgrade(backend.url)
    for n in (2, 3):
        with pytest.raises(IntegrityError), backend.engine.begin() as c:
            _insert_event(c, n=n)
    sink = DbEventSink(backend.factory)
    sink.emit(StepEvent(trace_id="x", stage="system", action="a", seq=1))
    assert sink.dropped == 0
    report = verify_events(backend.factory)
    assert report.ok and report.rows == 2, report.detail
    assert {"events_no_update", "events_no_delete"} <= backend.trigger_names()
    # the rollback path the runbook names: downgrade first, then the old release writes
    cfg = migrate.alembic_config(backend.url)
    with backend.engine.begin() as connection:
        cfg.attributes["connection"] = connection
        command.downgrade(cfg, "0012")
    with backend.engine.begin() as c:
        _insert_event(c, n=4)
    migrate.upgrade(backend.url)
    report = verify_events(backend.factory)
    assert report.ok and report.rows == 3, report.detail


def test_0014_adds_the_invitations_table_and_adoption_tolerates_its_absence(
    backend: Backend,
) -> None:
    """Revision 0014 adds ``invitations`` — the one-time invitation that brings the second
    person in (G-518). Mutable state, no append-only triggers: the audit trail is the
    account's ``user.*`` events. An ``init_db`` schema from the release before it (every
    table but ``invitations``) is a complete schema for that release: adoption stamps it at
    0013 and 0014 creates the table."""
    migrate.upgrade(backend.url, revision="0013")
    assert "invitations" not in set(inspect(backend.engine).get_table_names())
    migrate.upgrade(backend.url, revision="0014")
    assert migrate.current(backend.url) == "0014"
    cols = {c["name"] for c in inspect(backend.engine).get_columns("invitations")}
    assert cols == {
        "id",
        "user_id",
        "token_hash",
        "role",
        "created",
        "expires",
        "accepted",
        "revoked",
        "created_by",
        "revoked_reason",
    }
    assert not {t for t in backend.trigger_names() if t.startswith("invitations_")}
    # the token hash is unique — a redeemable token can never be shared by two invitations
    uniques = inspect(backend.engine).get_unique_constraints("invitations")
    assert {u["name"]: tuple(u["column_names"]) for u in uniques} == {
        "uq_invitations_token_hash": ("token_hash",)
    }
    assert {i["name"] for i in inspect(backend.engine).get_indexes("invitations")} >= {
        "ix_invitations_user"
    }
    # a pre-0014 create_all database (no alembic_version, no invitations table) adopts at 0013
    fresh = _reset(backend)
    init_db(fresh)
    with fresh.begin() as c:
        c.execute(text("DROP TABLE invitations"))
    assert migrate.current(backend.url) is None
    migrate.upgrade(backend.url)
    assert migrate.current(backend.url) == HEAD and _autogen_diff(fresh) == []
    assert "invitations" in set(inspect(fresh).get_table_names())


def test_0015_adds_the_decisions_due_table_and_adoption_tolerates_its_absence(
    backend: Backend,
) -> None:
    """Revision 0015 adds ``decisions_due`` — when each derived decisions-inbox row first
    became due and when it was last seen (G-516), unique on ``(repo, kind, key)``. A clock
    over a derivation, not evidence: no append-only triggers, and a downgrade drops it. An
    ``init_db`` schema from the release before it adopts at 0014 and 0015 creates it."""
    migrate.upgrade(backend.url, revision="0014")
    assert "decisions_due" not in set(inspect(backend.engine).get_table_names())
    migrate.upgrade(backend.url, revision="0015")
    assert migrate.current(backend.url) == "0015"
    cols = {c["name"] for c in inspect(backend.engine).get_columns("decisions_due")}
    assert cols == {
        "id",
        "repo",
        "kind",
        "key",
        "title",
        "role",
        "first_due",
        "last_seen",
        "resolved",
    }
    assert not {t for t in backend.trigger_names() if t.startswith("decisions_due")}
    uniques = inspect(backend.engine).get_unique_constraints("decisions_due")
    assert {u["name"]: tuple(u["column_names"]) for u in uniques} == {
        "uq_decisions_due_row": ("repo", "kind", "key")
    }
    # a pre-0015 create_all database (no alembic_version, no table) adopts at 0014
    fresh = _reset(backend)
    init_db(fresh)
    with fresh.begin() as c:
        c.execute(text("DROP TABLE decisions_due"))
    assert migrate.current(backend.url) is None
    migrate.upgrade(backend.url)
    assert migrate.current(backend.url) == HEAD and _autogen_diff(fresh) == []
    assert "decisions_due" in set(inspect(fresh).get_table_names())


def _insert_library_act(conn: Any, n: int) -> None:
    """One stored library act with every column revision 0016 requires."""
    conn.execute(
        text(
            "INSERT INTO library_acts (act_id, schema, repo, entry_id, version, act, actor, "
            "body_json, created, prev_hash, row_hash) VALUES (:id, 'crb.library.v1', 'calc', "
            "'convention/x', :v, 'propose', :who, '{}', '2026-09-27T00:00:00+00:00', :p, :h)"
        ),
        {"id": f"{n:032x}", "v": "v" * 64, "who": "a" * 32, "p": "0" * 64, "h": f"{n:064x}"},
    )


def test_0016_adds_the_library_acts_append_only_and_never_drops_a_signature(
    backend: Backend,
) -> None:
    """Revision 0016 (ADR-0026 item 10) adds ``library_acts`` — the context library's
    hash-chained acts — with the append-only triggers; a downgrade is refused while any act
    exists (a signature is never dropped) and otherwise drops the table."""
    migrate.upgrade(backend.url, revision="0015")
    assert "library_acts" not in inspect(backend.engine).get_table_names()
    migrate.upgrade(backend.url)
    assert migrate.current(backend.url) == migrate.head_revision() == HEAD
    assert {"library_acts_no_update", "library_acts_no_delete"} <= backend.trigger_names()
    with backend.engine.begin() as c:
        _insert_library_act(c, 1)
    with pytest.raises(DBAPIError, match="append-only"), backend.engine.begin() as c:
        c.execute(text("UPDATE library_acts SET actor = 'x'"))
    cfg = migrate.alembic_config(backend.url)
    with (
        pytest.raises(RuntimeError, match="refusing to downgrade 0016"),
        backend.engine.begin() as connection,
    ):
        cfg.attributes["connection"] = connection
        command.downgrade(cfg, "0015")
    assert migrate.current(backend.url) == HEAD
    fresh = _reset(backend)
    migrate.upgrade(backend.url)
    cfg = migrate.alembic_config(backend.url)
    with fresh.begin() as connection:
        cfg.attributes["connection"] = connection
        command.downgrade(cfg, "0015")
    assert migrate.current(backend.url) == "0015"
    assert "library_acts" not in inspect(fresh).get_table_names()
    # a create_all schema from before the library adopts at 0015 and 0016 adds the table
    fresh = _reset(backend)
    init_db(fresh)
    with fresh.begin() as c:
        c.execute(text("DROP TABLE library_acts"))
    migrate.upgrade(backend.url)
    assert migrate.current(backend.url) == HEAD and _autogen_diff(fresh) == []
