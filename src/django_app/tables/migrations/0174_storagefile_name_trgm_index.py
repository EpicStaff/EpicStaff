from django.contrib.postgres.indexes import GinIndex
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("tables", "0173_storagefile_name"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="storagefile",
            index=GinIndex(
                fields=["name"],
                name="storagefile_name_trgm_idx",
                opclasses=["gin_trgm_ops"],
            ),
        ),
    ]
