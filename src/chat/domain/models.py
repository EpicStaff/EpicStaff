from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from uuid import UUID

from domain.enums import (
    BindingStyle,
    CloseReason,
    ConversationStatus,
    IdentityMode,
    Mode,
    OnBudgetExhausted,
    OnResponseTimeout,
    Role,
    RunState,
    Stream,
)
from domain.errors import ContractFailedError, ConversationClosedError

# The last messages that leave the visitor unanswered: their own, or a system notice, which only
# ever reports a run that failed.
UNANSWERED_ROLES = frozenset({Role.USER, Role.SYSTEM})


@dataclass
class Binding:
    """A flow exposed as a chat. Limits live here so each audience has its own numbers."""

    id: UUID
    org_id: int
    graph_id: int
    name: str
    # Shown to visitors in the widget: assistant messages under the bot's, operator replies under the operator's.
    bot_display_name: str
    operator_display_name: str
    public_key: str
    allowed_origins: list[str]
    identity_mode: IdentityMode
    identity_secret: str | None
    is_active: bool
    history_window: int
    max_message_length: int
    max_turns: int
    token_budget_per_conversation: int
    daily_token_budget: int
    messages_per_minute: int
    on_budget_exhausted: OnBudgetExhausted
    budget_exhausted_message: str
    handoff_enabled: bool
    broken_reason: str | None
    contract_errors: list[str]
    created_at: datetime
    updated_at: datetime
    style: BindingStyle
    # The inactivity rules: how long a visitor may wait for a person, and what happens then.
    response_time_seconds: int
    on_response_timeout: OnResponseTimeout
    # Posted as the bot's message when a visitor is handed back; empty posts nothing.
    handback_message: str
    # How long a Support conversation may stay silent before it closes; Ongoing ignores it.
    close_after_seconds: int

    def response_due_at(self, conversation: "Conversation") -> datetime | None:
        """When the visitor's wait for a person runs past the response time.

        None when nobody waits, or the conversation is closed or a test. A visitor is overdue
        once the clock is past this, strictly: the inbox's overdue mark uses the same rule.
        """
        if not conversation.is_open or conversation.is_test:
            return None
        if conversation.visitor_waiting_since is None:
            return None
        return conversation.visitor_waiting_since + timedelta(seconds=self.response_time_seconds)

    def idle_close_at(self, conversation: "Conversation") -> datetime | None:
        """When the conversation closes for inactivity, counted from its last message.

        None on an Ongoing desk, and for a conversation that is closed, a test, silent, or
        waiting for the bot's reply (a run in flight is not inactivity). It closes once the
        clock is past this, strictly.
        """
        if self.style != BindingStyle.SUPPORT or not conversation.is_open or conversation.is_test:
            return None
        if conversation.last_message_at is None or conversation.run_state != RunState.IDLE:
            return None
        return conversation.last_message_at + timedelta(seconds=self.close_after_seconds)

    def operator_visible_name(self, alias: str | None) -> str:
        """The name visitors see on an operator's reply here: their alias on this desk, else the
        desk's operator name. Never the operator's real name."""
        return alias or self.operator_display_name

    def record_contract(self, errors: list[str], broken_reason: str | None) -> None:
        """Store the result of a fresh contract check; a failing one pauses the binding.

        A clean result clears both fields but never activates: only `resume` does. The database
        refuses an active row with contract errors; a broken reason on a live row is allowed,
        because the runtime sets it when Django loses the flow.
        """
        self.contract_errors = errors
        self.broken_reason = broken_reason
        if errors or broken_reason:
            self.is_active = False

    def resume(self) -> None:
        """Activate, on the contract errors last recorded.

        Raises:
            ContractFailedError: The flow cannot serve chat; the binding stays paused.
        """
        if self.contract_errors:
            raise ContractFailedError(self.contract_errors)
        self.is_active = True


