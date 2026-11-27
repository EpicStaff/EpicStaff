"""Remove the documents and content the previous migration could not move.

A document outside any collection belongs to no organization, so no one can reach it;
content no document of a collection refers to was left in Postgres by the previous
migration. Both go before the bytes column is dropped. The schema change is a migration
of its own: Postgres refuses to alter a table with deferred foreign-key checks still
pending from these deletes.

Going back restores nothing: the deleted rows were out of every organization's reach.
"""

from django.db import migrations
from loguru import logger


def delete_unstored_document_content(apps, schema_editor):
    document_content_model = apps.get_model("tables", "DocumentContent")
    document_metadata_model = apps.get_model("tables", "DocumentMetadata")

    _, deleted_documents = document_metadata_model.objects.filter(
        source_collection__isnull=True
    ).delete()
    document_count = deleted_documents.get(document_metadata_model._meta.label, 0)
    if document_count:
        logger.warning("Deleted {} documents that belong to no collection", document_count)

    _, deleted_contents = document_content_model.objects.filter(object_key__isnull=True).delete()
    content_count = deleted_contents.get(document_content_model._meta.label, 0)
    if content_count:
        logger.warning(
            "Deleted {} document contents that no document of a collection referred to",
            content_count,
        )


class Migration(migrations.Migration):
    dependencies = [
        ("tables", "0298_move_document_content_to_object_storage"),
    ]

    operations = [
        migrations.RunPython(delete_unstored_document_content, migrations.RunPython.noop),
    ]
