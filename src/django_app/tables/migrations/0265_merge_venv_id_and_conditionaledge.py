# Generated manually to merge the two leaf migrations of the venv manager work and the conditional edge removal

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("tables", "0257_remove_pythoncode_libraries_pythoncode_venv_id"),
        ("tables", "0264_alter_graphversion_snapshot_delete_conditionaledge"),
    ]

    operations = []
