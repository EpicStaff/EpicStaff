"""Editing a text document's content: what changes, what is refused, and what stays.

A new version always goes to a new key; the old file goes after the commit only when no
document refers to it any more, so the tests run the commit callbacks.
"""

import hashlib

import pytest
from django.db import DatabaseError, connection
from django.utils import timezone
from django.test.utils import CaptureQueriesContext

from rbac.models import Organization
from tables.constants.knowledge_constants import DocumentContentScope
from tables.exceptions import (
    ContentHashConflictError,
    DocumentContentMissingException,
    DocumentIndexingInProgressException,
    DocumentNotEditableException,
    DocumentNotFoundException,
    FileSizeExceededException,
)
from tables.models.knowledge_models import (
    BaseRagType,
    DocumentContent,
    DocumentMetadata,
    GraphRag,
    GraphRagDocument,
    NaiveRag,
    NaiveRagDocumentConfig,
    SourceCollection,
)
from tables.services.knowledge_services.document_management_service import (
    DocumentManagementService,
)
from tables.services.knowledge_services.naive_rag_service import NaiveRagService
from tests.knowledge_content import stored_document_bytes, stored_document_content

OLD_TEXT = b"old text"
NEW_TEXT = b"new text"
NAIVE_STATUS = NaiveRagDocumentConfig.NaiveRagDocumentStatus


def _config(naive_rag, document, status):
    """The document's config in `naive_rag` with `status`; creating the RAG may have made it already."""
    config, _ = NaiveRagDocumentConfig.objects.get_or_create(
        naive_rag=naive_rag,
        document=document,
        defaults={"chunk_strategy": "token", "chunk_size": 1000, "chunk_overlap": 150},
    )
    config.status = status
    config.save(update_fields=["status"])
    return config


def _graph_link(collection, document, status, test_embedding_config, llm_config):
    base = BaseRagType.objects.create(
        source_collection=collection, rag_type=BaseRagType.RagType.GRAPH
    )
    rag = GraphRag.objects.create(
        base_rag_type=base,
        embedder=test_embedding_config,
        llm=llm_config,
        rag_status=GraphRag.GraphRagStatus.COMPLETED,
    )
    return GraphRagDocument.objects.create(graph_rag=rag, document=document, status=status)


def _bin(row):
    """Move `row` to the recycle bin the way DeleteService marks it."""
    type(row).all_objects.filter(pk=row.pk).update(active=False, soft_deleted_at=timezone.now())


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _document(collection, content, name="notes.txt", file_type="txt"):
    return DocumentMetadata.objects.create(
        source_collection=collection,
        document_content=content,
        file_name=name,
        file_type=file_type,
        file_size=8,
    )


def _edit(document, data=NEW_TEXT, scope=DocumentContentScope.THIS_COLLECTION, expected_hash=None):
    return DocumentManagementService.update_document_content(
        document.document_id,
        org_id=document.source_collection.org_id,
        data=data,
        scope=scope,
        expected_hash=expected_hash or document.document_content.content_hash,
        user=None,
    )


@pytest.fixture
def content(default_org):
    return stored_document_content(OLD_TEXT, org_id=default_org.id)


@pytest.fixture
def document(source_collection, content):
    return _document(source_collection, content)


@pytest.fixture
def copy(empty_collection, content):
    return _document(empty_collection, content)


