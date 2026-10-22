from datetime import date, datetime
from uuid import UUID

from application.ports import OPERATOR_NAME_MAX_LENGTH
from domain.public_name import PUBLIC_NAME_KEY_MAX_LENGTH, PUBLIC_NAME_MAX_LENGTH
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.database.config import Base


class BindingRow(Base):
    __tablename__ = "binding"
    __table_args__ = (
        # broken_reason is left out: the runtime sets it on a live binding when Django loses the flow.
        CheckConstraint(
            "NOT is_active OR contract_errors = '[]'::jsonb",
            name="ck_binding_active_contract_clean",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    org_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    graph_id: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    bot_display_name: Mapped[str] = mapped_column(String(64), nullable=False)
    operator_display_name: Mapped[str] = mapped_column(String(64), nullable=False)
    public_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    allowed_origins: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    identity_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    identity_secret: Mapped[str | None] = mapped_column(String(128))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    history_window: Mapped[int] = mapped_column(Integer, nullable=False)
    max_message_length: Mapped[int] = mapped_column(Integer, nullable=False)
    max_turns: Mapped[int] = mapped_column(Integer, nullable=False)
    token_budget_per_conversation: Mapped[int] = mapped_column(Integer, nullable=False)
    daily_token_budget: Mapped[int] = mapped_column(Integer, nullable=False)
    messages_per_minute: Mapped[int] = mapped_column(Integer, nullable=False)
    on_budget_exhausted: Mapped[str] = mapped_column(String(16), nullable=False)
    budget_exhausted_message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    handoff_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    broken_reason: Mapped[str | None] = mapped_column(Text)
    contract_errors: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    style: Mapped[str] = mapped_column(String(16), nullable=False)
    response_time_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    on_response_timeout: Mapped[str] = mapped_column(String(16), nullable=False)
    handback_message: Mapped[str] = mapped_column(Text, nullable=False)
    close_after_seconds: Mapped[int] = mapped_column(Integer, nullable=False)


# Every section filter, and so every partial index predicate, tests `closed_at`, never
# `status`: a generic plan binds `status = $1` as a parameter, which proves no index predicate.
WAITING_PREDICATE = "visitor_waiting_since IS NOT NULL AND NOT is_test"
IN_PROGRESS_PREDICATE = (
    "assigned_operator_id IS NOT NULL AND visitor_waiting_since IS NULL"
    " AND last_message_at IS NOT NULL AND NOT is_test AND closed_at IS NULL"
)
CLOSED_PREDICATE = "closed_at IS NOT NULL AND last_message_at IS NOT NULL AND NOT is_test"


class ConversationRow(Base):
    __tablename__ = "conversation"
    __table_args__ = (
        UniqueConstraint(
            "binding_id", "visitor_number", name="uq_conversation_binding_visitor_number"
        ),
        # A signed customer has one open conversation per desk, and any number of closed ones.
        Index(
            "uq_conversation_binding_subject_open",
            "binding_id",
            "subject",
            unique=True,
            postgresql_where=text("closed_at IS NULL"),
        ),
        CheckConstraint(
            "(mode = 'bot') = (handoff_at IS NULL)", name="ck_conversation_handoff_at_matches_mode"
        ),
        # Bot: nobody waits. Awaiting a human: the visitor waits, unless it was closed while
        # waiting. Human: until the operator answers.
        CheckConstraint(
            "(mode <> 'bot' OR visitor_waiting_since IS NULL)"
            " AND (mode <> 'awaiting_human' OR visitor_waiting_since IS NOT NULL"
            " OR closed_at IS NOT NULL)",
            name="ck_conversation_waiting_matches_mode",
        ),
        # Exactly the conversations a person holds have a holder; a closed one keeps its last.
        CheckConstraint(
            "(mode = 'human') = (assigned_operator_id IS NOT NULL)",
            name="ck_conversation_holder_matches_mode",
        ),
        CheckConstraint(
            "(status = 'closed') = (closed_at IS NOT NULL)",
            name="ck_conversation_status_matches_closed_at",
        ),
        CheckConstraint(
            "(status = 'closed') = (close_reason IS NOT NULL)",
            name="ck_conversation_close_reason_matches_status",
        ),
        CheckConstraint(
            "(closed_by_user_id IS NOT NULL) = (close_reason IS NOT DISTINCT FROM 'resolved')",
            name="ck_conversation_closed_by_only_resolved",
        ),
        # Nobody waits on a closed conversation and no run holds it.
        CheckConstraint(
            "closed_at IS NULL OR (visitor_waiting_since IS NULL AND run_state = 'idle'"
            " AND active_run_id IS NULL AND active_since IS NULL AND late_reply_run_id IS NULL)",
            name="ck_conversation_closed_is_settled",
        ),
        # An idle conversation names no run: a run id left on an idle row would let that run's
        # result be applied as if it still held the slot.
        CheckConstraint(
            "run_state <> 'idle' OR active_run_id IS NULL",
            name="ck_conversation_idle_holds_no_run",
        ),
        # The operator inbox, one keyset per section; each predicate is exactly the section's
        # filter in ConversationRepository.list, per org and per binding (the binding filter).
        # Human and Waiting: queues, first handed off / longest waiting first, tests excluded.
        # A closed conversation never waits, so Waiting needs no `closed_at` test.
        *(
            Index(
                f"ix_conversation_{scope}_{section}",
                scope,
                key,
                "id",
                postgresql_where=text(predicate),
            )
            for scope in ("org_id", "binding_id")
            for section, key, predicate in (
                (
                    "human",
                    "handoff_at",
                    "handoff_at IS NOT NULL AND NOT is_test AND closed_at IS NULL",
                ),
                ("waiting", "visitor_waiting_since", WAITING_PREDICATE),
            )
        ),
        # In progress, Bot and Test: newest activity first, read backwards for oldest first; a
        # conversation with no message yet is not listed. Test keeps its closed conversations.
        *(
            Index(
                f"ix_conversation_{scope}_{section}",
                scope,
                text("last_message_at DESC"),
                text("id DESC"),
                postgresql_where=text(predicate),
            )
            for scope in ("org_id", "binding_id")
            for section, predicate in (
                ("in_progress", IN_PROGRESS_PREDICATE),
                (
                    "bot",
                    (
                        "handoff_at IS NULL AND last_message_at IS NOT NULL AND NOT is_test"
                        " AND closed_at IS NULL"
                    ),
                ),
                ("test", "is_test AND last_message_at IS NOT NULL"),
            )
        ),
        # Closed: most recently closed first, always.
        *(
            Index(
                f"ix_conversation_{scope}_closed",
                scope,
                text("closed_at DESC"),
                text("id DESC"),
                postgresql_where=text(CLOSED_PREDICATE),
            )
            for scope in ("org_id", "binding_id")
        ),
        # Mine, and the holder-name search: one operator's rows of Waiting, In progress, Test and
        # Closed in one org, on every desk. org_id leads, so nothing reads the operator's rows in
        # another org (a multi-org operator's volume there must not show in this org's timings).
        Index(
            "ix_conversation_mine_waiting",
            "org_id",
            "assigned_operator_id",
            "visitor_waiting_since",
            "id",
            postgresql_where=text(f"assigned_operator_id IS NOT NULL AND {WAITING_PREDICATE}"),
        ),
        Index(
            "ix_conversation_mine_in_progress",
            "org_id",
            "assigned_operator_id",
            text("last_message_at DESC"),
            text("id DESC"),
            postgresql_where=text(IN_PROGRESS_PREDICATE),
        ),
        Index(
            "ix_conversation_mine_test",
            "org_id",
            "assigned_operator_id",
            text("last_message_at DESC"),
            text("id DESC"),
            postgresql_where=text(
                "assigned_operator_id IS NOT NULL AND is_test AND last_message_at IS NOT NULL"
            ),
        ),
        Index(
            "ix_conversation_mine_closed",
            "org_id",
            "assigned_operator_id",
            text("closed_at DESC"),
            text("id DESC"),
            postgresql_where=text(f"assigned_operator_id IS NOT NULL AND {CLOSED_PREDICATE}"),
        ),
        # The close-after timer: a desk's open conversations with no run in flight, by last
        # activity. Read in order and stopped at the batch, index only: the query renders 'idle'
        # literally, so even a generic plan matches the predicate.
        Index(
            "ix_conversation_binding_id_open_activity",
            "binding_id",
            "last_message_at",
            "id",
            postgresql_where=text(
                "closed_at IS NULL AND last_message_at IS NOT NULL AND NOT is_test"
                " AND run_state = 'idle'"
            ),
        ),
        Index("ix_conversation_run_state", "run_state", "active_since"),
        # Not expressible here, so only migration 0001 creates it (alembic does not compare
        # statistics): st_conversation_binding_id_org_id, functional dependencies between
        # binding_id and org_id, so a desk's section list is not estimated at a handful of rows.
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    # Indexed by uq_conversation_binding_visitor_number, which leads with it: a plain index on it
    # would be one more write per insert for nothing.
    binding_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("binding.id", ondelete="CASCADE"), nullable=False
    )
    org_id: Mapped[int] = mapped_column(Integer, nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    visitor_number: Mapped[int] = mapped_column(Integer, nullable=False)
    is_test: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    assigned_operator_id: Mapped[int | None] = mapped_column(Integer)
    run_state: Mapped[str] = mapped_column(String(16), nullable=False)
    active_run_id: Mapped[UUID | None] = mapped_column(Uuid)
    active_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    tokens_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    turns: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    usage_day: Mapped[date] = mapped_column(Date, nullable=False)
    tokens_today: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    turns_today: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_message_preview: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    handoff_reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    late_reply_run_id: Mapped[UUID | None] = mapped_column(Uuid)
    handoff_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # SQL NULL for None, not JSON null, so "IS NULL" means "never set".
    chat_extra_data: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))
    is_signed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    visitor_waiting_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_message_role: Mapped[str | None] = mapped_column(String(16))
    last_message_author_user_id: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    close_reason: Mapped[str | None] = mapped_column(String(16))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_by_user_id: Mapped[int | None] = mapped_column(Integer)


# The signed-id search: a case-insensitive prefix (LIKE 'q%') of a verified customer id. Declared
# here, not in __table_args__, to name the expression's operator class in `postgresql_ops`.
Index(
    "ix_conversation_org_id_signed_subject",
    ConversationRow.org_id,
    func.lower(ConversationRow.subject).label("subject_lower"),
    postgresql_ops={"subject_lower": "text_pattern_ops"},
    postgresql_where=ConversationRow.is_signed,
)


class VisitorNumberCounterRow(Base):
    """The last visitor number handed out per binding.

    Not a column on `binding`: a visitor create holds FOR SHARE on the binding row, so two
    creates incrementing a binding column would each wait for the other's share lock.
    """

    __tablename__ = "visitor_number_counter"

    binding_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("binding.id", ondelete="CASCADE"), primary_key=True
    )
    last_number: Mapped[int] = mapped_column(Integer, nullable=False)


