import asyncio
import itertools
from datetime import UTC, datetime, timedelta

import pytest
from application.orchestrators.retention import RetentionOrchestrator
from common.utils import new_id
from domain.enums import CloseReason, Role, RunState, Stream
from domain.models import CallbackReceipt, ConversationEvent, Message, VisitorToken
from infrastructure.database.models import (
    CallbackReceiptRow,
    ConversationEventRow,
    ConversationRow,
    MessageRow,
    VisitorTokenRow,
)
from infrastructure.database.unit_of_work import SQLAlchemyUnitOfWork
from sqlalchemy import func, select
from tests.factories import make_binding, make_closed, make_conversation

PURGE = "/chat/internal/v1/retention/purge"
KEY_HEADER = "X-Internal-Api-Key"
CUTOFF = datetime.fromisoformat("2026-01-01T00:00:00+00:00")
OLD = CUTOFF - timedelta(days=1)
RECENT = CUTOFF + timedelta(days=1)


@pytest.fixture
def key_headers(settings):
    return {KEY_HEADER: settings.CHAT_INTERNAL_API_KEY}


def _body(org_id=1, older_than=CUTOFF.isoformat()):
    return {"org_id": org_id, "older_than": older_than}


def _message(conversation, created_at=OLD) -> Message:
    return Message(id=new_id(), conversation_id=conversation.id, role=Role.USER, content="hi", actions=None, session_id=None, created_at=created_at, author_user_id=None)


async def _store(uow_factory, *conversations):
    """Store each conversation under its own desk."""
    async with uow_factory() as uow:
        for conversation in conversations:
            if await uow.bindings.get(conversation.binding_id) is None:
                await uow.bindings.add(make_binding(org_id=conversation.org_id, id=conversation.binding_id))
            await uow.conversations.add(conversation)
        await uow.commit()


def _closed(org_id=1, *, last_message_at=OLD, created_at=OLD, **overrides):
    return make_closed(make_binding(org_id=org_id), last_message_at=last_message_at, created_at=created_at, closed_at=OLD, **overrides)


async def _remaining_ids(session_factory) -> set:
    async with session_factory() as session:
        return set((await session.execute(select(ConversationRow.id))).scalars())


async def _count(session_factory, row, conversation_id) -> int:
    async with session_factory() as session:
        return (await session.execute(select(func.count()).select_from(row).where(row.conversation_id == conversation_id))).scalar_one()


async def test_purge_deletes_only_old_conversations_of_that_org(client, uow_factory, session_factory, key_headers):
    old = _closed(org_id=1)
    recent = _closed(org_id=1, last_message_at=RECENT)
    other_org_old = _closed(org_id=2)
    await _store(uow_factory, old, recent, other_org_old)

    response = await client.post(PURGE, json=_body(org_id=1), headers=key_headers)

    assert response.status_code == 200
    assert response.json() == {"deleted": 1}
    assert await _remaining_ids(session_factory) == {recent.id, other_org_old.id}


@pytest.mark.parametrize("reason", list(CloseReason))
async def test_purge_deletes_a_closed_conversation_whatever_closed_it(client, uow_factory, session_factory, key_headers, reason):
    closed = _closed(reason=reason)
    await _store(uow_factory, closed)

    response = await client.post(PURGE, json=_body(), headers=key_headers)

    assert response.json() == {"deleted": 1}
    assert await _remaining_ids(session_factory) == set()


@pytest.mark.parametrize(
    "mode, state",
    [
        pytest.param("bot", {}, id="bot-idle"),
        pytest.param("bot", dict(run_state=RunState.STARTING, active_since=OLD), id="bot-starting"),
        pytest.param("bot", dict(run_state=RunState.RUNNING, active_run_id=new_id(), active_since=OLD), id="bot-running"),
        pytest.param("bot", dict(late_reply_run_id=new_id()), id="bot-awaiting-a-late-reply"),
        pytest.param("awaiting_human", {}, id="awaiting-human"),
        pytest.param("human", {}, id="human-with-an-operator"),
    ],
)
async def test_purge_never_deletes_an_open_conversation(client, uow_factory, session_factory, key_headers, mode, state):
    open_conversation = make_conversation(make_binding(org_id=1), mode=mode, last_message_at=OLD, created_at=OLD, **state)
    await _store(uow_factory, open_conversation)

    response = await client.post(PURGE, json=_body(), headers=key_headers)

    assert response.json() == {"deleted": 0}
    assert await _remaining_ids(session_factory) == {open_conversation.id}


