from tables.import_export.constants import MAIN_ENTITY_KEY
from tables.import_export.enums import EntityType

_CODE_KEYS = ("python_code", "pre_python_code", "post_python_code")
_META_KEYS = frozenset({MAIN_ENTITY_KEY, "version"})


def _project_python_code_tools(entities: list) -> list:
    items = []
    for entry in entities:
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
        items.append(
            {
                "kind": "mcp_tool",
                "name": entry.get("name"),
                "transport": entry.get("transport"),
            }
        )
    return items


def _project_flow_nodes(graphs: list) -> list:
    items = []
    for graph in graphs:
        flow_name = graph.get("name")

        for node in graph.get("nodes", []):
            code_fields = {key: node[key] for key in _CODE_KEYS if node.get(key)}
            if not code_fields:
                continue
            item = {
                "kind": "flow_node",
                "flow_name": flow_name,
                "node_name": node.get("node_name"),
                "node_type": node.get("node_type"),
            }
            item.update(code_fields)
            items.append(item)

        for edge in graph.get("conditional_edge_list", []):
            code_fields = {key: edge[key] for key in _CODE_KEYS if edge.get(key)}
            if not code_fields:
                continue
            item = {
                "kind": "flow_node",
                "flow_name": flow_name,
                "node_name": None,
                "node_type": "ConditionalEdge",
            }
            item.update(code_fields)
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
