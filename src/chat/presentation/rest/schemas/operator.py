import base64
import re
from datetime import datetime
from typing import Annotated, Literal, Self
from uuid import UUID

from common.utils import INTEGER_COLUMN_MAX
from domain.errors import InvalidCursorError
from domain.models import Message
from domain.public_name import PUBLIC_NAME_MAX_LENGTH, normalize_public_name
from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
)

from presentation.rest.schemas.base import BaseSchema, NulFreeStr

BLOCKS_ALL = "Maximum {}; 0 blocks every message."
PER_DAY = " Per conversation per UTC day."
# The cap is deployment config, so the orchestrator checks it (BindingLimits), not the schema.
BUDGET = "Tokens; at most the deployment's cap ({} setting)."
DURATION = "Seconds, at least 60 and at most the deployment's cap ({} setting)."
DISPLAYED = "Shown to visitors in the chat widget."
# A minute is the smallest step the reconcile loop can be relied on to keep.
MIN_DURATION_SECONDS = 60
HANDBACK_MESSAGE_MAX_LENGTH = 4000
# Defaults are not the schema's: the orchestrator fills an omitted field from BindingLimits.
OMITTED_DEFAULT = " Omitted: the default in GET /bindings/limits."
STYLE = (
    "support: closes on Resolve, on the visitor's new chat or after `close_after_seconds` of "
    "inactivity. ongoing: never closes on its own."
)
RESPONSE_TIME = "How long a visitor may wait for a person before `on_response_timeout` applies. "
ON_RESPONSE_TIMEOUT = (
    "handback: back to the bot, posting `handback_message`. overdue: the inbox marks it. "
    "wait: nothing."
)
HANDBACK_MESSAGE = "Posted as the bot's message on a hand-back; empty posts nothing."
CLOSE_AFTER = "Support desks close a conversation silent this long; Ongoing ignores it. "

BindingName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
PUBLIC_NAME_RULES = (
    f"At most {PUBLIC_NAME_MAX_LENGTH} characters of plain text: no control, invisible "
    "formatting (emoji joiners aside) or bidirectional override characters."
)


def _public_name(value: str) -> str:
    name = normalize_public_name(value)
    if name is None:
        raise ValueError("Must not be blank.")
    return name


# A name visitors see; trimmed and in NFC.
PublicName = Annotated[str, AfterValidator(_public_name)]


class BindingInput(BaseSchema):
    name: BindingName
    graph_id: int = Field(ge=1)
    # None (omitted or null): the orchestrator fills the binding name (first 64 characters) and "Support".
    bot_display_name: PublicName | None = Field(
        default=None, description=f"{DISPLAYED} {PUBLIC_NAME_RULES} Omitted: the binding name."
    )
    operator_display_name: PublicName | None = Field(
        default=None, description=f'{DISPLAYED} {PUBLIC_NAME_RULES} Omitted: "Support".'
    )
    allowed_origins: list[str] = Field(default_factory=list, max_length=50)
    identity_mode: Literal["anonymous", "signed"] = "anonymous"
    history_window: int = Field(default=20, ge=0, le=200)
    max_message_length: int = Field(default=4000, ge=1, le=100_000)
    max_turns: int = Field(default=200, ge=0, description=BLOCKS_ALL.format("turns") + PER_DAY)
    # None only when omitted (the validator refuses an explicit null); the orchestrator fills the default.
    token_budget_per_conversation: int | None = Field(
        default=None,
        ge=1,
        le=INTEGER_COLUMN_MAX,
        description=BUDGET.format("CHAT_CONVERSATION_TOKEN_BUDGET_MAX")
        + PER_DAY
        + " Omitted: CHAT_CONVERSATION_TOKEN_BUDGET_DEFAULT.",
    )
    daily_token_budget: int | None = Field(
        default=None,
        ge=1,
        le=INTEGER_COLUMN_MAX,
        description=BUDGET.format("CHAT_DAILY_TOKEN_BUDGET_MAX")
        + " Omitted: CHAT_DAILY_TOKEN_BUDGET_DEFAULT.",
    )
    messages_per_minute: int = Field(
        default=10, ge=0, le=1000, description=BLOCKS_ALL.format("messages per minute")
    )
    on_budget_exhausted: Literal["reply", "handoff"] = "reply"
    budget_exhausted_message: str = Field(
        default="This conversation has reached its limit.", max_length=4000
    )
    handoff_enabled: bool = True
    # These five, like the budgets, are None only when omitted (the validator refuses an
    # explicit null); the orchestrator fills the default.
    style: Literal["support", "ongoing"] | None = Field(
        default=None, description=STYLE + OMITTED_DEFAULT
    )
    response_time_seconds: int | None = Field(
        default=None,
        ge=MIN_DURATION_SECONDS,
        le=INTEGER_COLUMN_MAX,
        description=RESPONSE_TIME
        + DURATION.format("CHAT_RESPONSE_TIME_MAX")
        + " Omitted: CHAT_RESPONSE_TIME_DEFAULT.",
    )
    on_response_timeout: Literal["handback", "overdue", "wait"] | None = Field(
        default=None, description=ON_RESPONSE_TIMEOUT + OMITTED_DEFAULT
    )
    handback_message: NulFreeStr | None = Field(
        default=None,
        max_length=HANDBACK_MESSAGE_MAX_LENGTH,
        description=HANDBACK_MESSAGE + OMITTED_DEFAULT,
    )
    close_after_seconds: int | None = Field(
        default=None,
        ge=MIN_DURATION_SECONDS,
        le=INTEGER_COLUMN_MAX,
        description=CLOSE_AFTER
        + DURATION.format("CHAT_CLOSE_AFTER_MAX")
        + " Omitted: CHAT_CLOSE_AFTER_DEFAULT.",
    )

    @field_validator(
        "token_budget_per_conversation",
        "daily_token_budget",
        "style",
        "response_time_seconds",
        "on_response_timeout",
        "handback_message",
        "close_after_seconds",
        mode="before",
    )
    @classmethod
    def _defaulted_not_null(cls, value):
        # Defaults are not validated, so this runs only on a value the client sent.
        if value is None:
            raise ValueError("Cannot be null; omit it for the configured default.")
        return value


