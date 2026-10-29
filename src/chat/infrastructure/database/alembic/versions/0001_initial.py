"""initial

Revision ID: 0001
Revises:
Create Date: 2026-10-09 21:36:04.747104

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Inbox section filters; each partial index's predicate is exactly the section's filter in
# ConversationRepository.list, so a generic (prepared) plan still matches the index. Open and
# closed are told apart by `closed_at`, a bare column, never by `status`, which a generic plan
# binds as a parameter. Waiting needs no `closed_at` test (a closed conversation never waits),
# and Test keeps its closed conversations.
OPEN = " AND closed_at IS NULL"
HUMAN = "handoff_at IS NOT NULL AND NOT is_test" + OPEN
WAITING = "visitor_waiting_since IS NOT NULL AND NOT is_test"
IN_PROGRESS = (
    "assigned_operator_id IS NOT NULL AND visitor_waiting_since IS NULL"
    " AND last_message_at IS NOT NULL AND NOT is_test" + OPEN
)
BOT = "handoff_at IS NULL AND last_message_at IS NOT NULL AND NOT is_test" + OPEN
TEST = "is_test AND last_message_at IS NOT NULL"
CLOSED = "closed_at IS NOT NULL AND last_message_at IS NOT NULL AND NOT is_test"
# The close-after timer's read: a desk's open conversations with no run in flight.
OPEN_ACTIVITY = (
    "closed_at IS NULL AND last_message_at IS NOT NULL AND NOT is_test AND run_state = 'idle'"
)


def _newest_first_index(name: str, leading: list[str], key: str, predicate: str) -> None:
    op.create_index(
        name,
        "conversation",
        [*leading, sa.text(f"{key} DESC"), sa.text("id DESC")],
        unique=False,
        postgresql_where=sa.text(predicate),
    )


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "binding",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("org_id", sa.Integer(), nullable=False),
        sa.Column("graph_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("bot_display_name", sa.String(length=64), nullable=False),
        sa.Column("operator_display_name", sa.String(length=64), nullable=False),
        sa.Column("public_key", sa.String(length=64), nullable=False),
        sa.Column("allowed_origins", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("identity_mode", sa.String(length=16), nullable=False),
        sa.Column("identity_secret", sa.String(length=128), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("history_window", sa.Integer(), nullable=False),
        sa.Column("max_message_length", sa.Integer(), nullable=False),
        sa.Column("max_turns", sa.Integer(), nullable=False),
        sa.Column("token_budget_per_conversation", sa.Integer(), nullable=False),
        sa.Column("daily_token_budget", sa.Integer(), nullable=False),
        sa.Column("messages_per_minute", sa.Integer(), nullable=False),
        sa.Column("on_budget_exhausted", sa.String(length=16), nullable=False),
        sa.Column("budget_exhausted_message", sa.Text(), nullable=False),
        sa.Column("handoff_enabled", sa.Boolean(), nullable=False),
        sa.Column("broken_reason", sa.Text(), nullable=True),
        sa.Column("contract_errors", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        # The desk's style and inactivity rules; the service always writes them, so no default.
        sa.Column("style", sa.String(length=16), nullable=False),
        sa.Column("response_time_seconds", sa.Integer(), nullable=False),
        sa.Column("on_response_timeout", sa.String(length=16), nullable=False),
        sa.Column("handback_message", sa.Text(), nullable=False),
        sa.Column("close_after_seconds", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "NOT is_active OR contract_errors = '[]'::jsonb",
            name="ck_binding_active_contract_clean",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_key"),
    )
    op.create_index(op.f("ix_binding_org_id"), "binding", ["org_id"], unique=False)
    op.create_table(
        "conversation",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("binding_id", sa.Uuid(), nullable=False),
        sa.Column("org_id", sa.Integer(), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("visitor_number", sa.Integer(), nullable=False),
        sa.Column("is_test", sa.Boolean(), nullable=False),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column("assigned_operator_id", sa.Integer(), nullable=True),
        sa.Column("run_state", sa.String(length=16), nullable=False),
        sa.Column("active_run_id", sa.Uuid(), nullable=True),
        sa.Column("active_since", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tokens_used", sa.Integer(), nullable=False),
        sa.Column("turns", sa.Integer(), nullable=False),
        sa.Column("usage_day", sa.Date(), nullable=False),
        sa.Column("tokens_today", sa.Integer(), nullable=False),
        sa.Column("turns_today", sa.Integer(), nullable=False),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_message_preview", sa.String(length=160), nullable=False),
        sa.Column("handoff_reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("late_reply_run_id", sa.Uuid(), nullable=True),
        sa.Column("handoff_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("chat_extra_data", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("is_signed", sa.Boolean(), nullable=False),
        sa.Column("visitor_waiting_since", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_message_role", sa.String(length=16), nullable=True),
        sa.Column("last_message_author_user_id", sa.Integer(), nullable=True),
        # Open or closed, apart from the mode; a closed one keeps its mode and holder.
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("close_reason", sa.String(length=16), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_by_user_id", sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "(mode = 'bot') = (handoff_at IS NULL)", name="ck_conversation_handoff_at_matches_mode"
        ),
        # Bot: nobody waits. Awaiting a human: the visitor waits, unless it was closed while
        # waiting. Human: until the operator answers.
        sa.CheckConstraint(
            "(mode <> 'bot' OR visitor_waiting_since IS NULL)"
            " AND (mode <> 'awaiting_human' OR visitor_waiting_since IS NOT NULL"
            " OR closed_at IS NOT NULL)",
            name="ck_conversation_waiting_matches_mode",
        ),
        # Exactly the conversations a person holds have a holder.
        sa.CheckConstraint(
            "(mode = 'human') = (assigned_operator_id IS NOT NULL)",
            name="ck_conversation_holder_matches_mode",
        ),
        sa.CheckConstraint(
            "(status = 'closed') = (closed_at IS NOT NULL)",
            name="ck_conversation_status_matches_closed_at",
        ),
        sa.CheckConstraint(
            "(status = 'closed') = (close_reason IS NOT NULL)",
            name="ck_conversation_close_reason_matches_status",
        ),
        sa.CheckConstraint(
            "(closed_by_user_id IS NOT NULL) = (close_reason IS NOT DISTINCT FROM 'resolved')",
            name="ck_conversation_closed_by_only_resolved",
        ),
        # Nobody waits on a closed conversation and no run holds it.
        sa.CheckConstraint(
            "closed_at IS NULL OR (visitor_waiting_since IS NULL AND run_state = 'idle'"
            " AND active_run_id IS NULL AND active_since IS NULL AND late_reply_run_id IS NULL)",
            name="ck_conversation_closed_is_settled",
        ),
        # An idle conversation names no run: a run id left on an idle row would let that run's
        # result be applied as if it still held the slot.
        sa.CheckConstraint(
            "run_state <> 'idle' OR active_run_id IS NULL",
            name="ck_conversation_idle_holds_no_run",
        ),
        sa.ForeignKeyConstraint(["binding_id"], ["binding.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        # Leads with binding_id, so it also serves every per-desk read and the desk's cascade.
        sa.UniqueConstraint(
            "binding_id", "visitor_number", name="uq_conversation_binding_visitor_number"
        ),
    )
    # A signed customer has one open conversation per desk, and any number of closed ones.
    op.create_index(
        "uq_conversation_binding_subject_open",
        "conversation",
        ["binding_id", "subject"],
        unique=True,
        postgresql_where=sa.text("closed_at IS NULL"),
    )
    # Inbox keysets, per org and per binding. Human and Waiting are queues: first handed off,
    # longest waiting first; a conversation without a message is included.
    for scope in ("org_id", "binding_id"):
        for section, key, predicate in (
            ("human", "handoff_at", HUMAN),
            ("waiting", "visitor_waiting_since", WAITING),
        ):
            op.create_index(
                f"ix_conversation_{scope}_{section}",
                "conversation",
                [scope, key, "id"],
                unique=False,
                postgresql_where=sa.text(predicate),
            )
    # In progress, Bot and Test: newest activity first, read backwards for oldest first; a
    # conversation without a message is not listed. Closed: most recently closed first, always.
    for scope in ("org_id", "binding_id"):
        for section, predicate in (("in_progress", IN_PROGRESS), ("bot", BOT), ("test", TEST)):
            _newest_first_index(
                f"ix_conversation_{scope}_{section}", [scope], "last_message_at", predicate
            )
        _newest_first_index(f"ix_conversation_{scope}_closed", [scope], "closed_at", CLOSED)
    # Mine, and the holder-name search: one operator's rows of Waiting, In progress, Test and
    # Closed in one org; org_id leads, so another org's rows are never read.
    op.create_index(
        "ix_conversation_mine_waiting",
        "conversation",
        ["org_id", "assigned_operator_id", "visitor_waiting_since", "id"],
        unique=False,
        postgresql_where=sa.text(f"assigned_operator_id IS NOT NULL AND {WAITING}"),
    )
    for section, key, predicate in (
        ("in_progress", "last_message_at", IN_PROGRESS),
        (
            "test",
            "last_message_at",
            "assigned_operator_id IS NOT NULL AND is_test AND last_message_at IS NOT NULL",
        ),
        ("closed", "closed_at", f"assigned_operator_id IS NOT NULL AND {CLOSED}"),
    ):
        _newest_first_index(
            f"ix_conversation_mine_{section}", ["org_id", "assigned_operator_id"], key, predicate
        )
    # The signed-id search: a case-insensitive prefix of a verified customer id.
    op.create_index(
        "ix_conversation_org_id_signed_subject",
        "conversation",
        ["org_id", sa.text("lower(subject) text_pattern_ops")],
        unique=False,
        postgresql_where=sa.text("is_signed"),
    )
    op.create_index(
        "ix_conversation_run_state", "conversation", ["run_state", "active_since"], unique=False
    )
    # The close-after timer: a desk's idle open conversations by last activity, read in order
    # and stopped at the batch, index only. The query writes 'idle' literally, so even a
    # generic plan matches the predicate.
    op.create_index(
        "ix_conversation_binding_id_open_activity",
        "conversation",
        ["binding_id", "last_message_at", "id"],
        unique=False,
        postgresql_where=sa.text(OPEN_ACTIVITY),
    )
    # A desk belongs to one org, so `binding_id = $1 AND org_id = $2` is no rarer than the desk
    # alone; taken as independent, a desk's list would be estimated at a few rows and read
    # through the org's index plus a sort instead of the desk's own index, in order.
    op.execute(
        "CREATE STATISTICS st_conversation_binding_id_org_id (dependencies)"
        " ON binding_id, org_id FROM conversation"
    )
    # The last visitor number per binding: not a binding column, since a visitor create holds
    # FOR SHARE on the binding row and two creates would wait on each other's lock.
    op.create_table(
        "visitor_number_counter",
        sa.Column("binding_id", sa.Uuid(), nullable=False),
        sa.Column("last_number", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["binding_id"], ["binding.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("binding_id"),
    )
    # Operators' names, per org: every read of a name stays inside the caller's org.
    op.create_table(
        "operator_profile",
        sa.Column("org_id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("user_id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("org_id", "user_id"),
    )
    op.create_table(
        "operator_alias",
        sa.Column("binding_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("alias", sa.String(length=64), nullable=False),
        # The application writes it: the full case fold of the name (domain.public_name), which a
        # database lower() is not, and which does not depend on the server's locale.
        sa.Column("alias_key", sa.String(length=192), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["binding_id"], ["binding.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("binding_id", "user_id"),
        # Unique per desk by key: visitors must be able to tell operators apart.
        sa.UniqueConstraint("binding_id", "alias_key", name="uq_operator_alias_binding_alias"),
    )
    op.create_index("ix_operator_alias_user_id", "operator_alias", ["user_id"], unique=False)
    op.create_table(
        "daily_usage",
        sa.Column("binding_id", sa.Uuid(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("tokens", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(["binding_id"], ["binding.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("binding_id", "day"),
    )
    op.create_table(
        "callback_receipt",
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=True),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("message_id", sa.Uuid(), nullable=False),
        sa.Column("secret", sa.String(length=256), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tokens_counted", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversation.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("run_id"),
        sa.UniqueConstraint("session_id"),
    )
    op.create_index(
        op.f("ix_callback_receipt_conversation_id"),
        "callback_receipt",
        ["conversation_id"],
        unique=False,
    )
    # The retention prune deletes by this expression.
    op.create_index(
        "ix_callback_receipt_settled_at",
        "callback_receipt",
        [sa.text("coalesce(received_at, created_at)")],
        unique=False,
    )
    op.create_table(
        "conversation_event",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("seq", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("stream", sa.String(length=16), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("org_id", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversation.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("seq"),
    )
    op.create_index(
        op.f("ix_conversation_event_created_at"), "conversation_event", ["created_at"], unique=False
    )
    # conversation_id leads: deleting a conversation (closed ones outlive their use) cascades to
    # its events without reading the whole table.
    op.create_index(
        "ix_event_conversation_seq",
        "conversation_event",
        ["conversation_id", "stream", "seq"],
        unique=False,
    )
    op.create_index(
        "ix_event_org_seq", "conversation_event", ["stream", "org_id", "seq"], unique=False
    )
    op.create_table(
        "message",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("actions", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("session_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("author_user_id", sa.Integer(), nullable=True),
        sa.Column("action", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        # Operator messages only: the name visitors saw on it, as sent.
        sa.Column("visible_name", sa.String(length=64), nullable=True),
        sa.CheckConstraint("action IS NULL OR role = 'user'", name="ck_message_action_user_only"),
        sa.CheckConstraint(
            "(role = 'operator') = (visible_name IS NOT NULL)",
            name="ck_message_visible_name_operator_only",
        ),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversation.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_message_conversation_id_id", "message", ["conversation_id", "id"], unique=False
    )
    op.create_table(
        "visitor_token",
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversation.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("token_hash"),
    )
    op.create_index(
        op.f("ix_visitor_token_conversation_id"), "visitor_token", ["conversation_id"], unique=False
    )
    op.create_index(
        op.f("ix_visitor_token_last_used_at"), "visitor_token", ["last_used_at"], unique=False
    )


def downgrade() -> None:
    """Downgrade schema: drop the statistics object, then every table, children first (their
    indexes go with them)."""
    op.execute("DROP STATISTICS st_conversation_binding_id_org_id")
    for table in (
        "visitor_token",
        "message",
        "conversation_event",
        "callback_receipt",
        "daily_usage",
        "operator_alias",
        "operator_profile",
        "visitor_number_counter",
        "conversation",
        "binding",
    ):
        op.drop_table(table)
