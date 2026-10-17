import asyncio
from datetime import timedelta

import pytest
from application.orchestrators.conversation import ApplyOutcome, ConversationOrchestrator, RunConfig
from application.orchestrators.lifecycle import LifecycleTimers
from application.orchestrators.reconcile import Reconciler
from application.tokens import visitor_token_hash
from common.humanize import Rate
from common.utils import new_id, utc_today, utcnow
from domain.enums import BindingStyle, CloseReason, ConversationStatus, Mode, OnResponseTimeout, Role, RunState, Stream, SubmitState
from domain.models import CallbackReceipt, ConversationEvent
from infrastructure.database.models import VisitorTokenRow
from infrastructure.django.client import DjangoClient
from infrastructure.redis.counters import RedisRateLimiter
from infrastructure.redis.fanout import RedisFanout
from sqlalchemy import update
from tests.factories import HANDBACK_NOTICE, make_binding, make_closed, make_conversation
from tests.integration.test_callback_endpoint import _payload, _signed
from tests.infrastructure.test_django_client import CHAT_FLOW

ORIGIN = "https://example.com"


@pytest.fixture
async def parts(uow_factory, settings, django, redis_client):
    django.graphs[5] = CHAT_FLOW
    flows = DjangoClient(settings, transport=django.transport)
    conversations = ConversationOrchestrator(
        uow_factory, flows=flows, fanout=RedisFanout(redis_client), limiter=RedisRateLimiter(redis_client),
        config=RunConfig(callback_url="http://chat:8200/cb", ip_message_rate=Rate(30, 60), ip_conversation_rate=Rate(20, 3600)),
        visitor_token_idle_seconds=30 * 86400,
    )
    reconciler = _reconciler(uow_factory, conversations, flows, redis_client)
    yield conversations, reconciler
    await flows.aclose()


def _reconciler(uow_factory, conversations, flows, redis_client, **overrides) -> Reconciler:
    return Reconciler(
        uow_factory, conversations=conversations, flows=flows, timers=LifecycleTimers(uow_factory, fanout=RedisFanout(redis_client)),
        stale_after_seconds=300, unconfirmed_start_release_seconds=60, run_timeout_seconds=1800, retention_seconds=7 * 86400,
        visitor_token_idle_seconds=30 * 86400, **overrides,
    )


async def _stuck(uow_factory, conversations, *, minutes):
    binding = make_binding(org_id=1, graph_id=5)
    async with uow_factory() as uow:
        await uow.bindings.add(binding)
        await uow.commit()
    conversation, token, _ = await conversations.create(binding.public_key, None, ORIGIN, "1.1.1.1")
    await conversations.submit(conversation.id, token, "hi", ORIGIN, "1.1.1.1")
    async with uow_factory() as uow:
        stored = await uow.conversations.get(conversation.id)
        stored.active_since = utcnow() - timedelta(minutes=minutes)
        await uow.conversations.update(stored)
        await uow.commit()
        return stored


async def test_fresh_runs_are_left_alone(uow_factory, parts, django):
    conversations, reconciler = parts
    await _stuck(uow_factory, conversations, minutes=1)
    assert await reconciler.run_once(utcnow()) == 0
    assert not [r for r in django.requests if r.url.path.startswith("/api/sessions/")]


async def test_finished_run_is_applied_from_session_messages(uow_factory, parts, django):
    conversations, reconciler = parts
    conversation = await _stuck(uow_factory, conversations, minutes=10)
    django.sessions[100].update(status="end", token_usage={"total_tokens": 11})
    django.messages[100] = [{"id": 1, "message_data": {"message_type": "graph_end", "end_node_result": {"reply": "late reply"}}}]
    assert await reconciler.run_once(utcnow()) == 1
    async with uow_factory() as uow:
        stored = await uow.conversations.get(conversation.id)
        messages = await uow.messages.page(conversation.id, None, 10)
    assert stored.run_state == RunState.IDLE and stored.tokens_used == 11
    assert messages[-1].role == Role.ASSISTANT and messages[-1].content == "late reply"
    assert await reconciler.run_once(utcnow()) == 0


async def test_run_past_timeout_is_stopped(uow_factory, parts, django):
    conversations, reconciler = parts
    conversation = await _stuck(uow_factory, conversations, minutes=31)
    django.sessions[100].update(status="run")
    assert await reconciler.run_once(utcnow()) == 1
    assert django.stopped == [100]
    async with uow_factory() as uow:
        stored = await uow.conversations.get(conversation.id)
        messages = await uow.messages.page(conversation.id, None, 10)
    assert stored.run_state == RunState.IDLE and messages[-1].role == Role.SYSTEM and "stop" in messages[-1].content


