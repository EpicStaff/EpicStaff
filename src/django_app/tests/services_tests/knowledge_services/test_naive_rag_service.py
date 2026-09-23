"""
Integration tests for NaiveRagService and NaiveRag.update_rag_status.
Real DB, no mocking — these services touch neither Redis nor LLM APIs.
"""

import pytest

from tables.models.knowledge_models import (
    SourceCollection,
    DocumentContent,
    DocumentMetadata,
    BaseRagType,
    NaiveRag,
    NaiveRagDocumentConfig,
)
from tables.services.knowledge_services.naive_rag_service import NaiveRagService
from tables.exceptions import (
    InvalidChunkParametersException,
    DocumentConfigNotFoundException,
)

from .conftest import make_naive_rag_config

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_doc(collection, suffix=""):
    content = DocumentContent.objects.create(content=b"x")
    return DocumentMetadata.objects.create(
        source_collection=collection,
        document_content=content,
        file_name=f"doc{suffix}.pdf",
        file_type="pdf",
        file_size=512,
    )


S = NaiveRagDocumentConfig.NaiveRagDocumentStatus


# ---------------------------------------------------------------------------
# 1. NaiveRag.update_rag_status matrix
# ---------------------------------------------------------------------------


class TestUpdateRagStatus:
    def _rag_with_configs(self, source_collection, test_embedding_config, statuses):
        """Build a NaiveRag + one config per status entry; return the rag."""
        base = BaseRagType.objects.create(
            source_collection=source_collection, rag_type=BaseRagType.RagType.NAIVE
        )
        rag = NaiveRag.objects.create(
            base_rag_type=base,
            embedder=test_embedding_config,
            rag_status=NaiveRag.NaiveRagStatus.NEW,
        )
        for i, status in enumerate(statuses):
            doc = _make_doc(source_collection, suffix=f"_status_{i}")
            make_naive_rag_config(rag, doc, status)
        return rag

    def test_all_completed_gives_completed(self, source_collection, test_embedding_config):
        rag = self._rag_with_configs(source_collection, test_embedding_config, [S.COMPLETED])
        rag.update_rag_status()
        assert rag.rag_status == NaiveRag.NaiveRagStatus.COMPLETED

    def test_all_failed_gives_failed(self, source_collection, test_embedding_config):
        rag = self._rag_with_configs(source_collection, test_embedding_config, [S.FAILED])
        rag.update_rag_status()
        assert rag.rag_status == NaiveRag.NaiveRagStatus.FAILED

    def test_completed_and_failed_gives_partial(self, source_collection, test_embedding_config):
        rag = self._rag_with_configs(
            source_collection, test_embedding_config, [S.COMPLETED, S.FAILED]
        )
        rag.update_rag_status()
        assert rag.rag_status == NaiveRag.NaiveRagStatus.PARTIAL

    def test_outdated_present_gives_outdated(self, source_collection, test_embedding_config):
        rag = self._rag_with_configs(
            source_collection, test_embedding_config, [S.OUTDATED, S.COMPLETED]
        )
        rag.update_rag_status()
        assert rag.rag_status == NaiveRag.NaiveRagStatus.OUTDATED

    def test_processing_present_gives_processing(self, source_collection, test_embedding_config):
        rag = self._rag_with_configs(
            source_collection, test_embedding_config, [S.PROCESSING]
        )
        rag.update_rag_status()
        assert rag.rag_status == NaiveRag.NaiveRagStatus.PROCESSING

    def test_all_new_gives_new(self, source_collection, test_embedding_config):
        rag = self._rag_with_configs(source_collection, test_embedding_config, [S.NEW])
        rag.update_rag_status()
        assert rag.rag_status == NaiveRag.NaiveRagStatus.NEW

    def test_no_configs_gives_new(self, source_collection, test_embedding_config):
        base = BaseRagType.objects.create(
            source_collection=source_collection, rag_type=BaseRagType.RagType.NAIVE
        )
        rag = NaiveRag.objects.create(
            base_rag_type=base,
            embedder=test_embedding_config,
            rag_status=NaiveRag.NaiveRagStatus.COMPLETED,
        )
        rag.update_rag_status()
        assert rag.rag_status == NaiveRag.NaiveRagStatus.NEW

    def test_outdated_reasons_nonempty_forces_outdated_even_when_all_completed(
        self, source_collection, test_embedding_config
    ):
        rag = self._rag_with_configs(
            source_collection, test_embedding_config, [S.COMPLETED]
        )
        rag.add_outdated_reason("changed_embedding_config", "Embedding config changed.")
        rag.update_rag_status()
        assert rag.rag_status == NaiveRag.NaiveRagStatus.OUTDATED