class BindingPatch(BaseSchema):
    name: BindingName | None = None
    graph_id: int | None = Field(default=None, ge=1)
    bot_display_name: PublicName | None = Field(
        default=None, description=f"{DISPLAYED} {PUBLIC_NAME_RULES}"
    )
    operator_display_name: PublicName | None = Field(
        default=None, description=f"{DISPLAYED} {PUBLIC_NAME_RULES}"
    )
    allowed_origins: list[str] | None = Field(default=None, max_length=50)
    identity_mode: Literal["anonymous", "signed"] | None = None
    history_window: int | None = Field(default=None, ge=0, le=200)
    max_message_length: int | None = Field(default=None, ge=1, le=100_000)
    max_turns: int | None = Field(
        default=None, ge=0, description=BLOCKS_ALL.format("turns") + PER_DAY
    )
    token_budget_per_conversation: int | None = Field(
        default=None,
        ge=1,
        le=INTEGER_COLUMN_MAX,
        description=BUDGET.format("CHAT_CONVERSATION_TOKEN_BUDGET_MAX") + PER_DAY,
    )
    daily_token_budget: int | None = Field(
        default=None,
        ge=1,
        le=INTEGER_COLUMN_MAX,
        description=BUDGET.format("CHAT_DAILY_TOKEN_BUDGET_MAX"),
    )
    messages_per_minute: int | None = Field(
        default=None, ge=0, le=1000, description=BLOCKS_ALL.format("messages per minute")
    )
    on_budget_exhausted: Literal["reply", "handoff"] | None = None
    budget_exhausted_message: str | None = Field(default=None, max_length=4000)
    handoff_enabled: bool | None = None
    style: Literal["support", "ongoing"] | None = Field(default=None, description=STYLE)
    response_time_seconds: int | None = Field(
        default=None,
        ge=MIN_DURATION_SECONDS,
        le=INTEGER_COLUMN_MAX,
        description=RESPONSE_TIME + DURATION.format("CHAT_RESPONSE_TIME_MAX"),
    )
    on_response_timeout: Literal["handback", "overdue", "wait"] | None = Field(
        default=None, description=ON_RESPONSE_TIMEOUT
    )
    handback_message: NulFreeStr | None = Field(
        default=None, max_length=HANDBACK_MESSAGE_MAX_LENGTH, description=HANDBACK_MESSAGE
    )
    close_after_seconds: int | None = Field(
        default=None,
        ge=MIN_DURATION_SECONDS,
        le=INTEGER_COLUMN_MAX,
        description=CLOSE_AFTER + DURATION.format("CHAT_CLOSE_AFTER_MAX"),
    )


