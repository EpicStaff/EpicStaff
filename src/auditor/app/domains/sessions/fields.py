from app.domains.base import DictFieldCatalog, FreeTextFields
from app.filtering.ast import FieldSpec
from app.filtering.constants import (
    DURATION_OPS,
    RANGE_OPS,
    SELECT_OPS,
    TEXT_CONDITION_OPS,
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

DEEP_FILTER_ALIASES: dict[str, str] = {
    "agent": "details.agent_id",
    "tool": "details.tool",
    "task": "details.description",
    "prompt": "details.prompt_text",
    "message_text": "details.text",
    "message_thought": "details.thought",
}

# `error` is analyzed text: the standard analyzer treats '.' as a word-joiner, so
# a match on "AuthenticationError" inside a dotted stack trace finds nothing.
# Pattern ops therefore run against the `error.raw` wildcard sub-field instead.
WILDCARD_SUBFIELDS: dict[str, str] = {"error": "error.raw"}

FREE_TEXT_FIELDS = FreeTextFields(
    wildcard_fields=("name", "node_type", "flow_name"),
    query_string_fields=("input.*", "output.*", "details.*"),
)

SESSIONS_FIELDS = DictFieldCatalog(
    known_fields=KNOWN_FIELDS,
    aliases=DEEP_FILTER_ALIASES,
    flat_roots=FLAT_OBJECT_ROOTS,
    free_text=FREE_TEXT_FIELDS,
    wildcard_subfields=WILDCARD_SUBFIELDS,
)
