from django.db import migrations

from tables.migrations._helpers import assign_default_org, resolve_default_org


def forwards(apps, schema_editor):
    org = resolve_default_org(apps)
    assign_default_org(apps, "tables.SourceCollection", org)


class Migration(migrations.Migration):
    dependencies = [
        (
            "tables",
            "0195_remove_sourcecollection_unique_collection_name_per_user_and_more",
        ),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
