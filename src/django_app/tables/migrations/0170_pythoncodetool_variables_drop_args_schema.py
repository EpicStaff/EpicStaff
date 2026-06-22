from django.db import migrations, models


_FIELD_TYPE_TO_VAR_TYPE = {
    "llm_config": "number",
    "embedding_config": "number",
    "string": "string",
    "boolean": "boolean",
    "any": "any",
    "integer": "number",
    "float": "number",
}

_PASSTHROUGH_TYPES = {"string", "number", "boolean", "object", "array", "any"}


def _normalize_type(json_type) -> str:
    if not json_type:
        return "string"

    if json_type == "integer":
        return "number"

    if json_type in _PASSTHROUGH_TYPES:
        return json_type

    return json_type


def _json_schema_node_to_nested_variable(node: dict) -> dict:
    normalized_type = _normalize_type(node.get("type"))

    result = {
        "type": normalized_type,
        "description": node.get("description", ""),
        "default_value": node.get("default", None),
    }

    if normalized_type == "object":
        result["properties"] = {
            key: _json_schema_node_to_nested_variable(value)
            for key, value in node.get("properties", {}).items()
        }
        result["required_properties"] = node.get("required", [])

    if normalized_type == "array":
        result["item"] = _json_schema_node_to_nested_variable(node.get("items", {}))

    return result


def migrate_to_variables(apps, schema_editor):
    """Convert args_schema + PythonCodeToolConfigField records → variables list."""
    PythonCodeTool = apps.get_model("tables", "PythonCodeTool")
    PythonCodeToolConfigField = apps.get_model("tables", "PythonCodeToolConfigField")

    for tool in PythonCodeTool.objects.all():
        variables = []

        schema = tool.args_schema or {}
        required_names = set(schema.get("required", []))

        for name, prop in schema.get("properties", {}).items():
            variable = {
                "name": name,
                "input_type": "agent_input",
                "required": name in required_names,
            }
            variable.update(_json_schema_node_to_nested_variable(prop))
            variables.append(variable)

        for field in PythonCodeToolConfigField.objects.filter(tool=tool):
            variables.append(
                {
                    "name": field.name,
                    "type": _FIELD_TYPE_TO_VAR_TYPE.get(field.data_type, "string"),
                    "description": field.description or "",
                    "default_value": None,
                    "input_type": "user_input",
                    "required": field.required,
                }
            )

        tool.variables = variables
        tool.save(update_fields=["variables"])


class Migration(migrations.Migration):

    dependencies = [
        ("tables", "0169_merge_imp_auth"),
    ]

    operations = [
        migrations.AddField(
            model_name="pythoncodetool",
            name="variables",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.RunPython(migrate_to_variables, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name="pythoncodetool",
            name="args_schema",
        ),
        migrations.DeleteModel(
            name="PythonCodeToolConfigField",
        ),
    ]
