"""the retention purge's index covers open conversations

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-17 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "conversation"
ACTIVITY = "coalesce(last_message_at, created_at)"
IDLE_INDEX = "ix_conversation_org_id_idle_activity"
CLOSED_INDEX = "ix_conversation_org_id_closed_activity"


def _rebuild(drop: str, create: str, predicate: str) -> None:
    """Build `create` concurrently, then drop `drop`, so the purge always has an index.

    CONCURRENTLY cannot run in a transaction, hence the autocommit block. Dropping `create`
    first clears an invalid index a failed build leaves behind, and one built just before a
    failed version stamp, so a rerun does not stop on "already exists".
    """
    with op.get_context().autocommit_block():
        op.drop_index(create, table_name=TABLE, postgresql_concurrently=True, if_exists=True)
        op.create_index(
            create,
            TABLE,
            ["org_id", sa.text(ACTIVITY)],
            unique=False,
            postgresql_where=sa.text(predicate),
            postgresql_concurrently=True,
        )
        op.drop_index(drop, table_name=TABLE, postgresql_concurrently=True, if_exists=True)


def upgrade() -> None:
    """Upgrade schema.

    The nightly retention purge now deletes open conversations silent past retention as well
    as closed ones: an Ongoing desk never closes a conversation, so a thread nobody uses any
    more was kept forever. It still never deletes one with a run in flight, so the index
    holds every conversation whose `run_state` is `idle`, open or closed, and replaces 0002's
    closed-only index, which nothing else reads.

    The predicate is a bare comparison the purge writes into its statement literally, so a
    generic plan still matches it, and the purge orders by the indexed expression (see 0002:
    without the order the planner, having no statistics on a partial index's expression,
    keeps the sequential scan). Its columns are all indexed already (`run_state`,
    `last_message_at`), so it makes no update less eligible for HOT; an idle row's non-HOT
    update adds one entry here, while a turn's `starting` and `running` versions add none.

    Built concurrently: the conversation table takes writes while a new container migrates
    next to the old one.
    """
    _rebuild(drop=CLOSED_INDEX, create=IDLE_INDEX, predicate="run_state = 'idle'")


def downgrade() -> None:
    """Downgrade schema."""
    _rebuild(drop=IDLE_INDEX, create=CLOSED_INDEX, predicate="closed_at IS NOT NULL")
