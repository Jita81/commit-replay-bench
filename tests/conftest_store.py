"""Shared backend fixtures and row builders for the ``crb.store`` tests.

Deliberately NOT a ``conftest.py`` (that file belongs to the core suite, as with
``conftest_langs.py``): the ``test_store_*`` modules import this explicitly.

Every store test is parametrised over two backends:

* ``sqlite`` — always; a fresh file under ``tmp_path`` per test (WAL, FK on).
* ``postgres`` — only when ``CRB_TEST_POSTGRES_URL`` is set (CI's ``test-postgres`` job, or
  a developer's local server). A **session-scoped** fixture creates one throw-away schema
  (``crb_test_<hex>``) and drops it at the end; each test starts from that schema reset to
  empty, reached through ``?options=-csearch_path=<schema>`` so nothing here ever touches
  ``public``.

Same tests, same assertions, both dialects — the append-only triggers, the write lock and
the chain must behave identically or the production store is not the store we tested.

Navigation
----------
What it is:   Shared backend fixtures and row builders for the ``crb.store`` suites (imported
              explicitly; not a conftest).
What it does: Parametrises every store test over SQLite (always) and PostgreSQL (only when
              ``CRB_TEST_POSTGRES_URL`` is set), each test starting from an EMPTY database, and
              supplies a clean fully-evidenced ``GradeRow``, a ``TaskSpec`` and an
              ``EvidencePack`` so the append-only, lock and chain behaviour is asserted
              identically on both dialects.
How:          A session-scoped throw-away PostgreSQL schema (``crb_test_<hex>``) reached through
              ``search_path`` and reset per test; SQLite as a fresh file under ``tmp_path`` with
              WAL and foreign keys on; ``Backend`` wraps the engine and session factory.
Layer:        tests — docs/ARCHITECTURE.md#73-data-model-store-p4
ADRs:         docs/adr/0002-append-only-hash-chained-ledger.md
Works with:   src/crb/store/db.py (the engines and session factory under test),
              src/crb/store/ledger.py (``DbLedger`` the row builders feed), src/crb/core/ledger.py
              (``GradeRow``), tests/test_store_ledger.py and tests/test_store_migrate.py (typical
              callers), .github/workflows/ci.yml (the ``test-postgres`` job that sets the URL)
Tested by:    tests/test_store_db.py, tests/test_store_ledger.py, tests/test_store_migrate.py,
              tests/test_store_reviews.py (every consumer)
Touch when:   never for a new repository; a new dialect is supported (add it to the ``backend``
              parametrisation and CI); the ``GradeRow`` evidence fields change (``grade_row``
              must stay a row the write-time invariant accepts).
"""

from __future__ import annotations

import os
import secrets
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from crb.core import evidence as ev
from crb.core.grade import Belts, GradeResult
from crb.core.ledger import GradeRow
from crb.core.spec import TaskSpec
from crb.store.db import make_engine, make_session_factory

POSTGRES_URL = os.environ.get("CRB_TEST_POSTGRES_URL", "").strip()

BACKENDS = [
    pytest.param("sqlite", id="sqlite"),
    pytest.param(
        "postgres",
        id="postgres",
        marks=pytest.mark.skipif(not POSTGRES_URL, reason="CRB_TEST_POSTGRES_URL not set"),
    ),
]

SHA = "b7c6251293a287542ac8568cad7505b710fa3532"
PACK = "c" * 64


# ---------------------------------------------------------------------------
# Backends
# ---------------------------------------------------------------------------


@dataclass
class Backend:
    """One live, empty database plus the engine/session factory the store uses."""

    name: str
    url: str
    engine: Engine
    factory: sessionmaker[Session]

    @property
    def dialect(self) -> str:
        """``"sqlite"`` or ``"postgresql"`` — the tests branch on it only for
        dialect-specific SQL.
        """
        return self.engine.dialect.name

    def new_engine(self) -> Engine:
        """A second, independent engine to the same database (standalone verification)."""
        return make_engine(self.url)

    def trigger_names(self) -> set[str]:
        """The append-only triggers present on this database, read from the catalogue of the
        dialect.
        """
        with self.engine.connect() as c:
            if self.dialect == "sqlite":
                q = "SELECT name FROM sqlite_master WHERE type = 'trigger'"
            else:
                q = (
                    "SELECT t.tgname FROM pg_trigger t "
                    "JOIN pg_class c ON c.oid = t.tgrelid "
                    "JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "WHERE NOT t.tgisinternal AND n.nspname = current_schema()"
                )
            return {str(r[0]) for r in c.execute(text(q))}

    def drop_grades_triggers(self) -> None:
        """Remove the ``grades`` append-only triggers — for tests that prove tampering is still
        caught (by the chain) once the database-level protection is gone.
        """
        with self.engine.begin() as c:
            for name in ("grades_no_update", "grades_no_delete"):
                on = " ON grades" if self.dialect == "postgresql" else ""
                c.execute(text(f"DROP TRIGGER IF EXISTS {name}{on}"))


