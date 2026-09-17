"""github_installations — the GitHub App's installations (the enterprise connection)

Navigation
----------
What it is:   Revision 0005: the ``github_installations`` table — one row per installation
              of the deployment's GitHub App (account, repository selection, permissions,
              suspended flag). Mutable state, not a ledger: no append-only triggers.
What it does: Lets the API remember which organisations installed the app and what each
              installation may see, so the Connect screen can list an installation's
              repositories and the worker can mint a token for the right installation.
              Never a token: tokens are minted per use and never persisted (ADR-0014).
How:          ``op.create_table`` guarded by an existence check (an ``init_db`` schema from
              this release already has it); ``downgrade`` drops it — allowed, because the
              table holds re-syncable state and no evidence.
Layer:        store — docs/ARCHITECTURE.md#73-data-model-store-p4
ADRs:         docs/adr/0014-github-app-is-the-connection.md
Works with:   src/crb/store/models.py (``GitHubInstallation``), src/crb/store/migrate.py
              (``REVISION_TABLES`` carries ``("0005", "github_installations")``),
              src/crb/server/routes/github.py (writes it), src/crb/server/worker.py (reads it)
Tested by:    tests/test_store_migrate.py
Touch when:   never — a released revision is immutable.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "github_installations"


def _table_exists() -> bool:
    if context.is_offline_mode():
        return False
    return TABLE in sa.inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    """Create ``github_installations`` unless ``init_db`` already did."""
    if _table_exists():
        return
    op.create_table(
        TABLE,
        sa.Column(
            "installation_id", sa.Integer(), primary_key=True, autoincrement=False, nullable=False
        ),
        sa.Column("account_login", sa.String(length=256), nullable=False),
        sa.Column("account_type", sa.String(length=32), nullable=False),
        sa.Column("repository_selection", sa.String(length=16), nullable=False),
        sa.Column("html_url", sa.Text(), nullable=False),
        sa.Column("permissions_json", sa.JSON(), nullable=False),
        sa.Column("suspended", sa.Boolean(), nullable=False),
        sa.Column("recorded_by", sa.String(length=128), nullable=False),
        sa.Column("created", sa.String(length=40), nullable=False),
        sa.Column("updated", sa.String(length=40), nullable=False),
    )


def downgrade() -> None:
    """Drop the table — re-syncable state, no evidence, so this is always allowed."""
    if _table_exists() or context.is_offline_mode():
        op.drop_table(TABLE)
