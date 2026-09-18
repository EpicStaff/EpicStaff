from django.db import migrations

from tables.migrations._helpers import assign_default_org, resolve_default_org


def forwards(apps, schema_editor):
    org = resolve_default_org(apps)
    assign_default_org(apps, "tables.Label", org)


class Migration(migrations.Migration):

    dependencies = [
        ("tables", "0198_remove_label_unique_label_name_per_level_and_more"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
