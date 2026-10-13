from types import SimpleNamespace

import pytest
from application.commands import RemoveRag
from application.orchestrators.removing.strategies import graph_remover
from application.orchestrators.removing.strategies.graph_remover import (
    GraphRagRemoveOrchestrator,
)
from domain.enums import IndexStatusEnum
from domain.errors import RagInProcessingError, RagNotFoundError
from domain.models import Rag


class FakeGraphRagRepo:
    def __init__(self, *, rag: Rag | None):
        self._rag = rag

    async def get_rag(self, rag_id: int) -> Rag | None:
        return self._rag


class FakeUoW:
    def __init__(self, repo: FakeGraphRagRepo):
        self.graph_rag_repo = repo

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class FakeStorage:
    """Stand-in for the S3 storage graphrag builds from a storage config."""

    def __init__(self, config, clear_error: BaseException | None):
        self.prefix = config.prefix
        self._clear_error = clear_error
        self.cleared = False

    async def clear(self) -> None:
        if self._clear_error is not None:
            raise self._clear_error
        self.cleared = True


@pytest.fixture
def storage_service(monkeypatch):
    """The S3 service: records every storage the remover opens; set `clear_error` to make
    clearing fail."""
    service = SimpleNamespace(opened=[], clear_error=None)

    def create_storage(config):
        storage = FakeStorage(config, clear_error=service.clear_error)
        service.opened.append(storage)
        return storage

    monkeypatch.setattr(graph_remover, "create_storage", create_storage)
    return service


def _rag(rag_id: int, status: IndexStatusEnum) -> Rag:
    return Rag(id=rag_id, status=status, indexing_document_ids=set())


async def test_removing_a_rag_clears_only_that_rags_index_storage(storage_service):
    uow = FakeUoW(FakeGraphRagRepo(rag=_rag(42, IndexStatusEnum.COMPLETED)))

    await GraphRagRemoveOrchestrator(uow).execute(RemoveRag(rag_id=42))

    assert [(storage.prefix, storage.cleared) for storage in storage_service.opened] == [
        ("graphrag/rag_42", True)
    ]


@pytest.mark.parametrize(
    ("rag", "expected_error"),
    [
        (None, RagNotFoundError),
        (_rag(3, IndexStatusEnum.PROCESSING), RagInProcessingError),
    ],
    ids=["missing-rag", "rag-being-indexed"],
)
async def test_removal_is_refused_without_touching_storage(storage_service, rag, expected_error):
    uow = FakeUoW(FakeGraphRagRepo(rag=rag))

    with pytest.raises(expected_error):
        await GraphRagRemoveOrchestrator(uow).execute(RemoveRag(rag_id=3))

    assert storage_service.opened == []


async def test_storage_clear_failure_propagates(storage_service):
    storage_service.clear_error = RuntimeError("storage unavailable")
    uow = FakeUoW(FakeGraphRagRepo(rag=_rag(5, IndexStatusEnum.COMPLETED)))

    with pytest.raises(RuntimeError, match="storage unavailable"):
        await GraphRagRemoveOrchestrator(uow).execute(RemoveRag(rag_id=5))
