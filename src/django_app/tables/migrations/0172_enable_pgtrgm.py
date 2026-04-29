from django.contrib.postgres.operations import TrigramExtension
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("tables", "0171_alter_storagefile_path"),
    ]

    operations = [
        TrigramExtension(),
    ]
