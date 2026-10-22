import asyncio
import json
import re
from datetime import UTC, datetime, timedelta
from typing import NamedTuple

import pytest
from common.utils import new_id, utc_today, utcnow
from domain.enums import BindingStyle, CloseReason, InboxOrder, InboxSection, Mode, OnResponseTimeout, Role, RunState, Stream
from domain.errors import AliasTakenError
from domain.models import Binding, CallbackReceipt, Conversation, ConversationEvent, Message, VisitorToken
from domain.public_name import public_name_key
from domain.search import InboxSearch
from infrastructure.database.mappers import values_of
from infrastructure.database.models import BindingRow, ConversationRow, OperatorProfileRow
from infrastructure.database.unit_of_work import SQLAlchemyUnitOfWork
from sqlalchemy import event, insert, text
from sqlalchemy.exc import IntegrityError
from tests.factories import make_binding, make_closed, make_conversation


async def test_binding_round_trip(uow_factory):
    binding = make_binding(org_id=1, graph_id=5, name="Support")
    async with uow_factory() as uow:
        await uow.bindings.add(binding)
        await uow.commit()
    async with uow_factory() as uow:
        stored = await uow.bindings.get(binding.id, org_id=1)
        other_org = await uow.bindings.get(binding.id, org_id=2)
        by_key = await uow.bindings.get_by_public_key(binding.public_key)
    assert stored == binding
    assert other_org is None
    assert by_key.id == binding.id


async def test_a_subject_has_one_open_conversation_per_binding_and_any_number_of_closed_ones(uow_factory):
    binding, other = make_binding(org_id=1), make_binding(org_id=1)
    first_closed, second_closed = make_closed(binding, subject="user-7"), make_closed(binding, subject="user-7")
    open_one = make_conversation(binding, subject="user-7")
    async with uow_factory() as uow:
        for desk in (binding, other):
            await uow.bindings.add(desk)
        for conversation in (first_closed, second_closed, open_one, make_conversation(other, subject="user-7")):
            await uow.conversations.add(conversation)
        await uow.commit()
    async with uow_factory() as uow:
        assert (await uow.conversations.get_open_by_subject(binding.id, "user-7")).id == open_one.id
        assert await uow.conversations.get_open_by_subject(binding.id, "user-8") is None
        with pytest.raises(IntegrityError, match="uq_conversation_binding_subject_open"):
            await uow.conversations.add(make_conversation(binding, subject="user-7"))  # add() flushes


async def test_the_open_lookup_by_subject_ignores_closed_conversations(uow_factory):
    binding = make_binding(org_id=1)
    async with uow_factory() as uow:
        await uow.bindings.add(binding)
        await uow.conversations.add(make_closed(binding, subject="user-7"))
        await uow.commit()
    async with uow_factory() as uow:
        assert await uow.conversations.get_open_by_subject(binding.id, "user-7") is None


async def test_claim_run_slot_is_exclusive(uow_factory):
    binding = make_binding(org_id=1)
    conversation = make_conversation(binding)
    async with uow_factory() as uow:
        await uow.bindings.add(binding)
        await uow.conversations.add(conversation)
        await uow.commit()

    async def claim():
        async with uow_factory() as uow:
            claimed = await uow.conversations.claim_run_slot(conversation.id)
            await uow.commit()
            return claimed

    results = await asyncio.gather(claim(), claim())
    assert sorted(results) == [False, True]
    async with uow_factory() as uow:
        stored = await uow.conversations.get(conversation.id)
    assert stored.run_state == RunState.STARTING
    assert stored.active_since is not None


async def test_a_closed_conversation_never_takes_the_run_slot(uow_factory):
    binding = make_binding(org_id=1)
    closed = make_closed(binding)
    async with uow_factory() as uow:
        await uow.bindings.add(binding)
        await uow.conversations.add(closed)
        await uow.commit()
    async with uow_factory() as uow:
        assert await uow.conversations.claim_run_slot(closed.id) is False
        await uow.commit()
    async with uow_factory() as uow:
        assert (await uow.conversations.get(closed.id)).run_state == RunState.IDLE


async def test_skip_locked_answers_none_at_once_while_another_transaction_holds_the_row(uow_factory):
    binding = make_binding(org_id=1)
    conversation = make_conversation(binding)
    async with uow_factory() as uow:
        await uow.bindings.add(binding)
        await uow.conversations.add(conversation)
        await uow.commit()
    async with uow_factory() as holder:
        await holder.conversations.get(conversation.id, for_update=True)
        async with uow_factory() as skipper:
            skipped = await asyncio.wait_for(skipper.conversations.get(conversation.id, for_update=True, skip_locked=True), timeout=2)
        assert skipped is None
    async with uow_factory() as uow:  # released: the same read now locks and returns it
        assert (await uow.conversations.get(conversation.id, for_update=True, skip_locked=True)).id == conversation.id


async def test_get_for_update_waits_for_the_holder_to_commit(uow_factory):
    binding = make_binding(org_id=1)
    conversation = make_conversation(binding)
    async with uow_factory() as uow:
        await uow.bindings.add(binding)
        await uow.conversations.add(conversation)
        await uow.commit()

    async with uow_factory() as holder:
        locked = await holder.conversations.get(conversation.id, for_update=True)
        async with uow_factory() as waiter:
            second = asyncio.ensure_future(waiter.conversations.get(conversation.id, for_update=True))
            done, _ = await asyncio.wait({second}, timeout=0.3)
            assert not done, "the second locking read did not wait for the first transaction"
            locked.turns = 7
            await holder.conversations.update(locked)
            await holder.commit()
            assert (await asyncio.wait_for(second, timeout=5)).turns == 7


async def test_set_broken_reason_writes_only_that_column(uow_factory):
    binding = make_binding(org_id=1)
    async with uow_factory() as uow:
        await uow.bindings.add(binding)
        await uow.commit()
    async with uow_factory() as uow:
        await uow.bindings.set_broken_reason(binding.id, "gone")
        await uow.commit()
    async with uow_factory() as uow:
        stored = await uow.bindings.get(binding.id)
    assert stored.broken_reason == "gone" and stored.name == binding.name and stored.updated_at >= binding.updated_at


async def test_messages_page_and_history(uow_factory):
    binding = make_binding(org_id=1)
    conversation = make_conversation(binding)
    async with uow_factory() as uow:
        await uow.bindings.add(binding)
        await uow.conversations.add(conversation)
        for index in range(5):
            role = Role.USER if index % 2 == 0 else Role.ASSISTANT
            await uow.messages.add(Message(id=new_id(), conversation_id=conversation.id, role=role, content=f"m{index}", actions=None, session_id=None, created_at=utcnow(), author_user_id=None))
        await uow.messages.add(Message(id=new_id(), conversation_id=conversation.id, role=Role.SYSTEM, content="sys", actions=None, session_id=None, created_at=utcnow(), author_user_id=None))
        await uow.commit()
    async with uow_factory() as uow:
        newest = await uow.messages.page(conversation.id, before=None, limit=3)
        older = await uow.messages.page(conversation.id, before=newest[0].id, limit=10)
        history = await uow.messages.history(conversation.id, window=3)
    assert [m.content for m in newest] == ["m3", "m4", "sys"]
    assert [m.content for m in older] == ["m0", "m1", "m2"]
    assert history == [{"role": "user", "content": "m2"}, {"role": "assistant", "content": "m3"}, {"role": "user", "content": "m4"}]


