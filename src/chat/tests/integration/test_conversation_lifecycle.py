import asyncio
import json
import time
from datetime import date, timedelta
from uuid import UUID

import jwt
import pytest
from application.orchestrators.conversation import ApplyOutcome, ConversationOrchestrator, RunConfig
from application.orchestrators.events import Emitter, store_message
from application.orchestrators.operators import OperatorOrchestrator
from common.humanize import Rate
from common.utils import new_id, utc_today, utcnow
from domain.enums import CloseReason, IdentityMode, Mode, OnBudgetExhausted, Role, RunState, Stream, SubmitState
from domain.errors import (
    BindingBrokenError,
    BindingInactiveError,
    ConversationClosedError,
    FlowUnavailableError,
    InvalidIdentityError,
    InvalidTokenError,
    MessageTooLongError,
    NotFoundError,
    OriginNotAllowedError,
    RateLimitedError,
    RunInProgressError,
    SessionMismatchError,
)
from infrastructure.callback_verifier import SESSION_ID_HEADER, SIGNATURE_HEADER, TIMESTAMP_HEADER, sign
from infrastructure.database.repositories import ConversationRepository, VisitorNumberRepository
from infrastructure.django.client import DjangoClient
from infrastructure.redis.counters import RedisRateLimiter
from infrastructure.redis.fanout import RedisFanout
from tests.factories import make_binding, make_closed
from tests.infrastructure.test_django_client import CHAT_FLOW

ORIGIN = "https://example.com"
CALLBACK_URL = "http://chat:8200/chat/internal/v1/session-callbacks"


@pytest.fixture
async def orchestrator(uow_factory, settings, django, redis_client):
    django.graphs[5] = CHAT_FLOW
    flows = DjangoClient(settings, transport=django.transport)
    yield ConversationOrchestrator(
        uow_factory,
        flows=flows,
        fanout=RedisFanout(redis_client),
        limiter=RedisRateLimiter(redis_client),
        config=RunConfig(callback_url=CALLBACK_URL, ip_message_rate=Rate(30, 60), ip_conversation_rate=Rate(20, 3600)),
        visitor_token_idle_seconds=30 * 86400,
    )
    await flows.aclose()


class BrokenFanout(RedisFanout):
    async def publish(self, channel, event):
        raise ConnectionError("redis is down")


async def _binding(uow_factory, **overrides):
    binding = make_binding(**{"org_id": 1, "graph_id": 5, **overrides})
    async with uow_factory() as uow:
        await uow.bindings.add(binding)
        await uow.commit()
    return binding


async def _conversation(uow_factory, conversation_id):
    async with uow_factory() as uow:
        return await uow.conversations.get(conversation_id)


async def _messages(uow_factory, conversation_id):
    async with uow_factory() as uow:
        return await uow.messages.page(conversation_id, before=None, limit=50)


async def _active_run(uow_factory, conversation_id):
    return (await _conversation(uow_factory, conversation_id)).active_run_id


async def _events(uow_factory, conversation_id):
    async with uow_factory() as uow:
        return [e.type for e in await uow.events.replay(Stream.CONVERSATION, conversation_id=conversation_id, after_seq=None)]


# ---- creation --------------------------------------------------------------------------------

async def test_create_anonymous_conversation(orchestrator, uow_factory):
    binding = await _binding(uow_factory)
    conversation, token, _ = await orchestrator.create(binding.public_key, identity_token=None, origin=ORIGIN, client_ip="1.1.1.1")
    stored = await _conversation(uow_factory, conversation.id)
    assert stored.binding_id == binding.id and stored.org_id == 1 and stored.mode == Mode.BOT and not stored.is_test
    assert (await orchestrator.resolve(conversation.id, token))[0] == stored


async def test_resolve_after_the_binding_is_deleted_is_an_invalid_token(orchestrator, uow_factory):
    binding = await _binding(uow_factory)
    conversation, token, _ = await orchestrator.create(binding.public_key, None, ORIGIN, "1.1.1.1")
    async with uow_factory() as uow:  # cascades to the conversation and its tokens
        await uow.bindings.delete(binding.id, 1)
        await uow.commit()
    with pytest.raises(InvalidTokenError):
        await orchestrator.resolve(conversation.id, token)


async def test_create_rejects_unknown_key_origin_and_inactive(orchestrator, uow_factory):
    binding = await _binding(uow_factory)
    inactive = await _binding(uow_factory, is_active=False)
    with pytest.raises(NotFoundError):
        await orchestrator.create("nope", None, ORIGIN, "1.1.1.1")
    with pytest.raises(OriginNotAllowedError):
        await orchestrator.create(binding.public_key, None, "https://evil.example", "1.1.1.1")
    with pytest.raises(OriginNotAllowedError):
        await orchestrator.create(binding.public_key, None, None, "1.1.1.1")
    with pytest.raises(BindingInactiveError):
        await orchestrator.create(inactive.public_key, None, ORIGIN, "1.1.1.1")


async def test_create_limits_conversations_per_ip(orchestrator, uow_factory):
    binding = await _binding(uow_factory)
    orchestrator._config = RunConfig(callback_url=CALLBACK_URL, ip_message_rate=Rate(30, 60), ip_conversation_rate=Rate(1, 3600))
    await orchestrator.create(binding.public_key, None, ORIGIN, "9.9.9.9")
    with pytest.raises(RateLimitedError) as error:
        await orchestrator.create(binding.public_key, None, ORIGIN, "9.9.9.9")
    assert error.value.extra["retry_after"] >= 1


async def test_create_counts_ipv6_conversations_per_slash_64(orchestrator, uow_factory):
    binding = await _binding(uow_factory)
    orchestrator._config = RunConfig(callback_url=CALLBACK_URL, ip_message_rate=Rate(30, 60), ip_conversation_rate=Rate(1, 3600))
    await orchestrator.create(binding.public_key, None, ORIGIN, "2001:db8:1:2::1")
    with pytest.raises(RateLimitedError):
        await orchestrator.create(binding.public_key, None, ORIGIN, "2001:db8:1:2:ffff::9")
    await orchestrator.create(binding.public_key, None, ORIGIN, "2001:db8:1:3::1")


async def test_submit_counts_ipv6_messages_per_slash_64(orchestrator, uow_factory, redis_client):
    binding = await _binding(uow_factory)
    orchestrator._config = RunConfig(callback_url=CALLBACK_URL, ip_message_rate=Rate(1, 60), ip_conversation_rate=Rate(20, 3600))
    first, token_1, _ = await orchestrator.create(binding.public_key, None, ORIGIN, "2001:db8:1:2::1")
    second, token_2, _ = await orchestrator.create(binding.public_key, None, ORIGIN, "2001:db8:1:2::2")
    third, token_3, _ = await orchestrator.create(binding.public_key, None, ORIGIN, "2001:db8:1:3::1")
    await orchestrator.submit(first.id, token_1, "one", ORIGIN, "2001:db8:1:2::1")
    assert [key.decode() for key in await redis_client.keys("chat:rl:ip:2001:db8:1:2::/64:*")]
    with pytest.raises(RateLimitedError):
        await orchestrator.submit(second.id, token_2, "two", ORIGIN, "2001:db8:1:2::2")
    assert (await orchestrator.submit(third.id, token_3, "three", ORIGIN, "2001:db8:1:3::1")).state == SubmitState.PROCESSING


async def test_create_signed_reuses_subject_and_keeps_every_device_token(orchestrator, uow_factory):
    binding = await _binding(uow_factory, identity_mode=IdentityMode.SIGNED, identity_secret="id-secret")
    identity = jwt.encode({"sub": "customer-42", "exp": int(time.time()) + 600}, "id-secret", algorithm="HS256")
    with pytest.raises(InvalidIdentityError):
        await orchestrator.create(binding.public_key, None, ORIGIN, "1.1.1.1")
    first, token_1, _ = await orchestrator.create(binding.public_key, identity, ORIGIN, "1.1.1.1")
    second, token_2, _ = await orchestrator.create(binding.public_key, identity, ORIGIN, "1.1.1.1")
    assert first.id == second.id and first.subject == "customer-42" and token_1 != token_2
    # Two devices of one customer: the second token must not revoke the first.
    assert (await orchestrator.resolve(first.id, token_1))[0].id == first.id
    assert (await orchestrator.resolve(first.id, token_2))[0].id == first.id


async def test_concurrent_signed_creates_join_one_conversation(orchestrator, uow_factory):
    binding = await _binding(uow_factory, identity_mode=IdentityMode.SIGNED, identity_secret="id-secret")
    identity = jwt.encode({"sub": "customer-7", "exp": int(time.time()) + 600}, "id-secret", algorithm="HS256")
    (first, token_1, _), (second, token_2, _) = await asyncio.gather(
        orchestrator.create(binding.public_key, identity, ORIGIN, "1.1.1.1"),
        orchestrator.create(binding.public_key, identity, ORIGIN, "1.1.1.2"),
    )
    assert first.id == second.id
    assert (await orchestrator.resolve(first.id, token_1))[0].id == (await orchestrator.resolve(first.id, token_2))[0].id == first.id


async def test_resolve_rejects_foreign_conversation_id(orchestrator, uow_factory):
    binding = await _binding(uow_factory)
    conversation_a, token_a, _ = await orchestrator.create(binding.public_key, None, ORIGIN, "1.1.1.1")
    conversation_b, _, _ = await orchestrator.create(binding.public_key, None, ORIGIN, "1.1.1.2")
    with pytest.raises(NotFoundError):
        await orchestrator.resolve(conversation_b.id, token_a)
    with pytest.raises(InvalidTokenError):
        await orchestrator.resolve(conversation_a.id, "garbage")


async def test_create_test_conversation_skips_origin(orchestrator, uow_factory):
    binding = await _binding(uow_factory)
    row, token = await orchestrator.create_test(binding.id, org_id=1)
    assert row["is_test"]
    result = await orchestrator.submit(UUID(row["id"]), token, "hello", origin=None, client_ip="1.1.1.1")
    assert result.state == SubmitState.PROCESSING
    with pytest.raises(NotFoundError):
        await orchestrator.create_test(binding.id, org_id=2)


async def test_test_conversation_works_on_an_inactive_binding_but_not_a_broken_one(orchestrator, uow_factory):
    binding = await _binding(uow_factory, is_active=False)
    row, token = await orchestrator.create_test(binding.id, org_id=1)
    result = await orchestrator.submit(UUID(row["id"]), token, "hello", origin=None, client_ip="1.1.1.1")
    assert result.state == SubmitState.PROCESSING
    broken = await _binding(uow_factory, is_active=False, broken_reason="Django answered 404 for the flow.")
    row, token = await orchestrator.create_test(broken.id, org_id=1)
    with pytest.raises(BindingBrokenError) as error:
        await orchestrator.submit(UUID(row["id"]), token, "hello", origin=None, client_ip="1.1.1.1")
    assert "Django" not in error.value.message  # the stored reason is internal


