"""repos.github_full_name — the GitHub identity a connected repository is linked to, constrained

Navigation
----------
What it is:   Revision 0006: a nullable, UNIQUE ``repos.github_full_name`` column — the
              lower-cased ``owner/name`` of the GitHub repository a row was connected from
              (NULL for a repository connected by URL). Backfilled from the JSON link
              (``config_json.github.full_name``) on upgrade.
What it does: Makes "one GitHub repository connects once" a database fact. Before this the
              check was a Python scan of committed JSON, so two concurrent connects of the
              same repository could both pass it (PostgreSQL) and leave two rows minting
              tokens for one repository. Now the second commit fails and the route says 409.
How:          a duplicate preflight over the JSON links (refused with the names, as 0004
              refuses duplicate events); ``op.add_column`` guarded by an existence check (an
              ``init_db`` schema from this release already has it); the backfill reads the
              JSON in Python (dialect-neutral); the unique index is created LAST, and only
              if absent. Offline (``--sql``) emits the complete revision instead — column,
              a per-dialect SQL backfill, index — so a review script is never a partial
              0006 (a duplicate then fails at apply time, by the database). ``downgrade``
              drops the index and column — allowed: the link survives in ``config_json``.
Layer:        store — docs/ARCHITECTURE.md#73-data-model-store-p4
ADRs:         docs/adr/0014-github-app-is-the-connection.md
Works with:   src/crb/store/models.py (``Repo.github_full_name``), src/crb/store/migrate.py
              (``REVISION_MARKERS`` carries ``("0006", "repos", "github_full_name")``),
              src/crb/server/routes/github.py (writes it on connect; the 409 on the race),
              src/crb/server/routes/repos.py (clears it with the link when the URL changes)
Tested by:    tests/test_store_migrate.py, tests/test_server_github_app.py
Touch when:   never — a released revision is immutable.
"""

from __future__ import annotations

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "repos"
COLUMN = "github_full_name"
INDEX = "uq_repos_github_full_name"


def _dialect() -> str:
    name = str(op.get_context().dialect.name)
    if name not in _OFFLINE_BACKFILL:
        raise RuntimeError(f"revision 0006 has no offline backfill for dialect {name!r}")
    return name


#: The backfill as SQL per dialect, for ``--sql`` review scripts (the online path does it in
#: Python from the parsed JSON, which is what the tests exercise on both dialects).
_OFFLINE_BACKFILL: dict[str, str] = {
    "sqlite": (
        "UPDATE repos SET github_full_name = lower(trim(json_extract(config_json, "
        "'$.github.full_name'))) WHERE json_extract(config_json, '$.github.full_name') "
        "IS NOT NULL AND trim(json_extract(config_json, '$.github.full_name')) <> ''"
    ),
    "postgresql": (
        "UPDATE repos SET github_full_name = lower(trim(config_json->'github'->>'full_name')) "
        "WHERE config_json->'github'->>'full_name' IS NOT NULL "
        "AND trim(config_json->'github'->>'full_name') <> ''"
    ),
}


def _column_exists() -> bool:
    insp = sa.inspect(op.get_bind())
    return COLUMN in {c["name"] for c in insp.get_columns(TABLE)}


def _linked_names(bind: sa.engine.Connection) -> dict[str, list[str]]:
    """``owner/name`` (lower-cased) → the repository names whose JSON link carries it."""
    out: dict[str, list[str]] = {}
    for name, raw in bind.execute(sa.text("SELECT name, config_json FROM repos")).all():
        cfg = raw if isinstance(raw, dict) else (json.loads(raw) if raw else {})
        link = (cfg or {}).get("github") or {}
        full = str(link.get("full_name", "")).strip().lower()
        if full:
            out.setdefault(full, []).append(str(name))
    return out


def upgrade() -> None:
    """Preflight the legacy JSON links for duplicates (refuse, naming them, as 0004 does for
    duplicate events — an operator decides which row keeps the link); then add the column,
    backfill it, and only then create the unique index, so the index is never asked to
    judge a row the backfill has not reached."""
    if context.is_offline_mode():
        # offline (``--sql``) emits the COMPLETE revision for the target dialect: the column,
        # a SQL backfill from the JSON link, and the unique index last — so a reviewer applies
        # all of 0006 or none. The Python preflight cannot read rows here; a duplicate legacy
        # link makes the CREATE UNIQUE INDEX fail at apply time, which is the database
        # refusing on the operator's behalf, never a partial revision.
        op.add_column(TABLE, sa.Column(COLUMN, sa.String(length=256), nullable=True))
        op.execute(_OFFLINE_BACKFILL[_dialect()])
        op.create_index(INDEX, TABLE, [COLUMN], unique=True)
        return
    bind = op.get_bind()
    linked = _linked_names(bind)
    dupes = {full: names for full, names in linked.items() if len(names) > 1}
    if dupes:
        listing = "; ".join(f"{full} ← {', '.join(sorted(n))}" for full, n in sorted(dupes.items()))
        raise RuntimeError(
            "refusing to upgrade 0006: the same GitHub repository is linked from more than "
            f"one row ({listing}) — unlink all but one (PUT /repos/{{name}} with a new url "
            "drops the link, or edit config_json.github) and re-run the migration"
        )
    if not _column_exists():
        op.add_column(TABLE, sa.Column(COLUMN, sa.String(length=256), nullable=True))
    for full, names in linked.items():
        bind.execute(
            sa.text("UPDATE repos SET github_full_name = :full WHERE name = :name"),
            {"full": full, "name": names[0]},
        )
    insp = sa.inspect(bind)
    if INDEX not in {ix["name"] for ix in insp.get_indexes(TABLE)}:
        op.create_index(INDEX, TABLE, [COLUMN], unique=True)


def downgrade() -> None:
    """Drop the index and the column — the link survives in ``config_json``."""
    if context.is_offline_mode() or _column_exists():
        with op.batch_alter_table(TABLE) as batch:
            batch.drop_index(INDEX)
            batch.drop_column(COLUMN)
