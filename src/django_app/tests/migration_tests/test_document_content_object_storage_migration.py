"""tables 0298-0300 move document bytes into the knowledge bucket, and back.

Content no document of a collection refers to is not moved: 0299 deletes it together
with documents outside every collection.
"""

import hashlib

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

BEFORE = [("tables", "0297_documentcontent_object_key")]
AFTER = [("tables", "0300_remove_documentcontent_content")]


def _migrate(targets):
    executor = MigrationExecutor(connection)
    executor.migrate(targets)
    return MigrationExecutor(connection).loader.project_state(targets).apps


@pytest.mark.django_db(transaction=True)
def test_bytes_move_to_the_bucket_and_back(knowledge_bucket):
    try:
        old_apps = _migrate(BEFORE)
        organization = old_apps.get_model("rbac", "Organization").objects.create(
            name="migration-documents-org"
        )
        collection = old_apps.get_model("tables", "SourceCollection").objects.create(
            org=organization, collection_name="docs"
        )
        content_model = old_apps.get_model("tables", "DocumentContent")
        document_model = old_apps.get_model("tables", "DocumentMetadata")
        stored = content_model.objects.create(content=b"hello")
        document_model.objects.create(
            source_collection=collection,
            document_content=stored,
            file_name="a.txt",
            file_type="txt",
            file_size=5,
        )
        unreferenced = content_model.objects.create(content=b"nobody's")
        outside = content_model.objects.create(content=b"outside")
        outside_document = document_model.objects.create(
            source_collection=None,
            document_content=outside,
            file_name="b.txt",
            file_type="txt",
            file_size=7,
        )

        new_apps = _migrate(AFTER)
        new_content_model = new_apps.get_model("tables", "DocumentContent")
        moved = new_content_model.objects.get(pk=stored.pk)
        assert moved.object_key == f"documents/org_{organization.pk}/migrated-{stored.pk}"
        assert knowledge_bucket.files == {moved.object_key: b"hello"}
        assert moved.content_hash == hashlib.sha256(b"hello").hexdigest()
        assert not new_content_model.objects.filter(pk__in=[unreferenced.pk, outside.pk]).exists()
        assert not new_apps.get_model("tables", "DocumentMetadata").objects.filter(
            pk=outside_document.pk
        ).exists()

        reverted_apps = _migrate(BEFORE)
        back = reverted_apps.get_model("tables", "DocumentContent").objects.get(pk=stored.pk)
        assert bytes(back.content) == b"hello"
        assert back.object_key is None
    finally:
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
