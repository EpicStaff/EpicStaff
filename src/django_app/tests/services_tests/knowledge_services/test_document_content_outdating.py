"""A document whose content changed outdates the RAGs that indexed it.

Naive RAGs index documents one by one, so only the changed document's configs go
outdated. A graph cannot drop one document's contribution, so every indexed document
of an affected graph goes outdated and the next run rebuilds the graph whole.
"""

import pytest

from tables.models.knowledge_models import (
    BaseRagType,
    DocumentMetadata,
    GraphRag,
    GraphRagDocument,
    NaiveRag,
    NaiveRagDocumentConfig,
    NaiveRagPreviewChunk,
)
from tables.services.knowledge_services.graph_rag_service import GraphRagService
from tables.services.knowledge_services.naive_rag_service import NaiveRagService
from tests.knowledge_content import stored_document_content
from tests.services_tests.knowledge_services.conftest import (
    make_graph_rag_document,
    make_naive_rag_config,
)

NAIVE_STATUS = NaiveRagDocumentConfig.NaiveRagDocumentStatus
GRAPH_STATUS = GraphRagDocument.Status
REASON = {"document_content_changed": "Document content was changed."}


def _document(collection, name):
    return DocumentMetadata.objects.create(
        source_collection=collection,
        document_content=stored_document_content(name.encode()),
        file_name=name,
        file_type="txt",
        file_size=len(name),
    )


def _preview_chunk(config, text="old text"):
    return NaiveRagPreviewChunk.objects.create(
        naive_rag_document_config=config, text=text, chunk_index=1
    )


def _graph_rag(collection, test_embedding_config, llm_config):
    base = BaseRagType.objects.create(
        source_collection=collection, rag_type=BaseRagType.RagType.GRAPH
    )
    return GraphRag.objects.create(
        base_rag_type=base,
        embedder=test_embedding_config,
        llm=llm_config,
        rag_status=GraphRag.GraphRagStatus.COMPLETED,
    )


@pytest.mark.django_db
class TestNaive:
    def test_completed_config_becomes_outdated_with_reason(self, naive_rag, source_collection):
        changed = _document(source_collection, "changed.txt")
        config = make_naive_rag_config(naive_rag, changed, NAIVE_STATUS.COMPLETED)

        NaiveRagService.mark_documents_content_changed([changed.document_id])

        config.refresh_from_db()
        naive_rag.refresh_from_db()
        assert config.status == NAIVE_STATUS.OUTDATED
        assert config.outdated_reasons == REASON
        assert naive_rag.rag_status == NaiveRag.NaiveRagStatus.OUTDATED
        assert naive_rag.outdated_reasons == REASON

    def test_new_and_failed_configs_keep_their_status(self, naive_rag, source_collection):
        never_indexed = _document(source_collection, "new.txt")
        failed = _document(source_collection, "failed.txt")
        new_config = make_naive_rag_config(naive_rag, never_indexed, NAIVE_STATUS.NEW)
        failed_config = make_naive_rag_config(naive_rag, failed, NAIVE_STATUS.FAILED)

        NaiveRagService.mark_documents_content_changed(
            [never_indexed.document_id, failed.document_id]
        )

        new_config.refresh_from_db()
        failed_config.refresh_from_db()
        assert new_config.status == NAIVE_STATUS.NEW
        assert failed_config.status == NAIVE_STATUS.FAILED
        assert new_config.outdated_reasons == {}

    def test_preview_chunks_of_the_document_are_deleted(self, naive_rag, source_collection):
        changed = _document(source_collection, "changed.txt")
        untouched = _document(source_collection, "untouched.txt")
        changed_config = make_naive_rag_config(naive_rag, changed, NAIVE_STATUS.NEW)
        untouched_config = make_naive_rag_config(naive_rag, untouched, NAIVE_STATUS.NEW)
        _preview_chunk(changed_config)
        _preview_chunk(untouched_config)

        NaiveRagService.mark_documents_content_changed([changed.document_id])

        assert not NaiveRagPreviewChunk.objects.filter(
            naive_rag_document_config=changed_config
        ).exists()
        assert NaiveRagPreviewChunk.objects.filter(
            naive_rag_document_config=untouched_config
        ).exists()

    def test_other_documents_keep_their_status(self, naive_rag, source_collection):
        changed = _document(source_collection, "changed.txt")
        other = _document(source_collection, "other.txt")
        make_naive_rag_config(naive_rag, changed, NAIVE_STATUS.COMPLETED)
        other_config = make_naive_rag_config(naive_rag, other, NAIVE_STATUS.COMPLETED)

        NaiveRagService.mark_documents_content_changed([changed.document_id])

        other_config.refresh_from_db()
        assert other_config.status == NAIVE_STATUS.COMPLETED