async def test_run_and_reconcile_calls_use_the_system_key(uow_factory, parts, django, settings):
    # No user is present on these paths; the graph id comes from a binding checked with the user's own token.
    conversations, reconciler = parts
    await _stuck(uow_factory, conversations, minutes=31)
    django.sessions[100].update(status="run")
    assert await reconciler.run_once(utcnow()) == 1
    paths = {request.url.path for request in django.requests}
    assert {"/api/run-session/", "/api/sessions/100/", "/api/sessions/100/stop/"} <= paths
    for request in django.requests:
        assert request.headers["X-Api-Key"] == settings.DJANGO_API_KEY and "Authorization" not in request.headers


async def test_final_usage_after_a_timeout_stop_tops_up_the_budgets(uow_factory, parts, django, client):
    conversations, reconciler = parts
    conversation = await _stuck(uow_factory, conversations, minutes=31)
    django.sessions[100].update(status="run", token_usage={"total_tokens": 5})  # read before the stop
    assert await reconciler.run_once(utcnow()) == 1
    # Django's callback carries the final usage, including what the run spent while stopping.
    receipt = await conversations.receipt(conversation.active_run_id)
    assert receipt.tokens_counted == 5 and receipt.secret  # kept: the callback must still verify
    body, headers = _signed(receipt.secret, _payload(status="stop", tokens=12))
    url = f"/chat/internal/v1/session-callbacks/{receipt.run_id}"
    assert (await client.post(url, content=body, headers=headers)).json() == {"result": "duplicate"}
    body, headers = _signed(receipt.secret, _payload(status="stop", tokens=12))
    assert (await client.post(url, content=body, headers=headers)).json() == {"result": "ignored"}  # retry
    async with uow_factory() as uow:
        stored = await uow.conversations.get(conversation.id)
        messages = await uow.messages.page(conversation.id, None, 10)
        daily = await uow.usage.daily_tokens(stored.binding_id, utc_today())
    assert (stored.tokens_used, daily, stored.run_state) == (12, 12, RunState.IDLE)
    assert len(messages) == 2  # the user message and the stop notice: the top-up posts nothing


async def test_run_still_running_within_timeout_is_kept(uow_factory, parts, django):
    conversations, reconciler = parts
    conversation = await _stuck(uow_factory, conversations, minutes=10)
    django.sessions[100].update(status="run")
    assert await reconciler.run_once(utcnow()) == 0
    async with uow_factory() as uow:
        assert (await uow.conversations.get(conversation.id)).run_state == RunState.RUNNING


async def test_session_missing_in_django_releases_as_error(uow_factory, parts, django):
    conversations, reconciler = parts
    conversation = await _stuck(uow_factory, conversations, minutes=10)
    del django.sessions[100]
    assert await reconciler.run_once(utcnow()) == 1
    async with uow_factory() as uow:
        assert (await uow.conversations.get(conversation.id)).run_state == RunState.IDLE


async def test_old_events_are_pruned(uow_factory, parts):
    _, reconciler = parts
    binding = make_binding(org_id=1, graph_id=5)
    from tests.factories import make_conversation

    conversation = make_conversation(binding)
    async with uow_factory() as uow:
        await uow.bindings.add(binding)
        await uow.conversations.add(conversation)
        await uow.events.add(ConversationEvent(id=new_id(), stream=Stream.CONVERSATION, conversation_id=conversation.id, org_id=1, type="x", payload={}, created_at=utcnow() - timedelta(days=8)))
        await uow.events.add(ConversationEvent(id=new_id(), stream=Stream.CONVERSATION, conversation_id=conversation.id, org_id=1, type="y", payload={}, created_at=utcnow()))
        await uow.commit()
    await reconciler.run_once(utcnow())
    async with uow_factory() as uow:
        assert [e.type for e in await uow.events.replay(Stream.CONVERSATION, conversation_id=conversation.id, after_seq=None)] == ["y"]


