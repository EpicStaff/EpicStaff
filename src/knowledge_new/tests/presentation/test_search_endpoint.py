import asyncio
import json
from unittest.mock import MagicMock

import pytest
from application.ports import AbstractUnitOfWork
from application.results import SearchResult
from foundation.cryptographer import AbstractCryptographer
from litestar import Litestar
from litestar.di import Provide
from litestar.testing import TestClient
from presentation.rest.controllers import rag as rag_controller
from presentation.rest.controllers.rag import RagController
from presentation.rest.error_handlers import get_error_handlers

from tests.orchestrators.conftest import CRYPTOGRAPHER, seal
from tests.orchestrators.graph_output_fakes import FakeGraphRagRepo

SEARCH_PATH = "/rags/naive/1/search/"
SEARCH_BODY = {
    "query": "what is indexed",
    "search_config": {"rag_strategy": "naive", "search_limit": 3, "similarity_threshold": 0.2},
    "embedding_api_key": "sk-embedding",
}


class _AnsweringSearch:
    async def execute(self, command):
        return SearchResult(result=f"answer to {command.query}")


class _HangingSearch:
    """A search that never finishes; records that it started and that it was cancelled."""

    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.cancelled = False

    async def execute(self, command):
        self.started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise


def _app(monkeypatch, search) -> Litestar:
    monkeypatch.setattr(rag_controller, "build_search", lambda *args: search)
    return Litestar(
        route_handlers=[RagController],
        signature_types=[AbstractUnitOfWork, AbstractCryptographer],
        # The search orchestrator is replaced, so neither dependency is used.
        dependencies={
            "uow": Provide(lambda: MagicMock(spec=AbstractUnitOfWork), sync_to_thread=False),
            "cryptographer": Provide(
                lambda: MagicMock(spec=AbstractCryptographer), sync_to_thread=False
            ),
        },
        exception_handlers=get_error_handlers(),
    )


def test_search_returns_the_orchestrator_result_while_the_client_stays(monkeypatch):
    with TestClient(app=_app(monkeypatch, _AnsweringSearch())) as client:
        response = client.post(SEARCH_PATH, json=SEARCH_BODY)

    assert response.status_code == 200
    assert response.json()["result"] == "answer to what is indexed"


async def test_search_is_cancelled_and_answered_with_499_when_the_client_disconnects(
    monkeypatch,
):
    # Raw ASGI: TestClient only reports a disconnect after the response is complete.
    search = _HangingSearch()
    app = _app(monkeypatch, search)
    body = json.dumps(SEARCH_BODY).encode()
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": SEARCH_PATH,
        "raw_path": SEARCH_PATH.encode(),
        "root_path": "",
        "query_string": b"",
        "headers": [
            (b"host", b"knowledge.test"),
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode()),
        ],
        "client": ("127.0.0.1", 50000),
        "server": ("knowledge.test", 80),
    }
    body_sent = False
    sent_messages = []

    async def receive():
        nonlocal body_sent
        if not body_sent:
            body_sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        await search.started.wait()
        return {"type": "http.disconnect"}

    async def send(message):
        sent_messages.append(message)

    # A search that ignores the disconnect would hang forever; fail with TimeoutError instead.
    await asyncio.wait_for(app(scope, receive, send), timeout=5)

    assert search.cancelled
    response_start = next(m for m in sent_messages if m["type"] == "http.response.start")
    assert response_start["status"] == 499


class _GraphRagUow(AbstractUnitOfWork):
    def __init__(self, repo: FakeGraphRagRepo):
        self._repo = repo

    @property
    def graph_rag_repo(self):
        return self._repo

    @property
    def naive_rag_repo(self):
        return None

    async def commit(self): ...

    async def rollback(self): ...


@pytest.mark.parametrize(
    ("graph_exists", "expected_status", "expected_code"),
    [(False, 404, "not_found"), (True, 409, "graph_not_indexed")],
    ids=["deleted-graph-rag", "never-indexed-graph-rag"],
)
def test_graph_search_that_cannot_run_answers_with_a_client_error_code(
    monkeypatch, tmp_path, graph_exists, expected_status, expected_code
):
    """The agent tells the model whether retrying can help by these codes, not by a 500."""
    # An existing graph RAG with an empty output directory has never been indexed.
    repo = FakeGraphRagRepo(tmp_path if graph_exists else None)
    monkeypatch.setattr(rag_controller, "is_graphrag_available", lambda: True)
    app = Litestar(
        route_handlers=[RagController],
        signature_types=[AbstractUnitOfWork, AbstractCryptographer],
        dependencies={
            "uow": Provide(lambda: _GraphRagUow(repo), sync_to_thread=False),
            "cryptographer": Provide(lambda: CRYPTOGRAPHER, sync_to_thread=False),
        },
        exception_handlers=get_error_handlers(),
    )

    with TestClient(app=app) as client:
        response = client.post(
            "/rags/graph/7/search/",
            json={
                "query": "what is indexed",
                "search_config": {"rag_strategy": "graph", "method": "basic"},
                "embedding_api_key": seal("sk-embedding"),
                "llm_api_key": seal("sk-llm"),
            },
        )

    assert response.status_code == expected_status
    assert response.json()["code"] == expected_code
