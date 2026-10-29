import json
from datetime import datetime
from typing import Annotated, Any, Self
from uuid import UUID

from application.orchestrators.conversation import PublicLimits
from domain.models import Binding, Conversation
from pydantic import AfterValidator, Field, model_validator

from presentation.rest.schemas.base import BaseSchema, NulFreeStr, refuse_nul

MAX_NESTING_DEPTH = 10
# Crew's DotDict compiles these keys from any dict in the run state, so a visitor must never send them.
RESERVED_KEYS = frozenset({"__properties__", "__setters__"})
# What this service offers a widget beyond the v1 conversation: each name appears with its endpoint.
CAPABILITIES = ("stop",)


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


def flow_safe_object(value: dict) -> dict:
    """Validator for a visitor-supplied JSON object that is passed into the flow's run variables.

    Refuses nesting deeper than MAX_NESTING_DEPTH, and the RESERVED_KEYS and NUL characters at any
    depth. Its size limit is deployment config, which the schemas cannot see when they are
    built: `oversized_objects` checks it.
    """
    _check_value(value, 1)
    return value


def oversized_objects(
    limits: PublicLimits, *, action: dict | None = None, chat_extra_data: dict | None = None
) -> list[dict]:
    """The `errors` entries, in the shape Litestar gives a body field, for each object over its limit.

    Measured as compact UTF-8 JSON; empty means both fit.
    """
    errors = []
    for key, value, max_bytes in (
        ("action", action, limits.action_max_bytes),
        ("chat_extra_data", chat_extra_data, limits.extra_data_max_bytes),
    ):
        if value is None:
            continue
        size = len(json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
        if size > max_bytes:
            errors.append(
                {
                    "message": f"Must be at most {max_bytes} bytes as compact JSON; got {size}.",
                    "key": key,
                }
            )
    return errors


ActionObject = Annotated[dict[str, Any], AfterValidator(flow_safe_object)]
ExtraDataObject = Annotated[dict[str, Any], AfterValidator(flow_safe_object)]
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


class DeskFeatures(BaseSchema):
    """What the widget may offer on this desk: the same keys on create and on every state read."""

    capabilities: list[str] = Field(
        description="Features beyond sending and reading messages: stop (POST .../stop)."
    )
    max_message_length: int = Field(description="The desk's limit on `content`, in characters.")
    action_max_bytes: int = Field(description="Largest `action`, as compact UTF-8 JSON.")
    extra_data_max_bytes: int = Field(
        description="Largest `chat_extra_data`, as compact UTF-8 JSON."
    )


def desk_features(binding: Binding, limits: PublicLimits) -> dict:
    """The `DeskFeatures` fields: the only builder of them."""
    return {
        "capabilities": list(CAPABILITIES),
        "max_message_length": binding.max_message_length,
        "action_max_bytes": limits.action_max_bytes,
        "extra_data_max_bytes": limits.extra_data_max_bytes,
    }


class CreateConversationOutput(DeskFeatures):
    conversation_id: UUID
    visitor_token: str
    # Operator-chosen text: the widget must render both as text, never as HTML.
    bot_display_name: str
    operator_display_name: str


class ConversationStateOutput(DeskFeatures):
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
    def from_conversation(
        cls, conversation: Conversation, binding: Binding, limits: PublicLimits
    ) -> Self:
        return cls(
            mode=conversation.mode.value,
            state=conversation.state,
            bot_display_name=binding.bot_display_name,
            operator_display_name=binding.operator_display_name,
            status=conversation.status.value,
            close_reason=conversation.close_reason.value if conversation.close_reason else None,
            closed_at=conversation.closed_at,
            **desk_features(binding, limits),
        )


class SendMessageInput(BaseSchema):
    """The JSON body of a message.

    The binding's length limit is enforced in the orchestrator (413), the byte limits of the
    objects by `oversized_objects`, and the body size by PublicController.
    """

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
    state: str = Field(
        description="processing, forwarded_to_operator, budget_exhausted, or stopped (the "
        "visitor stopped the run before or while it started: no reply comes)."
    )


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