async def test_receipts_older_than_two_days_are_pruned(uow_factory, parts):
    _, reconciler = parts
    binding = make_binding(org_id=1, graph_id=5)
    conversation = make_conversation(binding)
    now = utcnow()
    cases = {  # name: (created days ago, received days ago)
        "applied long ago": (3, 3),
        "applied recently": (3, 1),
        "waiting": (1, None),
        "never answered": (3, None),
    }
    run_ids = {name: new_id() for name in cases}
    async with uow_factory() as uow:
        await uow.bindings.add(binding)
        await uow.conversations.add(conversation)
        for name, (created, received) in cases.items():
            await uow.receipts.add(CallbackReceipt(
                run_id=run_ids[name], conversation_id=conversation.id, message_id=new_id(),
                secret="" if received else "s" * 43, created_at=now - timedelta(days=created),
                received_at=now - timedelta(days=received) if received else None,
            ))
        await uow.commit()
    await reconciler.run_once(now)
    async with uow_factory() as uow:
        kept = [name for name in cases if await uow.receipts.get(run_ids[name])]
    assert kept == ["applied recently", "waiting"]


@pytest.mark.parametrize("seconds, released", [(90, True), (30, False)])
async def test_slot_claimed_without_a_receipt_is_released(uow_factory, parts, seconds, released):
    # The service stopped between claiming the slot and storing the run.
    _, reconciler = parts
    binding = make_binding(org_id=1, graph_id=5)
    conversation = make_conversation(binding, run_state=RunState.STARTING, active_since=utcnow() - timedelta(seconds=seconds))
    async with uow_factory() as uow:
        await uow.bindings.add(binding)
        await uow.conversations.add(conversation)
        await uow.commit()
    assert await reconciler.run_once(utcnow()) == (1 if released else 0)
    async with uow_factory() as uow:
        stored = await uow.conversations.get(conversation.id)
        messages = await uow.messages.page(conversation.id, None, 10)
    if released:
        assert stored.run_state == RunState.IDLE and stored.active_since is None
        assert [(m.role, m.content) for m in messages] == [(Role.SYSTEM, "The flow could not be started.")]
    else:
        assert stored.run_state == RunState.STARTING and messages == []


async def _unconfirmed(uow_factory, conversations, django):
    """A start whose answer Django lost although it created session 100. Returns conversation, token, run id."""
    binding = make_binding(org_id=1, graph_id=5)
    async with uow_factory() as uow:
        await uow.bindings.add(binding)
        await uow.commit()
    conversation, token, _ = await conversations.create(binding.public_key, None, ORIGIN, "1.1.1.1")
    django.lose_run_session_response = True
    assert (await conversations.submit(conversation.id, token, "hi", ORIGIN, "1.1.1.1")).state == SubmitState.PROCESSING
    django.lose_run_session_response = False
    async with uow_factory() as uow:
        run_id = (await uow.conversations.get(conversation.id)).active_run_id
    return conversation, token, run_id


async def _age(uow_factory, conversation_id, seconds):
    async with uow_factory() as uow:
        stored = await uow.conversations.get(conversation_id, for_update=True)
        stored.active_since = utcnow() - timedelta(seconds=seconds)
        await uow.conversations.update(stored)
        await uow.commit()


async def _run_events(uow_factory, conversation_id):
    async with uow_factory() as uow:
        events = await uow.events.replay(Stream.CONVERSATION, conversation_id=conversation_id, after_seq=None)
    return [{"type": e.type, **e.payload} for e in events if e.type.startswith("run.")]


async def test_unconfirmed_start_is_released_after_the_setting_and_not_before(uow_factory, parts, django):
    conversations, reconciler = parts
    conversation, _, run_id = await _unconfirmed(uow_factory, conversations, django)
    await _age(uow_factory, conversation.id, 30)
    assert await reconciler.run_once(utcnow()) == 0
    async with uow_factory() as uow:
        assert (await uow.conversations.get(conversation.id)).run_state == RunState.STARTING
    await _age(uow_factory, conversation.id, 90)  # past the 60 s release, well inside the 5 min stale window
    assert await reconciler.run_once(utcnow()) == 1
    async with uow_factory() as uow:
        stored = await uow.conversations.get(conversation.id)
        messages = await uow.messages.page(conversation.id, None, 10)
        receipt = await uow.receipts.get(run_id)
    assert (stored.run_state, stored.active_run_id) == (RunState.IDLE, None)
    assert [(m.role, m.content) for m in messages] == [(Role.USER, "hi"), (Role.SYSTEM, "The flow could not be started.")]
    assert await _run_events(uow_factory, conversation.id) == [{"type": "run.finished", "status": "error"}]
    assert receipt.received_at is None and receipt.secret  # a late callback can still be verified
    assert not [r for r in django.requests if r.url.path.startswith("/api/sessions/")]  # no session to ask about