@dataclass
class Conversation:
    """One end user's thread on a binding."""

    id: UUID
    binding_id: UUID
    org_id: int
    subject: str
    # 1, 2, ... per binding in creation order, test conversations included; operators call the
    # visitor by it. Never shown to the visitor: it would reveal how many chats the binding had.
    visitor_number: int
    is_test: bool
    mode: Mode
    assigned_operator_id: int | None
    run_state: RunState
    # The run holding the slot; its session id (once Django confirmed it) is on the receipt.
    active_run_id: UUID | None
    active_since: datetime | None
    # Lifetime totals.
    tokens_used: int
    turns: int
    # The per-conversation limits count these; they restart on the first touch of a new UTC day.
    usage_day: date
    tokens_today: int
    turns_today: int
    last_message_at: datetime | None
    last_message_preview: str
    handoff_reason: str
    created_at: datetime
    # Set only when an unconfirmed start was released: that run may still post its reply late.
    late_reply_run_id: UUID | None = None
    # When it last left bot mode; None exactly while in bot mode. The human inbox queues by it.
    handoff_at: datetime | None = None
    # Untrusted widget context sent to every run; set on create, replaced by each stored message
    # carrying one. {} is stored as None, so the run sends null.
    chat_extra_data: dict | None = None
    # True only when a verified identity token created it, so `subject` is the customer's `sub`.
    is_signed: bool = False
    # Since when the visitor has waited for a person; owned by `change_mode` and `record_message`.
    visitor_waiting_since: datetime | None = None
    last_message_role: Role | None = None
    # The operator who wrote the last message; None unless it is an operator reply.
    last_message_author_user_id: int | None = None
    # Owned by `close`; the inbox filters on `closed_at`, which is set exactly while closed.
    status: ConversationStatus = ConversationStatus.OPEN
    close_reason: CloseReason | None = None
    closed_at: datetime | None = None
    # The operator who resolved it; None for any other reason.
    closed_by_user_id: int | None = None

    @property
    def state(self) -> str:
        return "idle" if self.run_state == RunState.IDLE else "processing"

    @property
    def is_open(self) -> bool:
        return self.status == ConversationStatus.OPEN

    @property
    def chat_user_id(self) -> str | None:
        """The verified customer id the flow gets; None on anonymous and test conversations."""
        return self.subject if self.is_signed else None

    @property
    def operator_ids(self) -> set[int]:
        """The operators the inbox row names: the holder, the last message's author and who resolved it."""
        return {
            self.assigned_operator_id,
            self.last_message_author_user_id,
            self.closed_by_user_id,
        } - {None}

    def ensure_open(self) -> None:
        """Refuse to change a closed conversation; only its usage counters still move.

        Raises:
            ConversationClosedError: It is closed.
        """
        if not self.is_open:
            raise ConversationClosedError(self.close_reason.value)

    def close(self, reason: CloseReason, now: datetime, by_user_id: int | None = None) -> bool:
        """Close for good; False when it already was, whoever closed it.

        Nobody waits on a closed conversation and no run holds it: the wait ends and the run
        slot is freed, so a late reply is dropped and only counts its tokens. The mode, the
        hand-off and the holder stay as they were, a snapshot of who had it. The database
        refuses a closed row that still waits or runs.

        Args:
            by_user_id: The operator who resolved it: set exactly when `reason` is `resolved`.
        """
        if not self.is_open:
            return False
        if (reason == CloseReason.RESOLVED) != (by_user_id is not None):
            raise ValueError(
                "Only a resolved conversation names who closed it, and it always does."
            )
        self.status, self.close_reason, self.closed_at = ConversationStatus.CLOSED, reason, now
        self.closed_by_user_id = by_user_id
        self.visitor_waiting_since = None
        self.run_state, self.active_run_id, self.active_since = RunState.IDLE, None, None
        self.late_reply_run_id = None
        return True

    def return_to_bot(self, now: datetime) -> None:
        """Hand the conversation back to the bot: nobody holds it and no hand-off is pending.

        Raises:
            ConversationClosedError: It is closed.
        """
        self.change_mode(Mode.BOT, now)
        self.assigned_operator_id = None
        self.handoff_reason = ""
        # A reply of a run released before the hand-off belongs to the old exchange.
        self.late_reply_run_id = None

    def change_mode(self, mode: Mode, now: datetime) -> None:
        """Switch to `mode`, keeping `handoff_at` and `visitor_waiting_since` in step.

        Every mode change goes through here. Leaving bot mode stamps `handoff_at` with `now`,
        returning to it clears the stamp, and a move between `awaiting_human` and `human`
        keeps it, so a claimed conversation holds its place in the human queue.

        The visitor's wait follows the same moves: entering `awaiting_human` (a hand-off)
        starts it unless one is running, returning to the bot ends it, and a take over keeps it,
        because taking over is not answering. A take over straight from the bot starts the wait
        at the last message when nobody answered the visitor: the visitor wrote last (the bot's
        run was still going), or a system notice did (every system message reports a run that
        failed). After a bot or operator answer it starts none. The database refuses a row where
        any of these disagree with the mode.

        Raises:
            ConversationClosedError: It is closed.
        """
        self.ensure_open()
        if mode == Mode.BOT:
            self.handoff_at = None
            self.visitor_waiting_since = None
        elif self.mode == Mode.BOT:
            self.handoff_at = now
            if mode == Mode.HUMAN and self.last_message_role in UNANSWERED_ROLES:
                self.visitor_waiting_since = self.last_message_at
        if mode == Mode.AWAITING_HUMAN and self.visitor_waiting_since is None:
            self.visitor_waiting_since = now
        self.mode = mode

    def record_message(self, message: "Message") -> None:
        """Take a newly stored message as the conversation's last one; the caller saves the conversation.

        An operator reply ends the visitor's wait. A visitor message while a person has the
        conversation (any mode but bot) starts one if none is running, so the earliest
        unanswered message counts. Bot and system messages leave the wait as it is.

        Raises:
            ConversationClosedError: It is closed; the caller's transaction must not commit
                the message it stored.
        """
        self.ensure_open()
        self.last_message_at = message.created_at
        self.last_message_role = message.role
        self.last_message_author_user_id = message.author_user_id
        if message.role == Role.OPERATOR:
            self.visitor_waiting_since = None
        elif (
            message.role == Role.USER
            and self.mode != Mode.BOT
            and self.visitor_waiting_since is None
        ):
            self.visitor_waiting_since = message.created_at

    def usage_on(self, today: date) -> tuple[int, int]:
        """(tokens, turns) counted on `today`, without a write: zero while the stored counters are an earlier day's."""
        if self.usage_day < today:
            return 0, 0
        return self.tokens_today, self.turns_today

    def roll_usage_day(self, today: date) -> None:
        """Start today's counters if `usage_day` is an earlier day; the lifetime totals keep going."""
        if self.usage_day < today:
            self.usage_day, self.tokens_today, self.turns_today = today, 0, 0

    def count_tokens(self, tokens: int, today: date) -> None:
        self.roll_usage_day(today)
        self.tokens_used += tokens
        self.tokens_today += tokens

    def count_turn(self, today: date) -> None:
        self.roll_usage_day(today)
        self.turns += 1
        self.turns_today += 1