class BindingOutput(BaseSchema):
    id: UUID
    org_id: int
    graph_id: int
    name: str
    bot_display_name: str
    operator_display_name: str
    public_key: str
    allowed_origins: list[str]
    identity_mode: str
    is_active: bool
    history_window: int
    max_message_length: int
    max_turns: int
    token_budget_per_conversation: int
    daily_token_budget: int
    messages_per_minute: int
    on_budget_exhausted: str
    budget_exhausted_message: str
    handoff_enabled: bool
    broken_reason: str | None
    contract_errors: list[str]
    created_at: datetime
    updated_at: datetime
    style: str
    response_time_seconds: int
    on_response_timeout: str
    handback_message: str
    close_after_seconds: int


class BindingWithSecretOutput(BindingOutput):
    identity_secret: str | None


class ContractCheckOutput(BaseSchema):
    """What stops a flow from serving chat; empty means it can."""

    contract_errors: list[str]


class LimitCaps(BaseSchema):
    token_budget_per_conversation: int
    daily_token_budget: int
    response_time_seconds: int = Field(description="Seconds.")
    close_after_seconds: int = Field(description="Seconds.")


class LimitDefaults(LimitCaps):
    style: str
    on_response_timeout: str
    handback_message: str


class BindingLimitsOutput(BaseSchema):
    """What a binding created without them gets (`defaults`): the deployment's token budgets and
    inactivity durations, and the response action and notice; and the most a binding may set
    for each budget and duration (`caps`)."""

    defaults: LimitDefaults
    caps: LimitCaps


class SnippetOutput(BaseSchema):
    public_key: str
    chat_base_url: str
    snippet: str


class ConversationOutput(BaseSchema):
    """An inbox row: validates `conversation_summary`, the same dict `conversation.updated` carries."""

    # A key the summary adds or drops fails here, so the REST row and the stream row cannot drift.
    model_config = ConfigDict(extra="forbid")

    id: UUID
    binding_id: UUID
    visitor_number: int = Field(
        description="Per binding, from 1 in creation order, test conversations included."
    )
    chat_user_id: str | None = Field(
        description="The verified customer id on signed bindings; null otherwise."
    )
    mode: str
    state: str
    is_test: bool
    assigned_operator_id: int | None
    assigned_operator_name: str | None = Field(
        description="The holder's EpicStaff display name; null when unassigned or not known yet."
    )
    tokens_used: int = Field(description="Lifetime total.")
    turns: int = Field(description="Lifetime total.")
    tokens_today: int = Field(
        description="Counted against token_budget_per_conversation; restarts each UTC day."
    )
    turns_today: int = Field(description="Counted against max_turns; restarts each UTC day.")
    last_message_at: datetime | None
    last_message_preview: str
    last_message_role: str | None = Field(
        description="user, assistant, operator or system; null before the first message."
    )
    last_message_author_user_id: int | None = Field(
        description="The operator who wrote the last message; null unless it is an operator reply."
    )
    last_message_author_name: str | None = Field(
        description="That operator's EpicStaff display name; null when not known yet."
    )
    handoff_reason: str
    handoff_at: datetime | None = Field(
        description="When it last left bot mode; null in bot mode. The human section queues by it."
    )
    visitor_waiting_since: datetime | None = Field(
        description="Since when the visitor has waited for a person: set by a hand-off or by a "
        "visitor message after the last operator reply, cleared by an operator reply, a return "
        "to the bot or a close; a take over keeps it. Set while an open conversation is "
        "awaiting_human, null in bot mode. Overdue once the desk's response_time_seconds have "
        "passed since."
    )
    status: str = Field(description="open or closed; a closed conversation never reopens.")
    close_reason: str | None = Field(
        description="resolved (an operator), ended (the visitor) or inactive (the desk's "
        "close-after timer); null while open."
    )
    closed_at: datetime | None = Field(description="Null while open. Closed lists by it.")
    closed_by_user_id: int | None = Field(
        description="The operator who resolved it; null for any other reason."
    )
    closed_by_name: str | None = Field(
        description="That operator's EpicStaff display name; null when not known yet."
    )


class VisitorTokenOutput(BaseSchema):
    visitor_token: str