async def test_late_reply_after_release_is_stored_and_counted(uow_factory, parts, django):
    conversations, reconciler = parts
    conversation, _, run_id = await _unconfirmed(uow_factory, conversations, django)
    await _age(uow_factory, conversation.id, 90)
    await reconciler.run_once(utcnow())
    outcome = await conversations.apply_run_result(run_id, 100, "end", {"reply": "sorry I'm late"}, {"total_tokens": 13})
    assert outcome == ApplyOutcome.APPLIED
    async with uow_factory() as uow:
        stored = await uow.conversations.get(conversation.id)
        messages = await uow.messages.page(conversation.id, None, 10)
        daily = await uow.usage.daily_tokens(stored.binding_id, utc_today())
    assert (stored.run_state, stored.tokens_used, stored.turns, daily) == (RunState.IDLE, 13, 1, 13)
    assert (messages[-1].role, messages[-1].content, messages[-1].session_id) == (Role.ASSISTANT, "sorry I'm late", 100)
    assert await _run_events(uow_factory, conversation.id) == [{"type": "run.finished", "status": "error"}]  # no second finish
    assert stored.late_reply_run_id is None  # used up: nothing else may post as this run
    assert await conversations.apply_run_result(run_id, 100, "end", {"reply": "again"}, {"total_tokens": 13}) == ApplyOutcome.DUPLICATE


@pytest.mark.parametrize("newer_finished", [False, True])
async def test_late_reply_after_a_newer_run_counts_tokens_only(uow_factory, parts, django, newer_finished):
    conversations, reconciler = parts
    conversation, token, run_id = await _unconfirmed(uow_factory, conversations, django)
    await _age(uow_factory, conversation.id, 90)
    await reconciler.run_once(utcnow())
    await conversations.submit(conversation.id, token, "still there?", ORIGIN, "1.1.1.1")  # session 101
    async with uow_factory() as uow:
        newer_run_id = (await uow.conversations.get(conversation.id)).active_run_id
    if newer_finished:
        await conversations.apply_run_result(newer_run_id, 101, "end", {"reply": "yes"}, {"total_tokens": 2})
    before = await _snapshot(uow_factory, conversation.id)

    outcome = await conversations.apply_run_result(run_id, 100, "end", {"reply": "stale answer"}, {"total_tokens": 13})

    assert outcome == ApplyOutcome.IGNORED
    after = await _snapshot(uow_factory, conversation.id)
    assert after["tokens_used"] == before["tokens_used"] + 13 and after["daily"] == before["daily"] + 13
    assert {key: after[key] for key in ("run_state", "active_run_id", "turns", "messages")} == {
        key: before[key] for key in ("run_state", "active_run_id", "turns", "messages")
    }
    assert "stale answer" not in after["messages"]
    assert after["run_state"] == (RunState.IDLE if newer_finished else RunState.RUNNING)


async def _snapshot(uow_factory, conversation_id) -> dict:
    async with uow_factory() as uow:
        stored = await uow.conversations.get(conversation_id)
        messages = await uow.messages.page(conversation_id, None, 50)
        daily = await uow.usage.daily_tokens(stored.binding_id, utc_today())
    return {
        "run_state": stored.run_state, "active_run_id": stored.active_run_id, "turns": stored.turns,
        "tokens_used": stored.tokens_used, "daily": daily, "messages": [m.content for m in messages],
    }


async def test_reconcile_prunes_idle_visitor_tokens_only(uow_factory, parts, session_factory):
    conversations, reconciler = parts
    binding = make_binding(org_id=1, graph_id=5)
    async with uow_factory() as uow:
        await uow.bindings.add(binding)
        await uow.commit()
    _, idle_token, _ = await conversations.create(binding.public_key, None, ORIGIN, "1.1.1.1")
    _, fresh_token, _ = await conversations.create(binding.public_key, None, ORIGIN, "1.1.1.1")
    idle_hash, fresh_hash = visitor_token_hash(idle_token), visitor_token_hash(fresh_token)
    async with session_factory() as session:
        await session.execute(update(VisitorTokenRow).where(VisitorTokenRow.token_hash == idle_hash).values(last_used_at=utcnow() - timedelta(days=31)))
        await session.commit()
    await reconciler.run_once(utcnow())
    async with uow_factory() as uow:
        assert await uow.visitor_tokens.get(idle_hash) is None
        assert await uow.visitor_tokens.get(fresh_hash) is not None



