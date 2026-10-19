import asyncio
import json
import time
from uuid import UUID

import pytest
from application.orchestrators.conversation import ConversationOrchestrator, RunConfig
from common.humanize import Rate
from common.utils import new_id
from domain.enums import Role, RunState, SubmitState
from infrastructure.callback_verifier import SESSION_ID_HEADER, SIGNATURE_HEADER, TIMESTAMP_HEADER, sign
from infrastructure.redis.counters import RedisRateLimiter
from infrastructure.redis.fanout import RedisFanout
from tests.factories import make_binding
from tests.infrastructure.test_django_client import CHAT_FLOW
from tests.integration.test_conversation_lifecycle import GatedFlows

CALLBACKS = "/chat/internal/v1/session-callbacks"
ORIGIN = "https://example.com"


async def _start(client, uow_factory, django):
    """Send "hi" on a fresh conversation. Returns its id, the visitor headers, the send response, and its run's id and secret."""
    django.graphs[5] = CHAT_FLOW
    binding = make_binding(org_id=1, graph_id=5)
    async with uow_factory() as uow:
        await uow.bindings.add(binding)
        await uow.commit()
    created = (await client.post("/chat/public/v1/conversations", json={"public_key": binding.public_key}, headers={"Origin": ORIGIN})).json()
    headers = {"Authorization": f"Bearer {created['visitor_token']}", "Origin": ORIGIN}
    sent = await client.post(f"/chat/public/v1/conversations/{created['conversation_id']}/messages", json={"content": "hi"}, headers=headers)
    async with uow_factory() as uow:
        run_id = (await uow.conversations.get(UUID(created["conversation_id"]))).active_run_id
        secret = (await uow.receipts.get(run_id)).secret
    return created["conversation_id"], headers, sent, run_id, secret


@pytest.fixture
async def running(client, uow_factory, django):
    """A conversation with a run in flight (session 100): its id, visitor headers, callback secret and callback URL."""
    conversation_id, headers, _, run_id, secret = await _start(client, uow_factory, django)
    return conversation_id, headers, secret, f"{CALLBACKS}/{run_id}"


def _signed(secret: str, payload: dict, *, session_id=100, timestamp=None) -> tuple[bytes, dict]:
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    timestamp = timestamp or str(int(time.time()))
    return body, {
        "Content-Type": "application/json",
        SESSION_ID_HEADER: str(session_id),
        TIMESTAMP_HEADER: timestamp,
        SIGNATURE_HEADER: sign(secret, timestamp, body),
    }


def _payload(status="end", result=None, tokens=7, session_id=100):
    return {"session_id": session_id, "graph_id": 5, "status": status, "end_node_result": result, "token_usage": {"total_tokens": tokens}, "finished_at": "2026-10-09T12:00:00+00:00"}


async def test_valid_callback_is_applied_once(client, running):
    conversation_id, headers, secret, url = running
    body, signed_headers = _signed(secret, _payload(result={"reply": "Привіт", "actions": []}))
    first = await client.post(url, content=body, headers=signed_headers)
    assert first.status_code == 200 and first.json() == {"result": "applied"}
    state = await client.get(f"/chat/public/v1/conversations/{conversation_id}", headers=headers)
    assert state.json()["state"] == "idle"
    page = (await client.get(f"/chat/public/v1/conversations/{conversation_id}/messages", headers=headers)).json()
    assert [m["role"] for m in page] == ["user", "assistant"] and page[1]["content"] == "Привіт"
    # Django retries after a lost 2xx: same body, fresh timestamp and signature; the secret is gone, so it is ignored.
    body, replay_headers = _signed(secret, _payload(result={"reply": "again"}))
    second = await client.post(url, content=body, headers=replay_headers)
    assert second.status_code == 200 and second.json() == {"result": "ignored"}
    assert len((await client.get(f"/chat/public/v1/conversations/{conversation_id}/messages", headers=headers)).json()) == 2