@pytest.mark.django_db
class TestScope:
    def test_this_collection_gives_the_document_its_own_content(
        self, document, copy, content, knowledge_bucket, django_capture_on_commit_callbacks
    ):
        with django_capture_on_commit_callbacks(execute=True):
            edited = _edit(document)

        copy.refresh_from_db()
        assert edited.document_content_id != content.pk
        assert edited.document_content.content_hash == _sha256(NEW_TEXT)
        assert knowledge_bucket.files[edited.document_content.object_key] == NEW_TEXT
        assert copy.document_content_id == content.pk
        assert knowledge_bucket.files[content.object_key] == OLD_TEXT

    def test_this_collection_without_copies_edits_in_place(
        self, document, content, knowledge_bucket, django_capture_on_commit_callbacks
    ):
        old_key = content.object_key

        with django_capture_on_commit_callbacks(execute=True):
            edited = _edit(document)

        assert edited.document_content_id == content.pk
        assert edited.document_content.object_key != old_key
        assert old_key not in knowledge_bucket.files
        assert DocumentContent.objects.count() == 1

    def test_all_collections_changes_every_copy_and_outdates_their_rags(
        self, document, copy, content, naive_rag, knowledge_bucket,
        django_capture_on_commit_callbacks,
    ):
        copy_config = _config(naive_rag, copy, NAIVE_STATUS.COMPLETED)
        old_key = content.object_key

        with django_capture_on_commit_callbacks(execute=True):
            _edit(document, scope=DocumentContentScope.ALL_COLLECTIONS)

        copy.refresh_from_db()
        copy_config.refresh_from_db()
        assert copy.document_content_id == content.pk
        assert knowledge_bucket.files[copy.document_content.object_key] == NEW_TEXT
        assert old_key not in knowledge_bucket.files
        assert copy_config.status == NAIVE_STATUS.OUTDATED

    def test_this_collection_leaves_the_copy_rags_alone(self, document, copy, naive_rag):
        copy_config = _config(naive_rag, copy, NAIVE_STATUS.COMPLETED)

        _edit(document)

        copy_config.refresh_from_db()
        assert copy_config.status == NAIVE_STATUS.COMPLETED


@pytest.mark.django_db
class TestChanges:
    def test_identical_text_changes_nothing(self, document, content, naive_rag, knowledge_bucket):
        config = _config(naive_rag, document, NAIVE_STATUS.COMPLETED)

        edited = _edit(document, data=OLD_TEXT)

        config.refresh_from_db()
        assert edited.document_content.object_key == content.object_key
        assert config.status == NAIVE_STATUS.COMPLETED
        assert len(knowledge_bucket.files) == 1

    def test_edited_document_outdates_its_rag(self, document, naive_rag):
        config = _config(naive_rag, document, NAIVE_STATUS.COMPLETED)

        _edit(document)

        config.refresh_from_db()
        assert config.status == NAIVE_STATUS.OUTDATED

    def test_file_size_is_updated(self, document):
        edited = _edit(document, data=b"a longer new text")

        assert edited.file_size == len(b"a longer new text")

    def test_failure_after_the_write_leaves_no_new_file(
        self, document, content, knowledge_bucket, monkeypatch
    ):
        def fail(document_ids):
            raise RuntimeError("database went away")

        monkeypatch.setattr(NaiveRagService, "mark_documents_content_changed", staticmethod(fail))

        with pytest.raises(RuntimeError):
            _edit(document)

        document.refresh_from_db()
        assert list(knowledge_bucket.files) == [content.object_key]
        assert document.document_content_id == content.pk


    @pytest.mark.django_db(transaction=True)
    def test_failed_commit_leaves_no_new_file(
        self, document, content, knowledge_bucket, monkeypatch
    ):
        """The commit is the last step that can fail after the new file is written."""

        def fail_commit():
            raise DatabaseError("connection lost at commit")

        monkeypatch.setattr(connection, "commit", fail_commit)
        with pytest.raises(DatabaseError):
            _edit(document)
        monkeypatch.undo()

        document.refresh_from_db()
        assert list(knowledge_bucket.files) == [content.object_key]
        assert document.document_content.content_hash == _sha256(OLD_TEXT)