# ---- the desks' inactivity rules ----------------------------------------------------------------

NOW = utcnow()


async def _seed(uow_factory, binding, *conversations):
    async with uow_factory() as uow:
        await uow.bindings.add(binding)
        for conversation in conversations:
            await uow.conversations.add(conversation)
        await uow.commit()


async def _stored(uow_factory, conversation_id):
    async with uow_factory() as uow:
        return await uow.conversations.get(conversation_id), await uow.messages.page(conversation_id, None, 50)


async def _stream(uow_factory, stream, conversation_id):
    async with uow_factory() as uow:
        events = await uow.events.replay(stream, conversation_id=conversation_id, org_id=None, after_seq=None)
    return [(event.type, event.payload) for event in events]


def _waiting(binding, minutes, mode="awaiting_human", **overrides):
    """A visitor waiting for a person since `minutes` before NOW; held by operator 3 when human."""
    since = NOW - timedelta(minutes=minutes)
    holder = {"assigned_operator_id": 3} if mode == "human" else {}
    return make_conversation(binding, mode=mode, visitor_waiting_since=since, last_message_at=since, last_message_role=Role.USER, **{**holder, **overrides})


def _idle(binding, hours, **overrides):
    return make_conversation(binding, last_message_at=NOW - timedelta(hours=hours), **{"last_message_role": Role.ASSISTANT, **overrides})


@pytest.mark.parametrize("mode", ["awaiting_human", "human"], ids=["unclaimed", "held, the visitor wrote again"])
async def test_a_visitor_waiting_past_the_response_time_goes_back_to_the_bot_with_the_notice(uow_factory, parts, mode):
    _, reconciler = parts
    binding = make_binding(org_id=1, graph_id=5, response_time_seconds=600)
    overdue, not_yet = _waiting(binding, 11, mode), _waiting(binding, 9, mode)
    await _seed(uow_factory, binding, overdue, not_yet)
    await reconciler.run_once(NOW)
    stored, messages = await _stored(uow_factory, overdue.id)
    assert (stored.mode, stored.assigned_operator_id, stored.handoff_at, stored.visitor_waiting_since, stored.is_open) == (Mode.BOT, None, None, None, True)
    assert [(m.role, m.content, m.visible_name) for m in messages] == [(Role.ASSISTANT, HANDBACK_NOTICE, None)]
    visitor = await _stream(uow_factory, Stream.CONVERSATION, overdue.id)
    assert [kind for kind, _ in visitor] == ["mode.changed", "message.created"] and visitor[0][1] == {"mode": "bot"}
    inbox = await _stream(uow_factory, Stream.INBOX, overdue.id)
    assert inbox[-1][0] == "conversation.updated" and (inbox[-1][1]["mode"], inbox[-1][1]["assigned_operator_id"]) == ("bot", None)
    untouched, untouched_messages = await _stored(uow_factory, not_yet.id)
    assert (untouched.mode, untouched_messages) == (Mode(mode), [])


async def test_the_hand_back_comes_only_once_the_response_time_has_passed(uow_factory, parts):
    _, reconciler = parts
    binding = make_binding(org_id=1, graph_id=5, response_time_seconds=600)
    waiting = _waiting(binding, 10)
    await _seed(uow_factory, binding, waiting)
    await reconciler.run_once(NOW)  # the deadline is now: not past yet
    assert (await _stored(uow_factory, waiting.id))[0].mode == Mode.AWAITING_HUMAN
    await reconciler.run_once(NOW + timedelta(microseconds=1))
    assert (await _stored(uow_factory, waiting.id))[0].mode == Mode.BOT


@pytest.mark.parametrize("action", [OnResponseTimeout.OVERDUE, OnResponseTimeout.WAIT])
async def test_overdue_and_wait_desks_leave_the_visitor_waiting(uow_factory, parts, action):
    _, reconciler = parts
    binding = make_binding(org_id=1, graph_id=5, on_response_timeout=action, response_time_seconds=600)
    waiting = _waiting(binding, 60)
    await _seed(uow_factory, binding, waiting)
    await reconciler.run_once(NOW)
    stored, messages = await _stored(uow_factory, waiting.id)
    assert (stored.mode, stored.visitor_waiting_since, messages) == (Mode.AWAITING_HUMAN, waiting.visitor_waiting_since, [])


