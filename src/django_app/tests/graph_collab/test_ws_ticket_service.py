"""
Unit + integration tests for TicketService (ws variant) and TicketAuthMiddleware.

Redis is replaced with fakeredis.FakeStrictRedis so the real set/getdel logic
runs without a live Redis server.  DB access is minimal: only user creation
and deletion.
"""

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser

from tables.graph_collab.ws_auth import TicketAuthMiddleware
from tables.services.rbac.ticket_service import TicketService


def make_ws_service():
    return TicketService(
        prefix="rbac:ws_ticket:", ttl_seconds=settings.GRAPH_WS_TICKET_TTL_SECONDS
    )


# ---------------------------------------------------------------------------
# TicketService (ws) tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_issue_returns_token_and_stores_user(fake_redis):
    service = make_ws_service()
    User = get_user_model()
    user = User.objects.create_user(email="ticket1@example.com", password="Pass123!")

    token, ttl = service.issue(user)

    assert isinstance(token, str) and len(token) > 0
    assert isinstance(ttl, int) and ttl > 0
    stored = fake_redis.get(service._key(token))
    assert stored is not None
    assert int(stored) == user.pk


@pytest.mark.django_db
def test_consume_valid_ticket_returns_user(fake_redis):
    service = make_ws_service()
    User = get_user_model()
    user = User.objects.create_user(email="ticket2@example.com", password="Pass123!")

    token, _ = service.issue(user)
    result = service.consume(token)

    assert result is not None
    assert result.pk == user.pk


@pytest.mark.django_db
def test_consume_is_single_use(fake_redis):
    service = make_ws_service()
    User = get_user_model()
    user = User.objects.create_user(email="ticket3@example.com", password="Pass123!")

    token, _ = service.issue(user)

    first = service.consume(token)
    assert first is not None

    second = service.consume(token)
    assert second is None


@pytest.mark.django_db
def test_consume_empty_ticket_returns_none(fake_redis):
    service = make_ws_service()

    assert service.consume("") is None
    # No redis hit expected — early return before key lookup.
    assert fake_redis.dbsize() == 0


@pytest.mark.django_db
def test_consume_unknown_ticket_returns_none(fake_redis):
    service = make_ws_service()

    result = service.consume("completely-unknown-token")

    assert result is None


@pytest.mark.django_db
def test_consume_corrupted_value_returns_none(fake_redis):
    service = make_ws_service()

    fake_redis.set(service._key("bad"), b"not-an-int")
    result = service.consume("bad")

    assert result is None


@pytest.mark.django_db
def test_consume_deleted_user_returns_none(fake_redis):
    service = make_ws_service()
    User = get_user_model()
    user = User.objects.create_user(email="ticket4@example.com", password="Pass123!")

    token, _ = service.issue(user)
    user.delete()

    result = service.consume(token)
    assert result is None


@pytest.mark.django_db
def test_ttl_matches_setting(fake_redis):
    service = make_ws_service()
    User = get_user_model()
    user = User.objects.create_user(email="ticket5@example.com", password="Pass123!")

    token, _ = service.issue(user)
    ttl = fake_redis.ttl(service._key(token))

    assert ttl > 0
    assert ttl <= settings.GRAPH_WS_TICKET_TTL_SECONDS


# ---------------------------------------------------------------------------
# TicketAuthMiddleware._extract_ticket (pure, no I/O)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "query_string, expected",
    [
        ("ticket=abc", "abc"),
        ("foo=1&ticket=abc&bar=2", "abc"),
        ("foo=1&bar=2", ""),
        ("", ""),
    ],
)
def test_extract_ticket(query_string: str, expected: str):
    assert TicketAuthMiddleware._extract_ticket(query_string) == expected


# ---------------------------------------------------------------------------
# TicketAuthMiddleware.__call__ (async, uses fake redis)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_middleware_sets_user_for_valid_ticket(fake_redis):
    service = make_ws_service()
    User = get_user_model()
    from asgiref.sync import sync_to_async

    user = await sync_to_async(User.objects.create_user)(
        email="mw1@example.com", password="Pass123!"
    )
    token, _ = service.issue(user)

    captured: dict = {}

    async def inner(scope, receive, send):
        captured["user"] = scope["user"]

    middleware = TicketAuthMiddleware(inner)
    scope = {
        "type": "websocket",
        "query_string": f"ticket={token}".encode(),
    }
    await middleware(scope, None, None)

    assert "user" in captured
    assert captured["user"].pk == user.pk


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_middleware_sets_anonymous_for_missing_ticket(fake_redis):
    captured: dict = {}

    async def inner(scope, receive, send):
        captured["user"] = scope["user"]

    middleware = TicketAuthMiddleware(inner)
    scope = {
        "type": "websocket",
        "query_string": b"",
    }
    await middleware(scope, None, None)

    assert "user" in captured
    assert isinstance(captured["user"], AnonymousUser)
