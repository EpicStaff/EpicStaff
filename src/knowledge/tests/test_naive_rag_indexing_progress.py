"""
Integration-style tests for NaiveRAGStrategy's indexing progress events
(RagIndexingProgressMessage), published on KNOWLEDGE_INDEXING_PROGRESS_CHANNEL
while process_rag_indexing() runs.

Mocks: Redis (via the `published_messages` fixture in conftest.py) and the DB
(via FakeUnitOfWork / FakeNaiveRagStorage - in-memory doubles standing in for
the real Postgres-backed UnitOfWork) and chunking (FakeChunkDocumentService).
Real: NaiveRAGStrategy's actual control flow - the exact code under test.
"""

from contextlib import contextmanager

import pytest

import rag.naive_rag_strategy as naive_rag_strategy_module
from rag.naive_rag_strategy import (
    NaiveRAGStrategy,
    KNOWLEDGE_INDEXING_PROGRESS_CHANNEL,
)
from src.shared.models import (
    COLLECTION_STATUS_UPLOADING,
    COLLECTION_STATUS_WARNING,
    COLLECTION_STATUS_FAILED,
)


class FakeEmbedder:
    def embed(self, text: str):
        return [0.1, 0.2, 0.3]


class FakeDocument:
    def __init__(self, file_name: str):
        self.file_name = file_name


class FakeDocConfig:
    def __init__(self, config_id: int, file_name: str, status: str = "new"):
        self.naive_rag_document_id = config_id
        self.document = FakeDocument(file_name)
        self.status = status


class FakeNaiveRagStorage:
    """
    In-memory double for ORMNaiveRagStorage, implementing only the methods
    NaiveRAGStrategy.process_rag_indexing / update_naive_rag_status use.
    """

    def __init__(
        self,
        *,
        collection_id: int | None,
        doc_configs: list[FakeDocConfig],
        has_documents: bool = True,
        fail_update_rag_status_after: int | None = None,
        raise_on_get_document_configs: Exception | None = None,
    ):
        self.collection_id = collection_id
        self.doc_configs = {dc.naive_rag_document_id: dc for dc in doc_configs}
        self.rag_status = "new"
        self.has_documents = has_documents
        self.update_rag_status_calls = 0
        self.fail_update_rag_status_after = fail_update_rag_status_after
        self.raise_on_get_document_configs = raise_on_get_document_configs

    def get_embedder_configuration(self, rag_id, rag_type):
        return {"api_key": "x", "model_name": "y", "provider": "openai"}

    def update_rag_status(self, naive_rag_id, status):
        self.update_rag_status_calls += 1
        if (
            self.fail_update_rag_status_after is not None
            and self.update_rag_status_calls > self.fail_update_rag_status_after
        ):
            return False
        self.rag_status = status
        return True

    def get_naive_rag_document_configs(self, naive_rag_id, status=None):
        if self.raise_on_get_document_configs is not None:
            raise self.raise_on_get_document_configs

        configs = list(self.doc_configs.values())
        if status is None:
            return configs
        wanted = {status} if isinstance(status, str) else set(status)
        return [config for config in configs if config.status in wanted]

    def update_document_config_status(self, naive_rag_document_config_id, status):
        self.doc_configs[naive_rag_document_config_id].status = status
        return True

    def save_embedding(self, chunk_id, embedding, naive_rag_document_config_id):
        pass

    def get_collection_status_inputs(self, naive_rag_id):
        if self.collection_id is None:
            return None
        return (self.collection_id, self.has_documents, [self.rag_status])


class FakeUnitOfWorkContext:
    def __init__(self, storage: FakeNaiveRagStorage):
        self.naive_rag_storage = storage


class FakeUnitOfWork:
    def __init__(self, storage: FakeNaiveRagStorage):
        self._storage = storage

    @contextmanager
    def start(self):
        yield FakeUnitOfWorkContext(self._storage)