async def test_new_conversations_are_numbered_per_binding_in_creation_order(orchestrator, uow_factory):
    binding, other = await _binding(uow_factory), await _binding(uow_factory)
    first, _, _ = await orchestrator.create(binding.public_key, None, ORIGIN, "1.1.1.1")
    second, _, _ = await orchestrator.create(binding.public_key, None, ORIGIN, "1.1.1.2")
    test, _ = await orchestrator.create_test(binding.id, org_id=1)  # tests share the binding's sequence
    elsewhere, _, _ = await orchestrator.create(other.public_key, None, ORIGIN, "1.1.1.3")
    third, _, _ = await orchestrator.create(binding.public_key, None, ORIGIN, "1.1.1.4")
    assert [first.visitor_number, second.visitor_number, test["visitor_number"], third.visitor_number] == [1, 2, 3, 4]
    assert elsewhere.visitor_number == 1
    assert (await _conversation(uow_factory, UUID(test["id"]))).visitor_number == 3


async def test_a_returning_signed_visitor_keeps_the_number(orchestrator, uow_factory):
    binding = await _binding(uow_factory, identity_mode=IdentityMode.SIGNED, identity_secret="id-secret")
    first, _, _ = await orchestrator.create(binding.public_key, _identity("customer-1"), ORIGIN, "1.1.1.1")
    again, _, _ = await orchestrator.create(binding.public_key, _identity("customer-1"), ORIGIN, "1.1.1.1")
    other, _, _ = await orchestrator.create(binding.public_key, _identity("customer-2"), ORIGIN, "1.1.1.1")
    assert (first.id, first.visitor_number, again.visitor_number, other.visitor_number) == (again.id, 1, 1, 2)


async def test_concurrent_creates_get_distinct_consecutive_numbers(orchestrator, uow_factory):
    binding = await _binding(uow_factory)
    *visitors, (test, _) = await asyncio.wait_for(asyncio.gather(*(orchestrator.create(binding.public_key, None, ORIGIN, f"1.1.1.{index}") for index in range(6)), orchestrator.create_test(binding.id, org_id=1)), timeout=10)
    assert sorted([*(conversation.visitor_number for conversation, _, _ in visitors), test["visitor_number"]]) == [1, 2, 3, 4, 5, 6, 7]


async def test_racing_signed_creates_join_one_conversation_and_leave_no_gap(orchestrator, uow_factory, monkeypatch):
    """Both devices miss the subject before either inserts, so the loser's insert fails and is
    retried; its rolled-back number goes back to the counter."""
    binding = await _binding(uow_factory, identity_mode=IdentityMode.SIGNED, identity_secret="id-secret")
    both_looked, lookups = asyncio.Barrier(2), []
    get_open_by_subject = ConversationRepository.get_open_by_subject

    async def looked_up_together(self, *args, **kwargs):
        found = await get_open_by_subject(self, *args, **kwargs)
        lookups.append(found)
        if len(lookups) <= 2:
            await both_looked.wait()
        return found

    monkeypatch.setattr(ConversationRepository, "get_open_by_subject", looked_up_together)
    (first, _, _), (second, _, _) = await asyncio.wait_for(asyncio.gather(
        orchestrator.create(binding.public_key, _identity("customer-7"), ORIGIN, "1.1.1.1"),
        orchestrator.create(binding.public_key, _identity("customer-7"), ORIGIN, "1.1.1.2"),
    ), timeout=10)
    assert lookups[:2] == [None, None] and lookups[2].id == first.id  # the retry found the winner's
    assert first.id == second.id and first.visitor_number == second.visitor_number == 1
    next_one, _, _ = await orchestrator.create(binding.public_key, _identity("customer-8"), ORIGIN, "1.1.1.3")
    assert next_one.visitor_number == 2


async def _delete_binding(uow_factory, binding_id):
    async with uow_factory() as uow:
        deleted = await uow.bindings.delete(binding_id, 1)
        await uow.commit()
    return deleted


async def test_a_test_create_racing_a_desk_delete_finishes_first_without_a_deadlock(orchestrator, uow_factory, monkeypatch):
    """The create holds the counter row when the delete starts: the delete must wait on the binding,
    not on the counter row that its cascade reaches, or the create's conversation insert (a key
    share on the binding) and the delete wait on each other."""
    binding = await _binding(uow_factory)
    await orchestrator.create_test(binding.id, org_id=1)  # the counter row exists, so numbering only updates it
    numbered, proceed = asyncio.Event(), asyncio.Event()
    next_number = VisitorNumberRepository.next

    async def numbered_then_paused(self, binding_id):
        number = await next_number(self, binding_id)
        numbered.set()
        await proceed.wait()
        return number

    monkeypatch.setattr(VisitorNumberRepository, "next", numbered_then_paused)
    creation = asyncio.ensure_future(orchestrator.create_test(binding.id, org_id=1))
    await asyncio.wait_for(numbered.wait(), timeout=5)
    deletion = asyncio.ensure_future(_delete_binding(uow_factory, binding.id))
    done, _ = await asyncio.wait({deletion}, timeout=0.3)
    assert not done, "the delete did not wait for the test create"
    proceed.set()
    (row, _), deleted = await asyncio.wait_for(asyncio.gather(creation, deletion), timeout=10)
    assert row["visitor_number"] == 2 and deleted
    assert await _conversation(uow_factory, UUID(row["id"])) is None  # the delete then took it along


async def test_a_test_create_behind_a_desk_delete_is_not_found(orchestrator, uow_factory):
    binding = await _binding(uow_factory)
    await orchestrator.create_test(binding.id, org_id=1)
    async with uow_factory() as deleter:
        assert await deleter.bindings.delete(binding.id, 1)
        creation = asyncio.ensure_future(orchestrator.create_test(binding.id, org_id=1))
        done, _ = await asyncio.wait({creation}, timeout=0.3)
        assert not done, "the test create did not wait for the delete"
        await deleter.commit()
    with pytest.raises(NotFoundError):
        await asyncio.wait_for(creation, timeout=10)


# ---- inbound lifecycle -----------------------------------------------------------------------

async def test_submit_starts_a_run(orchestrator, uow_factory, django):
    binding = await _binding(uow_factory, token_budget_per_conversation=1000)
    conversation, token, _ = await orchestrator.create(binding.public_key, None, ORIGIN, "1.1.1.1")
    result = await orchestrator.submit(conversation.id, token, "hello", ORIGIN, "1.1.1.1")

    assert result.state == SubmitState.PROCESSING
    run_request = next(r for r in django.requests if r.url.path == "/api/run-session/")
    body = json.loads(run_request.content)
    assert body["variables"] == {"chat_history": [], "user_message": "hello", "action": None, "chat_extra_data": None, "chat_user_id": None, "chat_conversation_id": str(conversation.id)}
    stored = await _conversation(uow_factory, conversation.id)
    assert stored.run_state == RunState.RUNNING and stored.active_run_id is not None
    assert body["token_budget"] == 1000 and body["callback_url"] == f"{CALLBACK_URL}/{stored.active_run_id}"
    assert len(body["callback_secret"]) >= 32 and run_request.headers["X-Organization-Id"] == "1"
    messages = await _messages(uow_factory, conversation.id)
    assert [(m.role, m.content, m.session_id) for m in messages] == [(Role.USER, "hello", 100)]
    receipt = await orchestrator.receipt(stored.active_run_id)
    assert (receipt.secret, receipt.session_id, receipt.message_id, receipt.received_at) == (body["callback_secret"], 100, messages[0].id, None)
    assert await _events(uow_factory, conversation.id) == ["message.created", "run.started"]


async def test_history_is_the_last_window_before_the_new_message(orchestrator, uow_factory, django):
    binding = await _binding(uow_factory, history_window=2)
    conversation, token, _ = await orchestrator.create(binding.public_key, None, ORIGIN, "1.1.1.1")
    await orchestrator.submit(conversation.id, token, "one", ORIGIN, "1.1.1.1")
    await orchestrator.apply_run_result(await _active_run(uow_factory, conversation.id), 100, "end", {"reply": "r1"}, {"total_tokens": 1})
    await orchestrator.submit(conversation.id, token, "two", ORIGIN, "1.1.1.1")
    await orchestrator.apply_run_result(await _active_run(uow_factory, conversation.id), 101, "end", {"reply": "r2"}, {"total_tokens": 1})
    await orchestrator.submit(conversation.id, token, "three", ORIGIN, "1.1.1.1")
    body = json.loads([r for r in django.requests if r.url.path == "/api/run-session/"][-1].content)
    assert body["variables"]["chat_history"] == [{"role": "user", "content": "two"}, {"role": "assistant", "content": "r2"}]
    assert body["variables"]["user_message"] == "three"


async def test_submit_in_human_modes_forwards_without_a_run(orchestrator, uow_factory, django):
    binding = await _binding(uow_factory)
    conversation, token, _ = await orchestrator.create(binding.public_key, None, ORIGIN, "1.1.1.1")
    async with uow_factory() as uow:
        stored = await uow.conversations.get(conversation.id)
        stored.change_mode(Mode.AWAITING_HUMAN, utcnow())
        await uow.conversations.update(stored)
        await uow.commit()
    handed_off = await _conversation(uow_factory, conversation.id)
    result = await orchestrator.submit(conversation.id, token, "anyone there?", ORIGIN, "1.1.1.1")
    assert result.state == SubmitState.FORWARDED_TO_OPERATOR
    assert not [r for r in django.requests if r.url.path == "/api/run-session/"]
    stored = await _conversation(uow_factory, conversation.id)
    assert stored.run_state == RunState.IDLE and stored.last_message_role == Role.USER
    assert stored.visitor_waiting_since == handed_off.visitor_waiting_since  # the earliest unanswered moment


async def test_the_wait_through_a_take_over_reply_visitor_message_and_release(orchestrator, uow_factory):
    _, conversation, token, run_id = await _running(orchestrator, uow_factory)
    await orchestrator.apply_run_result(run_id, 100, "end", {"reply": "A human will help", "request_human": True}, {})
    handed_off = (await _conversation(uow_factory, conversation.id)).visitor_waiting_since
    operators = OperatorOrchestrator(uow_factory, flows=orchestrator._flows, fanout=orchestrator._fanout)
    await operators.claim(conversation.id, 1, operator_id=3, force=False, display_name="Ada")
    assert (await _conversation(uow_factory, conversation.id)).visitor_waiting_since == handed_off
    await operators.reply(conversation.id, 1, 3, "Hello, Ada here", display_name="Ada")
    answered = await _conversation(uow_factory, conversation.id)
    assert (answered.visitor_waiting_since, answered.last_message_role, answered.last_message_author_user_id) == (None, Role.OPERATOR, 3)
    await orchestrator.submit(conversation.id, token, "thanks", ORIGIN, "1.1.1.1")
    waiting = await _conversation(uow_factory, conversation.id)
    assert waiting.visitor_waiting_since == waiting.last_message_at and waiting.last_message_author_user_id is None
    await operators.release(conversation.id, 1, operator_id=3)
    released = await _conversation(uow_factory, conversation.id)
    assert (released.mode, released.visitor_waiting_since, released.assigned_operator_id) == (Mode.BOT, None, None)


