import pytest
from domain.errors import ChunkingError, GraphNotIndexedError, RagNotFoundError
from litestar import Litestar, get, status_codes
from litestar.exceptions import HTTPException
from litestar.testing import TestClient
from loguru import logger
from presentation.rest.error_handlers import get_error_handlers

INTERNAL_TEXT = "connection to /var/lib/knowledge/rag-7.db refused by db-internal:5432"
FIXED_BODY = {
    "code": "internal_error",
    "detail": "The knowledge service failed to process the request.",
}


@get("/domain-failure/")
async def raise_domain_failure() -> None:
    raise ChunkingError(INTERNAL_TEXT)


@get("/unexpected-failure/")
async def raise_unexpected_failure() -> None:
    raise RuntimeError(INTERNAL_TEXT)


@get("/rag-not-found/")
async def raise_rag_not_found() -> None:
    raise RagNotFoundError(rag_id=7)


@get("/graph-not-indexed/")
async def raise_graph_not_indexed() -> None:
    raise GraphNotIndexedError(rag_id=7)


@get("/unavailable/")
async def raise_unavailable() -> None:
    raise HTTPException(
        status_code=status_codes.HTTP_503_SERVICE_UNAVAILABLE, detail="GraphRAG is unavailable."
    )


@get("/typed-query/")
async def read_typed_query(limit: int) -> dict:
    return {"limit": limit}


@pytest.fixture
def client():
    app = Litestar(
        route_handlers=[
            raise_domain_failure,
            raise_unexpected_failure,
            raise_rag_not_found,
            raise_graph_not_indexed,
            raise_unavailable,
            read_typed_query,
        ],
        exception_handlers=get_error_handlers(),
    )
    with TestClient(app=app) as test_client:
        yield test_client


@pytest.fixture
def error_log():
    records = []
    sink_id = logger.add(records.append, level="ERROR", format="{message}")
    yield records
    logger.remove(sink_id)


@pytest.mark.parametrize(
    ("path", "error_type"),
    [
        ("/domain-failure/", ChunkingError),
        ("/unexpected-failure/", RuntimeError),
    ],
)
def test_server_failure_returns_a_fixed_body_and_logs_the_exception(
    client, error_log, path, error_type
):
    response = client.get(path)

    assert response.status_code == 500
    assert response.json() == FIXED_BODY
    assert INTERNAL_TEXT not in response.text
    assert len(error_log) == 1
    logged_exception = error_log[0].record["exception"]
    assert logged_exception.type is error_type
    assert str(logged_exception.value) == INTERNAL_TEXT
    assert f"GET {path.rstrip('/')}" in error_log[0].record["message"]


@pytest.mark.parametrize(
    ("path", "status_code", "body"),
    [
        (
            "/rag-not-found/",
            404,
            {"code": "not_found", "detail": "RAG(id=7) not found."},
        ),
        (
            "/graph-not-indexed/",
            409,
            {
                "code": "graph_not_indexed",
                "detail": "Graph index output not available for RAG(id=7). Run indexing first.",
            },
        ),
    ],
)
def test_domain_client_error_keeps_its_message(client, error_log, path, status_code, body):
    response = client.get(path)

    assert response.status_code == status_code
    assert response.json() == body
    assert error_log == []


@pytest.mark.parametrize(
    ("path", "status_code", "detail_fragment"),
    [
        ("/unavailable/", 503, "GraphRAG is unavailable."),
        ("/typed-query/?limit=many", 400, "Validation failed"),
        ("/no-such-route/", 404, "Not Found"),
    ],
)
def test_litestar_http_errors_are_not_turned_into_a_500(
    client, error_log, path, status_code, detail_fragment
):
    response = client.get(path)

    assert response.status_code == status_code
    assert detail_fragment in response.json()["detail"]
    assert error_log == []