class FakeChunkDocumentService:
    """
    Test double for ChunkDocumentService. `behavior_by_config_id` maps a
    document config id to either:
      - "success": returns one chunk
      - "empty": returns no chunks (triggers the "warning" branch)
      - an Exception instance: raised (triggers the "failed" branch)
    """

    behavior_by_config_id: dict = {}

    def process_chunk_document_in_session(self, uow_ctx, naive_rag_document_config_id):
        outcome = FakeChunkDocumentService.behavior_by_config_id[
            naive_rag_document_config_id
        ]
        if isinstance(outcome, Exception):
            raise outcome
        if outcome == "empty":
            return []
        return [{"chunk_id": naive_rag_document_config_id, "text": "hello world"}]


@pytest.fixture(autouse=True)
def _patch_strategy_collaborators(monkeypatch):
    """Bypass the real embedder cache/config resolution and chunking service."""
    monkeypatch.setattr(
        NaiveRAGStrategy,
        "_get_cached_embedder",
        lambda self, naive_rag_id: FakeEmbedder(),
    )
    monkeypatch.setattr(
        naive_rag_strategy_module, "ChunkDocumentService", FakeChunkDocumentService
    )
    FakeChunkDocumentService.behavior_by_config_id = {}


def _install_fake_uow(monkeypatch, storage: FakeNaiveRagStorage):
    monkeypatch.setattr(
        naive_rag_strategy_module, "UnitOfWork", lambda: FakeUnitOfWork(storage)
    )


def _progress_messages(published_messages):
    return [
        message
        for channel, message in published_messages
        if channel == KNOWLEDGE_INDEXING_PROGRESS_CHANNEL
    ]


class TestMixedDocumentIndexing:
    """A collection with one succeeding, one empty-chunk, and one failing
    document must emit the full per-document sequence and land on the
    correct aggregate terminal status."""

    def test_emits_correct_event_sequence_and_terminal_status(
        self, monkeypatch, published_messages
    ):
        doc_configs = [
            FakeDocConfig(1, "good.txt"),
            FakeDocConfig(2, "empty.txt"),
            FakeDocConfig(3, "bad.txt"),
        ]
        storage = FakeNaiveRagStorage(collection_id=42, doc_configs=doc_configs)
        _install_fake_uow(monkeypatch, storage)

        FakeChunkDocumentService.behavior_by_config_id = {
            1: "success",
            2: "empty",
            3: RuntimeError("chunking exploded"),
        }

        NaiveRAGStrategy().process_rag_indexing(rag_id=7)

        events = _progress_messages(published_messages)

        # start + 3 * (processing + terminal) + 1 aggregate terminal = 8
        assert len(events) == 8

        start_event = events[0]
        assert start_event["collection_id"] == 42
        assert start_event["rag_id"] == 7
        assert start_event["rag_type"] == "naive"
        assert start_event["document_config_id"] is None
        assert start_event["collection_status"] == COLLECTION_STATUS_UPLOADING

        per_document_events = events[1:-1]
        assert [
            (
                event["document_config_id"],
                event["doc_status"],
                event["done"],
                event["total"],
            )
            for event in per_document_events
        ] == [
            (1, "processing", 0, 3),
            (1, "completed", 1, 3),
            (2, "processing", 1, 3),
            (2, "warning", 2, 3),
            (3, "processing", 2, 3),
            (3, "failed", 3, 3),
        ]
        # every non-terminal event (including per-document ones) is reported
        # as "uploading" - the collection is still being indexed.
        assert all(
            event["collection_status"] == COLLECTION_STATUS_UPLOADING
            for event in events[:-1]
        )
        assert events[3]["error"] is None  # doc2 "processing" - initialization guard
        assert events[5]["error"] is None
        assert events[-2]["error"] == "chunking exploded"  # doc3 "failed"

        terminal_event = events[-1]
        assert terminal_event["document_config_id"] is None
        # completed + warning + failed -> mixed -> "warning" (never left at
        # an in-progress value)
        assert terminal_event["collection_status"] == COLLECTION_STATUS_WARNING
        assert storage.rag_status == "warning"


