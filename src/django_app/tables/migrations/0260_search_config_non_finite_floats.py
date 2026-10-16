from django.db import migrations

# Frozen copies of the model defaults at the time of this migration.
LOCAL_FIELD_DEFAULTS = {"text_unit_prop": 0.5, "community_prop": 0.15}
DRIFT_FIELD_DEFAULTS = {
    "reduce_temperature": 0.0,
    "local_search_text_unit_prop": 0.9,
    "local_search_community_prop": 0.1,
    "local_search_temperature": 0.0,
    "local_search_top_p": 1.0,
}
MODEL_FIELD_DEFAULTS = {
    "GraphRagLocalSearchConfig": LOCAL_FIELD_DEFAULTS,
    "KnowledgeNodeGraphRagLocalSearchConfig": LOCAL_FIELD_DEFAULTS,
    "GraphRagDriftSearchConfig": DRIFT_FIELD_DEFAULTS,
    "KnowledgeNodeGraphRagDriftSearchConfig": DRIFT_FIELD_DEFAULTS,
}
NON_FINITE_VALUES = (float("nan"), float("inf"), float("-inf"))


def reset_non_finite_values(apps, schema_editor=None):
    """Set every NaN or infinite search-config value back to its default.

    Postgres treats NaN as equal to itself, which is what lets ``__in`` match it.
    """
    for model_name, field_defaults in MODEL_FIELD_DEFAULTS.items():
        queryset = apps.get_model("tables", model_name)._base_manager.all()
        for field_name, default in field_defaults.items():
            queryset.filter(**{f"{field_name}__in": NON_FINITE_VALUES}).update(
                **{field_name: default}
            )


class Migration(migrations.Migration):
    dependencies = [
        ("tables", "0259_mcptool_clamp_timeouts"),
    ]

    operations = [
        migrations.RunPython(reset_non_finite_values, migrations.RunPython.noop),
    ]
