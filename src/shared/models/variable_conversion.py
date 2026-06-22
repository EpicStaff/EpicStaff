__all__ = [
    "args_schema_to_variables",
    "json_schema_node_to_nested_variable",
    "_normalize_type",
]

_PASSTHROUGH_TYPES = {"string", "number", "boolean", "object", "array", "any"}


def _normalize_type(json_type) -> str:
    if not json_type:
        return "string"

    if json_type == "integer":
        return "number"

    if json_type in _PASSTHROUGH_TYPES:
        return json_type

    return json_type


def json_schema_node_to_nested_variable(node: dict) -> dict:
    normalized_type = _normalize_type(node.get("type"))

    result = {
        "type": normalized_type,
        "description": node.get("description", ""),
        "default_value": node.get("default", None),
    }

    if normalized_type == "object":
        result["properties"] = {
            key: json_schema_node_to_nested_variable(value)
            for key, value in node.get("properties", {}).items()
        }
        result["required_properties"] = node.get("required", [])

    if normalized_type == "array":
        result["item"] = json_schema_node_to_nested_variable(node.get("items", {}))

    return result


def args_schema_to_variables(
    args_schema: dict, input_type: str = "agent_input"
) -> list[dict]:
    required_names = set(args_schema.get("required", []))
    variables = []

    for name, prop in args_schema.get("properties", {}).items():
        variable = {
            "name": name,
            "input_type": input_type,
            "required": name in required_names,
        }
        variable.update(json_schema_node_to_nested_variable(prop))
        variables.append(variable)

    return variables