@pytest.mark.django_db
class TestRefusals:
    def test_stale_expected_hash_is_refused(self, document, content, knowledge_bucket):
        with pytest.raises(ContentHashConflictError):
            _edit(document, expected_hash=_sha256(b"what the editor opened"))

        assert list(knowledge_bucket.files) == [content.object_key]

    def test_indexing_copy_refuses_all_collections(self, document, copy, naive_rag):
        _config(naive_rag, copy, NAIVE_STATUS.PROCESSING)

        with pytest.raises(DocumentIndexingInProgressException) as raised:
            _edit(document, scope=DocumentContentScope.ALL_COLLECTIONS)

        assert naive_rag.base_rag_type.source_collection.collection_name in str(raised.value.detail)

    def test_indexing_copy_does_not_block_this_collection(self, document, copy, naive_rag):
        _config(naive_rag, copy, NAIVE_STATUS.PROCESSING)

        edited = _edit(document)

        assert edited.document_content.content_hash == _sha256(NEW_TEXT)

    def test_indexing_document_is_refused(self, document, naive_rag):
        _config(naive_rag, document, NAIVE_STATUS.PROCESSING)

        with pytest.raises(DocumentIndexingInProgressException):
            _edit(document)

    def test_not_editable_type_is_refused(self, source_collection, content):
        pdf = _document(source_collection, content, name="report.pdf", file_type="pdf")

        with pytest.raises(DocumentNotEditableException):
            _edit(pdf)

    def test_invalid_json_is_refused(self, source_collection, content):
        json_document = _document(source_collection, content, name="data.json", file_type="json")

        with pytest.raises(DocumentNotEditableException):
            _edit(json_document, data=b"{not json")

    def test_json_with_a_byte_order_mark_is_saved(self, source_collection, content):
        json_document = _document(source_collection, content, name="data.json", file_type="json")

        edited = _edit(json_document, data=b'\xef\xbb\xbf{"a": 1}')

        assert edited.document_content.content_hash == _sha256(b'\xef\xbb\xbf{"a": 1}')

    def test_text_that_is_not_utf8_is_refused(self, document):
        with pytest.raises(DocumentNotEditableException):
            _edit(document, data=b"\xc3\x28")

    def test_text_over_the_upload_limit_is_refused(self, document, settings):
        settings.MAX_UPLOAD_FILE_SIZE = 4

        with pytest.raises(FileSizeExceededException):
            _edit(document)

    def test_missing_file_is_refused(self, document, content, knowledge_bucket):
        knowledge_bucket.files.pop(content.object_key)

        with pytest.raises(DocumentContentMissingException):
            _edit(document)

    def test_document_of_another_org_is_not_found(self, document):
        other_org = Organization.objects.create(name="Other Org")

        with pytest.raises(DocumentNotFoundException):
            DocumentManagementService.update_document_content(
                document.document_id,
                org_id=other_org.id,
                data=NEW_TEXT,
                scope=DocumentContentScope.THIS_COLLECTION,
                expected_hash=document.document_content.content_hash,
                user=None,
            )


