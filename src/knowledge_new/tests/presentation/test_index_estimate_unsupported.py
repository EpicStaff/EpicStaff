import pytest
from application.ports import AbstractUnitOfWork
from litestar import Litestar
from litestar.di import Provide
from litestar.testing import TestClient
from presentation.rest.controllers import rag as rag_controller
from presentation.rest.controllers.rag import RagController
from presentation.rest.error_handlers import get_error_handlers


class _UnusedUow(AbstractUnitOfWork):
    """The unsupported-strategy path fails before the unit of work is touched."""

    graph_rag_repo = None
    naive_rag_repo = None

    async def commit(self): ...

    async def rollback(self): ...


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(rag_controller, "is_graphrag_available", lambda: True)
    app = Litestar(
        route_handlers=[RagController],
        signature_types=[AbstractUnitOfWork],
        dependencies={"uow": Provide(lambda: _UnusedUow(), sync_to_thread=False)},
        exception_handlers=get_error_handlers(),
    )
    with TestClient(app=app) as test_client:
        yield test_client


def test_graph_index_estimate_is_rejected_with_a_readable_400(client):
    response = client.post("/rags/graph/1/index-estimate/", json={"document_ids": [1]})

    assert response.status_code == 400
    assert response.json() == {
        "code": "unsupported",
        "detail": "Unsupported estimate strategy: 'graph'",
    }