async def test_bad_signature_is_401_and_changes_nothing(client, running):
    conversation_id, headers, secret, url = running
    body, signed_headers = _signed("wrong-secret-wrong-secret-wrong-secret", _payload(result={"reply": "x"}))
    response = await client.post(url, content=body, headers=signed_headers)
    assert response.status_code == 401 and response.json()["code"] == "invalid_signature"
    assert (await client.get(f"/chat/public/v1/conversations/{conversation_id}", headers=headers)).json()["state"] == "processing"


async def test_stale_timestamp_is_401(client, running):
    _, _, secret, url = running
    body, signed_headers = _signed(secret, _payload(result={"reply": "x"}), timestamp=str(int(time.time()) - 3600))
    response = await client.post(url, content=body, headers=signed_headers)
    assert response.status_code == 401


async def test_unknown_run_is_404_so_django_retries(client, running):
    body, signed_headers = _signed("whatever", _payload())
    response = await client.post(f"{CALLBACKS}/{new_id()}", content=body, headers=signed_headers)
    assert response.status_code == 404 and response.json()["code"] == "unknown_run"


async def test_session_other_than_the_bound_one_is_rejected(client, running):
    conversation_id, headers, secret, url = running  # bound to session 100 by the start response
    body, signed_headers = _signed(secret, _payload(session_id=101, result={"reply": "not mine"}), session_id=101)
    response = await client.post(url, content=body, headers=signed_headers)
    assert (response.status_code, response.json()["code"]) == (409, "session_mismatch")
    assert (await client.get(f"/chat/public/v1/conversations/{conversation_id}", headers=headers)).json()["state"] == "processing"
    # The right session still applies afterwards: the rejection left the receipt untouched.
    body, signed_headers = _signed(secret, _payload(result={"reply": "mine"}))
    assert (await client.post(url, content=body, headers=signed_headers)).json() == {"result": "applied"}


async def test_applied_session_is_ignored_without_verification(client, running):
    _, _, secret, url = running
    body, signed_headers = _signed(secret, _payload(result={"reply": "done"}))
    assert (await client.post(url, content=body, headers=signed_headers)).json() == {"result": "applied"}
    # The secret is cleared on apply; there is nothing left to verify a late retry against.
    body, signed_headers = _signed(secret, _payload(result={"reply": "late"}), timestamp=str(int(time.time()) - 3600))
    response = await client.post(url, content=body, headers=signed_headers)
    assert response.status_code == 200 and response.json() == {"result": "ignored"}


async def test_header_and_body_session_must_match(client, running):
    _, _, secret, url = running
    body, signed_headers = _signed(secret, _payload(session_id=101), session_id=100)
    response = await client.post(url, content=body, headers=signed_headers)
    assert response.status_code == 400


async def test_missing_headers_is_400(client, running):
    _, _, _, url = running
    response = await client.post(url, content=b"{}", headers={"Content-Type": "application/json"})
    assert response.status_code == 400


async def test_non_terminal_status_is_400(client, running):
    _, _, secret, url = running
    body, signed_headers = _signed(secret, _payload(status="run"))
    response = await client.post(url, content=body, headers=signed_headers)
    assert response.status_code == 400


async def test_non_ascii_digits_in_the_session_header_are_400(client, running):
    _, _, secret, url = running
    body, signed_headers = _signed(secret, _payload())
    response = await client.post(url, content=body, headers={**signed_headers, SESSION_ID_HEADER: "²".encode("latin-1")})
    assert response.status_code == 400


