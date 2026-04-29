from django.db import migrations, models


def _backfill_name(apps, schema_editor):
    """Populate name from the last path segment for every existing StorageFile row."""
    StorageFile = apps.get_model("tables", "StorageFile")
    qs = StorageFile.objects.all().only("id", "path", "name")
    batch = []
    for row in qs.iterator(chunk_size=5000):
        row.name = row.path.rstrip("/").split("/")[-1]
        batch.append(row)
        if len(batch) >= 5000:
            StorageFile.objects.bulk_update(batch, ["name"])
            batch.clear()
    if batch:
        StorageFile.objects.bulk_update(batch, ["name"])


def _noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("tables", "0172_enable_pgtrgm"),
    ]

    operations = [
        migrations.AddField(
            model_name="storagefile",
            name="name",
            field=models.CharField(default="", max_length=255),
            preserve_default=False,
        ),
        migrations.RunPython(_backfill_name, reverse_code=_noop),
        migrations.AlterField(
            model_name="storagefile",
            name="name",
            field=models.CharField(
                max_length=255,
                help_text="Last path segment, denormalized for search",
            ),
        ),
    ]
