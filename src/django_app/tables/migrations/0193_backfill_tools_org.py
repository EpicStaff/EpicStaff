from django.db import migrations

from tables.migrations._helpers import assign_default_org, resolve_default_org

# Strict: every row → default org (NOT NULL enforced next, in 0194).
_STRICT = (
    "tables.PythonCodeToolConfig",
    "tables.McpTool",
)
# Hybrid: ONLY custom tools (built_in=False) → default org. Built-in tools keep
# org=NULL (globally visible); this table gets no NOT NULL flip.
_HYBRID = (
    "tables.PythonCodeTool",
)


def forwards(apps, schema_editor):
    org = resolve_default_org(apps)
    for label in _STRICT:
        assign_default_org(apps, label, org)
    for label in _HYBRID:
        assign_default_org(apps, label, org, extra_filter={"built_in": False})


class Migration(migrations.Migration):

    dependencies = [
        ("tables", "0192_alter_pythoncodetoolconfig_unique_together_and_more"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
