# Generated by Django 5.1.3 on 2025-06-04 10:50

from django.db import migrations
import uuid


def populate_uuids(apps, schema_editor):
    Model = apps.get_model("tables", "GraphSessionMessage")
    db_alias = schema_editor.connection.alias
    for obj in Model.objects.using(db_alias).filter(uuid__isnull=True):
        Model.objects.using(db_alias).filter(pk=obj.pk).update(uuid=uuid.uuid4())


class Migration(migrations.Migration):

    dependencies = [
        ("tables", "0092_graphsessionmessage_uuid"),
    ]

    operations = [
        migrations.RunPython(populate_uuids, reverse_code=migrations.RunPython.noop),
    ]