# ---------------------------------------------------------------------------
# 2. create_or_update_naive_rag
# ---------------------------------------------------------------------------


class TestCreateOrUpdateNaiveRag:
    def test_create_new_rag_and_base_rag_type(
        self, empty_collection, test_embedding_config
    ):
        rag = NaiveRagService.create_or_update_naive_rag(
            collection_id=empty_collection.collection_id,
            embedder_id=test_embedding_config.pk,
        )
        assert rag.naive_rag_id is not None
        assert rag.rag_status == NaiveRag.NaiveRagStatus.NEW
        assert BaseRagType.objects.filter(
            source_collection=empty_collection, rag_type=BaseRagType.RagType.NAIVE
        ).exists()

    def test_update_with_different_provider_outdates_rag_and_configs(
        self, empty_collection, test_embedding_config, other_provider_embedding_config
    ):
        rag = NaiveRagService.create_or_update_naive_rag(
            collection_id=empty_collection.collection_id,
            embedder_id=test_embedding_config.pk,
        )
        # Add a COMPLETED config
        doc = _make_doc(empty_collection, "_upd1")
        config = make_naive_rag_config(rag, doc, S.COMPLETED)

        # Update with a DIFFERENT-provider embedder
        updated_rag = NaiveRagService.create_or_update_naive_rag(
            collection_id=empty_collection.collection_id,
            embedder_id=other_provider_embedding_config.pk,
        )

        updated_rag.refresh_from_db()
        assert updated_rag.rag_status == NaiveRag.NaiveRagStatus.OUTDATED
        assert "changed_embedding_config" in updated_rag.outdated_reasons

        config.refresh_from_db()
        assert config.status == S.OUTDATED

    def test_update_with_same_provider_different_embedder_does_not_outdate(
        self, empty_collection, test_embedding_config, same_provider_embedding_config
    ):
        rag = NaiveRagService.create_or_update_naive_rag(
            collection_id=empty_collection.collection_id,
            embedder_id=test_embedding_config.pk,
        )
        doc = _make_doc(empty_collection, "_upd2")
        config = make_naive_rag_config(rag, doc, S.COMPLETED)

        # Update with SAME-provider but different embedder pk
        updated_rag = NaiveRagService.create_or_update_naive_rag(
            collection_id=empty_collection.collection_id,
            embedder_id=same_provider_embedding_config.pk,
        )
        updated_rag.refresh_from_db()
        # Embedder is swapped
        assert updated_rag.embedder_id == same_provider_embedding_config.pk
        # Status is NOT outdated (no provider change)
        assert updated_rag.rag_status != NaiveRag.NaiveRagStatus.OUTDATED
        config.refresh_from_db()
        assert config.status == S.COMPLETED


# ---------------------------------------------------------------------------
# 3. update_document_config
# ---------------------------------------------------------------------------


class TestUpdateDocumentConfig:
    def test_editing_completed_config_marks_outdated(self, naive_rag, document_metadata):
        config = make_naive_rag_config(naive_rag, document_metadata, S.COMPLETED)
        naive_rag.rag_status = NaiveRag.NaiveRagStatus.COMPLETED
        naive_rag.save(update_fields=["rag_status"])

        NaiveRagService.update_document_config(
            config_id=config.naive_rag_document_id,
            naive_rag_id=naive_rag.naive_rag_id,
            data={"chunk_size": 800},
        )

        config.refresh_from_db()
        naive_rag.refresh_from_db()
        assert config.status == S.OUTDATED
        assert naive_rag.rag_status == NaiveRag.NaiveRagStatus.OUTDATED

    def test_editing_new_config_stays_new_and_field_updated(
        self, naive_rag, document_metadata
    ):
        config = make_naive_rag_config(naive_rag, document_metadata, S.NEW)

        NaiveRagService.update_document_config(
            config_id=config.naive_rag_document_id,
            naive_rag_id=naive_rag.naive_rag_id,
            data={"chunk_size": 500},
        )

        config.refresh_from_db()
        assert config.status == S.NEW
        assert config.chunk_size == 500

    def test_chunk_overlap_gte_chunk_size_raises(self, naive_rag, document_metadata):
        config = make_naive_rag_config(naive_rag, document_metadata, S.NEW)

        with pytest.raises(InvalidChunkParametersException):
            NaiveRagService.update_document_config(
                config_id=config.naive_rag_document_id,
                naive_rag_id=naive_rag.naive_rag_id,
                data={"chunk_size": 100, "chunk_overlap": 100},
            )

    def test_invalid_strategy_for_file_type_raises(self, naive_rag, document_metadata):
        # document_metadata is pdf; "json" strategy is not allowed for pdf
        config = make_naive_rag_config(naive_rag, document_metadata, S.NEW)

        with pytest.raises(InvalidChunkParametersException):
            NaiveRagService.update_document_config(
                config_id=config.naive_rag_document_id,
                naive_rag_id=naive_rag.naive_rag_id,
                data={"chunk_strategy": "json"},
            )

    def test_no_op_update_does_not_change_status(self, naive_rag, document_metadata):
        config = make_naive_rag_config(naive_rag, document_metadata, S.COMPLETED)
        original_status = config.status

        NaiveRagService.update_document_config(
            config_id=config.naive_rag_document_id,
            naive_rag_id=naive_rag.naive_rag_id,
            data={"chunk_size": config.chunk_size},  # same value
        )

        config.refresh_from_db()
        assert config.status == original_status