@pytest.mark.parametrize("notice", ["", "   "])
async def test_an_empty_notice_hands_back_without_a_message(uow_factory, parts, notice):
    _, reconciler = parts
    binding = make_binding(org_id=1, graph_id=5, handback_message=notice)
    waiting = _waiting(binding, 60)
    await _seed(uow_factory, binding, waiting)
    await reconciler.run_once(NOW)
    stored, messages = await _stored(uow_factory, waiting.id)
    assert (stored.mode, messages) == (Mode.BOT, [])
    assert [kind for kind, _ in await _stream(uow_factory, Stream.CONVERSATION, waiting.id)] == ["mode.changed"]


@pytest.mark.parametrize("state", ["bot", "in progress", "waiting, keep waiting"])
async def test_a_support_desk_closes_a_conversation_idle_past_close_after_and_an_ongoing_desk_never_does(uow_factory, parts, state):
    _, reconciler = parts
    rules = dict(response_time_seconds=600, close_after_seconds=86_400, on_response_timeout=OnResponseTimeout.WAIT)
    support, ongoing = make_binding(org_id=1, graph_id=5, **rules), make_binding(org_id=1, graph_id=5, style=BindingStyle.ONGOING, **rules)

    def idle(binding, hours):
        if state == "bot":
            return _idle(binding, hours)
        if state == "in progress":
            return _idle(binding, hours, mode="human", assigned_operator_id=3, last_message_role=Role.OPERATOR)
        return _waiting(binding, hours * 60)

    closing, recent, kept = idle(support, 25), idle(support, 23), idle(ongoing, 24 * 30)
    await _seed(uow_factory, support, closing, recent)
    await _seed(uow_factory, ongoing, kept)
    await reconciler.run_once(NOW)
    stored, messages = await _stored(uow_factory, closing.id)
    assert (stored.status, stored.close_reason, stored.closed_at, stored.closed_by_user_id) == (ConversationStatus.CLOSED, CloseReason.INACTIVE, NOW, None)
    assert (stored.mode, stored.assigned_operator_id) == (closing.mode, closing.assigned_operator_id) and messages == []  # closing posts nothing
    closed_event = {"close_reason": "inactive", "closed_at": NOW.isoformat()}
    assert await _stream(uow_factory, Stream.CONVERSATION, closing.id) == [("conversation.closed", closed_event)]
    inbox = await _stream(uow_factory, Stream.INBOX, closing.id)
    assert inbox[0] == ("conversation.closed", {"conversation_id": str(closing.id), **closed_event, "closed_by_user_id": None})
    assert inbox[1][0] == "conversation.updated" and (inbox[1][1]["status"], inbox[1][1]["close_reason"]) == ("closed", "inactive")
    for open_one in (recent, kept):
        assert (await _stored(uow_factory, open_one.id))[0].is_open


async def test_silent_conversations_runs_in_flight_and_tests_are_left_alone(uow_factory, parts):
    _, reconciler = parts
    binding = make_binding(org_id=1, graph_id=5)
    silent = make_conversation(binding, created_at=NOW - timedelta(days=3))
    running = _idle(binding, 25, run_state=RunState.RUNNING, active_since=NOW - timedelta(minutes=1))
    idle_test, waiting_test = _idle(binding, 25, is_test=True), _waiting(binding, 60, is_test=True)
    await _seed(uow_factory, binding, silent, running, idle_test, waiting_test)
    await reconciler.run_once(NOW)
    for conversation in (silent, running, idle_test, waiting_test):
        stored, messages = await _stored(uow_factory, conversation.id)
        assert (stored.is_open, stored.mode, messages) == (True, conversation.mode, []), conversation


async def test_a_hand_back_is_activity_so_the_same_pass_does_not_also_close_it(uow_factory, parts):
    _, reconciler = parts
    binding = make_binding(org_id=1, graph_id=5, response_time_seconds=600, close_after_seconds=3600)
    waiting = _waiting(binding, 120)  # past both: overdue and silent past close-after
    await _seed(uow_factory, binding, waiting)
    await reconciler.run_once(NOW)
    stored, messages = await _stored(uow_factory, waiting.id)
    assert (stored.mode, stored.is_open, [m.content for m in messages]) == (Mode.BOT, True, [HANDBACK_NOTICE])


