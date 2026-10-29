"""the retention purge's index

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-20 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEX = "ix_conversation_org_id_closed_activity"


def upgrade() -> None:
    """Upgrade schema.

    The nightly retention purge reads one org's closed conversations whose last activity is
    older than the cutoff. Without this index each org's last, short batch reads the whole
    table. The purge orders by the indexed expression: a partial index's expression has no
    statistics the planner reads, so without that order it estimates a third of the org as due
    and still picks the sequential scan, stopped at the limit. The predicate is exactly the
    purge's `closed_at IS NOT NULL`, a bare column, so a generic plan still matches it. Only
    closed rows are indexed, and a closed conversation never reopens, so the index costs one
    entry when a conversation closes and nothing when an open one gets a message.

    Built concurrently: the conversation table takes writes while a new container migrates
    next to the old one. CONCURRENTLY cannot run in a transaction. The drop first clears an
    invalid index a failed build leaves behind, and an index built just before the version
    stamp failed, so a rerun does not stop on "already exists".
    """
    with op.get_context().autocommit_block():
        op.drop_index(
            INDEX, table_name="conversation", postgresql_concurrently=True, if_exists=True
        )
        op.create_index(
            INDEX,
            "conversation",
            ["org_id", sa.text("coalesce(last_message_at, created_at)")],
            unique=False,
            postgresql_where=sa.text("closed_at IS NOT NULL"),
            postgresql_concurrently=True,
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.get_context().autocommit_block():
        op.drop_index(
            INDEX, table_name="conversation", postgresql_concurrently=True, if_exists=True
        )
