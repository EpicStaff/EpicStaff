import json
import time
from datetime import timedelta
from uuid import UUID

import jwt
import pytest
from application.orchestrators.conversation import ConversationOrchestrator
from application.tokens import visitor_token_hash
from common.humanize import Rate
from common.utils import new_id, utcnow
from domain.enums import IdentityMode, Role, Stream
from domain.models import Message
from infrastructure.database.models import ConversationRow, VisitorTokenRow
from litestar.testing import AsyncTestClient
from main import create_app
from sqlalchemy import func, select, update
from tests.factories import make_binding
from tests.infrastructure.test_django_client import CHAT_FLOW
from tests.integration.test_callback_endpoint import CALLBACKS, _payload, _signed

ORIGIN = "https://example.com"


@pytest.fixture
async def binding(uow_factory, django):
    django.graphs[5] = CHAT_FLOW
    binding = make_binding(org_id=1, graph_id=5, max_message_length=20)
    async with uow_factory() as uow:
        await uow.bindings.add(binding)
        await uow.commit()
    return binding


async def _create(client, binding, origin=ORIGIN):
    response = await client.post("/chat/public/v1/conversations", json={"public_key": binding.public_key}, headers={"Origin": origin})
    assert response.status_code == 201, response.text
    body = response.json()
    return body["conversation_id"], {"Authorization": f"Bearer {body['visitor_token']}", "Origin": origin}


async def test_create_and_read_state(client, binding):
    created = await client.post("/chat/public/v1/conversations", json={"public_key": binding.public_key}, headers={"Origin": ORIGIN})
    assert created.status_code == 201
    body = created.json()
    assert set(body) == {"conversation_id", "visitor_token", "bot_display_name", "operator_display_name"}
    assert (body["bot_display_name"], body["operator_display_name"]) == ("Bot", "Support")
    headers = {"Authorization": f"Bearer {body['visitor_token']}", "Origin": ORIGIN}
    response = await client.get(f"/chat/public/v1/conversations/{body['conversation_id']}", headers=headers)
    assert response.status_code == 200
    assert response.json() == {"mode": "bot", "state": "idle", "bot_display_name": "Bot", "operator_display_name": "Support", "status": "open", "close_reason": None, "closed_at": None}


async def test_a_renamed_binding_shows_its_new_names_on_the_next_read(client, binding, uow_factory):
    conversation_id, headers = await _create(client, binding)
    async with uow_factory() as uow:
        stored = await uow.bindings.get(binding.id)
        stored.bot_display_name, stored.operator_display_name = "Ava", "Care team"
        await uow.bindings.update(stored)
        await uow.commit()
    state = (await client.get(f"/chat/public/v1/conversations/{conversation_id}", headers=headers)).json()
    assert (state["bot_display_name"], state["operator_display_name"]) == ("Ava", "Care team")


async def test_public_messages_carry_no_author_only_the_name_visitors_may_see(client, binding, uow_factory):
    conversation_id, headers = await _create(client, binding)
    async with uow_factory() as uow:
        await uow.messages.add(Message(id=new_id(), conversation_id=UUID(conversation_id), role=Role.USER, content="Hello", actions=None, session_id=None, created_at=utcnow(), author_user_id=None))
        await uow.messages.add(Message(id=new_id(), conversation_id=UUID(conversation_id), role=Role.OPERATOR, content="Hi", actions=None, session_id=None, created_at=utcnow(), author_user_id=7, visible_name="Mike"))
        await uow.commit()
    visitor_message, operator_message = (await client.get(f"/chat/public/v1/conversations/{conversation_id}/messages", headers=headers)).json()
    assert set(operator_message) == {"id", "role", "content", "actions", "action", "visible_name", "created_at"}
    assert (operator_message["role"], operator_message["visible_name"]) == ("operator", "Mike")
    assert visitor_message["visible_name"] is None


async def test_create_errors(client, binding):
    unknown = await client.post("/chat/public/v1/conversations", json={"public_key": "nope"}, headers={"Origin": ORIGIN})
    assert (unknown.status_code, unknown.json()["code"]) == (404, "not_found")
    origin = await client.post("/chat/public/v1/conversations", json={"public_key": binding.public_key}, headers={"Origin": "https://evil.example"})
    assert (origin.status_code, origin.json()["code"]) == (403, "origin_not_allowed")
    missing = await client.post("/chat/public/v1/conversations", json={}, headers={"Origin": ORIGIN})
    assert missing.status_code == 400 and missing.json()["code"] == "validation_error"


