from src.shared.models import args_schema_to_variables
from tables.import_export.version_conversions.base import VersionConverter

_FIELD_TYPE_TO_VAR_TYPE = {
    "llm_config": "number",
    "embedding_config": "number",
    "string": "string",
    "boolean": "boolean",
    "any": "any",
    "integer": "number",
    "float": "number",
}


@VersionConverter.register(from_version=1)
def v1_to_v2(data: dict) -> dict:
    """
    v1 → v2: replace args_schema + python_code_tool_config_fields on each
    PythonCodeTool entry with a single `variables` list, mirroring DB
    migration 0170_pythoncodetool_variables_drop_args_schema.

    agent_input variables come from args_schema.properties;
    user_input variables come from python_code_tool_config_fields records.
    Bundles that carry no PythonCodeTool key (e.g. graph-only snapshots)
    pass through unchanged.

    JSON-schema "integer" types are normalized to "number" to match the
    runtime VariableType enum, which has no integer variant. Nested
    object/array schemas are recursively converted to NestedVariable shape.
    """
    for tool in data.get("PythonCodeTool", []):
        variables = args_schema_to_variables(tool.get("args_schema") or {})

        for field in tool.get("python_code_tool_config_fields", []):
            variables.append(
                {
                    "name": field.get("name"),
                    "type": _FIELD_TYPE_TO_VAR_TYPE.get(
                        field.get("data_type"), "string"
                    ),
                    "description": field.get("description") or "",
                    "default_value": None,
                    "input_type": "user_input",
                    "required": field.get("required", True),
                }
            )

        tool["variables"] = variables
        tool.pop("args_schema", None)
        tool.pop("python_code_tool_config_fields", None)

    return data
