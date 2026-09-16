"""
Integration tests for GraphRagService and GraphRag.update_rag_status.
Real DB, no mocking — these services touch neither Redis nor LLM APIs.
"""

import pytest

from tables.models.knowledge_models import (
    SourceCollection,
    DocumentContent,
    DocumentMetadata,
    BaseRagType,
    GraphRag,
    GraphRagDocument,
    GraphRagIndexConfig,
)
from tables.services.knowledge_services.graph_rag_service import GraphRagService
from tables.exceptions import (
    InvalidGraphRagParametersException,
    GraphRagDocumentNotFoundException,
)

from .conftest import make_graph_rag_document

pytestmark = pytest.mark.django_db

S = GraphRagDocument.Status


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_doc(collection, suffix=""):
    content = DocumentContent.objects.create(content=b"graph doc")
    return DocumentMetadata.objects.create(
        source_collection=collection,
        document_content=content,
        file_name=f"graph_doc{suffix}.pdf",
        file_type="pdf",
        file_size=256,
    )


# ---------------------------------------------------------------------------
# 1. GraphRag.update_rag_status matrix
# ---------------------------------------------------------------------------


class TestGraphRagUpdateStatus:
    def _fresh_rag(self, source_collection, test_embedding_config, llm_config):
        """Empty GraphRag (no linked documents)."""
        from tables.constants.knowledge_constants import (
            GRAPHRAG_DEFAULT_INPUT_FILE_TYPE,
            GRAPHRAG_DEFAULT_CHUNK_SIZE,
            GRAPHRAG_DEFAULT_CHUNK_OVERLAP,
            GRAPHRAG_DEFAULT_CHUNK_STRATEGY,
            GRAPHRAG_DEFAULT_ENTITY_TYPES,
            GRAPHRAG_DEFAULT_MAX_GLEANINGS,
            GRAPHRAG_DEFAULT_MAX_CLUSTER_SIZE,
        )

        index_config = GraphRagIndexConfig.objects.create(
            file_type=GRAPHRAG_DEFAULT_INPUT_FILE_TYPE,
            chunk_size=GRAPHRAG_DEFAULT_CHUNK_SIZE,
            chunk_overlap=GRAPHRAG_DEFAULT_CHUNK_OVERLAP,
            chunk_strategy=GRAPHRAG_DEFAULT_CHUNK_STRATEGY,
            entity_types=GRAPHRAG_DEFAULT_ENTITY_TYPES.copy(),
            max_gleanings=GRAPHRAG_DEFAULT_MAX_GLEANINGS,
            max_cluster_size=GRAPHRAG_DEFAULT_MAX_CLUSTER_SIZE,
        )
        base = BaseRagType.objects.create(
            source_collection=source_collection, rag_type=BaseRagType.RagType.GRAPH
        )
        return GraphRag.objects.create(
            base_rag_type=base,
            embedder=test_embedding_config,
            llm=llm_config,
            index_config=index_config,
        )

    def test_all_completed_gives_completed(
        self, source_collection, test_embedding_config, llm_config
    ):
        rag = self._fresh_rag(source_collection, test_embedding_config, llm_config)
        doc = _make_doc(source_collection, "_gc")
        make_graph_rag_document(rag, doc, S.COMPLETED)
        rag.update_rag_status()
        assert rag.rag_status == GraphRag.GraphRagStatus.COMPLETED

    def test_all_failed_gives_failed(
        self, source_collection, test_embedding_config, llm_config
    ):
        rag = self._fresh_rag(source_collection, test_embedding_config, llm_config)
        doc = _make_doc(source_collection, "_gf")
        make_graph_rag_document(rag, doc, S.FAILED)
        rag.update_rag_status()
        assert rag.rag_status == GraphRag.GraphRagStatus.FAILED

    def test_outdated_gives_outdated(
        self, source_collection, test_embedding_config, llm_config
    ):
        rag = self._fresh_rag(source_collection, test_embedding_config, llm_config)
        doc = _make_doc(source_collection, "_go")
        make_graph_rag_document(rag, doc, S.OUTDATED)
        rag.update_rag_status()
        assert rag.rag_status == GraphRag.GraphRagStatus.OUTDATED

    def test_completed_and_failed_gives_completed_not_partial(
        self, source_collection, test_embedding_config, llm_config
    ):
        """GraphRag has no PARTIAL status; COMPLETED+FAILED → COMPLETED."""
        rag = self._fresh_rag(source_collection, test_embedding_config, llm_config)
        doc_c = _make_doc(source_collection, "_gcf_c")
        doc_f = _make_doc(source_collection, "_gcf_f")
        make_graph_rag_document(rag, doc_c, S.COMPLETED)
        make_graph_rag_document(rag, doc_f, S.FAILED)
        rag.update_rag_status()
        assert rag.rag_status == GraphRag.GraphRagStatus.COMPLETED

    def test_no_documents_gives_new(
        self, source_collection, test_embedding_config, llm_config
    ):
        rag = self._fresh_rag(source_collection, test_embedding_config, llm_config)
        rag.rag_status = GraphRag.GraphRagStatus.COMPLETED
        rag.update_rag_status()
        assert rag.rag_status == GraphRag.GraphRagStatus.NEW

    def test_indexing_ids_nonempty_gives_processing(
        self, source_collection, test_embedding_config, llm_config
    ):
        rag = self._fresh_rag(source_collection, test_embedding_config, llm_config)
        doc = _make_doc(source_collection, "_gp")
        link = make_graph_rag_document(rag, doc, S.NEW)
        rag.indexing_document_config_ids = [link.graph_rag_document_id]
        rag.save(update_fields=["indexing_document_config_ids"])
        rag.update_rag_status()
        assert rag.rag_status == GraphRag.GraphRagStatus.PROCESSING

    def test_outdated_reasons_nonempty_forces_outdated(
        self, source_collection, test_embedding_config, llm_config
    ):
        rag = self._fresh_rag(source_collection, test_embedding_config, llm_config)
        doc = _make_doc(source_collection, "_gr_out")
        make_graph_rag_document(rag, doc, S.COMPLETED)
        rag.add_outdated_reason("index_config_changed", "Config changed.")
        rag.update_rag_status()
        assert rag.rag_status == GraphRag.GraphRagStatus.OUTDATED

    def test_partial_is_not_a_valid_graph_rag_status(self):
        """GraphRag.GraphRagStatus does not contain PARTIAL."""
        assert "partial" not in GraphRag.GraphRagStatus.values


