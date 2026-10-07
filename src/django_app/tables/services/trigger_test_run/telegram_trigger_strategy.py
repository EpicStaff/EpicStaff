from collections import defaultdict

from tables.exceptions import InvalidTestRunPayloadError
from tables.models.graph_models import TelegramTriggerNode
from tables.services.trigger_spec import TriggerSpec
from tables.services.trigger_test_run.base import TriggerTestRunStrategy

_NO_FIELDS_SELECTED_MESSAGE = (
    "This Telegram trigger has no fields selected; select fields before running a test."
)

# Top-level keys of the Telegram update envelope that every real update carries but
# that are not field parents. They are accepted without inspecting their value so a
# pasted real update runs; they still reach the flow inside `telegram_payload`.
TELEGRAM_UPDATE_ENVELOPE_KEYS = frozenset({"update_id"})


class TelegramTriggerTestRunStrategy(TriggerTestRunStrategy):
    """Starts a run at a Telegram trigger node with a payload shaped like a Telegram update.

    Validation is key-level only: apart from the update envelope keys in
    `TELEGRAM_UPDATE_ENVELOPE_KEYS`, the payload may use only the parents and fields
    selected on the node. Values are never inspected, and omitted fields are
    allowed, as in a real update that does not carry every selected field.
    """

    node_type = "telegram-trigger"
    node_model = TelegramTriggerNode

    def validate_payload(self, node: TelegramTriggerNode, payload: dict) -> None:
        picked_fields_by_parent: dict[str, set[str]] = defaultdict(set)
        for field in node.fields.all():
            picked_fields_by_parent[field.parent].add(field.field_name)

        if not picked_fields_by_parent:
            raise InvalidTestRunPayloadError([_NO_FIELDS_SELECTED_MESSAGE])

        messages = []
        for parent, parent_value in payload.items():
            if parent in TELEGRAM_UPDATE_ENVELOPE_KEYS:
                continue
            if parent not in picked_fields_by_parent:
                messages.append(f"'{parent}': not a field parent selected on this node")
                continue
            if not isinstance(parent_value, dict):
                messages.append(f"'{parent}' must be an object")
                continue
            for field_name in parent_value:
                if field_name not in picked_fields_by_parent[parent]:
                    messages.append(f"'{parent}.{field_name}': field not selected on this node")

        if messages:
            raise InvalidTestRunPayloadError(messages)

    def build_variables(self, payload: dict) -> dict:
        return {"telegram_payload": payload}

    def build_trigger(self, node: TelegramTriggerNode, payload: dict) -> TriggerSpec:
        return TriggerSpec.telegram(node, payload)
