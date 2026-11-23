"""Copy every document's bytes from Postgres into the knowledge bucket.

Runs outside a transaction and commits each row on its own, so a run that stops part way
keeps what it moved: the next run starts with the rows whose `object_key` is still empty.
The key is derived from the row id, so a file written by a run that stopped before saving
its key is overwritten, not duplicated.

Content that no document of a collection refers to has no organization to file it under;
it is skipped here and removed by the next migration.

Going back copies the bytes from the bucket into the column again and leaves the stored
files in place.
"""

from django.db import migrations
from loguru import logger
from tables.services.knowledge_services import document_content_storage

_BATCH_SIZE = 100


def move_content_to_object_storage(apps, schema_editor):
    document_content_model = apps.get_model("tables", "DocumentContent")
    document_metadata_model = apps.get_model("tables", "DocumentMetadata")

    content_ids = list(
        document_content_model.objects.filter(object_key__isnull=True)
        .order_by("id")
        .values_list("id", flat=True)
    )
    if not content_ids:
        return

    bucket = document_content_storage.knowledge_bucket()
    moved_count = 0
    skipped_count = 0
    for start in range(0, len(content_ids), _BATCH_SIZE):
        batch_ids = content_ids[start : start + _BATCH_SIZE]
        # The historical default manager is a plain Manager, so documents in the recycle
        # bin are included: they can still be restored.
        org_by_content_id = dict(
            document_metadata_model.objects.filter(
                document_content_id__in=batch_ids, source_collection__org_id__isnull=False
            ).values_list("document_content_id", "source_collection__org_id")
        )
        for content_id in batch_ids:
            org_id = org_by_content_id.get(content_id)
            if org_id is None:
                skipped_count += 1
                continue
            # One row's bytes at a time: a document may be tens of megabytes.
            data = (
                document_content_model.objects.filter(pk=content_id)
                .values_list("content", flat=True)
                .get()
            )
            object_key = f"documents/org_{org_id}/migrated-{content_id}"
            bucket.object(object_key).write(bytes(data))
            document_content_model.objects.filter(pk=content_id).update(object_key=object_key)
            moved_count += 1
        logger.info(
            "Moved {} of {} document contents to object storage",
            moved_count,
            len(content_ids),
        )

    if skipped_count:
        logger.warning(
            "Skipped {} document contents that no document of a collection refers to",
            skipped_count,
        )


def move_content_back_to_postgres(apps, schema_editor):
    document_content_model = apps.get_model("tables", "DocumentContent")
    stored = list(
        document_content_model.objects.filter(object_key__isnull=False).values_list(
            "id", "object_key"
        )
    )
    if not stored:
        return

    bucket = document_content_storage.knowledge_bucket()
    for content_id, object_key in stored:
        data = bucket.object(object_key).read()
        document_content_model.objects.filter(pk=content_id).update(
            content=data, object_key=None
        )
    logger.info("Moved {} document contents back to Postgres", len(stored))


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("tables", "0297_documentcontent_object_key"),
    ]

    operations = [
        migrations.RunPython(move_content_to_object_storage, move_content_back_to_postgres),
    ]