@pytest.mark.django_db
class TestGraphAndRepeatedEdits:
    def test_edited_document_outdates_the_graph_that_indexed_it(
        self, document, source_collection, test_embedding_config, llm_config
    ):
        link = _graph_link(
            source_collection, document, GraphRagDocument.Status.COMPLETED,
            test_embedding_config, llm_config,
        )

        _edit(document)

        link.refresh_from_db()
        link.graph_rag.refresh_from_db()
        assert link.status == GraphRagDocument.Status.OUTDATED
        assert link.graph_rag.rag_status == GraphRag.GraphRagStatus.OUTDATED

    def test_document_queued_in_a_graph_run_is_refused(
        self, document, source_collection, test_embedding_config, llm_config
    ):
        link = _graph_link(
            source_collection, document, GraphRagDocument.Status.NEW,
            test_embedding_config, llm_config,
        )
        link.graph_rag.indexing_document_config_ids = [link.graph_rag_document_id]
        link.graph_rag.save(update_fields=["indexing_document_config_ids"])

        with pytest.raises(DocumentIndexingInProgressException):
            _edit(document)

    def test_second_edit_from_the_same_opened_version_is_refused(self, document, copy, content):
        """The same steps as two users saving at once, one after the other: the second must not win."""
        opened_hash = content.content_hash
        _edit(document, data=b"first edit", expected_hash=opened_hash)

        with pytest.raises(ContentHashConflictError):
            _edit(document, data=b"second edit", expected_hash=opened_hash)

    def test_document_text_comes_with_the_hash_of_that_text(self, document):
        loaded, text = DocumentManagementService.get_document_text(
            document.document_id, org_id=document.source_collection.org_id
        )

        assert text == OLD_TEXT.decode()
        assert loaded.document_content.content_hash == _sha256(OLD_TEXT)

    def test_document_text_of_a_file_that_is_not_utf8_is_refused(self, source_collection, default_org):
        latin = _document(source_collection, stored_document_content(b"\xe9t\xe9", org_id=default_org.id))

        with pytest.raises(DocumentNotEditableException):
            DocumentManagementService.get_document_text(latin.document_id, org_id=default_org.id)


    def test_document_text_leaves_out_a_byte_order_mark(self, source_collection, default_org):
        marked = _document(
            source_collection,
            stored_document_content(b'\xef\xbb\xbf{"a": 1}', org_id=default_org.id),
            name="data.json",
            file_type="json",
        )

        _loaded, text = DocumentManagementService.get_document_text(
            marked.document_id, org_id=default_org.id
        )

        assert text == '{"a": 1}'



@pytest.mark.django_db
class TestRecycleBin:
    def test_everywhere_leaves_a_binned_copy_with_the_file_it_was_binned_with(
        self, document, copy, content, default_org, naive_rag, knowledge_bucket,
        django_capture_on_commit_callbacks,
    ):
        binned_collection = SourceCollection.objects.create(
            collection_name="binned-copies", org=default_org
        )
        binned_copy = _document(binned_collection, content)
        binned_config = _config(naive_rag, binned_copy, NAIVE_STATUS.COMPLETED)
        _bin(binned_copy)

        with django_capture_on_commit_callbacks(execute=True):
            edited = _edit(document, scope=DocumentContentScope.ALL_COLLECTIONS)

        copy.refresh_from_db()
        binned_copy.refresh_from_db()
        binned_config.refresh_from_db()
        assert copy.document_content_id == edited.document_content_id != content.pk
        assert binned_copy.document_content_id == content.pk
        assert binned_config.status == NAIVE_STATUS.COMPLETED
        DocumentMetadata.all_objects.filter(pk=binned_copy.pk).update(
            active=True, soft_deleted_at=None
        )
        assert stored_document_bytes(binned_copy) == OLD_TEXT

    def test_copy_in_a_binned_collection_keeps_its_file(
        self, document, copy, content, empty_collection, knowledge_bucket
    ):
        _bin(empty_collection)

        edited = _edit(document)

        copy.refresh_from_db()
        assert edited.document_content_id != content.pk
        assert copy.document_content_id == content.pk
        assert knowledge_bucket.files[content.object_key] == OLD_TEXT

@pytest.mark.django_db
class TestIndexingLock:
    def test_edit_locks_the_rags_that_index_the_document(
        self, document, naive_rag, source_collection, test_embedding_config, llm_config
    ):
        """knowledge_new claims a run's documents under these row locks."""
        _config(naive_rag, document, NAIVE_STATUS.COMPLETED)
        _graph_link(
            source_collection, document, GraphRagDocument.Status.COMPLETED,
            test_embedding_config, llm_config,
        )

        with CaptureQueriesContext(connection) as queries:
            _edit(document)

        locks = [query["sql"] for query in queries.captured_queries if "FOR UPDATE" in query["sql"]]
        assert any(f'FROM "{NaiveRag._meta.db_table}"' in sql for sql in locks)
        assert any(f'FROM "{GraphRag._meta.db_table}"' in sql for sql in locks)