# ---------------------------------------------------------------------------
# 2. create_or_update_graph_rag
# ---------------------------------------------------------------------------


class TestCreateOrUpdateGraphRag:
    def test_create_makes_documents_and_index_config(
        self, source_collection, multiple_documents, test_embedding_config, llm_config
    ):
        # multiple_documents fixture creates 3 docs in source_collection
        rag = GraphRagService.create_or_update_graph_rag(
            collection_id=source_collection.collection_id,
            embedder_id=test_embedding_config.pk,
            llm_id=llm_config.pk,
        )
        assert rag.graph_rag_id is not None
        assert rag.index_config is not None
        linked_count = rag.graph_rag_documents.count()
        assert linked_count == len(multiple_documents)
        statuses = set(rag.graph_rag_documents.values_list("status", flat=True))
        assert statuses == {S.NEW}

    def test_update_with_different_provider_outdates_rag_and_completed_docs(
        self,
        source_collection,
        multiple_documents,
        test_embedding_config,
        other_provider_embedding_config,
        llm_config,
    ):
        rag = GraphRagService.create_or_update_graph_rag(
            collection_id=source_collection.collection_id,
            embedder_id=test_embedding_config.pk,
            llm_id=llm_config.pk,
        )
        # Mark all docs COMPLETED
        rag.graph_rag_documents.update(status=S.COMPLETED)

        # Update with a different-provider embedder — this previously failed if _update_rag
        # had a missing argument. Assert it does NOT raise.
        updated_rag = GraphRagService.create_or_update_graph_rag(
            collection_id=source_collection.collection_id,
            embedder_id=other_provider_embedding_config.pk,
            llm_id=llm_config.pk,
        )

        updated_rag.refresh_from_db()
        assert updated_rag.rag_status == GraphRag.GraphRagStatus.OUTDATED
        assert "changed_embedding_config" in updated_rag.outdated_reasons

        outdated_count = updated_rag.graph_rag_documents.filter(status=S.OUTDATED).count()
        assert outdated_count == len(multiple_documents)


# ---------------------------------------------------------------------------
# 3. remove_documents_from_graph_rag
# ---------------------------------------------------------------------------


