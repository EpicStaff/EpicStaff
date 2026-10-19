import json
from collections.abc import Callable
from datetime import datetime
from typing import Annotated, Any, Self
from uuid import UUID

from domain.models import Binding, Conversation
from pydantic import AfterValidator, Field, model_validator

from presentation.rest.schemas.base import BaseSchema, NulFreeStr, refuse_nul

ACTION_MAX_BYTES = 2048
EXTRA_DATA_MAX_BYTES = 8192
MAX_NESTING_DEPTH = 10
# Crew's DotDict compiles these keys from any dict in the run state, so a visitor must never send them.
RESERVED_KEYS = frozenset({"__properties__", "__setters__"})


def _check_value(value: object, depth: int) -> None:
    if isinstance(value, str):
        refuse_nul(value)
        return
    if not isinstance(value, dict | list):
        return
    # Checked before descending, so the walk itself never goes deeper than the cap.
    if depth > MAX_NESTING_DEPTH:
        raise ValueError(f"May be nested at most {MAX_NESTING_DEPTH} levels deep.")
    if isinstance(value, dict):
        reserved = RESERVED_KEYS & value.keys()
        if reserved:
            raise ValueError(f"Reserved key not allowed: {', '.join(sorted(reserved))}.")
        # Keys are strings, so walking them checks them for NUL too.
        children = [*value.keys(), *value.values()]
    else:
        children = value
    for child in children:
        _check_value(child, depth + 1)


def bounded_object(max_bytes: int) -> Callable[[dict], dict]:
    """Validator for a visitor-supplied JSON object that is passed into the flow's run variables.

    Refuses nesting deeper than MAX_NESTING_DEPTH, the RESERVED_KEYS and NUL characters at any
    depth, and a compact UTF-8 JSON encoding over `max_bytes`.
    """

    def validate(value: dict) -> dict:
        _check_value(value, 1)
        size = len(json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
        if size > max_bytes:
            raise ValueError(f"Must be at most {max_bytes} bytes as compact JSON; got {size}.")
        return value

    return validate


ActionObject = Annotated[dict[str, Any], AfterValidator(bounded_object(ACTION_MAX_BYTES))]
ExtraDataObject = Annotated[dict[str, Any], AfterValidator(bounded_object(EXTRA_DATA_MAX_BYTES))]
EXTRA_DATA_DESCRIPTION = (
    "Untrusted context for the flow (`chat_extra_data`). Replaces the stored value; "
    "omitted or null keeps it; {} clears it, so runs get null."
)


class CreateConversationInput(BaseSchema):
    public_key: str = Field(min_length=1, max_length=64)
    identity_token: str | None = None
    chat_extra_data: ExtraDataObject | None = Field(
        default=None, description=EXTRA_DATA_DESCRIPTION
    )


class CreateConversationOutput(BaseSchema):
    conversation_id: UUID
    visitor_token: str
    # Operator-chosen text: the widget must render both as text, never as HTML.
    bot_display_name: str
    operator_display_name: str


class ConversationStateOutput(BaseSchema):
    mode: str
    state: str
    # Read on every load, so a rename reaches an open widget the next time it loads.
    bot_display_name: str
    operator_display_name: str
    # Closed for good: the visitor's next message needs a new conversation. Who closed it is
    # never said: only why (resolved, ended, inactive) and when.
    status: str
    close_reason: str | None
    closed_at: datetime | None

    @classmethod
    def from_conversation(cls, conversation: Conversation, binding: Binding) -> Self:
        return cls(
            mode=conversation.mode.value,
            state=conversation.state,
            bot_display_name=binding.bot_display_name,
            operator_display_name=binding.operator_display_name,
            status=conversation.status.value,
            close_reason=conversation.close_reason.value if conversation.close_reason else None,
            closed_at=conversation.closed_at,
        )


class SendMessageInput(BaseSchema):
    # The binding's limit is enforced in the orchestrator (413); PublicController caps the body size.
    content: NulFreeStr = ""
    action: ActionObject | None = Field(
        default=None,
        description="The visitor's answer to an offered action; the flow gets it as `action`.",
    )
    chat_extra_data: ExtraDataObject | None = Field(
        default=None, description=EXTRA_DATA_DESCRIPTION
    )

    @model_validator(mode="after")
    def _content_or_action(self) -> Self:
        # Blank content that was sent stays the orchestrator's 413, as before actions existed.
        if self.action is None and "content" not in self.model_fields_set:
            raise ValueError("A message needs content or an action.")
        return self


class SendMessageOutput(BaseSchema):
    message_id: UUID
    state: str


class PublicMessageOutput(BaseSchema):
    id: UUID
    role: str
    content: str
    actions: list | None
    # Set only on user messages that answered an action.
    action: dict | None
    # Operator messages only: the name to show on it (an alias or the desk's operator name).
    visible_name: str | None
    created_at: datetime


class TicketOutput(BaseSchema):
    ticket: str
    expires_in: int
