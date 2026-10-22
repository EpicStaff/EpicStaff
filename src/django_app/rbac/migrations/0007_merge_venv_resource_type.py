# Generated manually to resolve the leaf conflict between the venv manager migrations and developer

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("rbac", "0005_alter_rolepermission_resource_type"),
        ("rbac", "0006_merge_20261009_0941"),
    ]

    operations = []