class TestRemoveDocumentsFromGraphRag:
    def test_remove_completed_doc_outdates_remaining_and_returns_document_ids(
        self, source_collection, test_embedding_config, llm_config
    ):
        # Create docs BEFORE creating the GraphRag so they are auto-linked on creation.
        doc_a = _make_doc(source_collection, "_ra")
        doc_b = _make_doc(source_collection, "_rb")
        rag = GraphRagService.create_or_update_graph_rag(
            collection_id=source_collection.collection_id,
            embedder_id=test_embedding_config.pk,
            llm_id=llm_config.pk,
        )
        rag.graph_rag_documents.update(status=S.COMPLETED)

        result = GraphRagService.remove_documents_from_graph_rag(
            graph_rag_id=rag.graph_rag_id,
            document_ids=[doc_a.document_id],
        )

        rag.refresh_from_db()
        assert rag.rag_status == GraphRag.GraphRagStatus.OUTDATED
        assert isinstance(result["removed_document_ids"], list)
        assert doc_a.document_id in result["removed_document_ids"]

        remaining_statuses = set(
            rag.graph_rag_documents.values_list("status", flat=True)
        )
        assert S.OUTDATED in remaining_statuses

    def test_remove_all_indexed_docs_gives_new_status(
        self, source_collection, test_embedding_config, llm_config
    ):
        # Create doc BEFORE creating the GraphRag so it is auto-linked.
        doc = _make_doc(source_collection, "_rall")
        rag = GraphRagService.create_or_update_graph_rag(
            collection_id=source_collection.collection_id,
            embedder_id=test_embedding_config.pk,
            llm_id=llm_config.pk,
        )
        # status stays NEW (default)

        GraphRagService.remove_documents_from_graph_rag(
            graph_rag_id=rag.graph_rag_id,
            document_ids=[doc.document_id],
        )

        rag.refresh_from_db()
        assert rag.rag_status == GraphRag.GraphRagStatus.NEW

    def test_removing_new_doc_does_not_outdate(
        self, source_collection, test_embedding_config, llm_config
    ):
        """Removing a NEW (unindexed) doc should not cause OUTDATED."""
        # Create doc BEFORE creating the GraphRag so it is auto-linked.
        doc = _make_doc(source_collection, "_rnew")
        rag = GraphRagService.create_or_update_graph_rag(
            collection_id=source_collection.collection_id,
            embedder_id=test_embedding_config.pk,
            llm_id=llm_config.pk,
        )
        # leave doc status as NEW (default)

        GraphRagService.remove_documents_from_graph_rag(
            graph_rag_id=rag.graph_rag_id,
            document_ids=[doc.document_id],
        )

        rag.refresh_from_db()
        assert rag.rag_status != GraphRag.GraphRagStatus.OUTDATED

    def test_not_linked_document_id_raises(
        self, source_collection, test_embedding_config, llm_config
    ):
        rag = GraphRagService.create_or_update_graph_rag(
            collection_id=source_collection.collection_id,
            embedder_id=test_embedding_config.pk,
            llm_id=llm_config.pk,
        )
        with pytest.raises(GraphRagDocumentNotFoundException):
            GraphRagService.remove_documents_from_graph_rag(
                graph_rag_id=rag.graph_rag_id,
                document_ids=[999999],
            )


# ---------------------------------------------------------------------------
# 4. delete_document (single)
# ---------------------------------------------------------------------------