class TestRobustnessAlwaysEmitsTerminalEvent:
    """ROBUSTNESS FIX: update_rag_status can silently return False. The
    terminal progress event must still be published, reporting "failed"
    rather than leaving the stream on an in-progress status."""

    def test_terminal_event_falls_back_to_failed_when_status_persist_fails(
        self, monkeypatch, published_messages
    ):
        doc_configs = [FakeDocConfig(1, "good.txt")]
        storage = FakeNaiveRagStorage(
            collection_id=99,
            doc_configs=doc_configs,
            # First update_rag_status call ("processing") succeeds; the
            # second one (the final aggregate write in
            # update_naive_rag_status) fails and returns False.
            fail_update_rag_status_after=1,
        )
        _install_fake_uow(monkeypatch, storage)
        FakeChunkDocumentService.behavior_by_config_id = {1: "success"}

        NaiveRAGStrategy().process_rag_indexing(rag_id=11)

        events = _progress_messages(published_messages)
        terminal_event = events[-1]

        # Document succeeded, so the "true" aggregate would be "completed" -
        # but since persisting that status failed, the terminal event must
        # report the safe "failed" fallback instead.
        assert terminal_event["collection_status"] == COLLECTION_STATUS_FAILED
        assert terminal_event["error"] is not None

    def test_terminal_event_emitted_when_outer_processing_fails(
        self, monkeypatch, published_messages
    ):
        """An error before/outside the per-document loop (e.g.
        get_naive_rag_document_configs raising) is handled by
        process_rag_indexing's own outer except - it must still publish a
        single terminal event, derived from the collection's real state."""
        storage = FakeNaiveRagStorage(
            collection_id=5,
            doc_configs=[],
            raise_on_get_document_configs=RuntimeError("db exploded"),
        )
        _install_fake_uow(monkeypatch, storage)

        NaiveRAGStrategy().process_rag_indexing(rag_id=13)

        events = _progress_messages(published_messages)
        assert len(events) == 2  # start event + outer-failure terminal event
        terminal_event = events[-1]
        assert terminal_event["collection_status"] != COLLECTION_STATUS_UPLOADING
        assert "db exploded" in terminal_event["error"]
        assert storage.rag_status == "failed"

    def test_raises_when_collection_cannot_be_resolved(
        self, monkeypatch, published_messages
    ):
        """No collection_id means no scoped event can be published - this
        must surface as an exception so the execute_indexing() safety net
        (main.py) can publish its own generic failure event instead of the
        stream silently dead-ending."""
        storage = FakeNaiveRagStorage(collection_id=None, doc_configs=[])
        _install_fake_uow(monkeypatch, storage)

        with pytest.raises(ValueError, match="Could not resolve source collection"):
            NaiveRAGStrategy().process_rag_indexing(rag_id=99)

        assert _progress_messages(published_messages) == []


class TestAllDocumentsSucceed:
    def test_terminal_status_is_completed(self, monkeypatch, published_messages):
        doc_configs = [FakeDocConfig(1, "a.txt"), FakeDocConfig(2, "b.txt")]
        storage = FakeNaiveRagStorage(collection_id=1, doc_configs=doc_configs)
        _install_fake_uow(monkeypatch, storage)
        FakeChunkDocumentService.behavior_by_config_id = {1: "success", 2: "success"}

        NaiveRAGStrategy().process_rag_indexing(rag_id=1)

        events = _progress_messages(published_messages)
        assert events[-1]["collection_status"] == "completed"
        assert storage.rag_status == "completed"


class TestAllDocumentsFail:
    def test_terminal_status_is_failed(self, monkeypatch, published_messages):
        doc_configs = [FakeDocConfig(1, "a.txt")]
        storage = FakeNaiveRagStorage(collection_id=1, doc_configs=doc_configs)
        _install_fake_uow(monkeypatch, storage)
        FakeChunkDocumentService.behavior_by_config_id = {1: RuntimeError("boom")}

        NaiveRAGStrategy().process_rag_indexing(rag_id=1)

        events = _progress_messages(published_messages)
        assert events[-1]["collection_status"] == COLLECTION_STATUS_FAILED
        assert storage.rag_status == "failed"