async def test_start_with_a_lost_answer_is_processing_and_its_callback_applies(client, uow_factory, django):
    django.lose_run_session_response = True  # Django starts session 100; the chat never hears so
    conversation_id, headers, sent, run_id, secret = await _start(client, uow_factory, django)
    assert sent.status_code == 202 and sent.json()["state"] == "processing"
    async with uow_factory() as uow:
        receipt = await uow.receipts.get(run_id)
    assert receipt.session_id is None and receipt.received_at is None and secret
    page = (await client.get(f"/chat/public/v1/conversations/{conversation_id}/messages", headers=headers)).json()
    assert [m["role"] for m in page] == ["user"]  # no error notice

    body, signed_headers = _signed(secret, _payload(result={"reply": "late but here"}, tokens=9))
    response = await client.post(f"{CALLBACKS}/{run_id}", content=body, headers=signed_headers)
    assert response.json() == {"result": "applied"}
    assert (await client.get(f"/chat/public/v1/conversations/{conversation_id}", headers=headers)).json()["state"] == "idle"
    page = (await client.get(f"/chat/public/v1/conversations/{conversation_id}/messages", headers=headers)).json()
    assert [(m["role"], m["content"]) for m in page] == [("user", "hi"), ("assistant", "late but here")]
    async with uow_factory() as uow:
        stored = await uow.conversations.get(UUID(conversation_id))
        receipt = await uow.receipts.get(run_id)
        user_message = (await uow.messages.page(stored.id, None, 10))[0]
    assert (stored.run_state, stored.active_run_id, stored.tokens_used) == (RunState.IDLE, None, 9)
    assert receipt.session_id == 100 and user_message.session_id == 100


async def test_callback_that_beats_the_start_response_is_applied(client, uow_factory, settings, django, redis_client):
    django.graphs[5] = CHAT_FLOW
    flows = GatedFlows(settings, transport=django.transport, answer_first=True)
    orchestrator = ConversationOrchestrator(
        uow_factory, flows=flows, fanout=RedisFanout(redis_client), limiter=RedisRateLimiter(redis_client),
        config=RunConfig(callback_url=CALLBACKS, ip_message_rate=Rate(30, 60), ip_conversation_rate=Rate(20, 3600)),
        visitor_token_idle_seconds=30 * 86400,
    )
    binding = make_binding(org_id=1, graph_id=5)
    async with uow_factory() as uow:
        await uow.bindings.add(binding)
        await uow.commit()
    conversation, token, _ = await orchestrator.create(binding.public_key, None, ORIGIN, "1.1.1.1")
    submit = asyncio.create_task(orchestrator.submit(conversation.id, token, "hi", ORIGIN, "1.1.1.1"))
    await asyncio.wait_for(flows.blocked.wait(), 5)  # Django created session 100; its answer is still in flight
    async with uow_factory() as uow:
        run_id = (await uow.conversations.get(conversation.id)).active_run_id
        secret = (await uow.receipts.get(run_id)).secret
    body, signed_headers = _signed(secret, _payload(result={"reply": "fast"}))
    assert (await client.post(f"{CALLBACKS}/{run_id}", content=body, headers=signed_headers)).json() == {"result": "applied"}
    flows.release.set()
    result = await submit
    await flows.aclose()

    assert result.state == SubmitState.PROCESSING
    assert django.stopped == []  # the finished run is not mistaken for one an operator took over
    async with uow_factory() as uow:
        stored = await uow.conversations.get(conversation.id)
        messages = await uow.messages.page(conversation.id, None, 10)
    assert (stored.run_state, stored.active_run_id, stored.turns) == (RunState.IDLE, None, 1)
    assert [(m.role, m.content, m.session_id) for m in messages] == [(Role.USER, "hi", 100), (Role.ASSISTANT, "fast", 100)]


async def test_a_callback_after_the_visitor_ended_the_conversation_counts_its_tokens_and_posts_nothing(client, running, uow_factory):
    conversation_id, headers, secret, url = running
    assert (await client.post(f"/chat/public/v1/conversations/{conversation_id}/end", headers=headers)).status_code == 200
    body, signed_headers = _signed(secret, _payload(result={"reply": "too late", "request_human": True}, tokens=11))
    response = await client.post(url, content=body, headers=signed_headers)
    assert (response.status_code, response.json()) == (200, {"result": "ignored"})
    page = (await client.get(f"/chat/public/v1/conversations/{conversation_id}/messages", headers=headers)).json()
    assert [m["content"] for m in page] == ["hi"]
    async with uow_factory() as uow:
        stored = await uow.conversations.get(UUID(conversation_id))
    assert (stored.tokens_used, stored.turns, stored.is_open, stored.mode.value) == (11, 0, False, "bot")
