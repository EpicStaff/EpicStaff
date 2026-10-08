from django.db import migrations

# Frozen copies of the bounds and defaults introduced alongside this migration,
# so later model edits cannot change what this backfill did.
TIMEOUT_FIELD_RULES = {
    "timeout": (1, 1800, 30),
    "init_timeout": (1, 120, 10),
}
NON_FINITE_VALUES = (float("nan"), float("inf"), float("-inf"))


def clamp_timeouts(mcp_tool_model):
    """Replace NaN and infinity with the default, then clamp every timeout into its bounds.

    Postgres sorts NaN above every number, so without this the clamp would turn it into the
    maximum. Postgres also treats NaN as equal to itself, which is what lets ``__in`` match it.
    """
    queryset = mcp_tool_model.objects.all()
    for field_name, (minimum, maximum, default) in TIMEOUT_FIELD_RULES.items():
        queryset.filter(**{f"{field_name}__in": NON_FINITE_VALUES}).update(**{field_name: default})
        queryset.filter(**{f"{field_name}__lt": minimum}).update(**{field_name: minimum})
        queryset.filter(**{f"{field_name}__gt": maximum}).update(**{field_name: maximum})


def forwards(apps, schema_editor):
    clamp_timeouts(apps.get_model("tables", "McpTool"))


class Migration(migrations.Migration):
    dependencies = [
        ("tables", "0258_mcptool_transport_timeout_validators"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
