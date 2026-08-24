from dataclasses import dataclass, field
from typing import Any

from tables.models.graph_models import (
    GraphOrganizationUser,
    ScheduleTriggerNode,
    TelegramTriggerNode,
    WebhookTriggerNode,
)
from tables.models.session_models import SessionTrigger


@dataclass(frozen=True)
class TriggerSpec:
    """Describes what started a Session, in a form that materializes 1:1 onto
    `SessionTrigger` columns via `to_fields()`.

    `trigger_type` always agrees with whichever node id is populated, because
    the only intended way to build one is through the named constructors below
    (`manual`, `schedule`, `webhook`, `telegram`, `parent_flow`). There is no
    check constraint on `SessionTrigger` enforcing this — the invariant holds
    by construction instead.
    """

    trigger_type: str
    node_name: str | None = None
    schedule_trigger_node_id: int | None = None
    webhook_trigger_node_id: int | None = None
    telegram_trigger_node_id: int | None = None
    triggered_by_session_id: int | None = None
    triggered_by_user: GraphOrganizationUser | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def manual(cls, graph_user: GraphOrganizationUser | None = None) -> "TriggerSpec":
        return cls(
            trigger_type=SessionTrigger.TriggerType.MANUAL,
            triggered_by_user=graph_user,
        )

    @classmethod
    def schedule(cls, node: ScheduleTriggerNode) -> "TriggerSpec":
        return cls(
            trigger_type=SessionTrigger.TriggerType.SCHEDULE,
            node_name=node.node_name,
            schedule_trigger_node_id=node.id,
        )

    @classmethod
    def webhook(
        cls, node: WebhookTriggerNode, path: str, config_id: str | None = None
    ) -> "TriggerSpec":
        return cls(
            trigger_type=SessionTrigger.TriggerType.WEBHOOK,
            node_name=node.node_name,
            webhook_trigger_node_id=node.id,
            extra={"path": path, "config_id": config_id},
        )

    @classmethod
    def telegram(cls, node: TelegramTriggerNode, payload: dict) -> "TriggerSpec":
        extra = {}
        chat_id = cls._extract_telegram_chat_id(payload)
        if chat_id is not None:
            extra["chat_id"] = chat_id
        return cls(
            trigger_type=SessionTrigger.TriggerType.TELEGRAM,
            node_name=node.node_name,
            telegram_trigger_node_id=node.id,
            extra=extra,
        )

    @classmethod
    def parent_flow(cls, parent_session_id: int) -> "TriggerSpec":
        return cls(
            trigger_type=SessionTrigger.TriggerType.PARENT_FLOW,
            triggered_by_session_id=parent_session_id,
        )

    @staticmethod
    def _extract_telegram_chat_id(payload: dict) -> int | None:
        """Telegram update payloads carry the chat id at `message.chat.id` or,
        for inline-keyboard callbacks, `callback_query.message.chat.id`."""
        payload = payload or {}
        message = payload.get("message")
        if message is None:
            message = (payload.get("callback_query") or {}).get("message")
        if not isinstance(message, dict):
            return None
        chat = message.get("chat")
        if not isinstance(chat, dict):
            return None
        return chat.get("id")

    @property
    def node_id(self) -> int | None:
        """Id of the node that triggered the session, whichever type applies."""
        return (
            self.schedule_trigger_node_id
            or self.webhook_trigger_node_id
            or self.telegram_trigger_node_id
        )

    def to_fields(self) -> dict:
        """Kwargs for `SessionTrigger.objects.create(session=session, **spec.to_fields())`."""
        return {
            "trigger_type": self.trigger_type,
            "node_name": self.node_name,
            "schedule_trigger_node_id": self.schedule_trigger_node_id,
            "webhook_trigger_node_id": self.webhook_trigger_node_id,
            "telegram_trigger_node_id": self.telegram_trigger_node_id,
            "triggered_by_session_id": self.triggered_by_session_id,
            "triggered_by_user": self.triggered_by_user,
            "extra": self.extra,
        }