async def test_token_and_id_mismatch(client, binding):
    conversation_a, headers_a = await _create(client, binding)
    conversation_b, _ = await _create(client, binding)
    foreign = await client.get(f"/chat/public/v1/conversations/{conversation_b}", headers=headers_a)
    assert (foreign.status_code, foreign.json()["code"]) == (404, "not_found")
    bad = await client.get(f"/chat/public/v1/conversations/{conversation_a}", headers={"Authorization": "Bearer nope"})
    assert (bad.status_code, bad.json()["code"]) == (401, "invalid_token")
    none = await client.get(f"/chat/public/v1/conversations/{conversation_a}")
    assert none.status_code == 401


async def test_send_message_and_page(client, binding, django):
    conversation_id, headers = await _create(client, binding)
    sent = await client.post(f"/chat/public/v1/conversations/{conversation_id}/messages", json={"content": "hello"}, headers=headers)
    assert sent.status_code == 202 and sent.json()["state"] == "processing"
    state = await client.get(f"/chat/public/v1/conversations/{conversation_id}", headers=headers)
    assert state.json()["state"] == "processing"
    again = await client.post(f"/chat/public/v1/conversations/{conversation_id}/messages", json={"content": "more"}, headers=headers)
    assert (again.status_code, again.json()["code"]) == (409, "run_in_progress")
    page = await client.get(f"/chat/public/v1/conversations/{conversation_id}/messages?limit=50", headers=headers)
    assert page.status_code == 200
    assert [m["role"] for m in page.json()] == ["user"] and set(page.json()[0]) == {"id", "role", "content", "actions", "action", "visible_name", "created_at"}


async def test_message_errors(client, binding):
    conversation_id, headers = await _create(client, binding)
    too_long = await client.post(f"/chat/public/v1/conversations/{conversation_id}/messages", json={"content": "x" * 21}, headers=headers)
    assert (too_long.status_code, too_long.json()["code"]) == (413, "message_too_long")
    bad_origin = await client.post(f"/chat/public/v1/conversations/{conversation_id}/messages", json={"content": "x"}, headers={**headers, "Origin": "https://evil.example"})
    assert bad_origin.status_code == 403


async def test_rate_limit_carries_retry_after(client, uow_factory, django):
    django.graphs[5] = CHAT_FLOW
    binding = make_binding(org_id=1, graph_id=5, messages_per_minute=0)
    async with uow_factory() as uow:
        await uow.bindings.add(binding)
        await uow.commit()
    conversation_id, headers = await _create(client, binding)
    limited = await client.post(f"/chat/public/v1/conversations/{conversation_id}/messages", json={"content": "x"}, headers=headers)
    assert limited.status_code == 429 and limited.json()["code"] == "rate_limited" and limited.json()["retry_after"] >= 1


async def test_inactive_binding_is_410(client, binding, uow_factory):
    conversation_id, headers = await _create(client, binding)
    async with uow_factory() as uow:
        stored = await uow.bindings.get(binding.id)
        stored.is_active = False
        await uow.bindings.update(stored)
        await uow.commit()
    response = await client.post(f"/chat/public/v1/conversations/{conversation_id}/messages", json={"content": "x"}, headers=headers)
    assert (response.status_code, response.json()["code"]) == (410, "binding_inactive")