class OperatorProfileRow(Base):
    """An operator's display name as an org knows it: what introspection last reported when they
    took over or replied in that org's inbox.

    Per org, although EpicStaff users are global: a name is personal data, and every read
    (row names, the holder-name search) stays inside the caller's org, so no query reads, or
    takes longer because of, another org's operators.
    """

    __tablename__ = "operator_profile"

    org_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    user_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    display_name: Mapped[str] = mapped_column(String(OPERATOR_NAME_MAX_LENGTH), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class OperatorAliasRow(Base):
    """The name one operator shows visitors on one desk, in place of the desk's operator name.

    Unique per desk by `alias_key` (domain.public_name.public_name_key, written with the alias),
    so visitors can tell operators apart; judged by the constraint alone, so two operators
    claiming one name at once cannot both get it.
    """

    __tablename__ = "operator_alias"
    __table_args__ = (
        UniqueConstraint("binding_id", "alias_key", name="uq_operator_alias_binding_alias"),
        # "My aliases": one operator's names on every desk.
        Index("ix_operator_alias_user_id", "user_id"),
    )

    binding_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("binding.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    alias: Mapped[str] = mapped_column(String(PUBLIC_NAME_MAX_LENGTH), nullable=False)
    alias_key: Mapped[str] = mapped_column(String(PUBLIC_NAME_KEY_MAX_LENGTH), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class VisitorTokenRow(Base):
    __tablename__ = "visitor_token"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    conversation_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("conversation.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_used_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )


class MessageRow(Base):
    __tablename__ = "message"
    __table_args__ = (
        Index("ix_message_conversation_id_id", "conversation_id", "id"),
        CheckConstraint("action IS NULL OR role = 'user'", name="ck_message_action_user_only"),
        CheckConstraint(
            "(role = 'operator') = (visible_name IS NOT NULL)",
            name="ck_message_visible_name_operator_only",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    conversation_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("conversation.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    actions: Mapped[list | None] = mapped_column(JSONB)
    session_id: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    author_user_id: Mapped[int | None] = mapped_column(Integer)
    # SQL NULL for None: ck_message_action_user_only tests IS NULL.
    action: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))
    visible_name: Mapped[str | None] = mapped_column(String(PUBLIC_NAME_MAX_LENGTH))


class ConversationEventRow(Base):
    __tablename__ = "conversation_event"
    __table_args__ = (
        # conversation_id leads: a conversation's delete cascades here, and must not read the table.
        Index("ix_event_conversation_seq", "conversation_id", "stream", "seq"),
        Index("ix_event_org_seq", "stream", "org_id", "seq"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    # The stream cursor: a UUIDv7 alone is not strictly ordered inside one millisecond.
    seq: Mapped[int] = mapped_column(BigInteger, Identity(always=True), nullable=False, unique=True)
    stream: Mapped[str] = mapped_column(String(16), nullable=False)
    conversation_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("conversation.id", ondelete="CASCADE"), nullable=False
    )
    org_id: Mapped[int] = mapped_column(Integer, nullable=False)
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )


class DailyUsageRow(Base):
    __tablename__ = "daily_usage"

    binding_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("binding.id", ondelete="CASCADE"), primary_key=True
    )
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)


class CallbackReceiptRow(Base):
    __tablename__ = "callback_receipt"
    # The retention prune's predicate.
    __table_args__ = (
        Index("ix_callback_receipt_settled_at", text("coalesce(received_at, created_at)")),
    )

    run_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    session_id: Mapped[int | None] = mapped_column(Integer, unique=True)
    conversation_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("conversation.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # No foreign key: a message delete would then scan this table, and messages only go with their conversation.
    message_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    secret: Mapped[str] = mapped_column(String(256), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    tokens_counted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