async def test_purge_skips_conversation_whose_run_callback_is_still_owed(client, uow_factory, session_factory, key_headers):
    # Closed while its run was in flight: the close stopped the session, but Django's callback is
    # still due to count the run's tokens, and its receipt keeps the secret until it arrives.
    waiting_for_callback = _closed()
    await _store(uow_factory, waiting_for_callback)
    async with uow_factory() as uow:
        message = _message(waiting_for_callback)
        await uow.messages.add(message)
        await uow.receipts.add(CallbackReceipt(run_id=new_id(), conversation_id=waiting_for_callback.id, message_id=message.id, secret="s" * 32, created_at=OLD))
        await uow.commit()

    response = await client.post(PURGE, json=_body(), headers=key_headers)

    assert response.json() == {"deleted": 0}
    assert await _remaining_ids(session_factory) == {waiting_for_callback.id}


async def test_purge_falls_back_to_created_at(client, uow_factory, session_factory, key_headers):
    created_long_ago = _closed(last_message_at=None, created_at=OLD)
    created_recently = _closed(last_message_at=None, created_at=RECENT)
    await _store(uow_factory, created_long_ago, created_recently)

    response = await client.post(PURGE, json=_body(), headers=key_headers)

    assert response.json() == {"deleted": 1}
    assert await _remaining_ids(session_factory) == {created_recently.id}


async def test_purge_cutoff_is_exclusive(client, uow_factory, session_factory, key_headers):
    at_cutoff = _closed(last_message_at=CUTOFF)
    await _store(uow_factory, at_cutoff)

    response = await client.post(PURGE, json=_body(), headers=key_headers)

    assert response.json() == {"deleted": 0}
    assert await _remaining_ids(session_factory) == {at_cutoff.id}


async def test_purge_cascades_to_messages_events_tokens_and_receipts(client, uow_factory, session_factory, key_headers):
    old, kept = _closed(), _closed(last_message_at=RECENT)
    await _store(uow_factory, old, kept)
    async with uow_factory() as uow:
        for conversation in (old, kept):
            message = _message(conversation)
            await uow.messages.add(message)
            await uow.events.add(ConversationEvent(id=new_id(), stream=Stream.CONVERSATION, conversation_id=conversation.id, org_id=1, type="message.created", payload={}, created_at=OLD))
            await uow.visitor_tokens.add(VisitorToken(new_id().hex * 2, conversation.id, OLD, OLD))
            # Applied: the secret is gone, so no callback is owed.
            await uow.receipts.add(CallbackReceipt(run_id=new_id(), conversation_id=conversation.id, message_id=message.id, secret="", created_at=OLD, received_at=OLD))
        await uow.commit()

    response = await client.post(PURGE, json=_body(), headers=key_headers)

    assert response.json() == {"deleted": 1}
    for row in (MessageRow, ConversationEventRow, VisitorTokenRow, CallbackReceiptRow):
        assert await _count(session_factory, row, old.id) == 0, row.__tablename__
        assert await _count(session_factory, row, kept.id) == 1, row.__tablename__


@pytest.mark.parametrize(
    "headers",
    [
        pytest.param({}, id="missing"),
        pytest.param({KEY_HEADER: "wrong-key"}, id="wrong"),
        pytest.param({KEY_HEADER: ""}, id="empty"),
        # Not ASCII: compare_digest raises on such a str instead of answering False.
        pytest.param({KEY_HEADER: "ключ".encode()}, id="not-ascii"),
    ],
)
async def test_purge_rejects_missing_or_wrong_key(client, uow_factory, session_factory, headers):
    old = _closed()
    await _store(uow_factory, old)

    response = await client.post(PURGE, json=_body(), headers=headers)

    assert response.status_code == 401
    assert response.json()["code"] == "invalid_internal_key"
    assert await _remaining_ids(session_factory) == {old.id}


async def test_purge_rejects_a_wrong_key_before_reading_the_body(client):
    response = await client.post(PURGE, json={"nonsense": True}, headers={KEY_HEADER: "wrong-key"})

    assert response.status_code == 401