async def test_cors_preflight_is_answered(client, binding):
    response = await client.options(
        "/chat/public/v1/conversations",
        headers={"Origin": "https://anything.example", "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "authorization,content-type"},
    )
    assert response.status_code in (200, 204)
    assert response.headers["access-control-allow-origin"] == "*"


async def _add_binding(uow_factory, django, **overrides):
    django.graphs[5] = CHAT_FLOW
    binding = make_binding(org_id=1, graph_id=5, **overrides)
    async with uow_factory() as uow:
        await uow.bindings.add(binding)
        await uow.commit()
    return binding


async def test_signed_identity_codes_and_resume(client, uow_factory, django):
    binding = await _add_binding(uow_factory, django, identity_mode=IdentityMode.SIGNED, identity_secret="id-secret")
    url = "/chat/public/v1/conversations"
    headers = {"Origin": ORIGIN}
    claims = {"sub": "u1", "exp": int(time.time()) + 600}
    missing = await client.post(url, json={"public_key": binding.public_key}, headers=headers)
    assert (missing.status_code, missing.json()["code"]) == (401, "invalid_identity")
    forged = jwt.encode(claims, "other-secret", algorithm="HS256")
    wrong = await client.post(url, json={"public_key": binding.public_key, "identity_token": forged}, headers=headers)
    assert (wrong.status_code, wrong.json()["code"]) == (401, "invalid_identity")
    valid = {"public_key": binding.public_key, "identity_token": jwt.encode(claims, "id-secret", algorithm="HS256")}
    first = await client.post(url, json=valid, headers=headers)
    second = await client.post(url, json=valid, headers=headers)
    assert first.status_code == 201 and second.status_code == 201
    assert first.json()["conversation_id"] == second.json()["conversation_id"]


async def test_broken_binding_is_503(client, binding, uow_factory):
    conversation_id, headers = await _create(client, binding)
    async with uow_factory() as uow:
        stored = await uow.bindings.get(binding.id)
        stored.broken_reason = "gone"
        await uow.bindings.update(stored)
        await uow.commit()
    response = await client.post(f"/chat/public/v1/conversations/{conversation_id}/messages", json={"content": "x"}, headers=headers)
    assert (response.status_code, response.json()["code"]) == (503, "binding_broken")
    assert "gone" not in response.json()["message"].split()  # the default text, never the stored reason


async def test_flow_failure_is_503_and_releases_the_slot(client, binding, django):
    conversation_id, headers = await _create(client, binding)
    django.run_session_response = (500, {"error": "boom"})
    response = await client.post(f"/chat/public/v1/conversations/{conversation_id}/messages", json={"content": "x"}, headers=headers)
    assert (response.status_code, response.json()["code"]) == (503, "flow_unavailable")
    state = await client.get(f"/chat/public/v1/conversations/{conversation_id}", headers=headers)
    assert state.json()["state"] == "idle"


async def test_per_ip_message_limit(settings, binding, django, redis_client):
    limited_settings = settings.model_copy(update={"CHAT_IP_MESSAGE_RATE": Rate(1, 60)})
    app = create_app(limited_settings, django_transport=django.transport, redis_client=redis_client)
    async with AsyncTestClient(app=app) as limited_client:
        first_id, first_headers = await _create(limited_client, binding)
        second_id, second_headers = await _create(limited_client, binding)
        sent = await limited_client.post(f"/chat/public/v1/conversations/{first_id}/messages", json={"content": "a"}, headers=first_headers)
        assert sent.status_code == 202
        limited = await limited_client.post(f"/chat/public/v1/conversations/{second_id}/messages", json={"content": "b"}, headers=second_headers)
        assert (limited.status_code, limited.json()["code"]) == (429, "rate_limited")


@pytest.mark.parametrize("query", ["limit=0", "limit=101", "before=junk"])
async def test_paging_validation_is_400(client, binding, query):
    conversation_id, headers = await _create(client, binding)
    response = await client.get(f"/chat/public/v1/conversations/{conversation_id}/messages?{query}", headers=headers)
    assert response.status_code == 400 and response.json()["code"] == "validation_error"


async def test_oversized_message_is_413_from_the_binding_limit(client, binding):
    conversation_id, headers = await _create(client, binding)
    response = await client.post(f"/chat/public/v1/conversations/{conversation_id}/messages", json={"content": "x" * 100_001}, headers=headers)
    assert (response.status_code, response.json()["code"]) == (413, "message_too_long")


async def test_unexpected_error_is_logged_and_500(client, binding, monkeypatch):
    conversation_id, headers = await _create(client, binding)

    async def explode(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(ConversationOrchestrator, "resolve", explode)
    response = await client.get(f"/chat/public/v1/conversations/{conversation_id}", headers=headers)
    assert response.status_code == 500 and response.json() == {"code": "internal_error", "message": "Internal error."}


# ---- visitor token idle expiry and reads on an inactive binding --------------------------------

async def _set_token_times(session_factory, headers, **values):
    token_hash = visitor_token_hash(headers["Authorization"].removeprefix("Bearer "))
    async with session_factory() as session:
        await session.execute(update(VisitorTokenRow).where(VisitorTokenRow.token_hash == token_hash).values(**values))
        await session.commit()
    return token_hash


async def _last_used_at(session_factory, token_hash):
    async with session_factory() as session:
        return (await session.get(VisitorTokenRow, token_hash)).last_used_at


async def test_a_token_idle_past_the_ttl_answers_like_an_unknown_one(client, binding, session_factory, settings):
    conversation_id, headers = await _create(client, binding)
    await _set_token_times(session_factory, headers, last_used_at=utcnow() - timedelta(seconds=settings.CHAT_VISITOR_TOKEN_IDLE_TTL + 60))
    expired = await client.get(f"/chat/public/v1/conversations/{conversation_id}", headers=headers)
    unknown = await client.get(f"/chat/public/v1/conversations/{conversation_id}", headers={**headers, "Authorization": "Bearer nope"})
    assert expired.status_code == unknown.status_code == 401
    assert expired.json() == unknown.json()
    sent = await client.post(f"/chat/public/v1/conversations/{conversation_id}/messages", json={"content": "x"}, headers=headers)
    assert sent.status_code == 401 and sent.json() == unknown.json()


async def test_use_within_the_ttl_slides_the_expiry_past_the_tokens_age(client, binding, session_factory, settings):
    conversation_id, headers = await _create(client, binding)
    ttl = timedelta(seconds=settings.CHAT_VISITOR_TOKEN_IDLE_TTL)
    # Issued two TTLs ago, last used just inside the TTL: still valid, and the use refreshes it.
    token_hash = await _set_token_times(session_factory, headers, created_at=utcnow() - 2 * ttl, last_used_at=utcnow() - ttl + timedelta(hours=2))
    assert (await client.get(f"/chat/public/v1/conversations/{conversation_id}", headers=headers)).status_code == 200
    assert await _last_used_at(session_factory, token_hash) > utcnow() - timedelta(minutes=1)


async def test_use_within_the_refresh_interval_does_not_write(client, binding, session_factory):
    conversation_id, headers = await _create(client, binding)
    used = utcnow() - timedelta(minutes=30)
    token_hash = await _set_token_times(session_factory, headers, last_used_at=used)
    assert (await client.get(f"/chat/public/v1/conversations/{conversation_id}", headers=headers)).status_code == 200
    assert await _last_used_at(session_factory, token_hash) == used


async def test_reads_on_an_inactive_binding_are_410(client, binding, uow_factory):
    conversation_id, headers = await _create(client, binding)
    async with uow_factory() as uow:
        stored = await uow.bindings.get(binding.id)
        stored.is_active = False
        await uow.bindings.update(stored)
        await uow.commit()
    base = f"/chat/public/v1/conversations/{conversation_id}"
    for response in (
        await client.get(base, headers=headers),
        await client.get(f"{base}/messages", headers=headers),
        await client.post(f"{base}/stream-ticket", headers=headers),
    ):
        assert (response.status_code, response.json()["code"]) == (410, "binding_inactive")


# ---- action replies and chat_extra_data --------------------------------------------------------

def _run_variables(django) -> list[dict]:
    return [json.loads(r.content)["variables"] for r in django.requests if r.url.path == "/api/run-session/"]


async def _apply_reply(client, uow_factory, conversation_id, session_id=100):
    async with uow_factory() as uow:
        run_id = (await uow.conversations.get(UUID(conversation_id))).active_run_id
        secret = (await uow.receipts.get(run_id)).secret
    body, headers = _signed(secret, _payload(result={"reply": "Noted"}, session_id=session_id), session_id=session_id)
    assert (await client.post(f"{CALLBACKS}/{run_id}", content=body, headers=headers)).json() == {"result": "applied"}


async def test_an_action_reply_round_trips_to_messages_stream_and_flow(client, binding, django, uow_factory):
    conversation_id, headers = await _create(client, binding)
    action = {"type": "button", "id": "refund", "label": "Привіт"}
    sent = await client.post(f"/chat/public/v1/conversations/{conversation_id}/messages", json={"action": action}, headers=headers)
    assert sent.status_code == 202 and sent.json()["state"] == "processing"
    assert _run_variables(django)[0]["action"] == action and _run_variables(django)[0]["user_message"] == ""
    await _apply_reply(client, uow_factory, conversation_id)
    page = (await client.get(f"/chat/public/v1/conversations/{conversation_id}/messages", headers=headers)).json()
    assert [(m["role"], m["content"], m["action"]) for m in page] == [("user", "", action), ("assistant", "Noted", None)]
    async with uow_factory() as uow:
        events = await uow.events.replay(Stream.CONVERSATION, conversation_id=UUID(conversation_id), after_seq=None)
    assert [e.payload["action"] for e in events if e.type == "message.created"] == [action, None]


@pytest.mark.parametrize("body", [
    {},
    {"action": None},
    {"action": ["yes"]},
    {"action": "yes"},
    {"action": {"k": "x" * 2048}},
    {"action": {"a": {"b": {"__properties__": {"x": "1"}}}}},
    {"content": "hi", "chat_extra_data": {"k": "x" * 8192}},
    {"content": "hi", "chat_extra_data": {"__setters__": {}}},
    {"content": "hi", "chat_extra_data": [1]},
])
async def test_an_invalid_send_is_400_and_stores_nothing(client, binding, django, uow_factory, body):
    conversation_id, headers = await _create(client, binding)
    response = await client.post(f"/chat/public/v1/conversations/{conversation_id}/messages", json=body, headers=headers)
    assert (response.status_code, response.json()["code"]) == (400, "validation_error")
    assert (await client.get(f"/chat/public/v1/conversations/{conversation_id}/messages", headers=headers)).json() == []
    stored = await _stored_conversation(uow_factory, conversation_id)
    assert (stored.turns, stored.chat_extra_data) == (0, None)
    assert not _run_variables(django)


async def _stored_conversation(uow_factory, conversation_id):
    async with uow_factory() as uow:
        return await uow.conversations.get(UUID(conversation_id))


@pytest.mark.parametrize("extra_data", [{"k": "x" * 8192}, {"a": [{"__properties__": {}}]}, "text"])
async def test_an_invalid_create_is_400_and_creates_nothing(client, binding, session_factory, extra_data):
    body = {"public_key": binding.public_key, "chat_extra_data": extra_data}
    response = await client.post("/chat/public/v1/conversations", json=body, headers={"Origin": ORIGIN})
    assert (response.status_code, response.json()["code"]) == (400, "validation_error")
    async with session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(ConversationRow)) == 0


async def test_blank_content_without_an_action_is_413(client, binding):
    conversation_id, headers = await _create(client, binding)
    response = await client.post(f"/chat/public/v1/conversations/{conversation_id}/messages", json={"content": "  "}, headers=headers)
    assert (response.status_code, response.json()["code"]) == (413, "message_too_long")


async def test_action_replies_count_for_the_message_rate_and_turns(client, uow_factory, django):
    binding = await _add_binding(uow_factory, django, messages_per_minute=1)
    conversation_id, headers = await _create(client, binding)
    url = f"/chat/public/v1/conversations/{conversation_id}/messages"
    assert (await client.post(url, json={"action": {"id": "a"}}, headers=headers)).status_code == 202
    await _apply_reply(client, uow_factory, conversation_id)
    assert (await _stored_conversation(uow_factory, conversation_id)).turns == 1
    limited = await client.post(url, json={"action": {"id": "b"}}, headers=headers)
    assert (limited.status_code, limited.json()["code"]) == (429, "rate_limited")


async def test_chat_extra_data_from_create_reaches_the_flow_and_a_send_replaces_it(client, binding, django, uow_factory):
    created = await client.post("/chat/public/v1/conversations", json={"public_key": binding.public_key, "chat_extra_data": {"plan": "pro"}}, headers={"Origin": ORIGIN})
    assert created.status_code == 201 and set(created.json()) == {"conversation_id", "visitor_token", "bot_display_name", "operator_display_name"}
    conversation_id = created.json()["conversation_id"]
    headers = {"Authorization": f"Bearer {created.json()['visitor_token']}", "Origin": ORIGIN}
    url = f"/chat/public/v1/conversations/{conversation_id}/messages"
    await client.post(url, json={"content": "one"}, headers=headers)
    await _apply_reply(client, uow_factory, conversation_id)
    await client.post(url, json={"content": "two", "chat_extra_data": {"page": "/b"}}, headers=headers)
    assert [v["chat_extra_data"] for v in _run_variables(django)] == [{"plan": "pro"}, {"page": "/b"}]


async def test_chat_user_id_is_the_signed_sub_and_null_when_anonymous(client, binding, uow_factory, django):
    signed = await _add_binding(uow_factory, django, identity_mode=IdentityMode.SIGNED, identity_secret="id-secret")
    identity = jwt.encode({"sub": "customer-9", "exp": int(time.time()) + 600}, "id-secret", algorithm="HS256")
    created = (await client.post("/chat/public/v1/conversations", json={"public_key": signed.public_key, "identity_token": identity}, headers={"Origin": ORIGIN})).json()
    signed_headers = {"Authorization": f"Bearer {created['visitor_token']}", "Origin": ORIGIN}
    await client.post(f"/chat/public/v1/conversations/{created['conversation_id']}/messages", json={"content": "a"}, headers=signed_headers)
    anonymous_id, anonymous_headers = await _create(client, binding)
    await client.post(f"/chat/public/v1/conversations/{anonymous_id}/messages", json={"content": "b"}, headers=anonymous_headers)
    assert [v["chat_user_id"] for v in _run_variables(django)] == ["customer-9", None]


async def test_a_sub_longer_than_the_subject_column_is_an_invalid_identity(client, uow_factory, django):
    signed = await _add_binding(uow_factory, django, identity_mode=IdentityMode.SIGNED, identity_secret="id-secret")
    identity = jwt.encode({"sub": "x" * 256, "exp": int(time.time()) + 600}, "id-secret", algorithm="HS256")
    response = await client.post("/chat/public/v1/conversations", json={"public_key": signed.public_key, "identity_token": identity}, headers={"Origin": ORIGIN})
    assert (response.status_code, response.json()["code"]) == (401, "invalid_identity")


async def test_another_conversations_token_cannot_send_an_action_or_extra_data(client, binding, django, uow_factory):
    _, headers_a = await _create(client, binding)
    conversation_b, _ = await _create(client, binding)
    url = f"/chat/public/v1/conversations/{conversation_b}/messages"
    body = {"action": {"id": "x"}, "chat_extra_data": {"hijack": True}}
    foreign = await client.post(url, json=body, headers=headers_a)
    assert (foreign.status_code, foreign.json()["code"]) == (404, "not_found")
    unknown = await client.post(url, json=body, headers={**headers_a, "Authorization": "Bearer nope"})
    assert (unknown.status_code, unknown.json()["code"]) == (401, "invalid_token")
    stored = await _stored_conversation(uow_factory, conversation_b)
    assert (stored.chat_extra_data, stored.last_message_at) == (None, None)
    assert not _run_variables(django)


# ---- body limits and characters Postgres cannot store ------------------------------------------

async def test_a_body_over_one_mebibyte_is_413_before_any_handler_work(client, binding, monkeypatch):
    conversation_id, headers = await _create(client, binding)
    calls = []

    async def recording_submit(*args, **kwargs):
        calls.append(args)

    monkeypatch.setattr(ConversationOrchestrator, "submit", recording_submit)
    body = json.dumps({"content": "x" * (1024 * 1024)})
    response = await client.post(f"/chat/public/v1/conversations/{conversation_id}/messages", content=body, headers={**headers, "Content-Type": "application/json"})
    assert response.status_code == 413 and calls == []
    create = await client.post("/chat/public/v1/conversations", content=json.dumps({"public_key": binding.public_key, "chat_extra_data": {"k": "x" * (1024 * 1024)}}), headers={"Origin": ORIGIN, "Content-Type": "application/json"})
    assert create.status_code == 413


async def test_a_largest_legitimate_body_fits_under_the_cap(client, uow_factory, django):
    binding = await _add_binding(uow_factory, django, max_message_length=100_000)
    conversation_id, headers = await _create(client, binding)
    # Worst case: every character escaped as \uXXXX, plus both objects at their caps.
    body = json.dumps({"content": " " * 100_000, "action": {"k": "x" * 2000}, "chat_extra_data": {"k": "x" * 8000}}, ensure_ascii=True)
    response = await client.post(f"/chat/public/v1/conversations/{conversation_id}/messages", content=body, headers={**headers, "Content-Type": "application/json"})
    assert response.status_code == 202, response.text


@pytest.mark.parametrize("body", [
    {"content": "hi\x00"},
    {"action": {"id": "\x00"}},
    {"content": "hi", "chat_extra_data": {"k\x00": 1}},
])
async def test_nul_is_400_and_leaves_the_conversation_usable(client, binding, django, body):
    conversation_id, headers = await _create(client, binding)
    url = f"/chat/public/v1/conversations/{conversation_id}/messages"
    refused = await client.post(url, json=body, headers=headers)
    assert (refused.status_code, refused.json()["code"]) == (400, "validation_error")
    # Nothing was claimed: the next message runs instead of answering 409.
    assert (await client.post(url, json={"content": "hello"}, headers=headers)).status_code == 202


async def test_json_nested_beyond_the_decoder_limit_is_400(client, binding):
    conversation_id, headers = await _create(client, binding)
    body = '{"content":"x","chat_extra_data":' + '{"a":' * 10_000 + "1" + "}" * 10_000 + "}"
    response = await client.post(f"/chat/public/v1/conversations/{conversation_id}/messages", content=body, headers={**headers, "Content-Type": "application/json"})
    assert (response.status_code, response.json()["code"]) == (400, "validation_error")


# ---- the visitor ends the conversation ("Start a new chat") ----------------------------------------

async def test_ending_closes_the_conversation_and_answers_its_state_again_and_again(client, binding, uow_factory):
    conversation_id, headers = await _create(client, binding)
    url = f"/chat/public/v1/conversations/{conversation_id}"
    ended = await client.post(f"{url}/end", headers=headers)
    assert ended.status_code == 200, ended.text
    body = ended.json()
    assert {key: body[key] for key in ("mode", "state", "status", "close_reason")} == {"mode": "bot", "state": "idle", "status": "closed", "close_reason": "ended"}
    assert body["closed_at"] is not None and set(body) == {"mode", "state", "bot_display_name", "operator_display_name", "status", "close_reason", "closed_at"}
    again = await client.post(f"{url}/end", headers=headers)
    assert (again.status_code, again.json()) == (200, body)
    assert (await client.get(url, headers=headers)).json() == body
    async with uow_factory() as uow:
        events = await uow.events.replay(Stream.CONVERSATION, conversation_id=UUID(conversation_id), after_seq=None)
    assert [e.type for e in events] == ["conversation.closed"]  # the second end changed nothing


async def test_a_message_after_the_end_is_409_and_the_history_stays_readable(client, binding):
    conversation_id, headers = await _create(client, binding)
    url = f"/chat/public/v1/conversations/{conversation_id}"
    assert (await client.post(f"{url}/messages", json={"content": "hello"}, headers=headers)).status_code == 202
    await client.post(f"{url}/end", headers=headers)
    refused = await client.post(f"{url}/messages", json={"content": "anyone?"}, headers=headers)
    assert refused.status_code == 409
    assert refused.json() == {"code": "conversation_closed", "message": refused.json()["message"], "close_reason": "ended"} and refused.json()["message"]
    # The visitor token outlives the close: history, state and the stream stay open to it.
    assert [m["content"] for m in (await client.get(f"{url}/messages", headers=headers)).json()] == ["hello"]
    assert (await client.post(f"{url}/stream-ticket", headers=headers)).status_code == 201


async def test_ending_needs_the_conversations_token_and_an_allowed_origin_on_a_live_desk(client, binding, uow_factory):
    conversation_id, headers = await _create(client, binding)
    _, other_headers = await _create(client, binding)
    url = f"/chat/public/v1/conversations/{conversation_id}/end"
    refusals = {
        "no token": (await client.post(url, headers={"Origin": ORIGIN}), 401, "invalid_token"),
        "unknown token": (await client.post(url, headers={**headers, "Authorization": "Bearer nope"}), 401, "invalid_token"),
        "another conversation's token": (await client.post(url, headers=other_headers), 404, "not_found"),
        "another origin": (await client.post(url, headers={**headers, "Origin": "https://evil.example"}), 403, "origin_not_allowed"),
    }
    async with uow_factory() as uow:
        stored = await uow.bindings.get(binding.id)
        stored.is_active = False
        await uow.bindings.update(stored)
        await uow.commit()
    refusals["a paused desk"] = (await client.post(url, headers=headers), 410, "binding_inactive")
    for name, (response, status, code) in refusals.items():
        assert (response.status_code, response.json()["code"]) == (status, code), name
    async with uow_factory() as uow:
        assert (await uow.conversations.get(UUID(conversation_id))).is_open
