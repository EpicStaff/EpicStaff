"""
Integration tests for DocumentManagementService focusing on RAG status sync
after document deletion. Real DB, no mocking.
"""

import pytest

from tables.models.knowledge_models import (
    SourceCollection,
    DocumentContent,
    DocumentMetadata,
    BaseRagType,
    NaiveRag,
    NaiveRagDocumentConfig,
    GraphRag,
    GraphRagDocument,
)
from tables.services.knowledge_services.document_management_service import (
    DocumentManagementService,
)
from tables.services.knowledge_services.graph_rag_service import GraphRagService
from tables.services.knowledge_services.naive_rag_service import NaiveRagService

pytestmark = pytest.mark.django_db

NS = NaiveRagDocumentConfig.NaiveRagDocumentStatus
GS = GraphRagDocument.Status


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_collection(suffix=""):
    """Each test gets an isolated collection to avoid cross-test conflicts."""
    return SourceCollection.objects.create(
        collection_name=f"dm_coll{suffix}", user_id=f"dm_user{suffix}"
    )


def _make_doc(collection, suffix=""):
    content = DocumentContent.objects.create(content=b"dm doc content")
    return DocumentMetadata.objects.create(
        source_collection=collection,
        document_content=content,
        file_name=f"dm_doc{suffix}.pdf",
        file_type="pdf",
        file_size=512,
    )


def _make_naive_rag(collection, embedding_config):
    """
    Creates a NaiveRag. Note: the naive_rag_signals post_save will auto-initialize
    configs for any documents already in the collection at creation time.
    """
    base = BaseRagType.objects.create(
        source_collection=collection, rag_type=BaseRagType.RagType.NAIVE
    )
    return NaiveRag.objects.create(
        base_rag_type=base,
        embedder=embedding_config,
        rag_status=NaiveRag.NaiveRagStatus.NEW,
    )


# ---------------------------------------------------------------------------
# 1. delete_document — single document syncs both RAG types
# ---------------------------------------------------------------------------


class TestDeleteDocumentSync:
    def test_deleting_doc_with_completed_naive_config_recomputes_to_new(
        self, test_embedding_config
    ):
        """Deleting the only doc (COMPLETED naive config) → NaiveRag becomes NEW."""
        collection = _make_collection("_dn1")
        # Create doc FIRST, then naive_rag — the signal auto-creates a config.
        doc = _make_doc(collection, "_dn1")
        rag = _make_naive_rag(collection, test_embedding_config)

        # The signal auto-created a config with NEW status — flip it to COMPLETED.
        config = NaiveRagDocumentConfig.objects.get(naive_rag=rag, document=doc)
        config.status = NS.COMPLETED
        config.save(update_fields=["status"])
        rag.rag_status = NaiveRag.NaiveRagStatus.COMPLETED
        rag.save(update_fields=["rag_status"])

        DocumentManagementService.delete_document(document_id=doc.document_id)

        rag.refresh_from_db()
        assert rag.rag_status == NaiveRag.NaiveRagStatus.NEW

    def test_deleting_one_of_two_completed_graph_docs_outdates_graph_rag(
        self, test_embedding_config, llm_config
    ):
        """Deleting one of two COMPLETED GraphRag documents → GraphRag becomes OUTDATED."""
        collection = _make_collection("_dg1")
        # Create both docs BEFORE GraphRag so they get auto-linked.
        doc_a = _make_doc(collection, "_dg1a")
        doc_b = _make_doc(collection, "_dg1b")
        rag = GraphRagService.create_or_update_graph_rag(
            collection_id=collection.collection_id,
            embedder_id=test_embedding_config.pk,
            llm_id=llm_config.pk,
        )
        rag.graph_rag_documents.update(status=GS.COMPLETED)
        rag.rag_status = GraphRag.GraphRagStatus.COMPLETED
        rag.save(update_fields=["rag_status"])

        # Delete only doc_a; doc_b remains and is flipped OUTDATED by sync.
        DocumentManagementService.delete_document(document_id=doc_a.document_id)

        rag.refresh_from_db()
        assert rag.rag_status == GraphRag.GraphRagStatus.OUTDATED

    def test_deleting_doc_with_new_graph_rag_link_does_not_outdate(
        self, test_embedding_config, llm_config
    ):
        """Deleting a NEW (unindexed) GraphRag document should not outdate the rag."""
        collection = _make_collection("_dg_new")
        doc = _make_doc(collection, "_dg_new")
        rag = GraphRagService.create_or_update_graph_rag(
            collection_id=collection.collection_id,
            embedder_id=test_embedding_config.pk,
            llm_id=llm_config.pk,
        )
        # doc is linked as NEW (default)

        DocumentManagementService.delete_document(document_id=doc.document_id)

        rag.refresh_from_db()
        assert rag.rag_status != GraphRag.GraphRagStatus.OUTDATED

    def test_deleting_doc_syncs_both_naive_and_graph_rag(
        self, test_embedding_config, llm_config
    ):
        """
        A document in a collection with both a NaiveRag and a GraphRag.
        When the only NaiveRag doc is deleted → NaiveRag→NEW.
        When one of two GraphRag docs is deleted → GraphRag→OUTDATED.
        """
        collection = _make_collection("_dboth")
        # Create docs FIRST so both RAG types auto-link them.
        doc = _make_doc(collection, "_dboth_main")
        doc_extra = _make_doc(collection, "_dboth_extra")  # extra for graph_rag

        naive_rag = _make_naive_rag(collection, test_embedding_config)
        # Signal auto-created configs for both docs — flip only doc's config to COMPLETED.
        naive_config = NaiveRagDocumentConfig.objects.get(naive_rag=naive_rag, document=doc)
        naive_config.status = NS.COMPLETED
        naive_config.save(update_fields=["status"])
        naive_rag.rag_status = NaiveRag.NaiveRagStatus.COMPLETED
        naive_rag.save(update_fields=["rag_status"])

        graph_rag = GraphRagService.create_or_update_graph_rag(
            collection_id=collection.collection_id,
            embedder_id=test_embedding_config.pk,
            llm_id=llm_config.pk,
        )
        # Both doc and doc_extra are linked; mark both COMPLETED.
        graph_rag.graph_rag_documents.update(status=GS.COMPLETED)
        graph_rag.rag_status = GraphRag.GraphRagStatus.COMPLETED
        graph_rag.save(update_fields=["rag_status"])

        # Delete only `doc`; doc_extra remains for graph_rag.
        DocumentManagementService.delete_document(document_id=doc.document_id)

        naive_rag.refresh_from_db()
        graph_rag.refresh_from_db()
        # naive_rag: doc was the only COMPLETED config → removed → NEW
        assert naive_rag.rag_status == NaiveRag.NaiveRagStatus.NEW
        # graph_rag: doc was COMPLETED, doc_extra remains → OUTDATED
        assert graph_rag.rag_status == GraphRag.GraphRagStatus.OUTDATED