class TestDeleteDocumentGraphRag:
    def test_removing_one_of_two_completed_docs_outdates_rag(
        self, source_collection, test_embedding_config, llm_config
    ):
        """Removing one COMPLETED doc when another COMPLETED doc remains → OUTDATED."""
        # Create both docs BEFORE graphrag so they are auto-linked.
        doc_a = _make_doc(source_collection, "_dd_ca")
        doc_b = _make_doc(source_collection, "_dd_cb")
        rag = GraphRagService.create_or_update_graph_rag(
            collection_id=source_collection.collection_id,
            embedder_id=test_embedding_config.pk,
            llm_id=llm_config.pk,
        )
        rag.graph_rag_documents.update(status=S.COMPLETED)
        rag.rag_status = GraphRag.GraphRagStatus.COMPLETED
        rag.save(update_fields=["rag_status"])

        # Remove only doc_a; doc_b remains.
        GraphRagService.delete_document(
            graph_rag_id=rag.graph_rag_id, document_id=doc_a.document_id
        )

        rag.refresh_from_db()
        assert rag.rag_status == GraphRag.GraphRagStatus.OUTDATED
        # Remaining doc_b should also be flipped to OUTDATED.
        remaining = rag.graph_rag_documents.get(document_id=doc_b.document_id)
        assert remaining.status == S.OUTDATED

    def test_removing_last_indexed_doc_gives_new(
        self, source_collection, test_embedding_config, llm_config
    ):
        """
        Removing the only COMPLETED doc with no remaining indexed docs.
        The sync marks remaining COMPLETED→OUTDATED (none), finds no outdated docs,
        and recomputes to NEW. This is correct: no content left to be stale.
        """
        # Create doc BEFORE graphrag so it is auto-linked.
        doc = _make_doc(source_collection, "_dd_last")
        rag = GraphRagService.create_or_update_graph_rag(
            collection_id=source_collection.collection_id,
            embedder_id=test_embedding_config.pk,
            llm_id=llm_config.pk,
        )
        rag.graph_rag_documents.update(status=S.COMPLETED)
        rag.rag_status = GraphRag.GraphRagStatus.COMPLETED
        rag.save(update_fields=["rag_status"])

        GraphRagService.delete_document(
            graph_rag_id=rag.graph_rag_id, document_id=doc.document_id
        )

        rag.refresh_from_db()
        # Only doc existed; after deletion no docs remain → status resets to NEW.
        assert rag.rag_status == GraphRag.GraphRagStatus.NEW

    def test_removing_last_new_doc_gives_new(
        self, source_collection, test_embedding_config, llm_config
    ):
        """Removing the only (NEW) doc from a graphrag leaves it NEW."""
        # Create doc BEFORE graphrag so it is auto-linked.
        doc = _make_doc(source_collection, "_dd_new_only")
        rag = GraphRagService.create_or_update_graph_rag(
            collection_id=source_collection.collection_id,
            embedder_id=test_embedding_config.pk,
            llm_id=llm_config.pk,
        )
        # doc is linked as NEW (default)

        GraphRagService.delete_document(
            graph_rag_id=rag.graph_rag_id, document_id=doc.document_id
        )

        rag.refresh_from_db()
        assert rag.rag_status == GraphRag.GraphRagStatus.NEW

    def test_not_linked_id_raises(
        self, source_collection, test_embedding_config, llm_config
    ):
        rag = GraphRagService.create_or_update_graph_rag(
            collection_id=source_collection.collection_id,
            embedder_id=test_embedding_config.pk,
            llm_id=llm_config.pk,
        )
        with pytest.raises(GraphRagDocumentNotFoundException):
            GraphRagService.delete_document(
                graph_rag_id=rag.graph_rag_id, document_id=999999
            )


# ---------------------------------------------------------------------------
# 5. update_index_config
# ---------------------------------------------------------------------------


class TestUpdateIndexConfig:
    def test_changing_chunk_size_outdates_completed_docs_and_rag(
        self, source_collection, test_embedding_config, llm_config
    ):
        # Create doc BEFORE graphrag so it is auto-linked.
        doc = _make_doc(source_collection, "_uic_c")
        rag = GraphRagService.create_or_update_graph_rag(
            collection_id=source_collection.collection_id,
            embedder_id=test_embedding_config.pk,
            llm_id=llm_config.pk,
        )
        rag.graph_rag_documents.filter(document_id=doc.document_id).update(
            status=S.COMPLETED
        )
        rag.rag_status = GraphRag.GraphRagStatus.COMPLETED
        rag.save(update_fields=["rag_status"])

        updated_rag = GraphRagService.update_index_config(
            graph_rag_id=rag.graph_rag_id,
            data={"chunk_size": 999},
        )

        updated_rag.refresh_from_db()
        assert updated_rag.rag_status == GraphRag.GraphRagStatus.OUTDATED
        assert "index_config_changed" in updated_rag.outdated_reasons
        outdated_docs = updated_rag.graph_rag_documents.filter(status=S.OUTDATED).count()
        assert outdated_docs >= 1

    def test_chunk_overlap_gte_chunk_size_raises(
        self, source_collection, test_embedding_config, llm_config
    ):
        rag = GraphRagService.create_or_update_graph_rag(
            collection_id=source_collection.collection_id,
            embedder_id=test_embedding_config.pk,
            llm_id=llm_config.pk,
        )
        with pytest.raises(InvalidGraphRagParametersException):
            GraphRagService.update_index_config(
                graph_rag_id=rag.graph_rag_id,
                data={"chunk_size": 100, "chunk_overlap": 100},
            )
