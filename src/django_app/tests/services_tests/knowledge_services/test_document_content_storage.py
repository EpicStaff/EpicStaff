"""Document content lives in the knowledge bucket: uploads write it, deletes remove it.

A file is removed only after the transaction that removed the last document pointing at
it commits, so the tests run the commit callbacks.
"""

import hashlib

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from tables.models import DocumentContent, DocumentMetadata
from tables.services.knowledge_services.document_content_storage import DocumentContentStorage
from tables.services.knowledge_services.document_management_service import (
    DocumentManagementService,
)


def _upload(collection, *files):
    return DocumentManagementService.upload_files_batch(
        collection.collection_id,
        [SimpleUploadedFile(name, data, content_type="text/plain") for name, data in files],
    )


def _copy_into(collection, document):
    return DocumentMetadata.objects.create(
        source_collection=collection,
        document_content=document.document_content,
        file_name=document.file_name,
        file_type=document.file_type,
        file_size=document.file_size,
    )


@pytest.mark.django_db
class TestUpload:
    def test_uploaded_bytes_are_stored_under_the_organization(
        self, source_collection, knowledge_bucket
    ):
        (document,) = _upload(source_collection, ("notes.txt", b"plain notes"))

        object_key = document.document_content.object_key
        assert object_key.startswith(f"documents/org_{source_collection.org_id}/")
        assert knowledge_bucket.files[object_key] == b"plain notes"
        assert document.document_content.content_hash == hashlib.sha256(b"plain notes").hexdigest()

    def test_a_row_that_cannot_be_created_leaves_no_file(self, knowledge_bucket, monkeypatch):
        def refuse(**kwargs):
            raise RuntimeError("database went away")

        monkeypatch.setattr(DocumentContent.objects, "create", refuse)

        with pytest.raises(RuntimeError):
            DocumentContentStorage.create(1, b"data")

        assert knowledge_bucket.files == {}

    def test_a_failed_upload_leaves_no_files_behind(
        self, source_collection, knowledge_bucket, monkeypatch
    ):
        real_create = DocumentManagementService.create_document_metadata
        calls = []

        def fail_on_second_document(**kwargs):
            calls.append(kwargs["file_name"])
            if len(calls) == 2:
                raise RuntimeError("database went away")
            return real_create(**kwargs)

        monkeypatch.setattr(
            DocumentManagementService,
            "create_document_metadata",
            staticmethod(fail_on_second_document),
        )

        with pytest.raises(RuntimeError):
            _upload(source_collection, ("a.txt", b"first"), ("b.txt", b"second"))

        assert knowledge_bucket.files == {}


@pytest.mark.django_db
class TestDelete:
    def test_deleting_the_last_document_deletes_its_file(
        self, document_metadata, knowledge_bucket, django_capture_on_commit_callbacks
    ):
        object_key = document_metadata.document_content.object_key

        with django_capture_on_commit_callbacks(execute=True):
            DocumentManagementService.delete_document(document_metadata.document_id)

        assert not DocumentContent.objects.filter(object_key=object_key).exists()
        assert object_key not in knowledge_bucket.files

    def test_deleting_one_copy_keeps_the_file_of_the_other(
        self,
        document_metadata,
        empty_collection,
        knowledge_bucket,
        django_capture_on_commit_callbacks,
    ):
        _copy_into(empty_collection, document_metadata)
        object_key = document_metadata.document_content.object_key

        with django_capture_on_commit_callbacks(execute=True):
            DocumentManagementService.delete_document(document_metadata.document_id)

        assert knowledge_bucket.files[object_key] == b"Test file content"

    def test_batch_delete_deletes_only_unshared_files(
        self,
        multiple_documents,
        empty_collection,
        knowledge_bucket,
        django_capture_on_commit_callbacks,
    ):
        shared, *unshared = multiple_documents
        _copy_into(empty_collection, shared)

        with django_capture_on_commit_callbacks(execute=True):
            DocumentManagementService.delete_documents_batch(
                [document.document_id for document in multiple_documents]
            )

        assert set(knowledge_bucket.files) == {shared.document_content.object_key}

    def test_a_rolled_back_delete_keeps_the_file(self, document_metadata, knowledge_bucket):
        object_key = document_metadata.document_content.object_key

        # Without a commit the callback never runs, as after a rollback.
        DocumentManagementService.delete_document(document_metadata.document_id)

        assert object_key in knowledge_bucket.files