@pytest.mark.parametrize("force", [False, True])
async def test_taking_over_while_the_bot_still_owes_the_visitor_a_reply_leaves_the_visitor_waiting(orchestrator, uow_factory, force):
    _, conversation, _, run_id = await _running(orchestrator, uow_factory)
    asked = await _conversation(uow_factory, conversation.id)
    operators = OperatorOrchestrator(uow_factory, flows=orchestrator._flows, fanout=orchestrator._fanout)
    await operators.claim(conversation.id, 1, operator_id=3, force=force, display_name=None)
    taken = await _conversation(uow_factory, conversation.id)
    assert (taken.mode, taken.last_message_role, taken.run_state) == (Mode.HUMAN, Role.USER, RunState.IDLE)
    assert taken.visitor_waiting_since == asked.last_message_at  # since the visitor's message, not the take over
    # The stopped run's reply never arrives, so only an operator reply ends the wait.
    assert await orchestrator.apply_run_result(run_id, 100, "end", {"reply": "late"}, {}) == ApplyOutcome.IGNORED
    assert (await _conversation(uow_factory, conversation.id)).visitor_waiting_since == asked.last_message_at
    await operators.reply(conversation.id, 1, 3, "Hello", display_name=None)
    assert (await _conversation(uow_factory, conversation.id)).visitor_waiting_since is None


async def test_taking_over_after_the_flow_failed_to_start_leaves_the_visitor_waiting(orchestrator, uow_factory, django):
    binding = await _binding(uow_factory)
    conversation, token, _ = await orchestrator.create(binding.public_key, None, ORIGIN, "1.1.1.1")
    django.run_session_response = (500, {"error": "boom"})
    with pytest.raises(FlowUnavailableError):
        await orchestrator.submit(conversation.id, token, "help", ORIGIN, "1.1.1.1")
    failed = await _conversation(uow_factory, conversation.id)
    assert (failed.mode, failed.last_message_role, failed.visitor_waiting_since) == (Mode.BOT, Role.SYSTEM, None)
    operators = OperatorOrchestrator(uow_factory, flows=orchestrator._flows, fanout=orchestrator._fanout)
    await operators.claim(conversation.id, 1, operator_id=3, force=False, display_name=None)
    taken = await _conversation(uow_factory, conversation.id)
    # The notice answered nobody: the visitor waits, since the notice, until an operator replies.
    assert (taken.mode, taken.visitor_waiting_since) == (Mode.HUMAN, failed.last_message_at)


async def test_taking_over_after_the_run_ended_without_a_reply_leaves_the_visitor_waiting(orchestrator, uow_factory):
    _, conversation, _, run_id = await _running(orchestrator, uow_factory)
    await orchestrator.apply_run_result(run_id, 100, "end", {"actions": []}, {})
    ended = await _conversation(uow_factory, conversation.id)
    assert (ended.mode, ended.last_message_role) == (Mode.BOT, Role.SYSTEM)
    operators = OperatorOrchestrator(uow_factory, flows=orchestrator._flows, fanout=orchestrator._fanout)
    await operators.claim(conversation.id, 1, operator_id=3, force=False, display_name=None)
    assert (await _conversation(uow_factory, conversation.id)).visitor_waiting_since == ended.last_message_at


async def test_taking_over_after_the_bot_answered_leaves_nobody_waiting(orchestrator, uow_factory):
    _, conversation, _, run_id = await _running(orchestrator, uow_factory)
    await orchestrator.apply_run_result(run_id, 100, "end", {"reply": "Hi"}, {})
    operators = OperatorOrchestrator(uow_factory, flows=orchestrator._flows, fanout=orchestrator._fanout)
    await operators.claim(conversation.id, 1, operator_id=3, force=False, display_name=None)
    taken = await _conversation(uow_factory, conversation.id)
    assert (taken.last_message_role, taken.visitor_waiting_since) == (Role.ASSISTANT, None)


async def test_a_take_over_straight_from_the_bot_leaves_nobody_waiting_until_the_visitor_writes(orchestrator, uow_factory):
    binding = await _binding(uow_factory)
    conversation, token, _ = await orchestrator.create(binding.public_key, None, ORIGIN, "1.1.1.1")
    operators = OperatorOrchestrator(uow_factory, flows=orchestrator._flows, fanout=orchestrator._fanout)
    await operators.claim(conversation.id, 1, operator_id=3, force=False, display_name=None)
    assert (await _conversation(uow_factory, conversation.id)).visitor_waiting_since is None
    await orchestrator.submit(conversation.id, token, "hello?", ORIGIN, "1.1.1.1")
    stored = await _conversation(uow_factory, conversation.id)
    assert stored.visitor_waiting_since is not None and stored.visitor_waiting_since == stored.last_message_at


class GatedFlows(DjangoClient):
    """start_run waits for `release` so a test can act while the conversation is `starting`.

    With `answer_first` Django has already created the session when the wait begins.
    """

    def __init__(self, *args, answer_first: bool = False, **kwargs):
        super().__init__(*args, **kwargs)
        self.blocked, self.release = asyncio.Event(), asyncio.Event()
        self._answer_first = answer_first

    async def start_run(self, **kwargs) -> int:
        session_id = await super().start_run(**kwargs) if self._answer_first else None
        self.blocked.set()
        await self.release.wait()
        return session_id if self._answer_first else await super().start_run(**kwargs)


async def test_claim_while_starting_aborts_the_run(uow_factory, settings, django, redis_client, client):
    django.graphs[5] = CHAT_FLOW
    flows = GatedFlows(settings, transport=django.transport)
    fanout = RedisFanout(redis_client)
    orchestrator = ConversationOrchestrator(
        uow_factory, flows=flows, fanout=fanout, limiter=RedisRateLimiter(redis_client),
        config=RunConfig(callback_url=CALLBACK_URL, ip_message_rate=Rate(30, 60), ip_conversation_rate=Rate(20, 3600)),
        visitor_token_idle_seconds=30 * 86400,
    )
    binding = await _binding(uow_factory)
    conversation, token, _ = await orchestrator.create(binding.public_key, None, ORIGIN, "1.1.1.1")
    submit = asyncio.create_task(orchestrator.submit(conversation.id, token, "help", ORIGIN, "1.1.1.1"))
    await asyncio.wait_for(flows.blocked.wait(), 5)
    run_id = await _active_run(uow_factory, conversation.id)
    assert (await _conversation(uow_factory, conversation.id)).run_state == RunState.STARTING
    await OperatorOrchestrator(uow_factory, flows=flows, fanout=fanout).claim(conversation.id, 1, operator_id=1, force=False, display_name=None)
    flows.release.set()
    result = await submit
    await flows.aclose()

    assert result.state == SubmitState.FORWARDED_TO_OPERATOR
    stored = await _conversation(uow_factory, conversation.id)
    assert (stored.mode, stored.run_state, stored.active_run_id, stored.assigned_operator_id) == (Mode.HUMAN, RunState.IDLE, None, 1)
    assert django.stopped == [100]
    assert [m.session_id for m in await _messages(uow_factory, conversation.id)] == [100]
    assert (await _events(uow_factory, conversation.id)).count("run.finished") == 1
    # The run finished before the stop took effect: its tokens count, its reply is not posted.
    receipt = await orchestrator.receipt(run_id)
    assert receipt.session_id == 100 and receipt.received_at is None and receipt.secret
    body = json.dumps({"session_id": 100, "status": "end", "end_node_result": {"reply": "bot after claim"}, "token_usage": {"total_tokens": 8}}).encode()

    async def deliver():
        timestamp = str(int(time.time()))
        return await client.post(
            f"/chat/internal/v1/session-callbacks/{run_id}",
            content=body,
            headers={SESSION_ID_HEADER: "100", TIMESTAMP_HEADER: timestamp, SIGNATURE_HEADER: sign(receipt.secret, timestamp, body)},
        )

    late = await deliver()
    assert late.status_code == 200 and late.json() == {"result": "ignored"}
    stored = await _conversation(uow_factory, conversation.id)
    assert (stored.tokens_used, stored.turns, stored.mode) == (8, 0, Mode.HUMAN)
    # The operator hands back to the bot, then Django retries the same callback.
    await OperatorOrchestrator(uow_factory, flows=flows, fanout=fanout).release(conversation.id, 1, operator_id=1)
    retry = await deliver()
    assert retry.status_code == 200 and retry.json() == {"result": "ignored"}
    stored = await _conversation(uow_factory, conversation.id)
    assert (stored.tokens_used, stored.turns, stored.mode) == (8, 0, Mode.BOT)
    assert [m.content for m in await _messages(uow_factory, conversation.id)] == ["help"]


async def test_reply_after_the_release_unconfirmed_start_raced_a_slow_start_is_never_posted(uow_factory, settings, django, redis_client):
    django.graphs[5] = CHAT_FLOW
    flows = GatedFlows(settings, transport=django.transport)
    orchestrator = ConversationOrchestrator(
        uow_factory, flows=flows, fanout=RedisFanout(redis_client), limiter=RedisRateLimiter(redis_client),
        config=RunConfig(callback_url=CALLBACK_URL, ip_message_rate=Rate(30, 60), ip_conversation_rate=Rate(20, 3600)),
        visitor_token_idle_seconds=30 * 86400,
    )
    binding = await _binding(uow_factory)
    conversation, token, _ = await orchestrator.create(binding.public_key, None, ORIGIN, "1.1.1.1")
    submit = asyncio.create_task(orchestrator.submit(conversation.id, token, "hi", ORIGIN, "1.1.1.1"))
    await asyncio.wait_for(flows.blocked.wait(), 5)
    run_id = await _active_run(uow_factory, conversation.id)
    assert await orchestrator.release_unconfirmed_start(conversation.id, run_id)  # what the reconciler does
    flows.release.set()  # Django's 201 arrives after the release
    with pytest.raises(FlowUnavailableError):
        await submit
    await flows.aclose()

    assert django.stopped == [100]
    stored = await _conversation(uow_factory, conversation.id)
    assert (stored.mode, stored.run_state, stored.late_reply_run_id) == (Mode.BOT, RunState.IDLE, None)
    outcome = await orchestrator.apply_run_result(run_id, 100, "end", {"reply": "too late"}, {"total_tokens": 4})
    assert outcome == ApplyOutcome.IGNORED
    stored = await _conversation(uow_factory, conversation.id)
    assert (stored.tokens_used, stored.turns) == (4, 0)
    assert [m.content for m in await _messages(uow_factory, conversation.id)] == ["hi", "The flow could not be started."]


@pytest.mark.parametrize("released_back_to_bot", [False, True])
async def test_reply_of_a_run_stopped_by_a_claim_is_never_posted(orchestrator, uow_factory, released_back_to_bot):
    _, conversation, _, run_id = await _running(orchestrator, uow_factory)
    operators = OperatorOrchestrator(uow_factory, flows=orchestrator._flows, fanout=orchestrator._fanout)
    await operators.claim(conversation.id, 1, operator_id=1, force=False, display_name=None)
    if released_back_to_bot:
        await operators.release(conversation.id, 1, operator_id=1)
    outcome = await orchestrator.apply_run_result(run_id, 100, "end", {"reply": "bot after claim"}, {"total_tokens": 6})
    assert outcome == ApplyOutcome.IGNORED
    stored = await _conversation(uow_factory, conversation.id)
    assert (stored.tokens_used, stored.turns) == (6, 0)
    assert [m.content for m in await _messages(uow_factory, conversation.id)] == ["hi"]


