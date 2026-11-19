"""A domain error with no handler of its own answers 500 with a fixed detail."""

import pytest
from domain.errors import ArtifactStorageError, RepositoryError
from litestar import Litestar, get
from litestar.testing import TestClient
from loguru import logger
from presentation.rest.error_handlers import get_error_handlers

RAISED = {
    "repository": RepositoryError(function="NaiveRagRepository.get_rag"),
    "artifact-storage": ArtifactStorageError(failed_count=2, prefix="graphrag/rag_9/"),
}


@get("/fails/{kind:str}/")
async def failing_route(kind: str) -> None:
    raise RAISED[kind]


@pytest.fixture
def client():
    app = Litestar(route_handlers=[failing_route], exception_handlers=get_error_handlers())
    with TestClient(app=app) as test_client:
        yield test_client


@pytest.mark.parametrize(
    ("kind", "raw_text"),
    [
        ("repository", "Repository call NaiveRagRepository.get_rag failed."),
        ("artifact-storage", "Could not delete 2 object(s) under 'graphrag/rag_9/'."),
    ],
)
def test_server_error_answers_a_fixed_detail_and_logs_the_raw_error(client, kind, raw_text):
    logged: list[str] = []
    sink_id = logger.add(logged.append, level="DEBUG", diagnose=False)
    try:
        response = client.get(f"/fails/{kind}/")
    finally:
        logger.remove(sink_id)

    assert response.status_code == 500
    assert response.json() == {
        "code": "internal_error",
        "detail": "The request failed because of a server error.",
    }
    assert raw_text in "".join(logged)
