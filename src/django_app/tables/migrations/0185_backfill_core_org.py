from django.db import migrations

from tables.migrations._helpers import assign_default_org, resolve_default_org


def forwards(apps, schema_editor):
    org = resolve_default_org(apps)
    for label in ("tables.Graph", "tables.Agent", "tables.Crew"):
        assign_default_org(apps, label, org)


class Migration(migrations.Migration):

    dependencies = [
        ("tables", "0184_rbac_inherit_org_scoped_in_graph_agent_crew"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
