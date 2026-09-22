from app.filtering.ast import FieldSpec
from app.filtering.constants import (
    RANGE_OPS,
    SELECT_OPS,
    TEXT_CONDITION_OPS,
    DURATION_OPS,
    FLATTENED_OPS,
)

FLAT_OBJECT_ROOTS = frozenset({"input", "output", "details"})
STATUS_VALUES = frozenset({"completed", "failed"})
KNOWN_FIELDS: dict[str, FieldSpec] = {
    # main fields
    "id": FieldSpec(RANGE_OPS | SELECT_OPS),
    "session_id": FieldSpec(SELECT_OPS | RANGE_OPS),
    "session_message_id": FieldSpec(SELECT_OPS),
    "status": FieldSpec(SELECT_OPS, allowed_values=STATUS_VALUES),
    "kind": FieldSpec(SELECT_OPS),
    "name": FieldSpec(TEXT_CONDITION_OPS),
    "flow_name": FieldSpec(SELECT_OPS | TEXT_CONDITION_OPS),
    "node_type": FieldSpec(SELECT_OPS),
    "run_type": FieldSpec(SELECT_OPS),
    "event_time": FieldSpec(RANGE_OPS),
    "error": FieldSpec(TEXT_CONDITION_OPS),
    # additional fields
    "agent": FieldSpec(SELECT_OPS),
    "tool": FieldSpec(SELECT_OPS),
    "task": FieldSpec(TEXT_CONDITION_OPS),
    "prompt": FieldSpec(TEXT_CONDITION_OPS),
    "message_text": FieldSpec(TEXT_CONDITION_OPS),
    "message_thought": FieldSpec(TEXT_CONDITION_OPS),
    "duration": FieldSpec(DURATION_OPS, computed=True),
    # special fields
    "__text__": FieldSpec(frozenset({"contains"})),
}
FLATTENED_PATH_SPEC = FieldSpec(FLATTENED_OPS)

DEEP_FILTER_ALIASES: dict[str, str] = {
    "agent": "details.agent_id",
    "tool": "details.tool",
    "task": "details.description",
    "prompt": "details.prompt_text",
    "message_text": "details.text",
    "message_thought": "details.thought",
}


class SessionFieldCatalog:
    def is_flattened_path(self, field: str) -> bool:
        return field.lower().split(".", 1)[0] in FLAT_OBJECT_ROOTS

    def resolve_alias(self, field: str) -> str:
        return DEEP_FILTER_ALIASES.get(field.lower(), field)

    def field_spec(self, field: str):
        lower = field.lower()
        if lower in KNOWN_FIELDS:
            return KNOWN_FIELDS[lower]
        root = lower.split(".", 1)[0]
        if root in FLAT_OBJECT_ROOTS:
            return FLATTENED_PATH_SPEC
        return None

    def computed_field_names(self):
        return frozenset(name for name, spec in KNOWN_FIELDS.items() if spec.computed)


SESSIONS_FIELDS = SessionFieldCatalog()