async def test_events_seq_replay_and_retention(uow_factory):
    binding = make_binding(org_id=1)
    conversation = make_conversation(binding)
    other = make_conversation(binding)
    async with uow_factory() as uow:
        await uow.bindings.add(binding)
        await uow.conversations.add(conversation)
        await uow.conversations.add(other)
        seqs = []
        for index in range(3):
            event = ConversationEvent(id=new_id(), stream=Stream.CONVERSATION, conversation_id=conversation.id, org_id=1, type="message.created", payload={"n": index}, created_at=utcnow())
            seqs.append(await uow.events.add(event))
        inbox = ConversationEvent(id=new_id(), stream=Stream.INBOX, conversation_id=conversation.id, org_id=1, type="conversation.updated", payload={}, created_at=utcnow() - timedelta(days=8))
        old_seq = await uow.events.add(inbox)
        other_seq = await uow.events.add(ConversationEvent(id=new_id(), stream=Stream.CONVERSATION, conversation_id=other.id, org_id=1, type="message.created", payload={}, created_at=utcnow()))
        await uow.commit()
    assert seqs == sorted(seqs) and old_seq > seqs[-1]
    async with uow_factory() as uow:
        replay = await uow.events.replay(Stream.CONVERSATION, conversation_id=conversation.id, after_seq=seqs[0])
        inbox_replay = await uow.events.replay(Stream.INBOX, org_id=1, after_seq=None)
        assert [e.payload["n"] for e in replay] == [1, 2]
        assert [e.seq for e in inbox_replay] == [old_seq]
        deleted = await uow.events.delete_older_than(utcnow() - timedelta(days=7))
        await uow.commit()
        assert deleted == 1
        assert await uow.events.min_seq(Stream.CONVERSATION, conversation_id=conversation.id) == seqs[0]
        # The other conversation's later row does not move this conversation's head.
        assert await uow.events.max_seq(Stream.CONVERSATION, conversation_id=conversation.id) == seqs[-1] < other_seq
        assert await uow.events.max_seq(Stream.CONVERSATION, conversation_id=other.id) == other_seq
        assert await uow.events.max_seq(Stream.INBOX, org_id=1) == 0  # the only inbox row was deleted
        assert await uow.events.min_seq(Stream.INBOX, org_id=2) == 0


async def test_daily_usage_upserts(uow_factory):
    binding = make_binding(org_id=1)
    async with uow_factory() as uow:
        await uow.bindings.add(binding)
        await uow.usage.add_daily(binding.id, utc_today(), 40)
        await uow.usage.add_daily(binding.id, utc_today(), 2)
        await uow.commit()
    async with uow_factory() as uow:
        assert await uow.usage.daily_tokens(binding.id, utc_today()) == 42
        assert await uow.usage.daily_tokens(binding.id, utc_today() - timedelta(days=1)) == 0


def _receipt(conversation, *, created_at=None, **overrides) -> CallbackReceipt:
    return CallbackReceipt(**{
        "run_id": new_id(), "conversation_id": conversation.id, "message_id": new_id(),
        "secret": "s" * 43, "created_at": created_at or utcnow(), **overrides,
    })


async def test_receipt_marks_received_once(uow_factory):
    binding = make_binding(org_id=1)
    conversation = make_conversation(binding)
    receipt = _receipt(conversation)
    async with uow_factory() as uow:
        await uow.bindings.add(binding)
        await uow.conversations.add(conversation)
        await uow.receipts.add(receipt)
        await uow.commit()
    async with uow_factory() as uow:
        assert (await uow.receipts.get(receipt.run_id)).secret == "s" * 43
        assert await uow.receipts.mark_received(receipt.run_id) is True
        assert await uow.receipts.mark_received(receipt.run_id) is False
        assert await uow.receipts.mark_received(new_id()) is False
        await uow.commit()
    async with uow_factory() as uow:
        assert (await uow.receipts.get(receipt.run_id)).secret == ""


async def test_receipt_binds_one_session_only(uow_factory):
    binding = make_binding(org_id=1)
    conversation = make_conversation(binding)
    receipt = _receipt(conversation)
    async with uow_factory() as uow:
        await uow.bindings.add(binding)
        await uow.conversations.add(conversation)
        await uow.receipts.add(receipt)
        await uow.commit()
    async with uow_factory() as uow:
        assert await uow.receipts.bind_session(receipt.run_id, 17) is True
        assert await uow.receipts.bind_session(receipt.run_id, 17) is True  # the same id again is fine
        assert await uow.receipts.bind_session(receipt.run_id, 18) is False
        assert await uow.receipts.bind_session(new_id(), 17) is False
        await uow.commit()
    async with uow_factory() as uow:
        assert (await uow.receipts.get(receipt.run_id)).session_id == 17


async def test_receipt_snapshot_keeps_the_secret_and_final_usage_tops_up(uow_factory):
    binding = make_binding(org_id=1)
    conversation = make_conversation(binding)
    receipt, unreceived = _receipt(conversation), _receipt(conversation)
    async with uow_factory() as uow:
        await uow.bindings.add(binding)
        await uow.conversations.add(conversation)
        await uow.receipts.add(receipt)
        await uow.receipts.add(unreceived)
        await uow.commit()
    async with uow_factory() as uow:
        assert await uow.receipts.mark_received(receipt.run_id, 5, keep_secret=True) is True
        assert await uow.receipts.raise_tokens_counted(unreceived.run_id, 9) == 0  # not received yet: nothing to top up
        await uow.commit()
    async with uow_factory() as uow:
        stored = await uow.receipts.get(receipt.run_id)
        assert (stored.tokens_counted, stored.secret) == (5, "s" * 43)
        assert await uow.receipts.raise_tokens_counted(receipt.run_id, 12) == 7
        assert await uow.receipts.raise_tokens_counted(receipt.run_id, 10) == 0  # never lowers
        await uow.commit()
    async with uow_factory() as uow:
        stored = await uow.receipts.get(receipt.run_id)
        assert (stored.tokens_counted, stored.secret) == (12, "")


async def test_stale_runs_and_list_order(uow_factory):
    binding = make_binding(org_id=1)
    idle = make_conversation(binding, last_message_at=utcnow())
    waiting = make_conversation(binding, mode="awaiting_human", last_message_at=utcnow() - timedelta(hours=1))
    silent = make_conversation(binding)
    stale = make_conversation(binding, last_message_at=utcnow() - timedelta(minutes=30))
    stale_receipt = _receipt(stale, session_id=9)
    stale.run_state, stale.active_run_id, stale.active_since = RunState.RUNNING, stale_receipt.run_id, utcnow() - timedelta(minutes=10)
    starting = make_conversation(binding, run_state=RunState.STARTING, active_since=utcnow() - timedelta(minutes=10))
    async with uow_factory() as uow:
        await uow.bindings.add(binding)
        for conversation in (idle, waiting, silent, stale, starting):
            await uow.conversations.add(conversation)
        await uow.receipts.add(stale_receipt)
        await uow.commit()
    async with uow_factory() as uow:
        stale_rows = await uow.conversations.stale_runs(older_than=utcnow() - timedelta(minutes=5))
        unconfirmed = await uow.conversations.unconfirmed_starts(older_than=utcnow() - timedelta(minutes=5))
        fresh_unconfirmed = await uow.conversations.unconfirmed_starts(older_than=utcnow() - timedelta(minutes=15))
        human = await uow.conversations.list(org_id=1, binding_id=None, section=InboxSection.HUMAN, limit=10, after=None)
        bot = await uow.conversations.list(org_id=1, binding_id=None, section=InboxSection.BOT, limit=10, after=None)
        after_idle = await uow.conversations.list(
            org_id=1, binding_id=None, section=InboxSection.BOT, limit=10, after=(idle.last_message_at, idle.id)
        )
        foreign = await uow.conversations.list(org_id=2, binding_id=None, section=InboxSection.BOT, limit=10, after=None)
    assert [(c.id, session_id) for c, session_id in stale_rows] == [(stale.id, 9)]
    assert [c.id for c in unconfirmed] == [starting.id] and fresh_unconfirmed == []
    assert [c.id for c in human] == [waiting.id]
    assert [c.id for c in bot] == [idle.id, stale.id]
    assert [c.id for c in after_idle] == [stale.id]
    assert foreign == []


async def test_a_handed_off_mode_without_handoff_at_is_refused(uow_factory):
    binding = make_binding(org_id=1)
    async with uow_factory() as uow:
        await uow.bindings.add(binding)
        await uow.commit()
    for broken in (make_conversation(binding, mode="human", handoff_at=None), make_conversation(binding, handoff_at=utcnow())):
        async with uow_factory() as uow:
            with pytest.raises(IntegrityError, match="ck_conversation_handoff_at_matches_mode"):
                await uow.conversations.add(broken)  # add() flushes