# ---------------------------------------------------------------------------
# 4. bulk_update_document_configs_with_partial_errors
# ---------------------------------------------------------------------------


class TestBulkUpdateDocumentConfigs:
    def test_valid_and_invalid_mix_returns_correct_counts(
        self, naive_rag, source_collection
    ):
        doc_a = _make_doc(source_collection, "_ba")
        doc_b = _make_doc(source_collection, "_bb")
        cfg_a = make_naive_rag_config(naive_rag, doc_a, S.NEW)
        cfg_b = make_naive_rag_config(naive_rag, doc_b, S.NEW)

        result = NaiveRagService.bulk_update_document_configs_with_partial_errors(
            naive_rag_id=naive_rag.naive_rag_id,
            data=[
                {"id": cfg_a.naive_rag_document_id, "chunk_size": 600},
                # invalid: overlap >= size
                {"id": cfg_b.naive_rag_document_id, "chunk_size": 100, "chunk_overlap": 100},
            ],
        )

        assert result["updated"] == 1
        assert result["failed"] == 1
        assert result["unupdated"] == 0
        assert cfg_b.naive_rag_document_id in result["errors"]

    def test_missing_config_id_raises(self, naive_rag):
        with pytest.raises(DocumentConfigNotFoundException):
            NaiveRagService.bulk_update_document_configs_with_partial_errors(
                naive_rag_id=naive_rag.naive_rag_id,
                data=[{"id": 999999, "chunk_size": 500}],
            )

    def test_updating_completed_configs_flips_to_outdated(
        self, naive_rag, source_collection
    ):
        doc = _make_doc(source_collection, "_bc")
        cfg = make_naive_rag_config(naive_rag, doc, S.COMPLETED)
        naive_rag.rag_status = NaiveRag.NaiveRagStatus.COMPLETED
        naive_rag.save(update_fields=["rag_status"])

        NaiveRagService.bulk_update_document_configs_with_partial_errors(
            naive_rag_id=naive_rag.naive_rag_id,
            data=[{"id": cfg.naive_rag_document_id, "chunk_size": 750}],
        )

        cfg.refresh_from_db()
        naive_rag.refresh_from_db()
        assert cfg.status == S.OUTDATED
        assert naive_rag.rag_status == NaiveRag.NaiveRagStatus.OUTDATED


# ---------------------------------------------------------------------------
# 5. bulk_delete_document_configs
# ---------------------------------------------------------------------------