async def test_a_second_pass_finds_nothing_left_to_do(uow_factory, parts):
    _, reconciler = parts
    binding = make_binding(org_id=1, graph_id=5)
    waiting, idle = _waiting(binding, 60), _idle(binding, 25)
    await _seed(uow_factory, binding, waiting, idle)
    await reconciler.run_once(NOW)
    before = [await _stream(uow_factory, stream, c.id) for stream in Stream for c in (waiting, idle)]
    await reconciler.run_once(NOW + timedelta(minutes=1))
    assert [await _stream(uow_factory, stream, c.id) for stream in Stream for c in (waiting, idle)] == before
    assert len((await _stored(uow_factory, waiting.id))[1]) == 1


async def test_two_workers_passing_at_once_handle_each_conversation_once(uow_factory, parts, settings, django, redis_client):
    conversations, first = parts
    second_flows = DjangoClient(settings, transport=django.transport)
    second = _reconciler(uow_factory, conversations, second_flows, redis_client)
    binding = make_binding(org_id=1, graph_id=5)
    waiting = [_waiting(binding, 60 + index) for index in range(8)]
    idle = [_idle(binding, 25 + index) for index in range(8)]
    await _seed(uow_factory, binding, *waiting, *idle)
    await asyncio.gather(first.run_once(NOW), second.run_once(NOW))
    await second_flows.aclose()
    for conversation in waiting:
        stored, messages = await _stored(uow_factory, conversation.id)
        assert (stored.mode, [m.content for m in messages]) == (Mode.BOT, [HANDBACK_NOTICE])
        assert [kind for kind, _ in await _stream(uow_factory, Stream.CONVERSATION, conversation.id)].count("mode.changed") == 1
    for conversation in idle:
        assert not (await _stored(uow_factory, conversation.id))[0].is_open
        assert [kind for kind, _ in await _stream(uow_factory, Stream.CONVERSATION, conversation.id)] == ["conversation.closed"]


@pytest.mark.parametrize("rule", ["hand-back", "close after"])
async def test_a_row_another_transaction_holds_is_skipped_and_handled_on_the_next_pass(uow_factory, parts, rule):
    _, reconciler = parts
    binding = make_binding(org_id=1, graph_id=5)
    due = _waiting(binding, 60) if rule == "hand-back" else _idle(binding, 25)
    await _seed(uow_factory, binding, due)
    async with uow_factory() as holder:  # e.g. a visitor's message being stored right now
        await holder.conversations.get(due.id, for_update=True)
        await asyncio.wait_for(reconciler.run_once(NOW), timeout=5)  # never waits for the lock
        stored = (await _stored(uow_factory, due.id))[0]
        assert (stored.mode, stored.is_open) == (due.mode, True)
    await reconciler.run_once(NOW + timedelta(minutes=1))
    stored = (await _stored(uow_factory, due.id))[0]
    assert stored.mode == Mode.BOT if rule == "hand-back" else not stored.is_open


async def test_a_pass_handles_a_batch_and_the_next_pass_the_rest(uow_factory, parts, settings, django, redis_client):
    conversations, _ = parts
    flows = DjangoClient(settings, transport=django.transport)
    reconciler = _reconciler(uow_factory, conversations, flows, redis_client, timer_batch=2)
    binding = make_binding(org_id=1, graph_id=5)
    waiting = [_waiting(binding, 60 + index) for index in range(3)]
    await _seed(uow_factory, binding, *waiting)
    await reconciler.run_once(NOW)
    modes = [(await _stored(uow_factory, c.id))[0].mode for c in waiting]
    assert modes == [Mode.AWAITING_HUMAN, Mode.BOT, Mode.BOT]  # longest waits first
    await reconciler.run_once(NOW)
    assert (await _stored(uow_factory, waiting[0].id))[0].mode == Mode.BOT
    await flows.aclose()


async def test_closed_conversations_are_never_touched_by_the_timers(uow_factory, parts):
    _, reconciler = parts
    binding = make_binding(org_id=1, graph_id=5)
    closed = make_closed(binding, mode="awaiting_human", last_message_at=NOW - timedelta(days=3), closed_at=NOW - timedelta(days=2))
    await _seed(uow_factory, binding, closed)
    await reconciler.run_once(NOW)
    stored, messages = await _stored(uow_factory, closed.id)
    assert (stored, messages) == (closed, [])