async def test_second_submit_during_a_run_is_409_and_stores_nothing(orchestrator, uow_factory):
    binding = await _binding(uow_factory)
    conversation, token, _ = await orchestrator.create(binding.public_key, None, ORIGIN, "1.1.1.1")
    outcomes = await asyncio.gather(
        orchestrator.submit(conversation.id, token, "a", ORIGIN, "1.1.1.1"),
        orchestrator.submit(conversation.id, token, "b", ORIGIN, "1.1.1.1"),
        return_exceptions=True,
    )
    states = sorted(type(o).__name__ for o in outcomes)
    assert states == ["RunInProgressError", "SubmitResult"]
    assert len(await _messages(uow_factory, conversation.id)) == 1
    with pytest.raises(RunInProgressError):
        await orchestrator.submit(conversation.id, token, "c", ORIGIN, "1.1.1.1")


async def test_submit_validates_length_and_rate(orchestrator, uow_factory):
    binding = await _binding(uow_factory, max_message_length=5, messages_per_minute=1)
    conversation, token, _ = await orchestrator.create(binding.public_key, None, ORIGIN, "1.1.1.1")
    for content in ("", "   ", "toolong"):
        with pytest.raises(MessageTooLongError):
            await orchestrator.submit(conversation.id, token, content, ORIGIN, "1.1.1.1")
    await orchestrator.submit(conversation.id, token, "ok", ORIGIN, "1.1.1.1")
    await orchestrator.apply_run_result(await _active_run(uow_factory, conversation.id), 100, "end", {"reply": "r"}, {})
    with pytest.raises(RateLimitedError):
        await orchestrator.submit(conversation.id, token, "ok2", ORIGIN, "1.1.1.1")
    assert len(await _messages(uow_factory, conversation.id)) == 2


async def test_submit_gate_inactive_broken_origin(orchestrator, uow_factory):
    binding = await _binding(uow_factory)
    conversation, token, _ = await orchestrator.create(binding.public_key, None, ORIGIN, "1.1.1.1")
    with pytest.raises(OriginNotAllowedError):
        await orchestrator.submit(conversation.id, token, "x", "https://evil.example", "1.1.1.1")
    async with uow_factory() as uow:
        stored = await uow.bindings.get(binding.id)
        stored.broken_reason = "gone"
        await uow.bindings.update(stored)
        await uow.commit()
    with pytest.raises(BindingBrokenError):
        await orchestrator.submit(conversation.id, token, "x", ORIGIN, "1.1.1.1")
    async with uow_factory() as uow:
        stored = await uow.bindings.get(binding.id)
        stored.broken_reason, stored.is_active = None, False
        await uow.bindings.update(stored)
        await uow.commit()
    with pytest.raises(BindingInactiveError):
        await orchestrator.submit(conversation.id, token, "x", ORIGIN, "1.1.1.1")
    assert await _messages(uow_factory, conversation.id) == []


@pytest.mark.parametrize("policy, expected_mode, expected_roles", [
    (OnBudgetExhausted.REPLY, Mode.BOT, [Role.USER, Role.ASSISTANT]),
    (OnBudgetExhausted.HANDOFF, Mode.AWAITING_HUMAN, [Role.USER]),
])
async def test_budget_exhausted(orchestrator, uow_factory, django, policy, expected_mode, expected_roles):
    binding = await _binding(uow_factory, max_turns=0, on_budget_exhausted=policy, budget_exhausted_message="No more today.")
    conversation, token, _ = await orchestrator.create(binding.public_key, None, ORIGIN, "1.1.1.1")
    result = await orchestrator.submit(conversation.id, token, "hi", ORIGIN, "1.1.1.1")
    assert result.state == SubmitState.BUDGET_EXHAUSTED
    stored = await _conversation(uow_factory, conversation.id)
    assert stored.run_state == RunState.IDLE and stored.mode == expected_mode
    assert (stored.handoff_at is not None) == (expected_mode != Mode.BOT)
    # The hand-off starts the visitor's wait; a reply from the bot leaves nobody waiting.
    assert stored.visitor_waiting_since == stored.handoff_at
    assert [m.role for m in await _messages(uow_factory, conversation.id)] == expected_roles
    assert not [r for r in django.requests if r.url.path == "/api/run-session/"]


async def test_budget_handoff_disabled_falls_back_to_reply(orchestrator, uow_factory):
    binding = await _binding(uow_factory, max_turns=0, on_budget_exhausted=OnBudgetExhausted.HANDOFF, handoff_enabled=False)
    conversation, token, _ = await orchestrator.create(binding.public_key, None, ORIGIN, "1.1.1.1")
    await orchestrator.submit(conversation.id, token, "hi", ORIGIN, "1.1.1.1")
    stored = await _conversation(uow_factory, conversation.id)
    assert stored.mode == Mode.BOT and [m.role for m in await _messages(uow_factory, conversation.id)] == [Role.USER, Role.ASSISTANT]
    assert stored.handoff_at is None


async def test_django_404_marks_binding_broken(orchestrator, uow_factory, django):
    binding = await _binding(uow_factory, graph_id=404)
    conversation, token, _ = await orchestrator.create(binding.public_key, None, ORIGIN, "1.1.1.1")
    with pytest.raises(BindingBrokenError):
        await orchestrator.submit(conversation.id, token, "hi", ORIGIN, "1.1.1.1")
    async with uow_factory() as uow:
        assert (await uow.bindings.get(binding.id)).broken_reason
    stored = await _conversation(uow_factory, conversation.id)
    assert stored.run_state == RunState.IDLE and stored.active_run_id is None
    assert [m.role for m in await _messages(uow_factory, conversation.id)] == [Role.USER, Role.SYSTEM]
    assert "run.finished" in await _events(uow_factory, conversation.id)
    run_id = json.loads(next(r for r in django.requests if r.url.path == "/api/run-session/").content)["callback_url"].rsplit("/", 1)[1]
    receipt = await orchestrator.receipt(UUID(run_id))
    assert receipt.received_at is not None and receipt.secret == ""  # refused: nothing can match it


async def _run_events(uow_factory, conversation_id):
    async with uow_factory() as uow:
        events = await uow.events.replay(Stream.CONVERSATION, conversation_id=conversation_id, after_seq=None)
    return [{"type": e.type, **e.payload} for e in events if e.type.startswith("run.")]


async def test_start_without_an_answer_stays_processing(orchestrator, uow_factory, django):
    binding = await _binding(uow_factory)
    conversation, token, _ = await orchestrator.create(binding.public_key, None, ORIGIN, "1.1.1.1")
    django.lose_run_session_response = True
    result = await orchestrator.submit(conversation.id, token, "hi", ORIGIN, "1.1.1.1")
    assert result.state == SubmitState.PROCESSING
    stored = await _conversation(uow_factory, conversation.id)
    assert stored.run_state == RunState.STARTING and stored.state == "processing"
    receipt = await orchestrator.receipt(stored.active_run_id)
    assert receipt.session_id is None and receipt.received_at is None and receipt.secret
    assert [m.role for m in await _messages(uow_factory, conversation.id)] == [Role.USER]
    assert await _run_events(uow_factory, conversation.id) == []
    with pytest.raises(RunInProgressError):  # the slot is still held: a retry cannot double the run
        await orchestrator.submit(conversation.id, token, "hi again", ORIGIN, "1.1.1.1")


async def test_django_failure_releases_slot(orchestrator, uow_factory, django):
    binding = await _binding(uow_factory)
    conversation, token, _ = await orchestrator.create(binding.public_key, None, ORIGIN, "1.1.1.1")
    django.run_session_response = (500, {"error": "boom"})
    with pytest.raises(FlowUnavailableError):
        await orchestrator.submit(conversation.id, token, "hi", ORIGIN, "1.1.1.1")
    assert (await _conversation(uow_factory, conversation.id)).run_state == RunState.IDLE
    messages = await _messages(uow_factory, conversation.id)
    assert [(m.role, m.content) for m in messages] == [(Role.USER, "hi"), (Role.SYSTEM, "The flow could not be started.")]
    assert {"type": "run.finished", "status": "error"} in await _run_events(uow_factory, conversation.id)
    run_id = json.loads(next(r for r in django.requests if r.url.path == "/api/run-session/").content)["callback_url"].rsplit("/", 1)[1]
    receipt = await orchestrator.receipt(UUID(run_id))
    assert receipt.received_at is not None and receipt.secret == ""  # refused: nothing can match it
    django.run_session_response = None
    assert (await orchestrator.submit(conversation.id, token, "again", ORIGIN, "1.1.1.1")).state == SubmitState.PROCESSING


# ---- applying results -------------------------------------------------------------------------

async def _running(orchestrator, uow_factory, **binding_overrides):
    """A conversation whose run is in flight; returns its binding, conversation, token and run id."""
    binding = await _binding(uow_factory, **binding_overrides)
    conversation, token, _ = await orchestrator.create(binding.public_key, None, ORIGIN, "1.1.1.1")
    await orchestrator.submit(conversation.id, token, "hi", ORIGIN, "1.1.1.1")
    return binding, conversation, token, await _active_run(uow_factory, conversation.id)


async def test_apply_end_stores_reply_and_counts(orchestrator, uow_factory):
    binding, conversation, _, run_id = await _running(orchestrator, uow_factory)
    outcome = await orchestrator.apply_run_result(run_id, 100, "end", {"reply": "Hello", "actions": [{"type": "buttons"}]}, {"total_tokens": 42})
    assert outcome == ApplyOutcome.APPLIED
    stored = await _conversation(uow_factory, conversation.id)
    assert (stored.run_state, stored.active_run_id, stored.tokens_used, stored.turns, stored.mode) == (RunState.IDLE, None, 42, 1, Mode.BOT)
    messages = await _messages(uow_factory, conversation.id)
    assert (messages[-1].role, messages[-1].content, messages[-1].actions, messages[-1].session_id) == (Role.ASSISTANT, "Hello", [{"type": "buttons"}], 100)
    async with uow_factory() as uow:
        assert await uow.usage.daily_tokens(binding.id, utc_today()) == 42
    assert (await _events(uow_factory, conversation.id))[-2:] == ["message.created", "run.finished"]
    assert await orchestrator.apply_run_result(run_id, 100, "end", {"reply": "again"}, {"total_tokens": 42}) == ApplyOutcome.DUPLICATE
    assert (await _conversation(uow_factory, conversation.id)).tokens_used == 42


async def test_apply_request_human_hands_off(orchestrator, uow_factory):
    _, conversation, _, run_id = await _running(orchestrator, uow_factory)
    await orchestrator.apply_run_result(run_id, 100, "end", {"reply": "Let me get a human", "request_human": True}, {})
    stored = await _conversation(uow_factory, conversation.id)
    assert stored.mode == Mode.AWAITING_HUMAN and stored.handoff_reason and stored.handoff_at is not None
    assert stored.visitor_waiting_since == stored.handoff_at
    assert (stored.last_message_role, stored.last_message_author_user_id) == (Role.ASSISTANT, None)
    assert "mode.changed" in await _events(uow_factory, conversation.id)


