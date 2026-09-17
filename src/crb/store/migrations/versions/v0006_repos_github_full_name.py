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
How:          ``op.add_column`` + a unique index, guarded by an existence check (an
              ``init_db`` schema from this release already has both); the backfill reads the
              JSON in Python (dialect-neutral). ``downgrade`` drops the index and column —
              allowed: the link survives in ``config_json``.
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


def _column_exists() -> bool:
    if context.is_offline_mode():
        return False
    insp = sa.inspect(op.get_bind())
    return COLUMN in {c["name"] for c in insp.get_columns(TABLE)}


def upgrade() -> None:
    """Add the column and its unique index unless ``init_db`` already did; backfill."""
    if not _column_exists():
        op.add_column(TABLE, sa.Column(COLUMN, sa.String(length=256), nullable=True))
        op.create_index(INDEX, TABLE, [COLUMN], unique=True)
    if context.is_offline_mode():
        return
    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT name, config_json FROM repos")).all()
    for name, raw in rows:
        cfg = raw if isinstance(raw, dict) else (json.loads(raw) if raw else {})
        link = (cfg or {}).get("github") or {}
        full = str(link.get("full_name", "")).strip().lower()
        if full:
            bind.execute(
                sa.text("UPDATE repos SET github_full_name = :full WHERE name = :name"),
                {"full": full, "name": name},
            )


def downgrade() -> None:
    """Drop the index and the column — the link survives in ``config_json``."""
    if context.is_offline_mode() or _column_exists():
        with op.batch_alter_table(TABLE) as batch:
            batch.drop_index(INDEX)
            batch.drop_column(COLUMN)