def _pg_schema_url(schema: str) -> str:
    base = make_url(POSTGRES_URL)
    return base.update_query_dict({"options": f"-csearch_path={schema}"}).render_as_string(
        hide_password=False
    )


@pytest.fixture(scope="session")
def pg_schema() -> Iterator[str]:
    """Create one throw-away PostgreSQL schema for the session; drop it afterwards."""
    if not POSTGRES_URL:
        pytest.skip("CRB_TEST_POSTGRES_URL not set")
    schema = f"crb_test_{secrets.token_hex(4)}"
    admin = make_engine(POSTGRES_URL)
    with admin.begin() as c:
        c.execute(text(f"CREATE SCHEMA {schema}"))
    try:
        yield schema
    finally:
        with admin.begin() as c:
            c.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
        admin.dispose()


def _reset_pg_schema(schema: str) -> None:
    admin = make_engine(POSTGRES_URL)
    with admin.begin() as c:
        c.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
        c.execute(text(f"CREATE SCHEMA {schema}"))
    admin.dispose()


@pytest.fixture(params=BACKENDS)
def backend(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[Backend]:
    """An EMPTY database (no tables) on the parametrised backend."""
    name = str(request.param)
    if name == "sqlite":
        url = f"sqlite:///{tmp_path / 'crb.db'}"
    else:
        schema = request.getfixturevalue("pg_schema")
        _reset_pg_schema(schema)
        url = _pg_schema_url(schema)
    engine = make_engine(url)
    try:
        yield Backend(name=name, url=url, engine=engine, factory=make_session_factory(engine))
    finally:
        engine.dispose()


# ---------------------------------------------------------------------------
# Row / pack builders (the same shapes tests/test_ledger.py and test_evidence.py use)
# ---------------------------------------------------------------------------


def grade_row(**kw: Any) -> GradeRow:
    """A clean, fully-evidenced ``GradeRow`` unless overridden."""
    base: dict[str, Any] = {
        "repo": "sqlalchemy",
        "task_id": SHA,
        "clean": True,
        "tests_unmodified": True,
        "target_green": True,
        "no_new_failures": True,
        "source_changed": True,
        "capability_class": "bug.fix",
        "size": "XS",
        "language": "python",
        "builder": "agentic",
        "model": "gpt-oss-120b",
        "provider": "cerebras",
        "evidence_pack_hash": PACK,
        "gold_clean": True,
    }
    base.update(kw)
    # a belt set implies the apparatus that recorded it (ledger invariant, review finding
    # 4): a "v4" row here stands for one written by the pre-belt-5 apparatus (2.1)
    if "apparatus_version" not in kw and base.get("belt_set") == "v4":
        base["apparatus_version"] = "2.1"
    return GradeRow(**base)


def task_spec() -> TaskSpec:
    """A minimal valid ``TaskSpec`` for rows and packs that need one."""
    return TaskSpec(
        task_id=SHA,
        repo="r",
        subject="s",
        authored="2026-01-01T00:00:00+00:00",
        test_files=("tests/test_a.py",),
        src_files=("src/a.py",),
        target_tests=("tests/test_a.py",),
        belt_scope=("tests/",),
        red_checked=True,
        gold_clean=True,
    )


def evidence_pack(**kw: Any) -> ev.EvidencePack:
    """A clean, fully-stamped ``EvidencePack`` (grade matches the belts) unless overridden."""
    base: dict[str, Any] = {
        "task": task_spec(),
        "grade": GradeResult(SHA, "r", "sighted", clean=True, belts=Belts(True, True, True, True)),
        "apparatus": ev.ApparatusStamp(runner="pytest", executor={"executor": "local"}),
        "builder": ev.BuilderRef(name="agentic", model="m", provider="p", cost_usd=0.01),
        "run_id": "run-1",
        "trial": "t1",
        "actor": "ci",
        "created": "2026-09-13T12:00:00+00:00",
    }
    base.update(kw)
    return ev.EvidencePack(**base)


__all__ = [
    "BACKENDS",
    "PACK",
    "POSTGRES_URL",
    "SHA",
    "Backend",
    "backend",
    "evidence_pack",
    "grade_row",
    "pg_schema",
    "task_spec",
]