# ---------------------------------------------------------------------------
# 2. delete_documents_batch
# ---------------------------------------------------------------------------


class TestDeleteDocumentsBatchSync:
    def test_batch_delete_recomputes_both_rag_types(
        self, test_embedding_config, llm_config
    ):
        """Batch delete spanning both a NaiveRag and a GraphRag: both recompute."""
        collection = _make_collection("_batch")
        doc_naive = _make_doc(collection, "_batch_naive")
        # doc_graph_keep remains in the collection after batch delete → graph_rag OUTDATED.
        doc_graph_keep = _make_doc(collection, "_batch_graph_keep")
        doc_graph_del = _make_doc(collection, "_batch_graph_del")

        naive_rag = _make_naive_rag(collection, test_embedding_config)
        naive_config = NaiveRagDocumentConfig.objects.get(
            naive_rag=naive_rag, document=doc_naive
        )
        naive_config.status = NS.COMPLETED
        naive_config.save(update_fields=["status"])
        naive_rag.rag_status = NaiveRag.NaiveRagStatus.COMPLETED
        naive_rag.save(update_fields=["rag_status"])

        graph_rag = GraphRagService.create_or_update_graph_rag(
            collection_id=collection.collection_id,
            embedder_id=test_embedding_config.pk,
            llm_id=llm_config.pk,
        )
        # Mark all linked graph_rag docs as COMPLETED.
        graph_rag.graph_rag_documents.update(status=GS.COMPLETED)
        graph_rag.rag_status = GraphRag.GraphRagStatus.COMPLETED
        graph_rag.save(update_fields=["rag_status"])

        # Batch-delete doc_naive and doc_graph_del; doc_graph_keep remains.
        DocumentManagementService.delete_documents_batch(
            document_ids=[doc_naive.document_id, doc_graph_del.document_id]
        )

        naive_rag.refresh_from_db()
        graph_rag.refresh_from_db()
        # naive_rag: doc_naive was the only COMPLETED config → removed → back to NEW
        assert naive_rag.rag_status == NaiveRag.NaiveRagStatus.NEW
        # graph_rag: doc_graph_del was COMPLETED, doc_graph_keep remains → OUTDATED
        assert graph_rag.rag_status == GraphRag.GraphRagStatus.OUTDATED

    def test_batch_delete_one_of_two_completed_graph_docs_outdates_rag(
        self, test_embedding_config, llm_config
    ):
        """GraphRag with two COMPLETED docs: delete one → OUTDATED, survivor flipped too."""
        collection = _make_collection("_bg")
        doc_a = _make_doc(collection, "_bg_a")
        doc_b = _make_doc(collection, "_bg_b")

        graph_rag = GraphRagService.create_or_update_graph_rag(
            collection_id=collection.collection_id,
            embedder_id=test_embedding_config.pk,
            llm_id=llm_config.pk,
        )
        graph_rag.graph_rag_documents.update(status=GS.COMPLETED)
        graph_rag.rag_status = GraphRag.GraphRagStatus.COMPLETED
        graph_rag.save(update_fields=["rag_status"])

        # Delete doc_a only
        DocumentManagementService.delete_documents_batch(
            document_ids=[doc_a.document_id]
        )

        graph_rag.refresh_from_db()
        assert graph_rag.rag_status == GraphRag.GraphRagStatus.OUTDATED
        # doc_b (surviving COMPLETED doc) should be flipped OUTDATED by sync
        surviving_doc_b = graph_rag.graph_rag_documents.filter(
            document_id=doc_b.document_id
        ).first()
        assert surviving_doc_b is not None
        assert surviving_doc_b.status == GS.OUTDATED

    def test_empty_batch_returns_zero_deleted(self):
        result = DocumentManagementService.delete_documents_batch(document_ids=[])
        assert result["deleted_count"] == 0
