__all__ = [
    "args_schema_to_variables",
    "json_schema_node_to_nested_variable",
    "nested_variable_to_json_schema_node",
    "variables_to_args_schema",
    "_normalize_type",
]

_PASSTHROUGH_TYPES = {"string", "number", "boolean", "object", "array", "any"}


def _normalize_type(json_type) -> str:
    # JSON Schema `type` may be a list for nullable fields, e.g. ["integer", "null"].
    if isinstance(json_type, list):
        json_type = next((t for t in json_type if t != "null"), None)

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


def nested_variable_to_json_schema_node(var: dict) -> dict:
    normalized_type = var.get("type", "string")

    node = {
        "type": normalized_type,
        "description": var.get("description", ""),
    }

    default_value = var.get("default_value")
    if default_value is not None:
        node["default"] = default_value

    if normalized_type == "object":
        node["properties"] = {
            key: nested_variable_to_json_schema_node(value)
            for key, value in var.get("properties", {}).items()
        }
        node["required"] = var.get("required_properties", [])

    if normalized_type == "array":
        node["items"] = nested_variable_to_json_schema_node(var.get("item", {}))

    return node


def variables_to_args_schema(variables: list[dict]) -> dict:
    properties = {}
    required = []

    for variable in variables:
        if variable.get("input_type") not in {"agent_input", "mixed"}:
            continue

        name = variable["name"]
        properties[name] = nested_variable_to_json_schema_node(variable)
        if variable.get("required"):
            required.append(name)

    return {"properties": properties, "required": required}