class TestConversationOutput(BaseSchema):
    visitor_token: str
    # The inbox stream announces the row before this response lands, so the caller gets it here too.
    conversation: ConversationOutput


class ConversationPageOutput(BaseSchema):
    results: list[ConversationOutput]
    next_cursor: str | None = Field(
        description="Pass back as `cursor` for the next page; null on the last page."
    )


class InboxBadgeOutput(BaseSchema):
    id: UUID
    binding_id: UUID
    assigned_operator_id: int | None


class InboxBadgesOutput(BaseSchema):
    """Every conversation the Waiting counts include, org-wide, tests excluded; a closed
    conversation never waits.

    Count per desk by `binding_id` and for Mine by `assigned_operator_id`; keep the set current
    from each `conversation.updated`. Only Waiting is counted: the demand still open, plus
    chats a visitor left unanswered (an unclaimed hand-off, a last "thanks" after an answer)
    until they are answered, released, handed back or closed. In progress holds answered
    conversations until someone releases or closes them, or a Support desk's close-after timer
    does, so it is no demand to count.
    """

    waiting: list[InboxBadgeOutput]


class _InboxCursor(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    # The section's key: `visitor_waiting_since` (waiting), `handoff_at` (human), `closed_at`
    # (closed) or `last_message_at` (in progress, bot, test).
    at: AwareDatetime
    id: UUID


_URL_SAFE_BASE64 = re.compile(r"[A-Za-z0-9_-]+")


def encode_inbox_cursor(key: tuple[datetime, UUID]) -> str:
    """Opaque `cursor` for the inbox list: unpadded url-safe base64 of the keyset as JSON."""
    at, conversation_id = key
    cursor = _InboxCursor(at=at, id=conversation_id)
    return base64.urlsafe_b64encode(cursor.model_dump_json().encode()).decode().rstrip("=")


def decode_inbox_cursor(value: str) -> tuple[datetime, UUID]:
    """Keyset from a `cursor` produced by `encode_inbox_cursor`.

    Raises:
        InvalidCursorError: Not url-safe base64, not JSON, or not exactly the two key fields.
    """
    # The decoder silently drops characters outside the alphabet; reject them instead.
    if not _URL_SAFE_BASE64.fullmatch(value):
        raise InvalidCursorError()
    # pydantic.ValidationError, binascii.Error and UnicodeDecodeError are all ValueErrors.
    try:
        cursor = _InboxCursor.model_validate_json(
            base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
        )
    except ValueError as error:
        raise InvalidCursorError() from error
    return cursor.at, cursor.id


class OperatorMessageOutput(BaseSchema):
    id: UUID
    role: str
    content: str
    actions: list | None
    action: dict | None
    session_id: int | None
    created_at: datetime
    author_user_id: int | None
    visible_name: str | None = Field(
        description="Operator messages: the name visitors saw on it (the author's alias on the "
        "desk, else the desk's operator name), as sent. Null on any other message."
    )
    author_name: str | None = Field(
        description="The authoring operator's EpicStaff display name; null when not known yet "
        "and on visitor, bot and system messages."
    )

    @classmethod
    def from_message(cls, message: Message, author_name: str | None) -> Self:
        fields = {
            name: getattr(message, name) for name in cls.model_fields if name != "author_name"
        }
        return cls.model_validate({**fields, "author_name": author_name})


class OperatorAliasOutput(BaseSchema):
    binding_id: UUID
    alias: str


class MyAliasInput(BaseSchema):
    alias: str | None = Field(
        description=f"Your name on this desk, shown to visitors on your replies. {PUBLIC_NAME_RULES} "
        "Unique on the desk ignoring case, and not the desk's bot name. Null or blank clears it."
    )

    @field_validator("alias")
    @classmethod
    def _normalized(cls, value: str | None) -> str | None:
        return normalize_public_name(value) if value is not None else None


class MyAliasOutput(BaseSchema):
    binding_id: UUID
    alias: str | None
    visible_name: str = Field(
        description="What visitors now see on your replies here: the alias, else the desk's "
        "operator name."
    )


class ClaimInput(BaseSchema):
    force: bool = False


class CloseInput(BaseSchema):
    force: bool = Field(default=False, description="Close one another operator holds.")


class ReplyInput(BaseSchema):
    content: NulFreeStr = Field(min_length=1, max_length=100_000)
