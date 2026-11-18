from django.db import migrations, models

GRANT_ACTIONS = ("read", "write", "delete")

# (model, switch field, prefix of the grant columns the switch gated)
SWITCHES = (
    ("pythonnode", "use_storage", ""),
    ("webhooktriggernode", "use_storage", ""),
    ("classificationdecisiontablenode", "pre_use_storage", "pre_"),
    ("classificationdecisiontablenode", "post_use_storage", "post_"),
)


def _grant_columns(prefix):
    return [f"{prefix}storage_grant_{action}" for action in GRANT_ACTIONS]


def untick_grants_of_nodes_without_storage(apps, schema_editor):
    """Clear the boxes of every node whose switch is off, so removing the switch grants nothing.

    Migration 0287 ticked every box on every existing node, including those whose switch
    was off, and those nodes reached no files. Once the switch is gone every node gets
    storage, so only unticked boxes keep them out of the flow's files.
    """
    for model_name, switch, prefix in SWITCHES:
        model = apps.get_model("tables", model_name)
        model.objects.filter(**{switch: False}).update(
            **{column: False for column in _grant_columns(prefix)}
        )


def restore_switch_from_grants(apps, schema_editor):
    """Switch a slot on again when any of its boxes is ticked (best effort).

    A slot with no box ticked had its switch on or off before; it comes back off, which is
    the field's default.
    """
    for model_name, switch, prefix in SWITCHES:
        model = apps.get_model("tables", model_name)
        any_box_ticked = models.Q()
        for column in _grant_columns(prefix):
            any_box_ticked |= models.Q(**{column: True})
        model.objects.filter(any_box_ticked).update(**{switch: True})


class Migration(migrations.Migration):

    dependencies = [
        ('tables', '0293_merge_20261116_1030'),
    ]

    # Kept apart from the RemoveField migration: Postgres refuses to alter a table in the
    # transaction that updated its rows ("pending trigger events").
    operations = [
        migrations.RunPython(
            untick_grants_of_nodes_without_storage, restore_switch_from_grants
        ),
    ]