async def test_a_create_holding_the_share_lock_finishes_before_a_rotation_revokes(uow_factory):
    binding = make_binding(org_id=1)
    conversation = make_conversation(binding)
    async with uow_factory() as uow:
        await uow.bindings.add(binding)
        await uow.conversations.add(conversation)
        await uow.commit()

    async def rotate():
        async with uow_factory() as rotator:
            locked = await rotator.bindings.get(binding.id, for_update=True)
            locked.public_key = "rotated-key"
            await rotator.bindings.update(locked)
            revoked = await rotator.visitor_tokens.delete_for_binding(binding.id)
            await rotator.commit()
            return revoked

    async with uow_factory() as creator:
        assert await creator.bindings.get_by_public_key(binding.public_key, for_share=True) is not None
        rotation = asyncio.ensure_future(rotate())
        done, _ = await asyncio.wait({rotation}, timeout=0.3)
        assert not done, "the rotation did not wait for the in-flight create"
        await creator.visitor_tokens.add(VisitorToken("h" * 64, conversation.id, utcnow(), utcnow()))
        await creator.commit()
    assert await asyncio.wait_for(rotation, timeout=5) == 1
    async with uow_factory() as uow:
        assert await uow.visitor_tokens.get("h" * 64) is None


async def test_a_create_behind_a_rotation_misses_the_old_key(uow_factory):
    binding = make_binding(org_id=1)
    async with uow_factory() as uow:
        await uow.bindings.add(binding)
        await uow.commit()
    async with uow_factory() as rotator:
        locked = await rotator.bindings.get(binding.id, for_update=True)
        async with uow_factory() as creator:
            lookup = asyncio.ensure_future(creator.bindings.get_by_public_key(binding.public_key, for_share=True))
            done, _ = await asyncio.wait({lookup}, timeout=0.3)
            assert not done, "the create did not wait for the rotation"
            locked.public_key = "rotated-key"
            await rotator.bindings.update(locked)
            await rotator.commit()
            # Read committed: the waiting lock re-checks the new row version, whose key no longer matches.
            assert await asyncio.wait_for(lookup, timeout=5) is None



async def test_an_active_binding_with_contract_errors_is_refused(uow_factory):
    async with uow_factory() as uow:
        with pytest.raises(IntegrityError, match="ck_binding_active_contract_clean"):
            await uow.bindings.add(make_binding(org_id=1, is_active=True, contract_errors=["The flow has no end node."]))  # add() flushes
    paused = make_binding(org_id=1, is_active=False, contract_errors=["The flow has no end node."])
    async with uow_factory() as uow:
        await uow.bindings.add(paused)
        await uow.commit()
    paused.is_active = True
    async with uow_factory() as uow:
        with pytest.raises(IntegrityError, match="ck_binding_active_contract_clean"):
            await uow.bindings.update(paused)


async def test_an_active_binding_may_carry_a_broken_reason(uow_factory):
    binding = make_binding(org_id=1, is_active=True, broken_reason="Django answered 404 for the flow.")
    async with uow_factory() as uow:
        await uow.bindings.add(binding)
        await uow.commit()
    async with uow_factory() as uow:
        stored = await uow.bindings.get(binding.id)
    assert (stored.is_active, stored.broken_reason) == (True, "Django answered 404 for the flow.")


def _message(conversation, role, content, action=None) -> Message:
    # An operator message always carries the name visitors see; the database refuses one without.
    visible_name = "Support" if role == Role.OPERATOR else None
    return Message(id=new_id(), conversation_id=conversation.id, role=role, content=content, actions=None, session_id=None, created_at=utcnow(), author_user_id=None, action=action, visible_name=visible_name)


async def _stored_conversation(uow_factory):
    binding = make_binding(org_id=1)
    conversation = make_conversation(binding)
    async with uow_factory() as uow:
        await uow.bindings.add(binding)
        await uow.conversations.add(conversation)
        await uow.commit()
    return conversation


@pytest.mark.parametrize("role", [Role.ASSISTANT, Role.OPERATOR, Role.SYSTEM])
async def test_an_action_on_a_non_user_message_is_refused(uow_factory, role):
    conversation = await _stored_conversation(uow_factory)
    async with uow_factory() as uow:
        with pytest.raises(IntegrityError, match="ck_message_action_user_only"):
            await uow.messages.add(_message(conversation, role, "x", action={"id": "a"}))  # add() flushes


async def test_history_includes_the_action_only_when_the_message_has_one(uow_factory):
    conversation = await _stored_conversation(uow_factory)
    async with uow_factory() as uow:
        await uow.messages.add(_message(conversation, Role.USER, "", action={"type": "button", "id": "yes"}))
        await uow.messages.add(_message(conversation, Role.ASSISTANT, "ok"))
        await uow.messages.add(_message(conversation, Role.USER, "plain"))
        await uow.commit()
    async with uow_factory() as uow:
        history = await uow.messages.history(conversation.id, window=10)
        (first, *_) = await uow.messages.page(conversation.id, before=None, limit=10)
    assert history == [
        {"role": "user", "content": "", "action": {"type": "button", "id": "yes"}},
        {"role": "assistant", "content": "ok"},
        {"role": "user", "content": "plain"},
    ]
    assert first.action == {"type": "button", "id": "yes"}


async def test_conversation_extra_data_and_is_signed_round_trip(uow_factory):
    binding = make_binding(org_id=1)
    conversation = make_conversation(binding, subject="customer-1", is_signed=True, chat_extra_data={"plan": "pro"})
    async with uow_factory() as uow:
        await uow.bindings.add(binding)
        await uow.conversations.add(conversation)
        await uow.commit()
    async with uow_factory() as uow:
        stored = await uow.conversations.get(conversation.id)
    assert (stored.is_signed, stored.chat_extra_data, stored.chat_user_id) == (True, {"plan": "pro"}, "customer-1")


# ---- the test inbox section ---------------------------------------------------------------------

async def test_test_conversations_list_only_in_the_test_section(uow_factory):
    binding = make_binding(org_id=1)
    real_bot = make_conversation(binding, last_message_at=utcnow())
    real_waiting = make_conversation(binding, mode="awaiting_human", last_message_at=utcnow())
    tests = [make_conversation(binding, mode=mode, is_test=True, last_message_at=utcnow() - timedelta(minutes=index)) for index, mode in enumerate(("bot", "awaiting_human", "human"))]
    silent_test = make_conversation(binding, is_test=True)
    async with uow_factory() as uow:
        await uow.bindings.add(binding)
        for conversation in (real_bot, real_waiting, *tests, silent_test):
            await uow.conversations.add(conversation)
        await uow.commit()

    async def listed(section, org_id=1, mode=None):
        async with uow_factory() as uow:
            return [c.id for c in await uow.conversations.list(org_id=org_id, binding_id=None, section=section, limit=10, after=None, mode=mode)]

    assert await listed(InboxSection.TEST) == [c.id for c in tests]
    assert await listed(InboxSection.HUMAN) == [real_waiting.id]
    assert await listed(InboxSection.HUMAN, mode=Mode.AWAITING_HUMAN) == [real_waiting.id]
    assert await listed(InboxSection.BOT) == [real_bot.id]
    assert await listed(InboxSection.TEST, org_id=2) == []


def _plan_nodes(node: dict):
    yield node
    for child in node.get("Plans", []):
        yield from _plan_nodes(child)


def _literal(value) -> str:
    """A SQL literal for EXECUTE, whose text goes through the driver: `%` is doubled for it."""
    if isinstance(value, int):
        return str(value)
    quoted = (value.isoformat() if hasattr(value, "isoformat") else str(value)).replace("'", "''")
    return ("'" + quoted + "'").replace("%", "%%")


# Many desks and operators, rows interleaved as conversations arrive: a desk filter and Mine are
# each selective, as in a busy org, so the plan reads the scoped index rather than the org one.
INBOX_BINDINGS = 40
INBOX_ROWS_PER_BINDING = 50
INBOX_OPERATORS = 40
HOLDER = 3


