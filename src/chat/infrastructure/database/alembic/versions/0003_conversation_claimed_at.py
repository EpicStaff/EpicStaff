"""when the current operator took the conversation

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-10 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Rows per backfill batch; each batch commits on its own.
BATCH_SIZE = 1000
BACKFILL = sa.text(
    """
    UPDATE conversation AS c
    SET claimed_at = coalesce(
        (
            SELECT e.created_at
            FROM conversation_event AS e
            WHERE e.conversation_id = c.id
                AND e.stream = 'conversation'
                AND e.type = 'mode.changed'
                AND e.payload ->> 'mode' = 'human'
            ORDER BY e.seq DESC
            LIMIT 1
        ),
        c.handoff_at
    )
    WHERE c.id IN (
        SELECT id FROM conversation
        WHERE assigned_operator_id IS NOT NULL AND claimed_at IS NULL
        LIMIT :batch_size
    )
    """
)


def upgrade() -> None:
    """Upgrade schema.

    `claimed_at` is set exactly while `assigned_operator_id` is, so the operator inbox can place
    "joined the conversation" in the thread. `handoff_at` cannot stand in for it: a claim from
    the queue keeps the hand-off time.

    Backfill, for rows that have a holder (open or closed) and no claim time: the time of the
    conversation's latest `mode.changed` to `human` event, which only a claim emits, so it is
    the current holder's claim, or a later claim again by the same holder. The lookup walks
    `ix_event_conversation_seq` backwards and stops at that event. Where retention already
    pruned it, `handoff_at`, which every held row has and which is the claim time of a take over
    straight from the bot. Rows without a holder stay null.

    The conversation table takes writes while a new container migrates next to the old one.
    The column is added on its own, a catalog change that gives up after a short lock wait
    rather than queue every conversation write behind it. The backfill then runs outside the
    migration's transaction, in batches that each commit, so no lock outlives a batch. A rerun
    after a failure finds the column (IF NOT EXISTS) and resumes from the rows still unset; a
    row that already has a claim time is never rewritten.

    No CHECK constraint ties the pair, unlike mode and holder: during the upgrade the container
    still running the previous release claims without setting `claimed_at` and releases without
    clearing it, and a CHECK would fail those claims and releases. So rows it writes may hold
    a holder with no claim time, or a stale claim time with no holder. A migration in the next
    release, once no previous-release container writes, should repair both cases and then add
    the CHECK `(assigned_operator_id IS NULL) = (claimed_at IS NULL)` as NOT VALID followed by
    VALIDATE CONSTRAINT.
    """
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute("ALTER TABLE conversation ADD COLUMN IF NOT EXISTS claimed_at timestamptz")
    with op.get_context().autocommit_block():
        connection = op.get_bind()
        while connection.execute(BACKFILL, {"batch_size": BATCH_SIZE}).rowcount:
            pass


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("conversation", "claimed_at")