@pytest.mark.django_db
class TestGraph:
    def test_every_completed_document_becomes_outdated(
        self, source_collection, test_embedding_config, llm_config
    ):
        rag = _graph_rag(source_collection, test_embedding_config, llm_config)
        changed = _document(source_collection, "changed.txt")
        other = _document(source_collection, "other.txt")
        changed_link = make_graph_rag_document(rag, changed, GRAPH_STATUS.COMPLETED)
        other_link = make_graph_rag_document(rag, other, GRAPH_STATUS.COMPLETED)

        GraphRagService.mark_documents_content_changed([changed.document_id])

        changed_link.refresh_from_db()
        other_link.refresh_from_db()
        rag.refresh_from_db()
        assert changed_link.status == GRAPH_STATUS.OUTDATED
        assert other_link.status == GRAPH_STATUS.OUTDATED
        assert rag.rag_status == GraphRag.GraphRagStatus.OUTDATED
        assert rag.outdated_reasons == REASON

    def test_graph_where_the_document_was_never_indexed_is_untouched(
        self, source_collection, test_embedding_config, llm_config
    ):
        rag = _graph_rag(source_collection, test_embedding_config, llm_config)
        changed = _document(source_collection, "changed.txt")
        other = _document(source_collection, "other.txt")
        make_graph_rag_document(rag, changed, GRAPH_STATUS.NEW)
        other_link = make_graph_rag_document(rag, other, GRAPH_STATUS.COMPLETED)

        GraphRagService.mark_documents_content_changed([changed.document_id])

        other_link.refresh_from_db()
        rag.refresh_from_db()
        assert other_link.status == GRAPH_STATUS.COMPLETED
        assert rag.outdated_reasons == {}


@pytest.mark.django_db
class TestIndexingCollectionNames:
    def test_naive_document_queued_in_a_run_counts_as_indexing(
        self, naive_rag, source_collection
    ):
        queued = _document(source_collection, "queued.txt")
        config = make_naive_rag_config(naive_rag, queued, NAIVE_STATUS.NEW)
        naive_rag.indexing_document_config_ids = [config.naive_rag_document_id]
        naive_rag.save(update_fields=["indexing_document_config_ids"])

        names = NaiveRagService.indexing_collection_names([queued.document_id])

        assert names == {source_collection.collection_name}

    def test_naive_document_being_processed_counts_as_indexing(
        self, naive_rag, source_collection
    ):
        processing = _document(source_collection, "processing.txt")
        make_naive_rag_config(naive_rag, processing, NAIVE_STATUS.PROCESSING)

        names = NaiveRagService.indexing_collection_names([processing.document_id])

        assert names == {source_collection.collection_name}

    def test_graph_document_queued_in_a_run_counts_as_indexing(
        self, source_collection, test_embedding_config, llm_config
    ):
        rag = _graph_rag(source_collection, test_embedding_config, llm_config)
        queued = _document(source_collection, "queued.txt")
        link = make_graph_rag_document(rag, queued, GRAPH_STATUS.NEW)
        rag.indexing_document_config_ids = [link.graph_rag_document_id]
        rag.save(update_fields=["indexing_document_config_ids"])

        names = GraphRagService.indexing_collection_names([queued.document_id])

        assert names == {source_collection.collection_name}

    def test_idle_documents_are_not_indexing(
        self, naive_rag, source_collection, test_embedding_config, llm_config
    ):
        idle = _document(source_collection, "idle.txt")
        make_naive_rag_config(naive_rag, idle, NAIVE_STATUS.COMPLETED)
        rag = _graph_rag(source_collection, test_embedding_config, llm_config)
        make_graph_rag_document(rag, idle, GRAPH_STATUS.COMPLETED)

        assert NaiveRagService.indexing_collection_names([idle.document_id]) == set()
        assert GraphRagService.indexing_collection_names([idle.document_id]) == set()

    def test_only_the_given_documents_are_checked(self, naive_rag, source_collection):
        busy = _document(source_collection, "busy.txt")
        idle = _document(source_collection, "idle.txt")
        make_naive_rag_config(naive_rag, busy, NAIVE_STATUS.PROCESSING)

        assert NaiveRagService.indexing_collection_names([idle.document_id]) == set()