def _inbox_row(binding, desk, index):
    """Every state the inbox lists, each a small share of the rows: bot, waiting (nobody holds it),
    in progress, held with the visitor waiting again, and closed (a sixth, a holder kept on some);
    a fifth are tests, some visitors signed."""
    at = utcnow() - timedelta(seconds=index)
    is_test = index % 5 == 0
    common = dict(last_message_at=at, is_test=is_test, is_signed=not is_test and index % 3 == 0, subject=f"customer-{index}")
    state = index % 4
    holder = 1 + (desk + index // 4) % INBOX_OPERATORS
    if index % 6 == 5:
        held = state >= 2
        return make_closed(binding, mode="human" if held else "bot", assigned_operator_id=holder if held else None, closed_at=at, **common)
    if state == 0:
        return make_conversation(binding, **common)
    if state == 1:
        return make_conversation(binding, mode="awaiting_human", **common)
    return make_conversation(binding, mode="human", assigned_operator_id=holder, visitor_waiting_since=at if state == 3 else None, **common)


async def _seed_inbox(session_factory):
    """The rows in one statement, the operator names, then fresh statistics: TRUNCATE keeps
    pg_statistic, so without ANALYZE the plan would follow whatever an earlier test left."""
    bindings = [make_binding(org_id=1) for _ in range(INBOX_BINDINGS)]
    async with session_factory() as session:
        await session.execute(insert(BindingRow), [values_of(binding) for binding in bindings])
        # Desks interleaved, as conversations arrive: a desk's rows stored together would make a
        # scan of the plain binding_id index look cheaper than any real desk's.
        rows = [_inbox_row(binding, desk, index) for index in range(INBOX_ROWS_PER_BINDING) for desk, binding in enumerate(bindings)]
        await session.execute(insert(ConversationRow), [values_of(row) for row in rows])
        await session.execute(insert(OperatorProfileRow), [{"org_id": 1, "user_id": user_id, "display_name": f"Agent {user_id:02d}", "updated_at": utcnow()} for user_id in range(1, INBOX_OPERATORS + 1)])
        await session.commit()
    engine = session_factory.kw["bind"]
    async with engine.connect() as connection:
        await connection.exec_driver_sql("ANALYZE conversation")
        await connection.exec_driver_sql("ANALYZE operator_profile")
        await connection.commit()
    return bindings


async def _generic_plan(session_factory, uow_factory, settings, **list_arguments) -> dict | None:
    """The plan of the list query as the driver sends it, planned generically (as a cached
    prepared statement is), under `settings`; None when the list answers without a query."""
    return await _generic_plan_of(session_factory, uow_factory, settings, lambda conversations: conversations.list(org_id=1, limit=51, **list_arguments))


async def _generic_plan_of(session_factory, uow_factory, settings, call, plan_cache_mode="force_generic_plan") -> dict | None:
    """The plan of the conversation query `call(uow.conversations)` sends, planned generically
    (as a cached prepared statement is) or, with `force_custom_plan`, for its actual values."""
    engine = session_factory.kw["bind"]
    captured = []

    def capture(connection, cursor, statement, parameters, context, executemany):
        if "FROM conversation" in statement and "LIMIT" in statement:
            captured.append((statement, parameters))

    event.listen(engine.sync_engine, "before_cursor_execute", capture)
    try:
        async with uow_factory() as uow:
            await call(uow.conversations)
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", capture)
    if not captured:
        return None
    (statement, parameters), = captured

    # Number the driver's named placeholders for PREPARE; EXECUTE then binds the same values.
    names: list[str] = []

    def number(match):
        if match.group(1) not in names:
            names.append(match.group(1))
        return f"${names.index(match.group(1)) + 1}"

    prepared = re.sub(r"%\((\w+)\)s", number, statement)
    async with engine.connect() as connection:
        async with connection.begin():
            for setting in (f"plan_cache_mode = {plan_cache_mode}", *settings):
                await connection.exec_driver_sql(f"SET LOCAL {setting}")
            await connection.exec_driver_sql(f"PREPARE inbox_list AS {prepared}")
            # EXPLAIN takes no bound parameters, so EXECUTE gets literals; the plan stays the generic one.
            arguments = ", ".join(_literal(parameters[name]) for name in names)
            result = await connection.exec_driver_sql(f"EXPLAIN (FORMAT JSON) EXECUTE inbox_list({arguments})")
            plan = result.scalar_one()[0]["Plan"]
            await connection.exec_driver_sql("DEALLOCATE inbox_list")
    return plan


def _assert_mine_reads_stay_in_the_org(nodes, shown):
    """A Mine index read starts at the caller's org: org_id leads its condition, so an operator's
    rows in other orgs are never read, and never show in this org's timings."""
    for node in nodes:
        if (node.get("Index Name") or "").startswith("ix_conversation_mine_"):
            assert (node.get("Index Cond") or "").startswith("((org_id = "), shown


class ListCase(NamedTuple):
    section: InboxSection
    # The index the plan must read; Mine on one desk may read either scoped index in order, the
    # desk's or the operator's, whichever has fewer rows to skip.
    indexes: tuple[str, ...]
    by_binding: bool = False
    mode: Mode | None = None
    mine: bool = False
    order: InboxOrder = InboxOrder.NEWEST
    backward: bool = False


LIST_CASES = {
    "human": ListCase(InboxSection.HUMAN, ("ix_conversation_org_id_human",)),
    "human+mode": ListCase(InboxSection.HUMAN, ("ix_conversation_org_id_human",), mode=Mode.AWAITING_HUMAN),
    "human+binding": ListCase(InboxSection.HUMAN, ("ix_conversation_binding_id_human",), by_binding=True),
    "human+binding+mode": ListCase(InboxSection.HUMAN, ("ix_conversation_binding_id_human",), by_binding=True, mode=Mode.AWAITING_HUMAN),
}
for _section in (InboxSection.WAITING, InboxSection.IN_PROGRESS, InboxSection.BOT, InboxSection.TEST, InboxSection.CLOSED):
    for _order in InboxOrder:
        # Waiting is a queue: oldest first whatever the order; Closed is most recently closed
        # first whatever the order. Either way always a forward scan.
        _backward = _order == InboxOrder.OLDEST and _section not in (InboxSection.WAITING, InboxSection.CLOSED)
        for _by_binding in (False, True):
            _scoped = f"ix_conversation_{'binding_id' if _by_binding else 'org_id'}_{_section}"
            _name = f"{_section}+{_order}" + ("+binding" if _by_binding else "")
            LIST_CASES[_name] = ListCase(_section, (_scoped,), _by_binding, order=_order, backward=_backward)
            if _section != InboxSection.BOT:
                _mine = f"ix_conversation_mine_{_section}"
                LIST_CASES[_name + "+mine"] = ListCase(_section, (_scoped, _mine) if _by_binding else (_mine,), _by_binding, mine=True, order=_order, backward=_backward)


@pytest.mark.parametrize("with_cursor", [False, True], ids=["first page", "with cursor"])
@pytest.mark.parametrize("case", LIST_CASES.values(), ids=LIST_CASES.keys())
async def test_each_inbox_section_reads_its_own_index_in_order_under_a_generic_plan(session_factory, uow_factory, case, with_cursor):
    """Each section, scope, direction and Mine must match its partial index and need no Sort.
    A predicate bound as a parameter (`is_test = $3`) would not imply the index's `NOT is_test`,
    and this would fail. Oldest first reads the same index backwards."""
    bindings = await _seed_inbox(session_factory)
    plan = await _generic_plan(
        session_factory, uow_factory, ("enable_seqscan = off", "enable_bitmapscan = off"),
        binding_id=bindings[0].id if case.by_binding else None, section=case.section,
        after=(utcnow(), new_id()) if with_cursor else None, mode=case.mode, order=case.order,
        holder_id=HOLDER if case.mine else None,
    )
    nodes = list(_plan_nodes(plan))
    shown = json.dumps(plan, indent=1)
    scans = [n for n in nodes if n["Node Type"] in ("Index Scan", "Index Only Scan")]
    assert len(scans) == 1 and scans[0].get("Index Name") in case.indexes, shown
    _assert_mine_reads_stay_in_the_org(nodes, shown)
    assert scans[0]["Scan Direction"] == ("Backward" if case.backward else "Forward"), shown
    assert not [n for n in nodes if n["Node Type"] in ("Sort", "Incremental Sort", "Seq Scan", "Bitmap Heap Scan")], shown


SEARCH_CASES = {
    f"{section}" + ("+binding" if by_binding else "") + ("+mine" if mine else ""): (section, by_binding, mine)
    for section in (InboxSection.WAITING, InboxSection.IN_PROGRESS, InboxSection.BOT, InboxSection.TEST, InboxSection.CLOSED)
    for by_binding in (False, True)
    for mine in ((False, True) if section != InboxSection.BOT else (False,))
}
SECTION_ORG_INDEXES = {f"ix_conversation_org_id_{section}" for section in InboxSection}


# Each names a few rows: visitor #12 on each desk (and "Agent 12"), one signed id, one operator.
@pytest.mark.parametrize("query", ["12", "Customer-12", "agent 03"], ids=["number", "signed id", "holder name"])
@pytest.mark.parametrize("case", SEARCH_CASES.values(), ids=SEARCH_CASES.keys())
async def test_a_search_finds_its_rows_through_indexes_not_by_reading_the_table(session_factory, uow_factory, case, query):
    """With `q` a small Sort is fine; reading every conversation row is not, nor a section's
    whole org-wide index filtered by the search. Each way of matching has an index, so the rows
    come from those. A generic plan read the whole section while the signed-id prefix was a LIKE
    parameter, or while the holders were a subquery the plan counted as ten operators."""
    section, by_binding, mine = case
    bindings = await _seed_inbox(session_factory)
    plan = await _generic_plan(
        session_factory, uow_factory, ("enable_seqscan = off",),
        binding_id=bindings[0].id if by_binding else None, section=section, after=None,
        holder_id=HOLDER if mine else None, search=InboxSearch.parse(query),
    )
    if plan is None:  # no way of matching fits the section: answered without a query
        assert section == InboxSection.TEST and query == "Customer-12"
        return
    nodes = list(_plan_nodes(plan))
    shown = json.dumps(plan, indent=1)
    assert not [n for n in nodes if n["Node Type"] == "Seq Scan" and n.get("Relation Name") == "conversation"], shown
    assert not SECTION_ORG_INDEXES & {n.get("Index Name") for n in nodes}, shown
    _assert_mine_reads_stay_in_the_org(nodes, shown)


# ---- visitor numbers ---------------------------------------------------------------------------

async def _next_numbers(uow_factory, binding, count):
    async with uow_factory() as uow:
        numbers = [await uow.visitor_numbers.next(binding.id) for _ in range(count)]
        await uow.commit()
    return numbers


async def test_visitor_numbers_count_from_one_per_binding(uow_factory):
    first, second = make_binding(org_id=1), make_binding(org_id=2)
    async with uow_factory() as uow:
        await uow.bindings.add(first)
        await uow.bindings.add(second)
        await uow.commit()
    assert await _next_numbers(uow_factory, first, 3) == [1, 2, 3]
    assert await _next_numbers(uow_factory, second, 2) == [1, 2]
    assert await _next_numbers(uow_factory, first, 1) == [4]


async def test_a_rolled_back_create_gives_its_number_back(uow_factory):
    binding = make_binding(org_id=1)
    async with uow_factory() as uow:
        await uow.bindings.add(binding)
        await uow.commit()
    async with uow_factory() as uow:
        assert await uow.visitor_numbers.next(binding.id) == 1  # leaving the block rolls back
    assert await _next_numbers(uow_factory, binding, 1) == [1]


async def test_concurrent_creates_take_consecutive_numbers_while_a_rotation_waits_without_deadlock(uow_factory):
    """Two creates hold the binding's share lock at once (as `create` does) and number in turn;
    a rotate-key queued behind them gets its update lock once both commit."""
    binding = make_binding(org_id=1)
    async with uow_factory() as uow:
        await uow.bindings.add(binding)
        await uow.commit()

    async def rotate():
        async with uow_factory() as rotator:
            locked = await rotator.bindings.get(binding.id, for_update=True)
            locked.public_key = "rotated-key"
            await rotator.bindings.update(locked)
            await rotator.commit()

    async with uow_factory() as first, uow_factory() as second:
        assert await first.bindings.get_by_public_key(binding.public_key, for_share=True) is not None
        assert await second.bindings.get_by_public_key(binding.public_key, for_share=True) is not None
        first_number = await first.visitor_numbers.next(binding.id)
        second_number = asyncio.ensure_future(second.visitor_numbers.next(binding.id))
        rotation = asyncio.ensure_future(rotate())
        done, _ = await asyncio.wait({second_number, rotation}, timeout=0.3)
        assert not done, "the second create did not wait for the first's number, or the rotation for the creates"
        await first.conversations.add(make_conversation(binding, visitor_number=first_number))
        await first.commit()
        assert await asyncio.wait_for(second_number, timeout=5) == first_number + 1
        done, _ = await asyncio.wait({rotation}, timeout=0.3)
        assert not done, "the rotation did not wait for the second create"
        await second.conversations.add(make_conversation(binding, visitor_number=second_number.result()))
        await second.commit()
    await asyncio.wait_for(rotation, timeout=5)
    assert first_number == 1
    async with uow_factory() as uow:
        assert (await uow.bindings.get(binding.id)).public_key == "rotated-key"


async def test_a_visitor_number_is_unique_per_binding_only(uow_factory):
    binding, other = make_binding(org_id=1), make_binding(org_id=1)
    async with uow_factory() as uow:
        await uow.bindings.add(binding)
        await uow.bindings.add(other)
        await uow.conversations.add(make_conversation(binding, visitor_number=1))
        await uow.conversations.add(make_conversation(other, visitor_number=1))
        await uow.commit()
    async with uow_factory() as uow:
        with pytest.raises(IntegrityError, match="uq_conversation_binding_visitor_number"):
            await uow.conversations.add(make_conversation(binding, visitor_number=1))  # add() flushes


# ---- who waits, who holds ----------------------------------------------------------------------

REFUSED_ROWS = {
    "bot and waiting": ("bot", {"visitor_waiting_since": utcnow()}, "ck_conversation_waiting_matches_mode"),
    "awaiting and not waiting": ("awaiting_human", {"visitor_waiting_since": None}, "ck_conversation_waiting_matches_mode"),
    "human without a holder": ("human", {"assigned_operator_id": None}, "ck_conversation_holder_matches_mode"),
    "awaiting with a holder": ("awaiting_human", {"assigned_operator_id": 2}, "ck_conversation_holder_matches_mode"),
    "bot with a holder": ("bot", {"assigned_operator_id": 2}, "ck_conversation_holder_matches_mode"),
    "closed without a time": ("bot", {"status": "closed", "close_reason": CloseReason.ENDED}, "ck_conversation_status_matches_closed_at"),
    "a close time while open": ("bot", {"closed_at": utcnow()}, "ck_conversation_status_matches_closed_at"),
    "closed without a reason": ("bot", {"status": "closed", "closed_at": utcnow()}, "ck_conversation_close_reason_matches_status"),
    "a reason while open": ("bot", {"close_reason": CloseReason.ENDED}, "ck_conversation_close_reason_matches_status"),
    "resolved by nobody": ("bot", {"status": "closed", "closed_at": utcnow(), "close_reason": CloseReason.RESOLVED}, "ck_conversation_closed_by_only_resolved"),
    "ended by an operator": ("bot", {"status": "closed", "closed_at": utcnow(), "close_reason": CloseReason.ENDED, "closed_by_user_id": 2}, "ck_conversation_closed_by_only_resolved"),
    "closed and waiting": ("human", {"status": "closed", "closed_at": utcnow(), "close_reason": CloseReason.INACTIVE, "visitor_waiting_since": utcnow()}, "ck_conversation_closed_is_settled"),
    "closed with a run": ("bot", {"status": "closed", "closed_at": utcnow(), "close_reason": CloseReason.INACTIVE, "run_state": RunState.RUNNING, "active_run_id": new_id(), "active_since": utcnow()}, "ck_conversation_closed_is_settled"),
    "closed with a late reply due": ("bot", {"status": "closed", "closed_at": utcnow(), "close_reason": CloseReason.INACTIVE, "late_reply_run_id": new_id()}, "ck_conversation_closed_is_settled"),
    # What a take over between a submit's two transactions used to leave behind.
    "idle naming a run": ("human", {"active_run_id": new_id()}, "ck_conversation_idle_holds_no_run"),
}


@pytest.mark.parametrize(("mode", "overrides", "constraint"), REFUSED_ROWS.values(), ids=REFUSED_ROWS.keys())
async def test_a_row_breaking_a_wait_holder_or_close_rule_is_refused(uow_factory, mode, overrides, constraint):
    binding = make_binding(org_id=1)
    async with uow_factory() as uow:
        await uow.bindings.add(binding)
        await uow.commit()
    async with uow_factory() as uow:
        with pytest.raises(IntegrityError, match=constraint):
            await uow.conversations.add(make_conversation(binding, mode=mode, **overrides))  # add() flushes


@pytest.mark.parametrize("mode", ["bot", "awaiting_human", "human"])
@pytest.mark.parametrize("reason", list(CloseReason))
async def test_a_closed_conversation_keeps_its_mode_and_holder_and_nobody_waits(uow_factory, mode, reason):
    binding = make_binding(org_id=1)
    closed = make_closed(binding, reason=reason, mode=mode, last_message_at=utcnow())
    async with uow_factory() as uow:
        await uow.bindings.add(binding)
        await uow.conversations.add(closed)
        await uow.commit()
    async with uow_factory() as uow:
        assert await uow.conversations.get(closed.id) == closed


@pytest.mark.parametrize("waiting_since", [None, utcnow()], ids=["answered", "waiting"])
async def test_a_held_conversation_may_wait_or_not(uow_factory, waiting_since):
    binding = make_binding(org_id=1)
    async with uow_factory() as uow:
        await uow.bindings.add(binding)
        await uow.conversations.add(make_conversation(binding, mode="human", assigned_operator_id=2, visitor_waiting_since=waiting_since))
        await uow.commit()


async def test_the_wait_and_the_last_message_round_trip_with_the_role_as_an_enum(uow_factory):
    binding = make_binding(org_id=1)
    conversation = make_conversation(binding, mode="human", assigned_operator_id=2, visitor_number=7, visitor_waiting_since=utcnow() - timedelta(minutes=5), last_message_at=utcnow(), last_message_role=Role.OPERATOR, last_message_author_user_id=2)
    async with uow_factory() as uow:
        await uow.bindings.add(binding)
        await uow.conversations.add(conversation)
        await uow.commit()
    async with uow_factory() as uow:
        stored = await uow.conversations.get(conversation.id)
    assert stored == conversation and stored.last_message_role is Role.OPERATOR


# ---- operator names ----------------------------------------------------------------------------

async def _profile(session_factory, user_id, org_id=1):
    async with session_factory() as session:
        return (await session.execute(text("SELECT display_name, updated_at, xmin::text FROM operator_profile WHERE org_id = :org_id AND user_id = :user_id"), {"org_id": org_id, "user_id": user_id})).one_or_none()


async def _remember(uow_factory, user_id, display_name, now, org_id=1):
    async with uow_factory() as uow:
        on_record = await uow.operator_profiles.remember(org_id, user_id, display_name, now)
        await uow.commit()
    return on_record


async def test_remember_writes_only_when_the_name_changed(uow_factory, session_factory):
    first, later = utcnow() - timedelta(hours=1), utcnow()
    assert await _remember(uow_factory, 7, "Ada", first) == "Ada"
    stored = await _profile(session_factory, 7)
    assert stored[:2] == ("Ada", first)
    # The same name, or none at all, leaves the row version untouched: no update, no lock.
    assert await _remember(uow_factory, 7, "Ada", later) == "Ada"
    assert await _remember(uow_factory, 7, None, later) == "Ada"
    assert await _profile(session_factory, 7) == stored
    assert await _remember(uow_factory, 7, "Ada Lovelace", later) == "Ada Lovelace"
    assert (await _profile(session_factory, 7))[:2] == ("Ada Lovelace", later)
    assert await _remember(uow_factory, 8, None, later) is None
    assert await _profile(session_factory, 8) is None


async def test_names_answers_the_remembered_ids_only(uow_factory):
    await _remember(uow_factory, 7, "Ada", utcnow())
    await _remember(uow_factory, 9, "Grace", utcnow())
    async with uow_factory() as uow:
        assert await uow.operator_profiles.names(1, {7, 8, 9}) == {7: "Ada", 9: "Grace"}
        assert await uow.operator_profiles.names(1, set()) == {}


async def test_names_are_kept_per_org_and_never_read_across(uow_factory):
    """An operator in two orgs is named in each where they acted; one org never sees the other's."""
    await _remember(uow_factory, 7, "Ada at Acme", utcnow(), org_id=1)
    await _remember(uow_factory, 7, "Ada at Beta", utcnow(), org_id=2)
    await _remember(uow_factory, 9, "Grace", utcnow(), org_id=1)
    async with uow_factory() as uow:
        assert await uow.operator_profiles.names(1, {7, 9}) == {7: "Ada at Acme", 9: "Grace"}
        assert await uow.operator_profiles.names(2, {7, 9}) == {7: "Ada at Beta"}
        assert await uow.operator_profiles.names(3, {7, 9}) == {}
        assert await uow.operator_profiles.remember(3, 9, None, utcnow()) is None  # Grace's name in org 1 is not org 3's


async def _statements_of(session_factory, uow_factory, **list_arguments):
    """The list call's result, and every statement it sent (text and parameters)."""
    engine, statements = session_factory.kw["bind"], []

    def capture(connection, cursor, statement, parameters, context, executemany):
        statements.append((statement, parameters))

    event.listen(engine.sync_engine, "before_cursor_execute", capture)
    try:
        async with uow_factory() as uow:
            rows = await uow.conversations.list(limit=51, after=None, **list_arguments)
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", capture)
    return rows, statements


async def test_the_holder_name_search_depends_on_nothing_outside_the_callers_org(session_factory, uow_factory):
    """An operator named in another org never enters this org's holder list, so the search takes
    the same statements, the same way, whether or not such an operator exists: no oracle for
    other orgs' operator names, and none for their volume."""
    acme, beta = make_binding(org_id=1), make_binding(org_id=2)
    beta_test = make_conversation(beta, mode="human", assigned_operator_id=8, is_test=True, last_message_at=utcnow())
    async with uow_factory() as uow:
        for binding in (acme, beta):
            await uow.bindings.add(binding)
        await uow.conversations.add(beta_test)
        await uow.commit()
    search = dict(org_id=2, binding_id=None, section=InboxSection.TEST, search=InboxSearch.parse("bea"))

    without, without_statements = await _statements_of(session_factory, uow_factory, **search)
    # Bea exists now, in Acme only: named there and holding Acme rows (and one test row in Beta,
    # where she never acted, so Beta does not know her name).
    await _remember(uow_factory, 7, "Bea Agent", utcnow(), org_id=1)
    async with uow_factory() as uow:
        await uow.conversations.add(make_conversation(acme, mode="human", assigned_operator_id=7, is_test=True, last_message_at=utcnow()))
        await uow.conversations.add(make_conversation(beta, mode="human", assigned_operator_id=7, is_test=True, last_message_at=utcnow()))
        await uow.commit()
    with_bea, with_bea_statements = await _statements_of(session_factory, uow_factory, **search)

    assert without == with_bea == []
    assert without_statements == with_bea_statements
    # Only the org's own names were read, and no conversation query was needed for either.
    ((statement, parameters),) = with_bea_statements
    assert "FROM operator_profile" in statement and "operator_profile.org_id = " in statement and 2 in parameters.values()
    # Once Bea acts in Beta, Beta knows her name, and finds only Beta's rows.
    await _remember(uow_factory, 7, "Bea Agent", utcnow(), org_id=2)
    found, _ = await _statements_of(session_factory, uow_factory, **search)
    assert [(c.org_id, c.assigned_operator_id) for c in found] == [(2, 7)]


async def test_the_name_lookup_reads_only_the_callers_org_range_of_the_directory(session_factory, uow_factory):
    async with session_factory() as session:
        await session.execute(insert(OperatorProfileRow), [{"org_id": org_id, "user_id": user_id, "display_name": f"Agent {user_id}", "updated_at": utcnow()} for org_id in range(1, 41) for user_id in range(1, 26)])
        await session.commit()
    engine = session_factory.kw["bind"]
    async with engine.connect() as connection:
        await connection.exec_driver_sql("ANALYZE operator_profile")
        await connection.exec_driver_sql("SET enable_seqscan = off")
        result = await connection.exec_driver_sql("EXPLAIN (FORMAT JSON) SELECT user_id FROM operator_profile WHERE org_id = 2 AND lower(display_name) LIKE '%%bea%%' ESCAPE '\\'")
        plan = result.scalar_one()[0]["Plan"]
    nodes, shown = list(_plan_nodes(plan)), json.dumps(plan, indent=1)
    index_reads = [n for n in nodes if "Index Name" in n]
    assert [(n["Index Name"], n["Index Cond"]) for n in index_reads] == [("operator_profile_pkey", "(org_id = 2)")], shown
    assert not [n for n in nodes if n["Node Type"] == "Seq Scan"], shown


async def test_mine_in_the_bot_section_answers_nothing_without_a_query(session_factory, uow_factory):
    binding = make_binding(org_id=1)
    async with uow_factory() as uow:
        await uow.bindings.add(binding)
        await uow.conversations.add(make_conversation(binding, last_message_at=utcnow()))
        await uow.commit()
    engine, statements = session_factory.kw["bind"], []

    def capture(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", capture)
    try:
        async with uow_factory() as uow:
            assert await uow.conversations.list(1, None, InboxSection.BOT, 51, None, holder_id=2) == []
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", capture)
    assert not [s for s in statements if "FROM conversation" in s]


async def test_the_page_limit_is_written_into_the_statement(session_factory, uow_factory):
    """A parameter would reach a prepared statement's generic plan as "a tenth of the rows"."""
    engine, statements = session_factory.kw["bind"], []

    def capture(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", capture)
    try:
        async with uow_factory() as uow:
            await uow.conversations.list(1, None, InboxSection.WAITING, 51, None)
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", capture)
    (statement,) = statements
    assert statement.rstrip().endswith("LIMIT 51")


# ---- operator aliases ----------------------------------------------------------------------------

async def _desks(uow_factory, *desks):
    async with uow_factory() as uow:
        for desk in desks:
            await uow.bindings.add(desk)
        await uow.commit()


async def _set_alias(uow_factory, desk, user_id, alias):
    async with uow_factory() as uow:
        await uow.operator_aliases.set(desk.id, user_id, alias, utcnow())
        await uow.commit()


async def test_an_alias_is_unique_on_a_desk_ignoring_case_but_free_on_other_desks(uow_factory):
    desk, other_desk = make_binding(org_id=1), make_binding(org_id=1)
    await _desks(uow_factory, desk, other_desk)
    await _set_alias(uow_factory, desk, 1, "Mike")
    with pytest.raises(AliasTakenError):
        await _set_alias(uow_factory, desk, 2, "MIKE")
    await _set_alias(uow_factory, other_desk, 2, "mike")  # another desk: its own namespace
    await _set_alias(uow_factory, desk, 1, "MIKE")  # one's own alias may change case
    async with uow_factory() as uow:
        assert await uow.operator_aliases.get(desk.id, 1) == "MIKE"
        assert await uow.operator_aliases.get(desk.id, 2) is None
        assert await uow.operator_aliases.get(other_desk.id, 2) == "mike"


async def test_a_refused_alias_leaves_the_transaction_usable(uow_factory):
    desk = make_binding(org_id=1)
    await _desks(uow_factory, desk)
    await _set_alias(uow_factory, desk, 1, "Mike")
    async with uow_factory() as uow:
        with pytest.raises(AliasTakenError):
            await uow.operator_aliases.set(desk.id, 2, "mike", utcnow())
        await uow.operator_aliases.set(desk.id, 2, "Bea", utcnow())  # would fail in an aborted transaction
        await uow.commit()
    async with uow_factory() as uow:
        assert await uow.operator_aliases.get(desk.id, 2) == "Bea"


async def test_of_two_operators_claiming_one_alias_at_once_the_second_is_refused(uow_factory):
    desk = make_binding(org_id=1)
    await _desks(uow_factory, desk)
    async with uow_factory() as first, uow_factory() as second:
        await first.operator_aliases.set(desk.id, 1, "Mike", utcnow())
        claim = asyncio.ensure_future(second.operator_aliases.set(desk.id, 2, "mike", utcnow()))
        done, _ = await asyncio.wait({claim}, timeout=0.3)
        assert not done, "the second claim did not wait for the first"
        await first.commit()
        with pytest.raises(AliasTakenError):
            await asyncio.wait_for(claim, timeout=5)
    async with uow_factory() as uow:
        assert (await uow.operator_aliases.get(desk.id, 1), await uow.operator_aliases.get(desk.id, 2)) == ("Mike", None)


async def test_clearing_frees_the_alias_and_deleting_the_desk_removes_its_aliases(uow_factory, session_factory):
    desk = make_binding(org_id=1)
    await _desks(uow_factory, desk)
    await _set_alias(uow_factory, desk, 1, "Mike")
    async with uow_factory() as uow:
        await uow.operator_aliases.clear(desk.id, 1)
        await uow.commit()
    await _set_alias(uow_factory, desk, 2, "Mike")
    async with uow_factory() as uow:
        assert await uow.bindings.delete(desk.id, 1)
        await uow.commit()
    async with session_factory() as session:
        assert await session.scalar(text("SELECT count(*) FROM operator_alias")) == 0


async def test_my_aliases_are_the_callers_on_the_orgs_desks_only(uow_factory):
    acme_one, acme_two, beta = make_binding(org_id=1), make_binding(org_id=1), make_binding(org_id=2)
    await _desks(uow_factory, acme_one, acme_two, beta)
    for desk, user_id, alias in ((acme_one, 1, "Mike"), (acme_two, 1, "Michael"), (beta, 1, "Mikko"), (acme_one, 2, "Bea")):
        await _set_alias(uow_factory, desk, user_id, alias)
    async with uow_factory() as uow:
        assert sorted(await uow.operator_aliases.mine(1, 1)) == sorted([(acme_one.id, "Mike"), (acme_two.id, "Michael")])
        assert await uow.operator_aliases.mine(2, 1) == [(beta.id, "Mikko")]
        assert await uow.operator_aliases.mine(3, 1) == []


@pytest.mark.parametrize(("role", "visible_name"), [(Role.OPERATOR, None), (Role.USER, "Mike"), (Role.ASSISTANT, "Mike"), (Role.SYSTEM, "Mike")])
async def test_only_an_operator_message_carries_a_visible_name_and_it_always_does(uow_factory, role, visible_name):
    conversation = await _stored_conversation(uow_factory)
    async with uow_factory() as uow:
        with pytest.raises(IntegrityError, match="ck_message_visible_name_operator_only"):
            await uow.messages.add(Message(id=new_id(), conversation_id=conversation.id, role=role, content="x", actions=None, session_id=None, created_at=utcnow(), author_user_id=None, visible_name=visible_name))  # add() flushes


SHARP_S, DOTTED_CAPITAL_I, COMBINING_DOT_ABOVE = chr(0xDF), chr(0x130), chr(0x0307)


async def test_aliases_on_a_desk_are_the_same_by_key_not_by_the_databases_lower(uow_factory):
    desk = make_binding(org_id=1)
    await _desks(uow_factory, desk)
    await _set_alias(uow_factory, desk, 1, "Stra" + SHARP_S + "e")
    with pytest.raises(AliasTakenError):
        await _set_alias(uow_factory, desk, 2, "STRASSE")  # lower() would let both in
    await _set_alias(uow_factory, desk, 3, DOTTED_CAPITAL_I + "pek")
    with pytest.raises(AliasTakenError):
        await _set_alias(uow_factory, desk, 4, "i" + COMBINING_DOT_ABOVE + "PEK")
    await _set_alias(uow_factory, desk, 4, "Ipek")  # a plain I is another name, as against the bot
    async with uow_factory() as uow:
        assert await uow.operator_aliases.is_taken(desk.id, public_name_key("strasse"))
        assert not await uow.operator_aliases.is_taken(desk.id, public_name_key("Strasser"))


# ---- the inactivity timers' candidates ----------------------------------------------------------

async def _seed_desks(uow_factory, *desks_and_rows):
    async with uow_factory() as uow:
        for desk, rows in desks_and_rows:
            await uow.bindings.add(desk)
            for conversation in rows:
                await uow.conversations.add(conversation)
        await uow.commit()


async def test_the_hand_back_candidates_waited_past_their_own_desks_response_time(uow_factory):
    now = utcnow()
    quick, slow = make_binding(org_id=1, response_time_seconds=60), make_binding(org_id=2, response_time_seconds=3600)
    overdue_rows = {action: make_binding(org_id=1, on_response_timeout=action, response_time_seconds=60) for action in (OnResponseTimeout.OVERDUE, OnResponseTimeout.WAIT)}
    waited = lambda desk, seconds, **overrides: make_conversation(desk, mode=overrides.pop("mode", "awaiting_human"), visitor_waiting_since=now - timedelta(seconds=seconds), last_message_at=now, **overrides)
    longest, held, just_due = waited(quick, 600), waited(quick, 300, mode="human", assigned_operator_id=4), waited(quick, 61)
    not_yet, exactly_due = waited(quick, 59), waited(quick, 60)
    slow_not_yet, slow_due = waited(slow, 600), waited(slow, 3601)
    await _seed_desks(
        uow_factory,
        (quick, [longest, held, just_due, not_yet, exactly_due, waited(quick, 600, is_test=True), make_conversation(quick, last_message_at=now)]),
        (slow, [slow_not_yet, slow_due]),
        *((desk, [waited(desk, 600)]) for desk in overdue_rows.values()),
    )
    async with uow_factory() as uow:
        due = await uow.conversations.unanswered_past_response_time(now, 10)
        first_two = await uow.conversations.unanswered_past_response_time(now, 2)
    # Earliest deadline first, across orgs (the loop serves every org); a deadline exactly now is
    # not past. just_due and slow_due are both due a second ago: the id decides.
    assert due == [longest.id, held.id, just_due.id, slow_due.id]
    assert first_two == due[:2]


async def test_the_close_candidates_are_open_support_conversations_silent_past_their_desks_close_after(uow_factory):
    now = utcnow()
    support = make_binding(org_id=1, style=BindingStyle.SUPPORT, close_after_seconds=3600)
    ongoing = make_binding(org_id=1, style=BindingStyle.ONGOING, close_after_seconds=3600)
    silent_for = lambda desk, seconds, **overrides: make_conversation(desk, last_message_at=now - timedelta(seconds=seconds), **overrides)
    idle_bot, idle_held, idle_waiting = silent_for(support, 7200), silent_for(support, 5000, mode="human", assigned_operator_id=4), silent_for(support, 3601, mode="awaiting_human")
    await _seed_desks(
        uow_factory,
        (support, [
            idle_bot, idle_held, idle_waiting,
            silent_for(support, 3600),  # exactly due: not past
            silent_for(support, 60),
            silent_for(support, 7200, is_test=True),
            silent_for(support, 7200, run_state=RunState.RUNNING, active_since=now),
            make_closed(support, last_message_at=now - timedelta(days=3)),
            make_conversation(support, created_at=now - timedelta(days=3)),  # silent: never said anything
        ]),
        (ongoing, [silent_for(ongoing, 7200)]),
    )
    async with uow_factory() as uow:
        due = await uow.conversations.inactive_past_close_after(now, 10)
    assert due == [idle_bot.id, idle_held.id, idle_waiting.id]


TIMER_QUERIES = {
    # Two days on, every open conversation of the busy inbox is past close-after too: a backlog.
    "hand-back": (lambda conversations: conversations.unanswered_past_response_time(utcnow(), 500), "ix_conversation_binding_id_waiting"),
    "close after": (lambda conversations: conversations.inactive_past_close_after(utcnow() + timedelta(days=2), 500), "ix_conversation_binding_id_open_activity"),
}


def _per_desk_limit(plan: dict) -> dict:
    """The LATERAL read's Limit: the one whose subtree reads conversations and no desks."""
    (node,) = [n for n in _plan_nodes(plan) if n["Node Type"] == "Limit" and not any(child.get("Relation Name") == "binding" for child in _plan_nodes(n))]
    return node


async def _statements_of_call(session_factory, uow_factory, call) -> list[str]:
    engine, statements = session_factory.kw["bind"], []

    def capture(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", capture)
    try:
        async with uow_factory() as uow:
            await call(uow.conversations)
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", capture)
    return statements


@pytest.mark.parametrize("plan_cache_mode", ["force_generic_plan", "force_custom_plan"], ids=["generic plan", "custom plan"])
@pytest.mark.parametrize(("call", "index"), TIMER_QUERIES.values(), ids=TIMER_QUERIES.keys())
async def test_each_timer_reads_each_desk_in_index_order_and_stops_at_the_batch(session_factory, uow_factory, call, index, plan_cache_mode):
    """The reconcile loop runs these every pass, so the driver soon prepares them, and a plan made
    for the actual `now` is as likely as a generic one. With a backlog, such a plan bitmap-read and
    sorted each desk's whole overdue range; with bitmap scans off for the read (the method's own
    setting), every desk is a range of its partial index read in order and stopped at the batch."""
    await _seed_inbox(session_factory)
    statements = await _statements_of_call(session_factory, uow_factory, call)
    assert statements[:2] == ["SET LOCAL enable_bitmapscan = off", "SET LOCAL jit = off"] and "FROM conversation" in statements[2], statements
    plan = await _generic_plan_of(session_factory, uow_factory, ("enable_seqscan = off", "enable_bitmapscan = off"), call, plan_cache_mode)
    nodes, shown = list(_plan_nodes(plan)), json.dumps(plan, indent=1)
    (read,) = [n for n in nodes if n.get("Relation Name") == "conversation"]
    assert (read["Node Type"] in ("Index Scan", "Index Only Scan"), read.get("Index Name")) == (True, index), shown
    # One desk's range, the deadline included: never a whole-index walk.
    assert read["Index Cond"].startswith("((binding_id = ") and " < (" in read["Index Cond"], shown
    # Straight from the index into the per-desk limit: no sort of a whole overdue range.
    assert _per_desk_limit(plan)["Plans"][0] is read, shown


# A day's deadline across Kyiv's clock changes in 2026: summer time ends on 25 October (the local
# day before is 25 hours long) and starts on 29 March (23 hours).
DST_CHANGES = {"summer time ends": datetime(2026, 10, 25, 12, 0, tzinfo=UTC), "summer time starts": datetime(2026, 3, 29, 12, 0, tzinfo=UTC)}


@pytest.mark.parametrize("now", DST_CHANGES.values(), ids=DST_CHANGES.keys())
async def test_a_deadline_is_exact_in_seconds_across_a_clock_change_of_the_sessions_time_zone(uow_factory, now):
    """`now` must reach the database as an instant: as a local wall time, a day before it would
    be an hour off across a change, in the server's zone."""
    binding = make_binding(org_id=1, response_time_seconds=86_400, close_after_seconds=86_400)
    late, early = now - timedelta(days=1, minutes=30), now - timedelta(days=1) + timedelta(minutes=30)
    waited, too_early = (make_conversation(binding, mode="awaiting_human", visitor_waiting_since=since, last_message_at=now) for since in (late, early))
    silent, recent = (make_conversation(binding, last_message_at=since) for since in (late, early))
    await _seed_desks(uow_factory, (binding, [waited, too_early, silent, recent]))
    async with uow_factory() as uow:
        await uow._session.execute(text("SET LOCAL TIME ZONE 'Europe/Kyiv'"))
        due = await uow.conversations.unanswered_past_response_time(now, 10)
        idle = await uow.conversations.inactive_past_close_after(now, 10)
    assert (due, idle) == ([waited.id], [silent.id])


async def test_the_earliest_deadline_comes_first_so_a_long_timeout_desk_never_starves_a_short_one(uow_factory):
    """Ordered by when the rule fell due, not by when the visitor wrote: a conversation a second
    past a day's response time does not go before one hours past an hour's."""
    now = utcnow()
    day_desk = make_binding(org_id=1, response_time_seconds=86_400, close_after_seconds=86_400)
    hour_desk = make_binding(org_id=1, response_time_seconds=3600, close_after_seconds=3600)
    # The day desk's visitor wrote first, but its deadline passed a second ago; the hour desk's
    # passed 23 hours ago.
    a_second_late = make_conversation(day_desk, mode="awaiting_human", visitor_waiting_since=now - timedelta(seconds=86_401), last_message_at=now - timedelta(seconds=86_401))
    hours_late = make_conversation(hour_desk, mode="awaiting_human", visitor_waiting_since=now - timedelta(seconds=86_400), last_message_at=now - timedelta(seconds=86_400))
    await _seed_desks(uow_factory, (day_desk, [a_second_late]), (hour_desk, [hours_late]))
    async with uow_factory() as uow:
        assert await uow.conversations.unanswered_past_response_time(now, 1) == [hours_late.id]
    async with uow_factory() as uow:
        assert await uow.conversations.inactive_past_close_after(now, 1) == [hours_late.id]