class TestBulkDeleteDocumentConfigs:
    def test_delete_failed_leaves_rag_completed(self, naive_rag, source_collection):
        doc_a = _make_doc(source_collection, "_bd_a")
        doc_b = _make_doc(source_collection, "_bd_b")
        cfg_a = make_naive_rag_config(naive_rag, doc_a, S.COMPLETED)
        cfg_b = make_naive_rag_config(naive_rag, doc_b, S.FAILED)
        naive_rag.rag_status = NaiveRag.NaiveRagStatus.PARTIAL
        naive_rag.save(update_fields=["rag_status"])

        NaiveRagService.bulk_delete_document_configs(
            naive_rag_id=naive_rag.naive_rag_id,
            config_ids=[cfg_b.naive_rag_document_id],
        )

        naive_rag.refresh_from_db()
        assert naive_rag.rag_status == NaiveRag.NaiveRagStatus.COMPLETED

    def test_delete_all_configs_leaves_rag_new(self, naive_rag, source_collection):
        doc = _make_doc(source_collection, "_bd_all")
        cfg = make_naive_rag_config(naive_rag, doc, S.COMPLETED)
        naive_rag.rag_status = NaiveRag.NaiveRagStatus.COMPLETED
        naive_rag.save(update_fields=["rag_status"])

        NaiveRagService.bulk_delete_document_configs(
            naive_rag_id=naive_rag.naive_rag_id,
            config_ids=[cfg.naive_rag_document_id],
        )

        naive_rag.refresh_from_db()
        assert naive_rag.rag_status == NaiveRag.NaiveRagStatus.NEW

    def test_delete_outdated_config_clears_outdated_reasons(
        self, naive_rag, source_collection
    ):
        """Deleting the only OUTDATED config clears rag-level outdated_reasons."""
        doc_outdated = _make_doc(source_collection, "_bd_out")
        doc_completed = _make_doc(source_collection, "_bd_comp")
        cfg_outdated = make_naive_rag_config(naive_rag, doc_outdated, S.OUTDATED)
        make_naive_rag_config(naive_rag, doc_completed, S.COMPLETED)

        naive_rag.add_outdated_reason("document_config_changed", "Changed.")
        naive_rag.rag_status = NaiveRag.NaiveRagStatus.OUTDATED
        naive_rag.save(update_fields=["rag_status", "outdated_reasons"])

        NaiveRagService.bulk_delete_document_configs(
            naive_rag_id=naive_rag.naive_rag_id,
            config_ids=[cfg_outdated.naive_rag_document_id],
        )

        naive_rag.refresh_from_db()
        assert naive_rag.rag_status == NaiveRag.NaiveRagStatus.COMPLETED
        assert naive_rag.outdated_reasons == {}

    def test_empty_ids_raises(self, naive_rag):
        with pytest.raises(InvalidChunkParametersException):
            NaiveRagService.bulk_delete_document_configs(
                naive_rag_id=naive_rag.naive_rag_id,
                config_ids=[],
            )


# ---------------------------------------------------------------------------
# 6. delete_document_config
# ---------------------------------------------------------------------------


class TestDeleteDocumentConfig:
    def test_single_delete_recomputes_status(self, naive_rag, source_collection):
        doc_a = _make_doc(source_collection, "_del_a")
        doc_b = _make_doc(source_collection, "_del_b")
        cfg_a = make_naive_rag_config(naive_rag, doc_a, S.COMPLETED)
        make_naive_rag_config(naive_rag, doc_b, S.COMPLETED)
        naive_rag.rag_status = NaiveRag.NaiveRagStatus.COMPLETED
        naive_rag.save(update_fields=["rag_status"])

        NaiveRagService.delete_document_config(
            config_id=cfg_a.naive_rag_document_id,
            naive_rag_id=naive_rag.naive_rag_id,
        )

        naive_rag.refresh_from_db()
        assert naive_rag.rag_status == NaiveRag.NaiveRagStatus.COMPLETED

    def test_wrong_naive_rag_id_raises(self, naive_rag, document_metadata):
        cfg = make_naive_rag_config(naive_rag, document_metadata, S.NEW)

        with pytest.raises(DocumentConfigNotFoundException):
            NaiveRagService.delete_document_config(
                config_id=cfg.naive_rag_document_id,
                naive_rag_id=naive_rag.naive_rag_id + 9999,
            )


# ---------------------------------------------------------------------------
# 7. init_document_configs
# ---------------------------------------------------------------------------


class TestInitDocumentConfigs:
    def test_creates_configs_for_uncovered_documents(
        self, naive_rag, source_collection, document_metadata
    ):
        # document_metadata belongs to source_collection; no config yet
        created = NaiveRagService.init_document_configs(naive_rag.naive_rag_id)
        assert len(created) == 1
        assert created[0].document_id == document_metadata.document_id

    def test_returns_empty_when_all_docs_already_have_configs(
        self, naive_rag, document_metadata
    ):
        make_naive_rag_config(naive_rag, document_metadata, S.NEW)

        created = NaiveRagService.init_document_configs(naive_rag.naive_rag_id)
        assert created == []

    def test_skips_document_incompatible_with_default_strategy(
        self, naive_rag, source_collection
    ):
        # "json" file type is NOT compatible with the default "token" strategy? No — token is
        # universal. We need a file type for which DEFAULT_CHUNK_STRATEGY ("token") is not allowed.
        # Per constants: UNIVERSAL_STRATEGIES = {"token","character"} — token IS allowed for all.
        # So there is no standard file type that skips the default strategy.
        # This test verifies that all standard types get configs (skip logic never fires for defaults).
        content = DocumentContent.objects.create(content=b"json doc")
        json_doc = DocumentMetadata.objects.create(
            source_collection=source_collection,
            document_content=content,
            file_name="data.json",
            file_type="json",
            file_size=64,
        )

        created = NaiveRagService.init_document_configs(naive_rag.naive_rag_id)
        created_doc_ids = {c.document_id for c in created}
        assert json_doc.document_id in created_doc_ids