@pytest.mark.parametrize(
    "body",
    [
        pytest.param(_body(older_than="2026-01-01T00:00:00"), id="naive-datetime"),
        pytest.param(_body(older_than="yesterday"), id="not-a-datetime"),
        pytest.param(_body(older_than=None), id="null-datetime"),
        pytest.param({"org_id": 1}, id="no-datetime"),
        pytest.param({"older_than": CUTOFF.isoformat()}, id="no-org"),
        pytest.param(_body(org_id="one"), id="org-not-a-number"),
        pytest.param(_body(org_id=True), id="org-a-boolean"),
        pytest.param(_body(org_id="1"), id="org-a-string"),
        pytest.param(_body(org_id=0), id="org-zero"),
        pytest.param(_body(org_id=2**31), id="org-above-the-integer-column"),
        pytest.param([], id="not-an-object"),
    ],
)
async def test_purge_rejects_an_invalid_body(client, uow_factory, session_factory, key_headers, body):
    old = _closed()
    await _store(uow_factory, old)

    response = await client.post(PURGE, json=body, headers=key_headers)

    assert response.status_code == 400
    assert response.json()["code"] == "validation_error"
    assert await _remaining_ids(session_factory) == {old.id}


async def test_purge_rejects_a_cutoff_in_the_future(client, uow_factory, session_factory, key_headers):
    just_closed = _closed(last_message_at=datetime.now(UTC), created_at=datetime.now(UTC))
    await _store(uow_factory, just_closed)
    soon = (datetime.now(UTC) + timedelta(minutes=5)).isoformat()

    response = await client.post(PURGE, json=_body(older_than=soon), headers=key_headers)

    assert response.status_code == 400
    assert response.json()["code"] == "validation_error"
    assert await _remaining_ids(session_factory) == {just_closed.id}


async def test_purge_accepts_the_largest_org_id(client, key_headers):
    response = await client.post(PURGE, json=_body(org_id=2**31 - 1), headers=key_headers)

    assert response.status_code == 200
    assert response.json() == {"deleted": 0}


async def test_purge_accepts_a_non_utc_offset(client, uow_factory, session_factory, key_headers):
    # 02:00 at +03:00 is 23:00 UTC the day before: the conversation from 23:30 UTC is newer.
    newer = _closed(last_message_at=datetime.fromisoformat("2025-12-31T23:30:00+00:00"))
    await _store(uow_factory, newer)

    response = await client.post(PURGE, json=_body(older_than="2026-01-01T02:00:00+03:00"), headers=key_headers)

    assert response.json() == {"deleted": 0}


async def test_purge_with_nothing_to_delete_returns_zero(client, key_headers):
    response = await client.post(PURGE, json=_body(), headers=key_headers)

    assert response.status_code == 200
    assert response.json() == {"deleted": 0}


async def test_purge_deletes_every_batch(uow_factory, session_factory):
    old = [_closed() for _ in range(5)]
    recent = _closed(last_message_at=RECENT)
    await _store(uow_factory, *old, recent)

    deleted = await RetentionOrchestrator(uow_factory, batch_size=2).purge_conversations(1, CUTOFF)

    assert deleted == 5
    assert await _remaining_ids(session_factory) == {recent.id}


async def test_purge_keeps_the_batches_committed_before_one_failed(uow_factory, session_factory):
    await _store(uow_factory, *(_closed() for _ in range(5)))
    units_opened = itertools.count(1)

    async def lost_connection():
        raise ConnectionError("chatdb went away")

    def second_batch_fails():
        uow = SQLAlchemyUnitOfWork(session_factory)
        if next(units_opened) == 2:
            uow.commit = lost_connection
        return uow

    with pytest.raises(ConnectionError):
        await RetentionOrchestrator(second_batch_fails, batch_size=2).purge_conversations(1, CUTOFF)

    assert len(await _remaining_ids(session_factory)) == 3


async def test_delete_inactive_batch_skips_a_conversation_another_transaction_holds(uow_factory, session_factory):
    # Another transaction holds the row lock (here, any FOR UPDATE read): the purge neither
    # waits for it nor deletes the row under it; the next purge takes it.
    held, free = _closed(), _closed()
    await _store(uow_factory, held, free)

    async with uow_factory() as other:
        await other.conversations.get(held.id, for_update=True)
        async with uow_factory() as purge:
            deleted = await asyncio.wait_for(purge.conversations.delete_inactive_batch(1, CUTOFF, 500), timeout=10)
            await purge.commit()
        await other.commit()

    assert deleted == 1
    assert await _remaining_ids(session_factory) == {held.id}


async def test_delete_inactive_batch_takes_the_oldest_first(uow_factory, session_factory):
    newer, oldest, older = _closed(last_message_at=OLD), _closed(last_message_at=OLD - timedelta(days=30)), _closed(last_message_at=None, created_at=OLD - timedelta(days=2))
    await _store(uow_factory, newer, oldest, older)

    async with uow_factory() as purge:
        deleted = await purge.conversations.delete_inactive_batch(1, CUTOFF, 2)
        await purge.commit()

    assert deleted == 2
    assert await _remaining_ids(session_factory) == {newer.id}
