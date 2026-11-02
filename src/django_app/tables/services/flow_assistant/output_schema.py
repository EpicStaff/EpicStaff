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

import copy

from src.shared.litellm_model_names import litellm_call_model, litellm_routed_provider

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
                                    "type": {"enum": ["text", "number", "boolean", "date"]},
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


_CELL_SCHEMA: dict = {
    "anyOf": [
        {"type": "string"},
        {"type": "number"},
        {"type": "boolean"},
        {"type": "null"},
    ],
}


def _build_anthropic_output_schema() -> dict:
    """Derive the Anthropic variant from the default schema.

    Anthropic's structured output closes every object (``additionalProperties: false``),
    so a row declared as a free-form object can only ever be ``{}``. Rows are therefore
    sent as arrays of scalar cells ordered like ``columns`` and turned back into flat
    row objects by ``normalize_table_cells`` after parsing.
    """
    schema = copy.deepcopy(FLOW_ASSISTANT_OUTPUT_SCHEMA)
    table_schema = schema["schema"]["properties"]["ef_tables"]["items"]
    del table_schema["properties"]["rows"]
    table_schema["properties"]["cells"] = {
        "type": "array",
        "description": (
            "One entry per table row. Each row is an array of cell values in the same "
            "order as `columns`, so row[i] is the value for columns[i]."
        ),
        "items": {"type": "array", "items": _CELL_SCHEMA},
    }
    table_schema["required"] = ["columns", "cells"]
    return schema


ANTHROPIC_FLOW_ASSISTANT_OUTPUT_SCHEMA: dict = _build_anthropic_output_schema()


def uses_anthropic_structured_output(llm_config) -> bool:
    """Return True when LiteLLM sends this config's model to the Anthropic provider.

    Uses the same model-string rule as ``LiteLLMClient``, so an OpenAI-row config holding
    a bare ``claude-*`` name counts, and an Anthropic-row config does not when its model
    routes elsewhere. Needs ``model`` (and ideally ``model.llm_provider``) loaded.
    """
    model = llm_config.model if llm_config is not None else None
    if model is None or not (model.name or "").strip():
        return False
    provider = model.llm_provider
    model_string = litellm_call_model(
        provider.name if provider else None, model.name, model.deployment_id
    )
    return litellm_routed_provider(model_string) == "anthropic"


def normalize_table_cells(ef_tables: list) -> list:
    """Turn tables that carry ``cells`` into tables with flat ``rows``.

    Each row array is matched positionally with ``columns``: cell i belongs to column i,
    and a cell whose column has no string ``key`` is skipped without shifting the others.
    A row shorter than ``columns`` leaves the missing keys out; extra trailing cells have
    no column and are dropped. A row that is already an object passes through as-is; any
    other row type becomes ``{}``. The ``cells`` key is removed.

    When a table has both ``rows`` and ``cells``, ``cells`` wins and replaces ``rows``.
    Tables without ``cells`` (including ones that already have ``rows``) and non-dict
    entries are returned untouched, as is an ``ef_tables`` value that is not a list.
    A table whose ``cells`` is present but ``columns`` is missing gets empty rows.
    """
    if not isinstance(ef_tables, list):
        return ef_tables
    return [_normalize_table(table) for table in ef_tables]


def _normalize_table(table):
    if not isinstance(table, dict) or "cells" not in table:
        return table
    keys = [
        column.get("key") if isinstance(column, dict) else None
        for column in table.get("columns") or []
    ]
    normalized = {name: value for name, value in table.items() if name != "cells"}
    normalized["rows"] = [_row_from_cells(row, keys) for row in table["cells"] or []]
    return normalized


def _row_from_cells(row, keys: list) -> dict:
    if isinstance(row, dict):
        return row
    if not isinstance(row, list):
        return {}
    return {key: cell for key, cell in zip(keys, row, strict=False) if isinstance(key, str)}
