"""The error envelope the real app answers with, for the framework's own refusals.

No lifespan runs, so no OpenSearch or Redis is needed: every request here stops at
routing, the authorization gate or request validation.
"""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from loguru import logger

from app.main import create_app
from tests._auth import auth

pytestmark = pytest.mark.asyncio

SEARCH_PATH = "/api/audit/sessions/search"


def _client_error(code: str, detail: str, attr: str | None = None) -> dict:
    return {"code": code, "detail": detail, "attr": attr, "context": None}


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client


@pytest.fixture
def logged():
    messages: list[str] = []
    sink_id = logger.add(messages.append, format="{message}")
    yield messages
    logger.remove(sink_id)


async def test_rejected_token_names_no_failed_check_but_logs_it(client, logged):
    response = await client.post(SEARCH_PATH, json={}, headers=auth(iss="someone-else"))

    assert response.status_code == 401
    assert response.json() == {
        "type": "client_error",
        "errors": [_client_error("unauthorized", "Invalid or expired token")],
    }
    assert "issuer" not in response.text.lower()
    assert any("Invalid issuer" in message for message in logged)


@pytest.mark.parametrize(
    ("method", "path", "headers", "status", "error"),
    [
        ("POST", SEARCH_PATH, {}, 401, _client_error("unauthorized", "Missing bearer token")),
        (
            "POST",
            SEARCH_PATH,
            auth(AUDIT=["export"]),
            403,
            _client_error("forbidden", "Missing AUDIT:read permission"),
        ),
        ("GET", "/api/audit/no-such-route", {}, 404, _client_error("not_found", "Not Found")),
        (
            "GET",
            SEARCH_PATH,
            {},
            405,
            _client_error("method_not_allowed", "Method Not Allowed"),
        ),
    ],
    ids=["no-token", "missing-grant", "unknown-route", "wrong-method"],
)
async def test_http_refusal_carries_its_status_phrase_as_code(
    client, method, path, headers, status, error
):
    response = await client.request(method, path, headers=headers, json={})

    assert response.status_code == status
    assert response.json() == {"type": "client_error", "errors": [error]}


async def test_http_refusal_keeps_its_headers(client):
    response = await client.get(SEARCH_PATH)

    assert response.status_code == 405
    assert response.headers["Allow"] == "POST"


@pytest.mark.parametrize(
    ("body", "error"),
    [
        (
            {"size": 0},
            _client_error(
                "greater_than_equal", "Input should be greater than or equal to 1", "size"
            ),
        ),
        (
            {"match_scope": {"rows_before": -1}},
            _client_error(
                "greater_than_equal",
                "Input should be greater than or equal to 0",
                "match_scope.rows_before",
            ),
        ),
        (
            {"bogus": True},
            _client_error("extra_forbidden", "Extra inputs are not permitted", "bogus"),
        ),
        (
            {"filters": {"field": "status", "op": "equals", "value": "failed"}, "query": "x"},
            _client_error(
                "value_error",
                "Value error, 'filters' and 'query' are mutually exclusive - send exactly one",
            ),
        ),
    ],
    ids=["top-level-field", "nested-field", "unknown-field", "rule-across-fields"],
)
async def test_invalid_body_reports_each_field_by_its_path(client, body, error):
    response = await client.post(SEARCH_PATH, json=body, headers=auth())

    assert response.status_code == 422
    assert response.json() == {"type": "client_error", "errors": [error]}


async def test_invalid_body_reports_every_problem(client):
    response = await client.post(
        SEARCH_PATH, json={"size": 0, "match_scope": {"rows_before": -1}}, headers=auth()
    )

    assert response.status_code == 422
    assert sorted(error["attr"] for error in response.json()["errors"]) == [
        "match_scope.rows_before",
        "size",
    ]


async def test_unparseable_body_is_reported_without_a_field(client):
    response = await client.post(
        SEARCH_PATH,
        content=b'{"size": ',
        headers={**auth(), "Content-Type": "application/json"},
    )

    assert response.status_code == 422
    assert response.json() == {
        "type": "client_error",
        "errors": [_client_error("json_invalid", "JSON decode error")],
    }


async def test_invalid_value_is_not_echoed_back(client):
    response = await client.post(SEARCH_PATH, json={"size": "secret-value"}, headers=auth())

    assert response.status_code == 422
    assert response.json()["errors"][0]["code"] == "int_parsing"
    assert "secret-value" not in response.text


async def test_an_unhandled_error_is_a_500_that_hides_its_text():
    app = create_app()

    @app.get("/boom")
    async def boom():
        raise RuntimeError("secret internal detail")

    # Starlette re-raises after answering, so the server logs it; the client still gets the answer.
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as http_client:
        response = await http_client.get("/boom")

    assert response.status_code == 500
    assert response.json() == {
        "type": "server_error",
        "errors": [_client_error("unknown", "Internal server error.")],
    }
    assert "secret internal detail" not in response.text
