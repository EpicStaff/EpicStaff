from tables.import_export.constants import MAIN_ENTITY_KEY
from tables.import_export.enums import EntityType

_CODE_KEYS = ("python_code", "pre_python_code", "post_python_code")
_META_KEYS = frozenset({MAIN_ENTITY_KEY, "version"})


def _file_id(entry: dict) -> int | None:
    # The review dialog matches nodes by integer id only; a hand-made file with
    # string or bool ids must not produce an id that never matches.
    file_id = entry.get("id")
    return file_id if type(file_id) is int else None


def _project_python_code_tools(entities: list) -> list:
    items = []
    for entry in entities:
        if not isinstance(entry, dict):
            continue
        items.append(
            {
                "kind": "python_code_tool",
                "name": entry.get("name"),
                "description": entry.get("description"),
                "python_code": entry.get("python_code"),
                "variables": entry.get("variables"),
                "use_storage": entry.get("use_storage"),
            }
        )
    return items


def _project_mcp_tools(entities: list) -> list:
    items = []
    for entry in entities:
        if not isinstance(entry, dict):
            continue
        items.append(
            {
                "kind": "mcp_tool",
                "name": entry.get("name"),
                "transport": entry.get("transport"),
            }
        )
    return items


def _has_code(value) -> bool:
    return value is not None and str(value).strip() != ""


def _text(entry: dict, key: str) -> str:
    value = entry.get(key)
    return "" if value is None else str(value)


# Every decision-table expression crew runs as Python; the file is untrusted, so a
# malformed shape is skipped, never raised on.
def _project_expressions(condition_groups) -> list:
    if not isinstance(condition_groups, list):
        return []
    labelled_values = []
    for group in condition_groups:
        if not isinstance(group, dict):
            continue
        group_label = f'Group "{_text(group, "group_name")}"'
        labelled_values.append((f"{group_label}: expression", group.get("expression")))
        labelled_values.append((f"{group_label}: manipulation", group.get("manipulation")))
        conditions = group.get("conditions")
        for condition in conditions if isinstance(conditions, list) else []:
            if isinstance(condition, dict):
                labelled_values.append(
                    (
                        f'{group_label}, condition "{_text(condition, "condition_name")}"',
                        condition.get("condition"),
                    )
                )
        # Crew pastes each field name into the code it runs, so the raw name is shown
        # in the code, never only in the label.
        for field_key, label, separator in (
            ("field_expressions", "field expression", " "),
            ("field_manipulations", "field manipulation", " = "),
        ):
            fields = group.get(field_key)
            if isinstance(fields, dict):
                labelled_values.extend(
                    (f"{group_label}: {label}", f"{name}{separator}{value}")
                    for name, value in fields.items()
                    if _has_code(value)
                )
    return [
        {"label": label, "code": str(value)} for label, value in labelled_values if _has_code(value)
    ]


def _project_flow_nodes(graphs: list) -> list:
    items = []
    for graph in graphs:
        if not isinstance(graph, dict):
            continue
        flow_name = graph.get("name")

        nodes = graph.get("nodes")
        for node in nodes if isinstance(nodes, list) else []:
            if not isinstance(node, dict):
                continue
            code_fields = {key: node[key] for key in _CODE_KEYS if node.get(key)}
            # Projected from any node carrying condition groups, whatever its
            # node_type says: a misspelled type must not hide code.
            expressions = _project_expressions(node.get("condition_groups"))
            if not code_fields and not expressions:
                continue
            item = {
                "kind": "flow_node",
                "flow_name": flow_name,
                "node_id": _file_id(node),
                "node_name": node.get("node_name"),
                "node_type": node.get("node_type"),
            }
            item.update(code_fields)
            if expressions:
                item["expressions"] = expressions
            items.append(item)

    return items


_PROJECTORS = {
    EntityType.PYTHON_CODE_TOOL: _project_python_code_tools,
    EntityType.MCP_TOOL: _project_mcp_tools,
    EntityType.GRAPH: _project_flow_nodes,
}


class InspectService:
    def inspect(self, data: dict, org_id: int | None = None) -> dict:
        review_items = []
        for key, entities in data.items():
            if key in _META_KEYS or not isinstance(entities, list):
                continue
            projector = _PROJECTORS.get(key)
            if projector is None:
                continue
            review_items.extend(projector(entities))
        return {"review_items": review_items}