@dataclass(frozen=True)
class InboxBadge:
    """A conversation a Waiting or In progress count includes: its desk and its holder."""

    id: UUID
    binding_id: UUID
    assigned_operator_id: int | None


@dataclass
class VisitorToken:
    """One device's credential for a conversation; signed bindings keep one per device."""

    token_hash: str
    conversation_id: UUID
    created_at: datetime
    # Sliding idle expiry: refreshed on use (at most hourly), rejected once older than the idle TTL.
    last_used_at: datetime


@dataclass
class Message:
    id: UUID
    conversation_id: UUID
    role: Role
    content: str
    actions: list | None
    session_id: int | None
    created_at: datetime
    # The operator who wrote it; None for visitor, bot and system messages.
    author_user_id: int | None
    # The visitor's answer to an offered action; only user messages carry one.
    action: dict | None = None
    # Operator messages only: the name visitors saw on it when it was sent (the operator's alias
    # on the desk, else the desk's operator name). Kept as sent: a later rename does not rewrite it.
    visible_name: str | None = None


@dataclass
class ConversationEvent:
    """One line of the append-only log the streams push; `seq` is assigned by the database."""

    id: UUID
    stream: Stream
    conversation_id: UUID
    org_id: int
    type: str
    payload: dict
    created_at: datetime
    seq: int | None = field(default=None)


@dataclass
class CallbackReceipt:
    """One row per run, written before Django is asked to start it.

    The run id is in the callback URL, so a callback that beats the start response, or one for a
    start whose response was lost, still finds its secret. `session_id` is bound from Django's
    start response or from the first verified callback, whichever comes first.
    """

    run_id: UUID
    conversation_id: UUID
    # The user message that started the run.
    message_id: UUID
    secret: str
    created_at: datetime
    session_id: int | None = None
    received_at: datetime | None = None
    # Tokens already added to the budgets for this run; a later, larger final usage adds the difference.
    tokens_counted: int = 0
