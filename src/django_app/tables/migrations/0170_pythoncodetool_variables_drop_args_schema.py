from django.db import migrations, models


_FIELD_TYPE_TO_VAR_TYPE = {
    "llm_config": "integer",
    "embedding_config": "integer",
    "string": "string",
    "boolean": "boolean",
    "any": "any",
    "integer": "integer",
    "float": "number",
}


def migrate_to_variables(apps, schema_editor):
    """Convert args_schema + PythonCodeToolConfigField records → variables list."""
    PythonCodeTool = apps.get_model("tables", "PythonCodeTool")
    PythonCodeToolConfigField = apps.get_model("tables", "PythonCodeToolConfigField")

    for tool in PythonCodeTool.objects.all():
        variables = []

        schema = tool.args_schema or {}
        properties = schema.get("properties", {})
        required_names = set(schema.get("required", []))

        for name, prop in properties.items():
            var = {
                "name": name,
                "type": prop.get("type", "string"),
                "description": prop.get("description", ""),
                "default_value": prop.get("default", None),
                "input_type": "agent_input",
                "required": name in required_names,
            }
            if prop.get("properties"):
                var["properties"] = prop["properties"]
            if prop.get("required"):
                var["required_properties"] = prop["required"]
            if prop.get("items"):
                var["items"] = prop["items"]
            variables.append(var)

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