async def test_apply_request_human_without_reply_still_hands_off(orchestrator, uow_factory):
    _, conversation, _, run_id = await _running(orchestrator, uow_factory)
    await orchestrator.apply_run_result(run_id, 100, "end", {"request_human": True}, {})
    stored = await _conversation(uow_factory, conversation.id)
    messages = await _messages(uow_factory, conversation.id)
    assert stored.mode == Mode.AWAITING_HUMAN and messages[-1].role == Role.SYSTEM
    assert "mode.changed" in await _events(uow_factory, conversation.id)


async def test_apply_end_without_reply_leaves_system_message(orchestrator, uow_factory):
    for session_id, result in ((100, None), (101, "text"), (102, {"actions": []})):
        _, conversation, _, run_id = await _running(orchestrator, uow_factory)
        await orchestrator.apply_run_result(run_id, session_id, "end", result, {})
        stored = await _conversation(uow_factory, conversation.id)
        messages = await _messages(uow_factory, conversation.id)
        assert stored.run_state == RunState.IDLE and messages[-1].role == Role.SYSTEM
        assert (await _events(uow_factory, conversation.id))[-1] == "run.finished"


async def test_apply_error_status_hands_off_when_enabled(orchestrator, uow_factory):
    _, conversation, _, run_id = await _running(orchestrator, uow_factory)
    await orchestrator.apply_run_result(run_id, 100, "error", None, {"total_tokens": 5})
    stored = await _conversation(uow_factory, conversation.id)
    messages = await _messages(uow_factory, conversation.id)
    assert stored.mode == Mode.AWAITING_HUMAN and stored.tokens_used == 5 and messages[-1].role == Role.SYSTEM and "error" in messages[-1].content
    assert stored.handoff_at is not None and stored.visitor_waiting_since == stored.handoff_at


async def test_apply_ignores_an_unknown_run(orchestrator, uow_factory):
    _, conversation, _, _ = await _running(orchestrator, uow_factory)
    assert await orchestrator.apply_run_result(new_id(), 100, "end", {"reply": "?"}, {"total_tokens": 5}) == ApplyOutcome.IGNORED
    stored = await _conversation(uow_factory, conversation.id)
    assert (stored.run_state, stored.tokens_used) == (RunState.RUNNING, 0)


async def test_apply_rejects_a_session_other_than_the_bound_one(orchestrator, uow_factory):
    _, conversation, _, run_id = await _running(orchestrator, uow_factory)  # bound to 100
    with pytest.raises(SessionMismatchError):
        await orchestrator.apply_run_result(run_id, 101, "end", {"reply": "?"}, {"total_tokens": 5})
    stored = await _conversation(uow_factory, conversation.id)
    assert (stored.run_state, stored.tokens_used) == (RunState.RUNNING, 0)
    assert (await orchestrator.receipt(run_id)).received_at is None


async def test_apply_end_clears_broken_reason(orchestrator, uow_factory):
    binding, conversation, _, run_id = await _running(orchestrator, uow_factory)
    async with uow_factory() as uow:
        stored = await uow.bindings.get(binding.id)
        stored.broken_reason = "was gone"
        await uow.bindings.update(stored)
        await uow.commit()
    await orchestrator.apply_run_result(run_id, 100, "end", {"reply": "back"}, {})
    async with uow_factory() as uow:
        assert (await uow.bindings.get(binding.id)).broken_reason is None


async def test_fanout_failure_does_not_fail_a_committed_submit(orchestrator, uow_factory, redis_client):
    orchestrator._fanout = BrokenFanout(redis_client)
    binding = await _binding(uow_factory)
    conversation, token, _ = await orchestrator.create(binding.public_key, None, ORIGIN, "1.1.1.1")
    result = await orchestrator.submit(conversation.id, token, "hello", ORIGIN, "1.1.1.1")
    assert result.state == SubmitState.PROCESSING
    stored = await _conversation(uow_factory, conversation.id)
    assert stored.run_state == RunState.RUNNING and (await orchestrator.receipt(stored.active_run_id)).session_id == 100
    assert await _events(uow_factory, conversation.id) == ["message.created", "run.started"]


async def test_apply_counts_a_non_integer_token_total_as_zero(orchestrator, uow_factory):
    _, conversation, _, run_id = await _running(orchestrator, uow_factory)
    assert await orchestrator.apply_run_result(run_id, 100, "end", {"reply": "ok"}, {"total_tokens": "oops"}) == ApplyOutcome.APPLIED
    stored = await _conversation(uow_factory, conversation.id)
    assert stored.tokens_used == 0 and stored.turns == 1


async def test_submit_limits_messages_per_ip_across_conversations(orchestrator, uow_factory):
    binding = await _binding(uow_factory)
    orchestrator._config = RunConfig(callback_url=CALLBACK_URL, ip_message_rate=Rate(1, 60), ip_conversation_rate=Rate(20, 3600))
    first, token_1, _ = await orchestrator.create(binding.public_key, None, ORIGIN, "7.7.7.7")
    second, token_2, _ = await orchestrator.create(binding.public_key, None, ORIGIN, "7.7.7.7")
    await orchestrator.submit(first.id, token_1, "one", ORIGIN, "7.7.7.7")
    with pytest.raises(RateLimitedError):
        await orchestrator.submit(second.id, token_2, "two", ORIGIN, "7.7.7.7")
    assert await _messages(uow_factory, second.id) == []


