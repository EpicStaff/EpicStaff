"""The error envelope every Litestar service answers with, through a real app."""

import pydantic
import pytest
from litestar import Litestar, get
from litestar.testing import TestClient
from loguru import logger

from foundation.schemas import ErrorDetailSchema
from foundation.utils.litestar import error_handler

RAW_ERROR_TEXT = 'relation "secret" does not exist at /var/lib/postgresql'


class _Limited(pydantic.BaseModel):
    count: int = pydantic.Field(le=3)


@get("/explodes")
async def explodes() -> None:
    raise RuntimeError(RAW_ERROR_TEXT)


@get("/invalid-model")
async def invalid_model() -> None:
    _Limited(count=4)


@get("/with-context")
async def with_context() -> None:
    raise _ContextualError()


class _ContextualError(Exception):
    pass


@error_handler.registry(_ContextualError)
def _handle_contextual_error(request, error):
    return error_handler.create_response(
        status_code=409,
        errors=[ErrorDetailSchema(code="blocked", detail="Blocked.", context={"max": 3})],
    )


@pytest.fixture
def client():
    app = Litestar(
        route_handlers=[explodes, invalid_model, with_context],
        exception_handlers=error_handler.get_handlers(),
    )
    with TestClient(app=app) as test_client:
        yield test_client


def test_an_unhandled_error_answers_a_fixed_detail_and_logs_the_raw_error(client):
    logged: list[str] = []
    sink_id = logger.add(logged.append, level="ERROR")
    try:
        response = client.get("/explodes")
    finally:
        logger.remove(sink_id)

    assert response.status_code == 500
    assert response.json() == {
        "type": "server_error",
        "errors": [
            {"code": "unknown", "detail": "Internal server error.", "attr": None, "context": None}
        ],
    }
    assert RAW_ERROR_TEXT in "".join(logged)


@pytest.mark.parametrize("path", ["/invalid-model", "/no-such-route"])
def test_every_item_carries_attr_and_context_even_when_null(client, path):
    response = client.get(path)

    assert response.status_code in (400, 404)
    for item in response.json()["errors"]:
        assert set(item) == {"code", "detail", "attr", "context"}
        assert item["context"] is None


def test_context_reaches_the_caller(client):
    response = client.get("/with-context")

    assert response.status_code == 409
    assert response.json()["errors"] == [
        {"code": "blocked", "detail": "Blocked.", "attr": None, "context": {"max": 3}}
    ]
