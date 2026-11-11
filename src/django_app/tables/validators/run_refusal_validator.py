"""Author templates and flow state paths that crew refuses at run time, found before a write.

A node is checked by field name, so a bulk-save item and an exported node entry go through
the same table. The fields are the ones crew renders or walks:

- Templates (`src/shared/flow_templates.py`): a REFUSED placeholder makes crew fail the node.
- State paths (`src/shared/state_path.py`): crew's `split_state_path` refuses a segment
  starting with `_`. An input map value (`map_variables_to_input`) is read up to its first
  `|`, the rest being a default; an output path is read whole.

Deliberately stricter than crew where a field is stored but unused at run time: fields are
matched by name, and a refused path is refused wherever it is stored.

- A classification table's `pre_output_variable_path` / `post_output_variable_path` while its
  matching pre/post code is empty: crew skips that computation and never reads the path.
- A key-value node's `input_map` and `output_variable_path`: crew builds that node with
  neither.

Not checked here, because crew does not refuse them: a classification table's pre/post and
prompt input maps (resolved by its own walker, which yields None instead), the `prompt_text`
of a System One prompt (crew receives it empty, and the editor locks the field), and
key-value node entries (`KeyValueEntriesValidator`).

The template fields here are also listed in the `inventory_flow_templates` command
(`tables/management/commands/inventory_flow_templates.py`), which reports stored templates.
A template field crew starts rendering goes into both.
"""

from collections.abc import Callable, Iterable, Iterator, Mapping
from typing import Any

from src.shared.flow_templates import PlaceholderKind, inspect_template
from src.shared.models.system_one import SYSTEM_ONE_PROMPT_KIND
from src.shared.state_path import state_path_refusal

from tables.import_export.enums import EntityType, NodeType

# A field's value -> the author-facing reasons crew refuses it; empty when it does not.
RefusalCheck = Callable[[Any], list[str]]


def _template_refusals(value: Any) -> list[str]:
    if not isinstance(value, str):
        return []
    return _unique(
        placeholder.reason
        for placeholder in inspect_template(value).placeholders
        if placeholder.kind is PlaceholderKind.REFUSED
    )


def _state_path_refusals(value: Any) -> list[str]:
    if not isinstance(value, str):
        return []
    refusal = state_path_refusal(value)
    return [] if refusal is None else [refusal]


def _input_map_refusals(value: Any) -> list[str]:
    if not isinstance(value, Mapping):
        return []
    return _unique(
        refusal
        for path in value.values()
        if isinstance(path, str)
        and (refusal := state_path_refusal(path.split("|", 1)[0])) is not None
    )


_NODE_FIELDS: dict[str, RefusalCheck] = {
    # TaskNode
    "instructions": _template_refusals,
    # KnowledgeNode
    "query": _template_refusals,
    # Every BaseNode: crew's input mapping, and where the node's output is stored.
    "input_map": _input_map_refusals,
    "output_variable_path": _state_path_refusals,
    # EndNode: mapped like an input map.
    "output_map": _input_map_refusals,
    # ClassificationDecisionTableNode: where pre/post computation output is stored.
    "pre_output_variable_path": _state_path_refusals,
    "post_output_variable_path": _state_path_refusals,
}

# A node's child list -> the fields of each row.
_CHILD_LIST_FIELDS: dict[str, dict[str, RefusalCheck]] = {
    # AgentNode
    "tasks": {"instructions": _template_refusals},
    # ClassificationDecisionTableNode, LLM prompts only (see `_is_system_one_prompt`).
    "prompt_configs": {"prompt_text": _template_refusals},
    # TelegramTriggerNode
    "fields": {"variable_path": _state_path_refusals},
}


def node_run_refusals(node: Mapping[str, Any]) -> dict[str, Any]:
    """Return what crew would refuse in `node`, shaped like a DRF serializer's `errors`.

    A field maps to its messages; a child list maps to one detail per sent row, `{}` for a
    clean row, so the indexes match the sent list. Empty when nothing is refused. Values of
    an unexpected type are skipped; the serializer reports those.
    """
    errors: dict[str, Any] = _field_errors(node, _NODE_FIELDS)
    for list_field, row_fields in _CHILD_LIST_FIELDS.items():
        rows = node.get(list_field)
        if not isinstance(rows, list):
            continue
        row_errors = [
            {} if _is_system_one_prompt(row) else _field_errors(row, row_fields) for row in rows
        ]
        if any(row_errors):
            errors[list_field] = row_errors
    return errors


def find_run_refusals_in_export(export_data: Mapping[str, Any]) -> list[str]:
    """List what crew would refuse in an import file, each message naming flow, node and field.

    Walks what `ImportService` imports: every flow's nodes (subflows included) and any
    top-level node list.
    """
    messages: list[str] = []
    for flow in export_data.get(EntityType.GRAPH) or []:
        if isinstance(flow, Mapping):
            messages += _node_entry_messages(flow.get("nodes"), f" of flow '{flow.get('name')}'")
    for node_type in NodeType:
        messages += _node_entry_messages(export_data.get(node_type), "")
    return messages


def _node_entry_messages(nodes: Any, location: str) -> list[str]:
    if not isinstance(nodes, list):
        return []
    # An end node has no stored name; its type names it.
    return [
        f"Node '{node.get('node_name') or node.get('node_type')}'{location}, "
        f"field '{field}': {message}"
        for node in nodes
        if isinstance(node, Mapping)
        for field, message in _flatten(node_run_refusals(node))
    ]


def _flatten(detail: Mapping[str, Any], prefix: str = "") -> Iterator[tuple[str, str]]:
    """Yield (field path, message) for each message of a `node_run_refusals` detail."""
    for field, entries in detail.items():
        for position, entry in enumerate(entries):
            if isinstance(entry, Mapping):
                yield from _flatten(entry, f"{prefix}{field}[{position}].")
            else:
                yield f"{prefix}{field}", entry


def _is_system_one_prompt(row: Any) -> bool:
    # Text left in a System One prompt's `prompt_text` never runs, and its author could not
    # remove it. Only classification prompt rows carry a `kind`. A row sent without one is
    # checked as an LLM prompt; the editor and an export always send it.
    return isinstance(row, Mapping) and row.get("kind") == SYSTEM_ONE_PROMPT_KIND


def _field_errors(entry: Any, fields: Mapping[str, RefusalCheck]) -> dict[str, list[str]]:
    if not isinstance(entry, Mapping):
        return {}
    errors = {}
    for field, check in fields.items():
        messages = check(entry.get(field))
        if messages:
            errors[field] = messages
    return errors


def _unique(messages: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(messages))
