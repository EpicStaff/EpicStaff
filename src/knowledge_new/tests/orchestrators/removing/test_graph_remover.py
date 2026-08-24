import pytest
from application.commands import RemoveRag
from application.orchestrators.removing.strategies import graph_remover
from application.orchestrators.removing.strategies.graph_remover import (
    GraphRagRemoveOrchestrator,
)
from domain.enums import IndexStatusEnum
from domain.errors import (
    RagInProcessingError,
    RagNotFoundError,
)
from domain.models import Rag


def _completed_rag(rag_id: int = 1) -> Rag:
    return Rag(id=rag_id, status=IndexStatusEnum.COMPLETED, indexing_document_ids=set())


def _processing_rag(rag_id: int = 1) -> Rag:
    return Rag(
        id=rag_id, status=IndexStatusEnum.PROCESSING, indexing_document_ids=set()
    )


class FakeGraphRagRepo:
    """Minimal in-memory repo covering the GraphRagRemoveOrchestrator call surface."""

    def __init__(self, *, rag: Rag | None):
        self._rag = rag
        self.get_config_calls: list[int] = []
        self.remove_rag_calls: list[int] = []

    async def get_rag(self, rag_id: int) -> Rag | None:
        return self._rag

    async def get_config(self, rag_id: int) -> object | None:
        self.get_config_calls.append(rag_id)
        return None

    async def remove_rag(self, *, rag_id: int) -> None:
        self.remove_rag_calls.append(rag_id)


class FakeUoW:
    """Re-enterable unit of work that delegates to a single FakeGraphRagRepo."""

    def __init__(self, repo: FakeGraphRagRepo):
        self.graph_rag_repo = repo
        self.commit_count: int = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def commit(self):
        self.commit_count += 1


class FakeStorage:
    """Stand-in for a graphrag storage object."""

    def __init__(self, *, clear_error: BaseException | None = None):
        self.clear_called: bool = False
        self.clear_error: BaseException | None = clear_error

    async def clear(self) -> None:
        if self.clear_error is not None:
            raise self.clear_error
        self.clear_called = True


async def test_happy_path_clears_storage(monkeypatch):
    rag = _completed_rag(rag_id=42)
    repo = FakeGraphRagRepo(rag=rag)
    uow = FakeUoW(repo)

    storage = FakeStorage()
    sentinel_config = object()
    create_storage_config_calls: list[int] = []
    create_storage_calls: list = []

    def fake_create_storage_config(rag_id: int) -> object:
        create_storage_config_calls.append(rag_id)
        return sentinel_config

    def fake_create_storage(storage_cfg: object) -> FakeStorage:
        create_storage_calls.append(storage_cfg)
        return storage

    monkeypatch.setattr(
        graph_remover, "create_storage_config", fake_create_storage_config
    )
    monkeypatch.setattr(graph_remover, "create_storage", fake_create_storage)

    await GraphRagRemoveOrchestrator(uow).execute(RemoveRag(rag_id=42))

    assert create_storage_config_calls == [42]
    assert create_storage_calls == [sentinel_config]
    assert storage.clear_called is True
    assert repo.get_config_calls == []
    assert repo.remove_rag_calls == []
    assert uow.commit_count == 0


async def test_rag_not_found_raises_and_never_touches_storage(monkeypatch):
    repo = FakeGraphRagRepo(rag=None)
    uow = FakeUoW(repo)

    create_storage_config_calls: list = []
    create_storage_calls: list = []

    def fake_create_storage_config(rag_id: int) -> object:
        create_storage_config_calls.append(rag_id)
        return object()

    def fake_create_storage(storage_cfg: object) -> FakeStorage:
        create_storage_calls.append(storage_cfg)
        return FakeStorage()

    monkeypatch.setattr(
        graph_remover, "create_storage_config", fake_create_storage_config
    )
    monkeypatch.setattr(graph_remover, "create_storage", fake_create_storage)

    with pytest.raises(RagNotFoundError):
        await GraphRagRemoveOrchestrator(uow).execute(RemoveRag(rag_id=7))

    assert create_storage_config_calls == []
    assert create_storage_calls == []


async def test_rag_in_processing_raises_and_never_touches_storage(monkeypatch):
    rag = _processing_rag(rag_id=3)
    repo = FakeGraphRagRepo(rag=rag)
    uow = FakeUoW(repo)

    create_storage_config_calls: list = []
    create_storage_calls: list = []

    def fake_create_storage_config(rag_id: int) -> object:
        create_storage_config_calls.append(rag_id)
        return object()

    def fake_create_storage(storage_cfg: object) -> FakeStorage:
        create_storage_calls.append(storage_cfg)
        return FakeStorage()

    monkeypatch.setattr(
        graph_remover, "create_storage_config", fake_create_storage_config
    )
    monkeypatch.setattr(graph_remover, "create_storage", fake_create_storage)

    with pytest.raises(RagInProcessingError):
        await GraphRagRemoveOrchestrator(uow).execute(RemoveRag(rag_id=3))

    assert create_storage_config_calls == []
    assert create_storage_calls == []


async def test_storage_clear_failure_propagates(monkeypatch):
    rag = _completed_rag(rag_id=5)
    repo = FakeGraphRagRepo(rag=rag)
    uow = FakeUoW(repo)

    storage = FakeStorage(clear_error=RuntimeError("minio unavailable"))

    monkeypatch.setattr(graph_remover, "create_storage_config", lambda rag_id: object())
    monkeypatch.setattr(graph_remover, "create_storage", lambda cfg: storage)

    with pytest.raises(RuntimeError, match="minio unavailable"):
        await GraphRagRemoveOrchestrator(uow).execute(RemoveRag(rag_id=5))

    assert uow.commit_count == 0


async def test_storage_config_derived_from_rag_id(monkeypatch):
    rag = _completed_rag(rag_id=99)
    repo = FakeGraphRagRepo(rag=rag)
    uow = FakeUoW(repo)

    sentinel_config = object()
    create_storage_config_calls: list[int] = []
    create_storage_calls: list = []

    def fake_create_storage_config(rag_id: int) -> object:
        create_storage_config_calls.append(rag_id)
        return sentinel_config

    def fake_create_storage(storage_cfg: object) -> FakeStorage:
        create_storage_calls.append(storage_cfg)
        return FakeStorage()

    monkeypatch.setattr(
        graph_remover, "create_storage_config", fake_create_storage_config
    )
    monkeypatch.setattr(graph_remover, "create_storage", fake_create_storage)

    await GraphRagRemoveOrchestrator(uow).execute(RemoveRag(rag_id=99))

    assert len(create_storage_config_calls) == 1
    assert create_storage_config_calls[0] == 99
    assert len(create_storage_calls) == 1
    assert create_storage_calls[0] is sentinel_config
