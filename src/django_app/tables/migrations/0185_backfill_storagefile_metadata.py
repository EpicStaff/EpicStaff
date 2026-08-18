from django.db import migrations


def _parent_of_inline(path: str) -> str:
    stripped = path.rstrip("/")
    if "/" not in stripped:
        return ""
    return stripped.rsplit("/", 1)[0] + "/"


def backfill_storagefile_metadata(apps, schema_editor):
    StorageFile = apps.get_model("tables", "StorageFile")

    rows = list(
        StorageFile.objects.values_list("id", "path").iterator(chunk_size=2000)
    )

    to_update = []
    for row_id, path in rows:
        item_type = "folder" if path.endswith("/") else "file"
        parent_path = _parent_of_inline(path)
        name = path.rstrip("/").split("/")[-1]
        obj = StorageFile(id=row_id, item_type=item_type, parent_path=parent_path, name=name)
        to_update.append(obj)

    StorageFile.objects.bulk_update(
        to_update,
        fields=["item_type", "parent_path", "name"],
        batch_size=2000,
    )


class Migration(migrations.Migration):

    dependencies = [
        ("tables", "0184_storagefile_db_authoritative"),
    ]

    operations = [
        migrations.RunPython(
            backfill_storagefile_metadata,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
