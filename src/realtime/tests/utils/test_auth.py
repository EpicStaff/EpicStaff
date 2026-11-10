"""DjangoAuthClient: token introspection against Django's auth API.

Django is the external boundary, replaced by an `httpx.MockTransport` that answers
the two auth endpoints and records every request it receives.
"""

import asyncio
import json

import httpx
import pytest
import pytest_asyncio

from utils.auth import DjangoAuthClient

pytestmark = pytest.mark.asyncio

BASE_URL = "http://django:8000"
VALIDATE_PATH = "/api/auth/api-key/validate/"
INTROSPECT_PATH = "/api/auth/introspect/"
ACTIVE_USER = {"active": True, "user_id": 1, "org_ids": [1], "is_superadmin": False}


class FakeDjangoAuth:
    """Answers the auth endpoints with scripted responses; records what it was sent."""

    def __init__(self):
        self.answers: dict[str, httpx.Response | Exception] = {
            VALIDATE_PATH: httpx.Response(200, json={"active": True}),
            INTROSPECT_PATH: httpx.Response(200, json=ACTIVE_USER),
        }
        self.requests: list[httpx.Request] = []
        # Set, a request waits for it before answering: lets a test hold handshakes open.
        self.hold: asyncio.Event | None = None

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.hold is not None:
            await self.hold.wait()
        answer = self.answers[request.url.path]
        if isinstance(answer, Exception):
            raise answer
        return answer

    def paths(self) -> list[str]:
        return [request.url.path for request in self.requests]


@pytest.fixture
def django():
    return FakeDjangoAuth()


@pytest_asyncio.fixture
async def auth_client(django):
    client = DjangoAuthClient(
        base_url=BASE_URL, api_key="service-key", timeout=5.0, transport=httpx.MockTransport(django)
    )
    await client.start()
    yield client
    await client.stop()


async def test_active_token_returns_the_introspection(auth_client, django):
    assert await auth_client.introspect_token("user-token") == ACTIVE_USER

    validate, introspect = django.requests
    assert str(validate.url) == f"{BASE_URL}{VALIDATE_PATH}"
    assert str(introspect.url) == f"{BASE_URL}{INTROSPECT_PATH}"
    assert json.loads(introspect.content) == {"token": "user-token"}
    # Django would reject the compose service name as a Host header.
    for request in django.requests:
        assert request.headers["Host"] == "localhost"
        assert request.headers["X-API-Key"] == "service-key"


async def test_a_validated_api_key_is_not_checked_again(auth_client, django):
    await auth_client.introspect_token("first")
    await auth_client.introspect_token("second")

    assert django.paths() == [VALIDATE_PATH, INTROSPECT_PATH, INTROSPECT_PATH]


@pytest.mark.parametrize(
    "answer",
    [
        pytest.param(httpx.Response(200, json={"active": False}), id="inactive"),
        pytest.param(httpx.Response(403, json={"detail": "forbidden"}), id="non-200"),
        pytest.param(httpx.Response(200, text="<html>proxy</html>"), id="non-json-200"),
        pytest.param(httpx.Response(200, json=["active"]), id="non-object-200"),
        pytest.param(httpx.ConnectTimeout("timed out"), id="request-error"),
    ],
)
async def test_refused_api_key_rejects_the_token_and_is_checked_again_next_time(
    auth_client, django, answer
):
    django.answers[VALIDATE_PATH] = answer

    assert await auth_client.introspect_token("user-token") is None
    assert await auth_client.introspect_token("user-token") is None

    assert django.paths() == [VALIDATE_PATH, VALIDATE_PATH]


@pytest.mark.parametrize(
    "answer",
    [
        pytest.param(httpx.Response(200, json={"active": False}), id="inactive"),
        pytest.param(httpx.Response(401, json={"detail": "bad token"}), id="non-200"),
        pytest.param(httpx.Response(200, text="<html>proxy</html>"), id="non-json-200"),
        pytest.param(httpx.Response(200, content=b"null"), id="non-object-200"),
        pytest.param(httpx.ConnectError("connection refused"), id="request-error"),
    ],
)
async def test_refused_or_failed_introspection_returns_none(auth_client, django, answer):
    django.answers[INTROSPECT_PATH] = answer

    assert await auth_client.introspect_token("user-token") is None


async def test_handshakes_waiting_on_django_do_not_block_each_other(auth_client, django):
    """Both cold-start handshakes reach Django while neither has an answer yet."""
    django.hold = asyncio.Event()

    first = asyncio.create_task(auth_client.introspect_token("first"))
    second = asyncio.create_task(auth_client.introspect_token("second"))
    async with asyncio.timeout(1):
        while len(django.requests) < 2:
            await asyncio.sleep(0)
        django.hold.set()
        results = await asyncio.gather(first, second)

    assert results == [ACTIVE_USER, ACTIVE_USER]
