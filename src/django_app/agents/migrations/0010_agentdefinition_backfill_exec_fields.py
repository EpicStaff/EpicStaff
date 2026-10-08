from django.db import migrations

# Frozen copies of the bounds and defaults introduced alongside this migration,
# so later model edits cannot change what this backfill did.
INTEGER_FIELD_RULES = {
    "max_iter": (1, 90, 15),
    "max_rpm": (1, 240, 30),
    "max_execution_time": (60, 1800, 600),
    "max_retry_limit": (0, 10, 3),
    "schema_max_retries": (0, 20, 2),
    "max_tool_calls": (1, 300, 15),
    "tool_timeout": (10, 1800, 300),
    "max_consecutive_failures": (1, 20, 3),
}
CACHE_DEFAULT = False
TEMPERATURE_MIN = 0.0
TEMPERATURE_MAX = 2.0
NON_FINITE_VALUES = (float("nan"), float("inf"), float("-inf"))
SINGLETON_FIELDS = (*INTEGER_FIELD_RULES, "cache")


def _clamp(queryset, field_name, minimum, maximum):
    queryset.filter(**{f"{field_name}__lt": minimum}).update(**{field_name: minimum})
    queryset.filter(**{f"{field_name}__gt": maximum}).update(**{field_name: maximum})


def backfill_execution_fields(agent_definition_model, singleton_values: dict):
    """Replace NULLs with the singleton value (or the new default), then clamp into bounds.

    A NaN or infinite default_temperature becomes NULL, so it falls back to the singleton
    at runtime instead of being clamped to a bound.
    """
    queryset = agent_definition_model.objects.all()

    for field_name, (minimum, maximum, default) in INTEGER_FIELD_RULES.items():
        replacement = singleton_values.get(field_name)
        if replacement is None:
            replacement = default
        queryset.filter(**{f"{field_name}__isnull": True}).update(**{field_name: replacement})
        _clamp(queryset, field_name, minimum, maximum)

    cache_replacement = singleton_values.get("cache")
    if cache_replacement is None:
        cache_replacement = CACHE_DEFAULT
    queryset.filter(cache__isnull=True).update(cache=cache_replacement)

    queryset.filter(default_temperature__in=NON_FINITE_VALUES).update(default_temperature=None)
    _clamp(queryset, "default_temperature", TEMPERATURE_MIN, TEMPERATURE_MAX)


def forwards(apps, schema_editor):
    config_model = apps.get_model("agents", "DefaultAgentDefinitionConfig")
    singleton_values = config_model.objects.filter(pk=1).values(*SINGLETON_FIELDS).first() or {}
    backfill_execution_fields(apps.get_model("agents", "AgentDefinition"), singleton_values)


class Migration(migrations.Migration):
    dependencies = [
        ("agents", "0009_alter_agentdefinition_organization_and_more"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