async def test_ip_message_rate_window_drives_the_key_bucket_and_expiry(orchestrator, uow_factory, redis_client):
    binding = await _binding(uow_factory)
    orchestrator._config = RunConfig(callback_url=CALLBACK_URL, ip_message_rate=Rate(1, 10), ip_conversation_rate=Rate(20, 3600))
    first, token_1, _ = await orchestrator.create(binding.public_key, None, ORIGIN, "6.6.6.6")
    second, token_2, _ = await orchestrator.create(binding.public_key, None, ORIGIN, "6.6.6.6")
    before = int(time.time() // 10)
    await orchestrator.submit(first.id, token_1, "one", ORIGIN, "6.6.6.6")
    after = int(time.time() // 10)
    keys = [key.decode() for key in await redis_client.keys("chat:rl:ip:6.6.6.6:*")]
    assert len(keys) == 1 and int(keys[0].rsplit(":", 1)[1]) in (before, after)  # a 10 s bucket, not a minute
    assert 0 < await redis_client.ttl(keys[0]) <= 10
    with pytest.raises(RateLimitedError) as error:
        await orchestrator.submit(second.id, token_2, "two", ORIGIN, "6.6.6.6")
    assert 1 <= error.value.extra["retry_after"] <= 10


async def test_request_human_without_handoff_stays_with_the_bot(orchestrator, uow_factory):
    _, conversation, _, run_id = await _running(orchestrator, uow_factory, handoff_enabled=False)
    await orchestrator.apply_run_result(run_id, 100, "end", {"reply": "Let me get a human", "request_human": True}, {})
    stored = await _conversation(uow_factory, conversation.id)
    assert stored.mode == Mode.BOT and stored.handoff_at is None and "mode.changed" not in await _events(uow_factory, conversation.id)


# ---- per-conversation limits count each UTC day -------------------------------------------------

DAY_ONE = date(2026, 10, 10)


@pytest.fixture
def clock(monkeypatch):
    """Today's UTC date as the conversation orchestrator sees it; move `clock.today` to cross midnight."""
    class Clock:
        today = DAY_ONE

    monkeypatch.setattr("application.orchestrators.conversation.utc_today", lambda: Clock.today)
    return Clock


async def _reply(orchestrator, uow_factory, conversation_id, session_id, tokens):
    run_id = await _active_run(uow_factory, conversation_id)
    assert await orchestrator.apply_run_result(run_id, session_id, "end", {"reply": "ok"}, {"total_tokens": tokens}) == ApplyOutcome.APPLIED


async def test_max_turns_blocks_on_todays_turns_and_restarts_the_next_utc_day(orchestrator, uow_factory, clock):
    binding = await _binding(uow_factory, max_turns=1)
    conversation, token, _ = await orchestrator.create(binding.public_key, None, ORIGIN, "1.1.1.1")
    assert (await orchestrator.submit(conversation.id, token, "one", ORIGIN, "1.1.1.1")).state == SubmitState.PROCESSING
    await _reply(orchestrator, uow_factory, conversation.id, 100, 10)
    assert (await orchestrator.submit(conversation.id, token, "two", ORIGIN, "1.1.1.1")).state == SubmitState.BUDGET_EXHAUSTED
    clock.today = DAY_ONE + timedelta(days=1)
    assert (await orchestrator.submit(conversation.id, token, "three", ORIGIN, "1.1.1.1")).state == SubmitState.PROCESSING
    stored = await _conversation(uow_factory, conversation.id)
    assert (stored.usage_day, stored.turns_today, stored.tokens_today) == (DAY_ONE + timedelta(days=1), 0, 0)
    await _reply(orchestrator, uow_factory, conversation.id, 101, 5)
    stored = await _conversation(uow_factory, conversation.id)
    assert (stored.turns, stored.tokens_used, stored.turns_today, stored.tokens_today) == (2, 15, 1, 5)


async def test_a_run_started_near_the_conversation_cap_gets_the_whole_budget(orchestrator, uow_factory, django):
    binding = await _binding(uow_factory, token_budget_per_conversation=10)
    conversation, token, _ = await orchestrator.create(binding.public_key, None, ORIGIN, "1.1.1.1")
    await orchestrator.submit(conversation.id, token, "one", ORIGIN, "1.1.1.1")
    await _reply(orchestrator, uow_factory, conversation.id, 100, 9)
    assert (await orchestrator.submit(conversation.id, token, "two", ORIGIN, "1.1.1.1")).state == SubmitState.PROCESSING
    assert django.sessions[101]["body"]["token_budget"] == 10  # not the 1 token left


async def test_token_budget_blocks_on_todays_tokens_and_the_next_day_gets_the_full_budget(orchestrator, uow_factory, django, clock):
    binding = await _binding(uow_factory, token_budget_per_conversation=10)
    conversation, token, _ = await orchestrator.create(binding.public_key, None, ORIGIN, "1.1.1.1")
    await orchestrator.submit(conversation.id, token, "one", ORIGIN, "1.1.1.1")
    await _reply(orchestrator, uow_factory, conversation.id, 100, 10)
    assert (await orchestrator.submit(conversation.id, token, "two", ORIGIN, "1.1.1.1")).state == SubmitState.BUDGET_EXHAUSTED
    clock.today = DAY_ONE + timedelta(days=1)
    assert (await orchestrator.submit(conversation.id, token, "three", ORIGIN, "1.1.1.1")).state == SubmitState.PROCESSING
    assert django.sessions[101]["body"]["token_budget"] == 10  # a run gets the whole budget, never the remainder
    await _reply(orchestrator, uow_factory, conversation.id, 101, 4)
    clock.today = DAY_ONE + timedelta(days=2)
    await orchestrator.submit(conversation.id, token, "four", ORIGIN, "1.1.1.1")
    assert django.sessions[102]["body"]["token_budget"] == 10
    assert (await _conversation(uow_factory, conversation.id)).tokens_used == 14  # the lifetime total keeps growing


async def test_a_run_applied_after_midnight_counts_on_the_new_day(orchestrator, uow_factory, clock):
    binding = await _binding(uow_factory)
    conversation, token, _ = await orchestrator.create(binding.public_key, None, ORIGIN, "1.1.1.1")
    await orchestrator.submit(conversation.id, token, "late night", ORIGIN, "1.1.1.1")
    clock.today = DAY_ONE + timedelta(days=1)
    await _reply(orchestrator, uow_factory, conversation.id, 100, 7)
    stored = await _conversation(uow_factory, conversation.id)
    assert (stored.usage_day, stored.tokens_today, stored.turns_today, stored.tokens_used, stored.turns) == (DAY_ONE + timedelta(days=1), 7, 1, 7, 1)
    async with uow_factory() as uow:
        assert await uow.usage.daily_tokens(binding.id, DAY_ONE + timedelta(days=1)) == 7
        assert await uow.usage.daily_tokens(binding.id, DAY_ONE) == 0


# ---- flow inputs: action, chat_extra_data, chat_user_id ---------------------------------------

def _run_variables(django) -> list[dict]:
    return [json.loads(r.content)["variables"] for r in django.requests if r.url.path == "/api/run-session/"]


async def _finish(orchestrator, uow_factory, conversation_id, session_id):
    await orchestrator.apply_run_result(await _active_run(uow_factory, conversation_id), session_id, "end", {"reply": f"r{session_id}"}, {"total_tokens": 1})


async def test_an_action_only_reply_starts_a_run_with_an_empty_user_message(orchestrator, uow_factory, django):
    binding = await _binding(uow_factory)
    conversation, token, _ = await orchestrator.create(binding.public_key, None, ORIGIN, "1.1.1.1")
    action = {"type": "button", "id": "yes"}
    result = await orchestrator.submit(conversation.id, token, "", ORIGIN, "1.1.1.1", action=action)
    assert result.state == SubmitState.PROCESSING
    (variables,) = _run_variables(django)
    assert variables == {"chat_history": [], "user_message": "", "action": action, "chat_extra_data": None, "chat_user_id": None, "chat_conversation_id": str(conversation.id)}
    (message,) = await _messages(uow_factory, conversation.id)
    assert (message.content, message.action) == ("", action)
    assert (await _conversation(uow_factory, conversation.id)).last_message_preview == '{"type":"button","id":"yes"}'


async def test_blank_content_with_an_action_is_stored_empty(orchestrator, uow_factory, django):
    binding = await _binding(uow_factory)
    conversation, token, _ = await orchestrator.create(binding.public_key, None, ORIGIN, "1.1.1.1")
    await orchestrator.submit(conversation.id, token, "   ", ORIGIN, "1.1.1.1", action={"id": "a"})
    assert _run_variables(django)[0]["user_message"] == ""


async def test_an_action_does_not_lift_the_content_length_limit(orchestrator, uow_factory):
    binding = await _binding(uow_factory, max_message_length=5)
    conversation, token, _ = await orchestrator.create(binding.public_key, None, ORIGIN, "1.1.1.1")
    with pytest.raises(MessageTooLongError):
        await orchestrator.submit(conversation.id, token, "toolong", ORIGIN, "1.1.1.1", action={"id": "a"})
    assert await _messages(uow_factory, conversation.id) == []


async def test_a_text_message_sends_a_null_action(orchestrator, uow_factory, django):
    binding = await _binding(uow_factory)
    conversation, token, _ = await orchestrator.create(binding.public_key, None, ORIGIN, "1.1.1.1")
    await orchestrator.submit(conversation.id, token, "hello", ORIGIN, "1.1.1.1")
    (variables,) = _run_variables(django)
    assert set(variables) == {"chat_history", "user_message", "action", "chat_extra_data", "chat_user_id", "chat_conversation_id"}
    assert variables["action"] is None


async def test_history_carries_the_action_only_on_the_reply_that_had_one(orchestrator, uow_factory, django):
    binding = await _binding(uow_factory)
    conversation, token, _ = await orchestrator.create(binding.public_key, None, ORIGIN, "1.1.1.1")
    await orchestrator.submit(conversation.id, token, "Yes", ORIGIN, "1.1.1.1", action={"type": "button", "id": "yes"})
    await _finish(orchestrator, uow_factory, conversation.id, 100)
    await orchestrator.submit(conversation.id, token, "next", ORIGIN, "1.1.1.1")
    # Its own run gets the whole action; later runs see in the history only which one and what it said.
    assert _run_variables(django)[0]["action"] == {"type": "button", "id": "yes"}
    assert _run_variables(django)[1]["chat_history"] == [
        {"role": "user", "content": "Yes", "action": {"type": "button"}},
        {"role": "assistant", "content": "r100"},
    ]


async def test_chat_extra_data_is_replaced_kept_and_cleared_to_null_per_message(orchestrator, uow_factory, django):
    binding = await _binding(uow_factory)
    conversation, token, _ = await orchestrator.create(binding.public_key, None, ORIGIN, "1.1.1.1", chat_extra_data={"plan": "pro", "page": "/a"})
    await orchestrator.submit(conversation.id, token, "one", ORIGIN, "1.1.1.1")
    await _finish(orchestrator, uow_factory, conversation.id, 100)
    await orchestrator.submit(conversation.id, token, "two", ORIGIN, "1.1.1.1", chat_extra_data={"page": "/b"})
    await _finish(orchestrator, uow_factory, conversation.id, 101)
    await orchestrator.submit(conversation.id, token, "three", ORIGIN, "1.1.1.1")
    await _finish(orchestrator, uow_factory, conversation.id, 102)
    await orchestrator.submit(conversation.id, token, "four", ORIGIN, "1.1.1.1", chat_extra_data={})
    # {} is stored as no value, so the run sends null, which also replaces a default the flow declares.
    assert [v["chat_extra_data"] for v in _run_variables(django)] == [{"plan": "pro", "page": "/a"}, {"page": "/b"}, {"page": "/b"}, None]
    assert (await _conversation(uow_factory, conversation.id)).chat_extra_data is None


async def test_a_refused_message_leaves_chat_extra_data_unchanged(orchestrator, uow_factory):
    binding = await _binding(uow_factory, messages_per_minute=2)
    conversation, token, _ = await orchestrator.create(binding.public_key, None, ORIGIN, "1.1.1.1", chat_extra_data={"v": 1})
    await orchestrator.submit(conversation.id, token, "one", ORIGIN, "1.1.1.1")
    with pytest.raises(RunInProgressError):
        await orchestrator.submit(conversation.id, token, "two", ORIGIN, "1.1.1.1", chat_extra_data={"v": 2})
    assert (await _conversation(uow_factory, conversation.id)).chat_extra_data == {"v": 1}
    await _finish(orchestrator, uow_factory, conversation.id, 100)
    with pytest.raises(RateLimitedError):
        await orchestrator.submit(conversation.id, token, "three", ORIGIN, "1.1.1.1", chat_extra_data={"v": 3})
    with pytest.raises(MessageTooLongError):
        await orchestrator.submit(conversation.id, token, " ", ORIGIN, "1.1.1.1", chat_extra_data={"v": 4})
    assert (await _conversation(uow_factory, conversation.id)).chat_extra_data == {"v": 1}


async def test_a_forwarded_or_budget_exhausted_message_still_updates_chat_extra_data(orchestrator, uow_factory, django):
    binding = await _binding(uow_factory, max_turns=0)
    conversation, token, _ = await orchestrator.create(binding.public_key, None, ORIGIN, "1.1.1.1")
    result = await orchestrator.submit(conversation.id, token, "hi", ORIGIN, "1.1.1.1", chat_extra_data={"v": "budget"})
    assert result.state == SubmitState.BUDGET_EXHAUSTED
    assert (await _conversation(uow_factory, conversation.id)).chat_extra_data == {"v": "budget"}
    async with uow_factory() as uow:
        stored = await uow.conversations.get(conversation.id)
        stored.change_mode(Mode.AWAITING_HUMAN, utcnow())
        await uow.conversations.update(stored)
        await uow.commit()
    result = await orchestrator.submit(conversation.id, token, "", ORIGIN, "1.1.1.1", action={"id": "x"}, chat_extra_data={"v": "forwarded"})
    assert result.state == SubmitState.FORWARDED_TO_OPERATOR
    assert (await _conversation(uow_factory, conversation.id)).chat_extra_data == {"v": "forwarded"}
    assert [m.action for m in await _messages(uow_factory, conversation.id)][-1] == {"id": "x"}


def _identity(sub, secret="id-secret"):
    return jwt.encode({"sub": sub, "exp": int(time.time()) + 600}, secret, algorithm="HS256")


async def test_chat_user_id_is_the_verified_sub_on_signed_bindings_only(orchestrator, uow_factory, django):
    signed = await _binding(uow_factory, identity_mode=IdentityMode.SIGNED, identity_secret="id-secret")
    anonymous = await _binding(uow_factory)
    signed_conversation, signed_token, _ = await orchestrator.create(signed.public_key, _identity("customer-42"), ORIGIN, "1.1.1.1")
    anonymous_conversation, anonymous_token, _ = await orchestrator.create(anonymous.public_key, None, ORIGIN, "1.1.1.2")
    test_row, test_token = await orchestrator.create_test(signed.id, org_id=1)
    await orchestrator.submit(signed_conversation.id, signed_token, "a", ORIGIN, "1.1.1.1")
    await orchestrator.submit(anonymous_conversation.id, anonymous_token, "b", ORIGIN, "1.1.1.2")
    await orchestrator.submit(UUID(test_row["id"]), test_token, "c", None, "1.1.1.3")
    assert [v["chat_user_id"] for v in _run_variables(django)] == ["customer-42", None, None]


async def test_a_second_device_rejoins_with_the_sub_and_replaces_chat_extra_data(orchestrator, uow_factory, django):
    binding = await _binding(uow_factory, identity_mode=IdentityMode.SIGNED, identity_secret="id-secret")
    first, _, _ = await orchestrator.create(binding.public_key, _identity("customer-7"), ORIGIN, "1.1.1.1", chat_extra_data={"device": "laptop"})
    kept, _, _ = await orchestrator.create(binding.public_key, _identity("customer-7"), ORIGIN, "1.1.1.1")
    assert kept.id == first.id and (await _conversation(uow_factory, first.id)).chat_extra_data == {"device": "laptop"}
    second, token, _ = await orchestrator.create(binding.public_key, _identity("customer-7"), ORIGIN, "1.1.1.2", chat_extra_data={"device": "phone"})
    assert second.id == first.id
    await orchestrator.submit(second.id, token, "hi", ORIGIN, "1.1.1.2")
    (variables,) = _run_variables(django)
    assert (variables["chat_user_id"], variables["chat_extra_data"]) == ("customer-7", {"device": "phone"})
    await _finish(orchestrator, uow_factory, first.id, 100)
    await orchestrator.create(binding.public_key, _identity("customer-7"), ORIGIN, "1.1.1.3", chat_extra_data={})
    assert (await _conversation(uow_factory, first.id)).chat_extra_data is None


async def test_empty_chat_extra_data_on_create_stores_no_value(orchestrator, uow_factory):
    binding = await _binding(uow_factory)
    conversation, _, _ = await orchestrator.create(binding.public_key, None, ORIGIN, "1.1.1.1", chat_extra_data={})
    assert (await _conversation(uow_factory, conversation.id)).chat_extra_data is None


# ---- closing ------------------------------------------------------------------------------------

def _operators(orchestrator, flows=None):
    return OperatorOrchestrator(orchestrator._uow, flows=flows or orchestrator._flows, fanout=orchestrator._fanout)


async def test_a_signed_customer_returning_after_a_close_gets_a_new_conversation_with_the_next_number(orchestrator, uow_factory):
    binding = await _binding(uow_factory, identity_mode=IdentityMode.SIGNED, identity_secret="id-secret")
    first, first_token, _ = await orchestrator.create(binding.public_key, _identity("customer-1"), ORIGIN, "1.1.1.1")
    await orchestrator.end(first.id, first_token, ORIGIN)
    second, second_token, _ = await orchestrator.create(binding.public_key, _identity("customer-1"), ORIGIN, "1.1.1.1")
    again, _, _ = await orchestrator.create(binding.public_key, _identity("customer-1"), ORIGIN, "1.1.1.2")
    assert second.id != first.id and (second.visitor_number, second.subject, second.is_open) == (2, "customer-1", True)
    assert again.id == second.id  # the open one is resumed until it closes too
    # Both tokens keep reading their own conversation: the closed history stays visible.
    old, _ = await orchestrator.resolve(first.id, first_token)
    assert (old.is_open, old.close_reason) == (False, CloseReason.ENDED)
    assert (await orchestrator.resolve(second.id, second_token))[0].id == second.id


async def test_racing_signed_creates_after_a_close_join_one_new_conversation(orchestrator, uow_factory, monkeypatch):
    binding = await _binding(uow_factory, identity_mode=IdentityMode.SIGNED, identity_secret="id-secret")
    first, token, _ = await orchestrator.create(binding.public_key, _identity("customer-7"), ORIGIN, "1.1.1.1")
    await orchestrator.end(first.id, token, ORIGIN)
    both_looked, lookups = asyncio.Barrier(2), []
    get_open_by_subject = ConversationRepository.get_open_by_subject

    async def looked_up_together(self, *args, **kwargs):
        found = await get_open_by_subject(self, *args, **kwargs)
        lookups.append(found)
        if len(lookups) <= 2:
            await both_looked.wait()
        return found

    monkeypatch.setattr(ConversationRepository, "get_open_by_subject", looked_up_together)
    (one, _, _), (other, _, _) = await asyncio.wait_for(asyncio.gather(
        orchestrator.create(binding.public_key, _identity("customer-7"), ORIGIN, "1.1.1.1"),
        orchestrator.create(binding.public_key, _identity("customer-7"), ORIGIN, "1.1.1.2"),
    ), timeout=10)
    # Neither saw the closed one; the partial unique index let only one new one in.
    assert lookups[:2] == [None, None] and lookups[2].id == one.id
    assert one.id == other.id != first.id and one.visitor_number == 2


async def test_a_message_to_a_closed_conversation_stores_and_counts_nothing(orchestrator, uow_factory, django, redis_client):
    binding = await _binding(uow_factory, max_message_length=5)
    conversation, token, _ = await orchestrator.create(binding.public_key, None, ORIGIN, "1.1.1.1")
    await orchestrator.end(conversation.id, token, ORIGIN)
    for content in ("hello", "far too long", ""):  # before the content checks: 409, never 413
        with pytest.raises(ConversationClosedError) as refused:
            await orchestrator.submit(conversation.id, token, content, ORIGIN, "1.1.1.1", chat_extra_data={"v": 1})
        assert refused.value.extra == {"close_reason": "ended"}
    assert await _messages(uow_factory, conversation.id) == []
    assert (await _conversation(uow_factory, conversation.id)).chat_extra_data is None
    assert await redis_client.keys("chat:rl:conv:*") == [] and await redis_client.keys("chat:rl:ip:*") == []  # before the rate limits
    assert not [r for r in django.requests if r.url.path == "/api/run-session/"]
    # The desk's own state still comes first: an origin it does not allow is 403, not 409.
    with pytest.raises(OriginNotAllowedError):
        await orchestrator.submit(conversation.id, token, "hi", "https://evil.example", "1.1.1.1")


async def test_ending_during_a_run_stops_it_and_its_late_reply_only_counts_tokens(orchestrator, uow_factory, django):
    _, conversation, token, run_id = await _running(orchestrator, uow_factory)
    ended, _ = await orchestrator.end(conversation.id, token, ORIGIN)
    assert (ended.is_open, ended.close_reason, ended.run_state, ended.active_run_id) == (False, CloseReason.ENDED, RunState.IDLE, None)
    assert django.stopped == [100]
    async with uow_factory() as uow:
        events = await uow.events.replay(Stream.CONVERSATION, conversation_id=conversation.id, after_seq=None)
    assert [(e.type, e.payload) for e in events][-2:] == [("run.finished", {"status": "stop"}), ("conversation.closed", {"close_reason": "ended", "closed_at": ended.closed_at.isoformat()})]
    outcome = await orchestrator.apply_run_result(run_id, 100, "end", {"reply": "too late", "request_human": True}, {"total_tokens": 9})
    assert outcome == ApplyOutcome.IGNORED
    stored = await _conversation(uow_factory, conversation.id)
    assert (stored.tokens_used, stored.turns, stored.mode, stored.is_open) == (9, 0, Mode.BOT, False)
    assert [m.content for m in await _messages(uow_factory, conversation.id)] == ["hi"]


async def test_ending_twice_answers_the_same_close(orchestrator, uow_factory, django):
    binding = await _binding(uow_factory)
    conversation, token, _ = await orchestrator.create(binding.public_key, None, ORIGIN, "1.1.1.1")
    first, _ = await orchestrator.end(conversation.id, token, ORIGIN)
    second, _ = await orchestrator.end(conversation.id, token, ORIGIN)
    assert (second.closed_at, second.close_reason) == (first.closed_at, CloseReason.ENDED)
    async with uow_factory() as uow:
        events = await uow.events.replay(Stream.CONVERSATION, conversation_id=conversation.id, after_seq=None)
    assert [e.type for e in events] == ["conversation.closed"] and django.stopped == []


def _between_the_submit_phases(monkeypatch, act):
    """Run `act` once submit's first phase committed the run slot, before its second locks the row."""
    reads, get = [], ConversationRepository.get

    async def act_before_the_second_read(self, *args, **kwargs):
        reads.append(args)
        if len(reads) == 2:
            await act()
        return await get(self, *args, **kwargs)

    monkeypatch.setattr(ConversationRepository, "get", act_before_the_second_read)


async def test_a_close_between_claiming_the_slot_and_storing_the_message_is_409_and_stores_nothing(orchestrator, uow_factory, django, monkeypatch):
    binding = await _binding(uow_factory)
    conversation, token, _ = await orchestrator.create(binding.public_key, None, ORIGIN, "1.1.1.1")
    _between_the_submit_phases(monkeypatch, lambda: _operators(orchestrator).close(conversation.id, 1, operator_id=3, force=False, display_name=None))
    with pytest.raises(ConversationClosedError) as refused:
        await orchestrator.submit(conversation.id, token, "hi", ORIGIN, "1.1.1.1")
    assert refused.value.extra == {"close_reason": "resolved"}
    stored = await _conversation(uow_factory, conversation.id)
    assert (stored.is_open, stored.run_state, stored.active_run_id, stored.last_message_at) == (False, RunState.IDLE, None, None)
    assert await _messages(uow_factory, conversation.id) == []
    assert not [r for r in django.requests if r.url.path == "/api/run-session/"]


@pytest.mark.parametrize("max_turns", [200, 0], ids=["within budget", "budget exhausted"])
async def test_a_take_over_between_claiming_the_slot_and_storing_the_message_forwards_it_and_starts_no_run(orchestrator, uow_factory, django, monkeypatch, max_turns):
    """A take over waiting on phase one's row lock always lands before phase two. The message then
    goes to the operator: no run starts (whose result would later be applied to the held
    conversation), and no budget reply is posted into it."""
    binding = await _binding(uow_factory, max_turns=max_turns)
    conversation, token, _ = await orchestrator.create(binding.public_key, None, ORIGIN, "1.1.1.1")
    _between_the_submit_phases(monkeypatch, lambda: _operators(orchestrator).claim(conversation.id, 1, operator_id=3, force=False, display_name=None))
    result = await orchestrator.submit(conversation.id, token, "hi", ORIGIN, "1.1.1.1")
    assert result.state == SubmitState.FORWARDED_TO_OPERATOR
    stored = await _conversation(uow_factory, conversation.id)
    assert (stored.mode, stored.assigned_operator_id, stored.run_state, stored.active_run_id, stored.turns) == (Mode.HUMAN, 3, RunState.IDLE, None, 0)
    assert stored.visitor_waiting_since == stored.last_message_at  # the operator owes the visitor an answer
    assert [(m.role, m.content, m.session_id) for m in await _messages(uow_factory, conversation.id)] == [(Role.USER, "hi", None)]
    assert not [r for r in django.requests if r.url.path == "/api/run-session/"]


@pytest.mark.parametrize("max_turns", [200, 1], ids=["within budget", "budget exhausted"])
async def test_a_late_reply_handing_off_between_the_phases_forwards_the_message_and_starts_no_run(orchestrator, uow_factory, django, monkeypatch, max_turns):
    """The slot is untouched (a late reply never holds it), but the conversation now waits for a
    person: the visitor's new message is theirs, with no run and no budget reply."""
    binding = await _binding(uow_factory, max_turns=max_turns)
    conversation, token, _ = await orchestrator.create(binding.public_key, None, ORIGIN, "1.1.1.1")
    django.lose_run_session_response = True  # Django starts session 100; the chat never hears so
    await orchestrator.submit(conversation.id, token, "hi", ORIGIN, "1.1.1.1")
    django.lose_run_session_response = False
    old_run = await _active_run(uow_factory, conversation.id)
    assert await orchestrator.release_unconfirmed_start(conversation.id, old_run)  # what the reconciler does
    late_reply = lambda: orchestrator.apply_run_result(old_run, 100, "end", {"reply": "late", "request_human": True}, {"total_tokens": 1})
    _between_the_submit_phases(monkeypatch, late_reply)
    result = await orchestrator.submit(conversation.id, token, "again", ORIGIN, "1.1.1.1")
    assert result.state == SubmitState.FORWARDED_TO_OPERATOR
    stored = await _conversation(uow_factory, conversation.id)
    assert (stored.mode, stored.run_state, stored.active_run_id, stored.active_since) == (Mode.AWAITING_HUMAN, RunState.IDLE, None, None)
    assert [(m.role, m.content) for m in await _messages(uow_factory, conversation.id)] == [
        (Role.USER, "hi"), (Role.SYSTEM, "The flow could not be started."), (Role.ASSISTANT, "late"), (Role.USER, "again"),
    ]
    assert len([r for r in django.requests if r.url.path == "/api/run-session/"]) == 1 and django.stopped == []


async def test_a_slot_the_reconciler_released_between_the_phases_is_503_and_starts_no_run(orchestrator, uow_factory, django, monkeypatch):
    binding = await _binding(uow_factory)
    conversation, token, _ = await orchestrator.create(binding.public_key, None, ORIGIN, "1.1.1.1")
    # What the reconciler does to a start it takes for lost (the service stopped between the phases).
    _between_the_submit_phases(monkeypatch, lambda: orchestrator.release_unconfirmed_start(conversation.id, None))
    with pytest.raises(FlowUnavailableError):
        await orchestrator.submit(conversation.id, token, "hi", ORIGIN, "1.1.1.1")
    stored = await _conversation(uow_factory, conversation.id)
    assert (stored.mode, stored.run_state, stored.active_run_id) == (Mode.BOT, RunState.IDLE, None)
    assert [(m.role, m.content) for m in await _messages(uow_factory, conversation.id)] == [(Role.SYSTEM, "The flow could not be started.")]
    assert not [r for r in django.requests if r.url.path == "/api/run-session/"]


async def test_a_close_while_the_run_starts_is_409_keeps_the_message_and_stops_the_run(uow_factory, settings, django, redis_client):
    django.graphs[5] = CHAT_FLOW
    flows = GatedFlows(settings, transport=django.transport)
    orchestrator = ConversationOrchestrator(
        uow_factory, flows=flows, fanout=RedisFanout(redis_client), limiter=RedisRateLimiter(redis_client),
        config=RunConfig(callback_url=CALLBACK_URL, ip_message_rate=Rate(30, 60), ip_conversation_rate=Rate(20, 3600)),
        visitor_token_idle_seconds=30 * 86400,
    )
    binding = await _binding(uow_factory)
    conversation, token, _ = await orchestrator.create(binding.public_key, None, ORIGIN, "1.1.1.1")
    submit = asyncio.create_task(orchestrator.submit(conversation.id, token, "hi", ORIGIN, "1.1.1.1"))
    await asyncio.wait_for(flows.blocked.wait(), 5)
    run_id = await _active_run(uow_factory, conversation.id)
    await orchestrator.end(conversation.id, token, ORIGIN)  # the visitor starts a new chat meanwhile
    flows.release.set()
    with pytest.raises(ConversationClosedError):
        await submit
    await flows.aclose()
    assert django.stopped == [100]
    stored = await _conversation(uow_factory, conversation.id)
    assert (stored.is_open, stored.run_state, stored.active_run_id) == (False, RunState.IDLE, None)
    assert [m.content for m in await _messages(uow_factory, conversation.id)] == ["hi"]
    assert (await orchestrator.receipt(run_id)).secret  # the stopped run's callback still counts its tokens
    assert await orchestrator.apply_run_result(run_id, 100, "end", {"reply": "late"}, {"total_tokens": 3}) == ApplyOutcome.IGNORED
    assert (await _conversation(uow_factory, conversation.id)).tokens_used == 3


@pytest.mark.parametrize(("response", "broken"), [((500, {"error": "boom"}), False), ((404, {"code": "graph_not_found"}), True)], ids=["refused", "flow gone"])
async def test_a_start_refused_after_a_close_retires_the_run_and_posts_nothing(uow_factory, settings, django, redis_client, response, broken):
    django.graphs[5] = CHAT_FLOW
    flows = GatedFlows(settings, transport=django.transport)
    orchestrator = ConversationOrchestrator(
        uow_factory, flows=flows, fanout=RedisFanout(redis_client), limiter=RedisRateLimiter(redis_client),
        config=RunConfig(callback_url=CALLBACK_URL, ip_message_rate=Rate(30, 60), ip_conversation_rate=Rate(20, 3600)),
        visitor_token_idle_seconds=30 * 86400,
    )
    binding = await _binding(uow_factory)
    conversation, token, _ = await orchestrator.create(binding.public_key, None, ORIGIN, "1.1.1.1")
    submit = asyncio.create_task(orchestrator.submit(conversation.id, token, "hi", ORIGIN, "1.1.1.1"))
    await asyncio.wait_for(flows.blocked.wait(), 5)
    run_id = await _active_run(uow_factory, conversation.id)
    await _operators(orchestrator, flows).close(conversation.id, 1, operator_id=3, force=False, display_name=None)
    django.run_session_response = response
    flows.release.set()
    with pytest.raises(ConversationClosedError):
        await submit
    await flows.aclose()
    assert [m.content for m in await _messages(uow_factory, conversation.id)] == ["hi"]  # no "could not be started" notice
    receipt = await orchestrator.receipt(run_id)
    assert receipt.received_at is not None and receipt.secret == ""
    async with uow_factory() as uow:
        assert bool((await uow.bindings.get(binding.id)).broken_reason) is broken  # the flow's state is still recorded


async def test_no_message_is_stored_into_a_closed_conversation_even_by_a_caller_that_commits(uow_factory, redis_client):
    binding = make_binding(org_id=1, graph_id=5)
    closed = make_closed(binding)
    async with uow_factory() as uow:
        await uow.bindings.add(binding)
        await uow.conversations.add(closed)
        await uow.commit()
    async with uow_factory() as uow:
        conversation = await uow.conversations.get(closed.id)
        with pytest.raises(ConversationClosedError):
            await store_message(uow, Emitter(uow, RedisFanout(redis_client)), conversation, Role.ASSISTANT, "too late")
        await uow.commit()  # a caller that carries on: nothing was inserted to commit
    assert await _messages(uow_factory, closed.id) == []


async def test_a_second_device_racing_an_end_gets_a_new_conversation_not_the_closing_one(orchestrator, uow_factory, monkeypatch):
    binding = await _binding(uow_factory, identity_mode=IdentityMode.SIGNED, identity_secret="id-secret")
    first, token, _ = await orchestrator.create(binding.public_key, _identity("customer-1"), ORIGIN, "1.1.1.1")
    paused, proceed = asyncio.Event(), asyncio.Event()
    update = ConversationRepository.update

    async def update_then_hold_the_lock(self, conversation):
        await update(self, conversation)
        if not conversation.is_open and not paused.is_set():
            paused.set()
            await proceed.wait()  # inside the end's transaction: the row is locked, the close not committed

    monkeypatch.setattr(ConversationRepository, "update", update_then_hold_the_lock)
    ending = asyncio.ensure_future(orchestrator.end(first.id, token, ORIGIN))
    await asyncio.wait_for(paused.wait(), timeout=5)
    joining = asyncio.ensure_future(orchestrator.create(binding.public_key, _identity("customer-1"), ORIGIN, "1.1.1.2"))
    done, _ = await asyncio.wait({joining}, timeout=0.3)
    assert not done, "the create did not wait for the end"
    proceed.set()
    await asyncio.wait_for(ending, timeout=5)
    joined, joined_token, _ = await asyncio.wait_for(joining, timeout=5)
    assert joined.id != first.id and (joined.visitor_number, joined.is_open) == (2, True)
    assert (await orchestrator.resolve(joined.id, joined_token))[0].is_open


async def test_a_stop_while_the_run_starts_answers_stopped_keeps_the_message_and_stops_the_run(uow_factory, settings, django, redis_client):
    django.graphs[5] = CHAT_FLOW
    flows = GatedFlows(settings, transport=django.transport)
    orchestrator = ConversationOrchestrator(
        uow_factory, flows=flows, fanout=RedisFanout(redis_client), limiter=RedisRateLimiter(redis_client),
        config=RunConfig(callback_url=CALLBACK_URL, ip_message_rate=Rate(30, 60), ip_conversation_rate=Rate(20, 3600)),
        visitor_token_idle_seconds=30 * 86400,
    )
    binding = await _binding(uow_factory)
    conversation, token, _ = await orchestrator.create(binding.public_key, None, ORIGIN, "1.1.1.1")
    submit = asyncio.create_task(orchestrator.submit(conversation.id, token, "hi", ORIGIN, "1.1.1.1"))
    await asyncio.wait_for(flows.blocked.wait(), 5)
    run_id = await _active_run(uow_factory, conversation.id)
    await orchestrator.stop(conversation.id, token, ORIGIN)  # the visitor presses Stop
    assert django.stopped == []  # Django has not named the session yet: the starting submit stops it
    flows.release.set()
    result = await submit
    await flows.aclose()

    assert result.state == SubmitState.STOPPED
    assert django.stopped == [100]
    stored = await _conversation(uow_factory, conversation.id)
    assert (stored.mode, stored.run_state, stored.active_run_id, stored.handoff_reason) == (Mode.BOT, RunState.IDLE, None, "")
    assert [(m.role, m.content) for m in await _messages(uow_factory, conversation.id)] == [(Role.USER, "hi")]
    events = await _events(uow_factory, conversation.id)
    assert events.count("run.finished") == 1 and "run.started" not in events
    # The stopped run's result counts its tokens and posts nothing.
    assert await orchestrator.apply_run_result(run_id, 100, "stop", None, {"total_tokens": 2}) == ApplyOutcome.IGNORED
    stored = await _conversation(uow_factory, conversation.id)
    assert (stored.tokens_used, stored.mode) == (2, Mode.BOT)
    assert [m.content for m in await _messages(uow_factory, conversation.id)] == ["hi"]


async def test_a_stop_queued_on_the_first_phases_lock_keeps_the_message_and_answers_stopped(orchestrator, uow_factory, django, monkeypatch):
    """The visitor presses Stop as the message goes out: the stop waits on phase one's row lock,
    frees the slot it claimed, and the message is kept with no run for it."""
    binding = await _binding(uow_factory)
    conversation, token, _ = await orchestrator.create(binding.public_key, None, ORIGIN, "1.1.1.1")
    _between_the_submit_phases(monkeypatch, lambda: orchestrator.stop(conversation.id, token, ORIGIN))
    result = await orchestrator.submit(conversation.id, token, "hi", ORIGIN, "1.1.1.1")
    assert result.state == SubmitState.STOPPED
    stored = await _conversation(uow_factory, conversation.id)
    assert (stored.mode, stored.run_state, stored.active_run_id) == (Mode.BOT, RunState.IDLE, None)
    assert [(m.id, m.role, m.content) for m in await _messages(uow_factory, conversation.id)] == [(result.message_id, Role.USER, "hi")]
    # The stop's own run.finished closes what the widget showed; no run was asked for.
    assert await _events(uow_factory, conversation.id) == ["run.finished", "message.created"]
    assert not [r for r in django.requests if r.url.path == "/api/run-session/"] and django.stopped == []
