from __future__ import annotations

"""
Structured-output JSON Schema for the Flow Assistant LLM.

Passed to the LLM client as ``response_format: json_schema`` so that
OpenAI-compatible models (gpt-4o and newer) enforce the shape.  Anthropic
falls back to best-effort via litellm's translation layer combined with the
system-prompt guidance.

``strict`` is set to ``False`` for gradual adoption — the model may omit
optional fields (``ef_tables``, ``action_message``) or add unknown keys.
Tighten to ``True`` once all providers support full strict mode and the
frontend handles all defined action types.
"""

FLOW_ASSISTANT_OUTPUT_SCHEMA: dict = {
    "name": "flow_assistant_response",
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "message": {
                "type": "string",
                "description": "Markdown reply text shown in the chat panel.",
            },
            "ef_tables": {
                "type": "array",
                "description": "Interactive data tables rendered below the message.",
                "items": {
                    "type": "object",
                    # Allow extra table-level keys (e.g. preselectedRows, unions)
                    "additionalProperties": True,
                    "properties": {
                        "id": {"type": "string"},
                        "rows": {
                            "type": "array",
                            "description": (
                                "Each row is a FLAT object whose keys correspond to the "
                                "`key` field of each entry in `columns`. "
                                'Example: {"node_id": "4", "node_type": "start", "node_name": "__start__"}. '
                                "DO NOT nest a `columns` array inside individual rows."
                            ),
                            "items": {
                                "type": "object",
                                "description": (
                                    "Flat key-value row. Keys match `columns[].key`. "
                                    "Values are scalars (string, number, boolean) — "
                                    "no nested objects, no `columns` field inside the row."
                                ),
                            },
                        },
                        "columns": {
                            "type": "array",
                            "description": (
                                "Column metadata. Each entry has `key` (required, matches the keys "
                                "of objects in `rows`), `title` (optional display label), "
                                "`type` (optional, one of 'text', 'number', 'boolean', 'date')."
                            ),
                            "items": {
                                "type": "object",
                                "properties": {
                                    "key": {"type": "string"},
                                    "title": {"type": "string"},
                                    "type": {
                                        "enum": ["text", "number", "boolean", "date"]
                                    },
                                    "visible": {"type": "boolean"},
                                    "editable": {"type": "boolean"},
                                },
                                "required": ["key"],
                            },
                        },
                        "isEditable": {"type": "boolean"},
                        "isSortable": {"type": "boolean"},
                        "defaultSortField": {"type": "string"},
                        "rowsSelectionType": {
                            "enum": ["edit", "select", "multiSelect"],
                        },
                    },
                    "required": ["rows"],
                },
            },
            "action_message": {
                "type": "array",
                "description": (
                    "Interactive elements (buttons, links, prompt chips) rendered "
                    "alongside the message."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "type": {
                            "enum": ["button", "link", "prompt"],
                        },
                        "action": {
                            "enum": [
                                "sendAction",
                                "sendButtonTextWithParams",
                                "link",
                                "openFlow",
                                "openNode",
                                "refreshCache",
                            ],
                        },
                        "text": {"type": "string"},
                        "params": {
                            "type": "object",
                            "additionalProperties": True,
                        },
                    },
                    "required": ["type", "text"],
                },
            },
        },
        "required": ["message"],
    },
    # strict=False: permissive during gradual adoption.
    # Set to True once all target providers support strict JSON schema enforcement
    # and the frontend handles every defined action type.
    "strict": False,
}
