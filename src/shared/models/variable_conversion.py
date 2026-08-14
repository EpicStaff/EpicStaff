from .variables import VariableTypeInput

__all__ = [
    "args_schema_to_variables",
    "json_schema_node_to_nested_variable",
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
        # A property may opt out of the schema-wide default by declaring its
        # own "input_type" (e.g. "user_input" for a config-only secret like an
        # API key). Absent that key, behavior is unchanged (falls back to the
        # `input_type` argument, "agent_input" by default) — fully backward
        # compatible with existing tool_data.yaml / args_schema.json files.
        property_input_type = prop.get("input_type", input_type)
        allowed_input_types = {v.value for v in VariableTypeInput}
        if property_input_type not in allowed_input_types:
            allowed = ", ".join(sorted(allowed_input_types))
            raise ValueError(
                f"Invalid input_type {property_input_type!r} for property {name!r}: "
                f"allowed values are {allowed}"
            )

        variable = {
            "name": name,
            "input_type": property_input_type,
            "required": name in required_names,
        }
        variable.update(json_schema_node_to_nested_variable(prop))
        variables.append(variable)

    return variables
