import json
from collections.abc import Mapping
from datetime import datetime

from common.utils import new_id, utc_today, utcnow
from domain.enums import Role, Stream
from domain.models import Conversation, ConversationEvent, Message
from loguru import logger

from application.ports import AbstractFanout, AbstractUnitOfWork

PREVIEW_LENGTH = 160


def message_payload(message: Message) -> dict:
    """A message as both streams carry it; the visitor's sees exactly this.

    `visible_name` is the only name in it: an operator's alias or the desk's operator name,
    never who the operator is.
    """
    return {
        "id": str(message.id),
        "role": message.role.value,
        "content": message.content,
        "actions": message.actions,
        "action": message.action,
        "visible_name": message.visible_name,
        "created_at": message.created_at.isoformat(),
    }


def _isoformat(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def conversation_summary(conversation: Conversation, names: Mapping[int, str]) -> dict:
    """The operator-facing inbox row; the only builder of it.

    `conversation.updated`, the operator list and single read, and the take over, release,
    close and test-conversation responses all carry exactly these keys. Operators only: it names
    operators, so it never goes on the visitor's conversation stream.

    Args:
        names: Display names by user id, covering `conversation.operator_ids`; a missing id
            leaves its name null.
    """
    tokens_today, turns_today = conversation.usage_on(utc_today())
    return {
        "id": str(conversation.id),
        "binding_id": str(conversation.binding_id),
        "visitor_number": conversation.visitor_number,
        "chat_user_id": conversation.chat_user_id,
        "mode": conversation.mode.value,
        "state": conversation.state,
        "is_test": conversation.is_test,
        "assigned_operator_id": conversation.assigned_operator_id,
        "assigned_operator_name": names.get(conversation.assigned_operator_id),
        "tokens_used": conversation.tokens_used,
        "turns": conversation.turns,
        "tokens_today": tokens_today,
        "turns_today": turns_today,
        "last_message_at": _isoformat(conversation.last_message_at),
        "last_message_preview": conversation.last_message_preview,
        "last_message_role": conversation.last_message_role.value
        if conversation.last_message_role
        else None,
        "last_message_author_user_id": conversation.last_message_author_user_id,
        "last_message_author_name": names.get(conversation.last_message_author_user_id),
        "handoff_reason": conversation.handoff_reason,
        "handoff_at": _isoformat(conversation.handoff_at),
        "visitor_waiting_since": _isoformat(conversation.visitor_waiting_since),
        "status": conversation.status.value,
        "close_reason": conversation.close_reason.value if conversation.close_reason else None,
        "closed_at": _isoformat(conversation.closed_at),
        "closed_by_user_id": conversation.closed_by_user_id,
        "closed_by_name": names.get(conversation.closed_by_user_id),
    }


class Emitter:
    """Writes event rows in the open transaction; `flush()` after commit wakes the streams."""

    def __init__(self, uow: AbstractUnitOfWork, fanout: AbstractFanout):
        self._uow = uow
        self._fanout = fanout
        self._pending: list[tuple[str, dict]] = []

    async def conversation(self, conversation: Conversation, type: str, payload: dict) -> None:
        await self._add(
            Stream.CONVERSATION, conversation, type, payload, f"chat:conversation:{conversation.id}"
        )

    async def inbox(self, conversation: Conversation, type: str, payload: dict) -> None:
        await self._add(
            Stream.INBOX, conversation, type, payload, f"chat:org:{conversation.org_id}"
        )

    async def conversation_updated(self, conversation: Conversation) -> dict:
        """Emit the conversation's inbox row, naming its operators (one lookup); returns the row."""
        names = await self._uow.operator_profiles.names(
            conversation.org_id, conversation.operator_ids
        )
        row = conversation_summary(conversation, names)
        await self.inbox(conversation, "conversation.updated", row)
        return row

    async def conversation_closed(self, conversation: Conversation) -> None:
        """Announce a close on both streams: why and when, and on the inbox also who resolved it."""
        closed = {
            "close_reason": conversation.close_reason.value,
            "closed_at": _isoformat(conversation.closed_at),
        }
        await self.conversation(conversation, "conversation.closed", closed)
        await self.inbox(
            conversation,
            "conversation.closed",
            {
                "conversation_id": str(conversation.id),
                **closed,
                "closed_by_user_id": conversation.closed_by_user_id,
            },
        )

    async def _add(
        self, stream: Stream, conversation: Conversation, type: str, payload: dict, channel: str
    ) -> None:
        event = ConversationEvent(
            id=new_id(),
            stream=stream,
            conversation_id=conversation.id,
            org_id=conversation.org_id,
            type=type,
            payload=payload,
            created_at=utcnow(),
        )
        seq = await self._uow.events.add(event)
        self._pending.append((channel, {"seq": seq, "type": type, "payload": payload}))

    async def flush(self) -> None:
        pending, self._pending = self._pending, []
        for channel, event in pending:
            # Best effort: the rows are committed and streams replay by seq, so a publish is only a wake-up.
            try:
                await self._fanout.publish(channel, event)
            except Exception as error:
                logger.warning("Fan-out publish failed on {}: {}", channel, error)


async def store_message(
    uow: AbstractUnitOfWork,
    emitter: Emitter,
    conversation: Conversation,
    role: Role,
    content: str,
    *,
    actions: list | None = None,
    action: dict | None = None,
    session_id: int | None = None,
    author_user_id: int | None = None,
    author_name: str | None = None,
    visible_name: str | None = None,
) -> Message:
    """Insert a message, record it on the conversation (caller saves it) and emit it on both streams.

    The visitor's stream gets the message alone; the inbox stream adds the operator who wrote
    it, `author_user_id` and `author_name`, which the visitor never sees.

    Args:
        visible_name: Operator messages only (the database refuses it on any other): the name
            visitors see on it.

    Raises:
        ConversationClosedError: It is closed; nothing was inserted.
    """
    # Before the insert, so no caller can commit a message into a closed conversation.
    conversation.ensure_open()
    message = Message(
        id=new_id(),
        conversation_id=conversation.id,
        role=role,
        content=content,
        actions=actions,
        session_id=session_id,
        created_at=utcnow(),
        author_user_id=author_user_id,
        action=action,
        visible_name=visible_name,
    )
    await uow.messages.add(message)
    conversation.record_message(message)
    # An action-only reply has no text, so the inbox shows the action itself.
    preview = (
        content
        if content or action is None
        else json.dumps(action, separators=(",", ":"), ensure_ascii=False)
    )
    conversation.last_message_preview = preview[:PREVIEW_LENGTH]
    payload = message_payload(message)
    await emitter.conversation(conversation, "message.created", payload)
    await emitter.inbox(
        conversation,
        "message.created",
        {
            "conversation_id": str(conversation.id),
            **payload,
            "author_user_id": author_user_id,
            "author_name": author_name,
        },
    )
    return message
