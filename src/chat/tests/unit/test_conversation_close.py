from datetime import timedelta

import pytest
from common.utils import new_id, utcnow
from domain.enums import CloseReason, ConversationStatus, Mode, Role, RunState
from domain.errors import ConversationClosedError
from domain.models import Message
from tests.factories import make_binding, make_closed, make_conversation

BINDING = make_binding()
NOW = utcnow()
EARLIER = NOW - timedelta(hours=1)


def _message(conversation, role=Role.USER) -> Message:
    return Message(id=new_id(), conversation_id=conversation.id, role=role, content="x", actions=None, session_id=None, created_at=NOW, author_user_id=None)


@pytest.mark.parametrize(("reason", "by_user_id"), [(CloseReason.RESOLVED, 7), (CloseReason.ENDED, None), (CloseReason.INACTIVE, None)])
def test_closing_records_why_when_and_who_resolved_it(reason, by_user_id):
    conversation = make_conversation(BINDING, last_message_at=EARLIER)
    assert conversation.is_open and conversation.close(reason, NOW, by_user_id) is True
    assert (conversation.status, conversation.close_reason, conversation.closed_at, conversation.closed_by_user_id) == (ConversationStatus.CLOSED, reason, NOW, by_user_id)
    assert not conversation.is_open


def test_closing_twice_changes_nothing_and_says_so():
    conversation = make_conversation(BINDING)
    conversation.close(CloseReason.ENDED, EARLIER)
    assert conversation.close(CloseReason.RESOLVED, NOW, 7) is False
    assert (conversation.close_reason, conversation.closed_at, conversation.closed_by_user_id) == (CloseReason.ENDED, EARLIER, None)


@pytest.mark.parametrize(("reason", "by_user_id"), [(CloseReason.RESOLVED, None), (CloseReason.ENDED, 7), (CloseReason.INACTIVE, 7)])
def test_only_a_resolved_close_names_an_operator_and_it_always_does(reason, by_user_id):
    conversation = make_conversation(BINDING)
    with pytest.raises(ValueError, match="resolved"):
        conversation.close(reason, NOW, by_user_id)
    assert conversation.is_open


def test_closing_ends_the_wait_and_frees_the_run_slot_but_keeps_who_had_it():
    run_id = new_id()
    conversation = make_conversation(BINDING, mode="human", assigned_operator_id=3, handoff_reason="run error", visitor_waiting_since=EARLIER, run_state=RunState.STARTING, active_run_id=run_id, active_since=EARLIER, late_reply_run_id=new_id())
    handoff_at = conversation.handoff_at
    conversation.close(CloseReason.RESOLVED, NOW, by_user_id=4)
    assert (conversation.visitor_waiting_since, conversation.run_state, conversation.active_run_id, conversation.active_since, conversation.late_reply_run_id) == (None, RunState.IDLE, None, None, None)
    # A snapshot of who had it: the inbox still shows the holder and the hand-off.
    assert (conversation.mode, conversation.assigned_operator_id, conversation.handoff_at, conversation.handoff_reason) == (Mode.HUMAN, 3, handoff_at, "run error")
    assert conversation.operator_ids == {3, 4}


@pytest.mark.parametrize("change", [
    lambda conversation: conversation.change_mode(Mode.AWAITING_HUMAN, NOW),
    lambda conversation: conversation.return_to_bot(NOW),
    lambda conversation: conversation.record_message(_message(conversation)),
    lambda conversation: conversation.ensure_open(),
], ids=["change mode", "return to bot", "record a message", "ensure open"])
def test_a_closed_conversation_refuses_every_change_with_its_reason(change):
    conversation = make_closed(BINDING, reason=CloseReason.ENDED, mode="human", assigned_operator_id=3, last_message_at=EARLIER)
    before = (conversation.mode, conversation.last_message_at, conversation.assigned_operator_id)
    with pytest.raises(ConversationClosedError) as refused:
        change(conversation)
    assert (refused.value.code, refused.value.status_code, refused.value.extra) == ("conversation_closed", 409, {"close_reason": "ended"})
    assert (conversation.mode, conversation.last_message_at, conversation.assigned_operator_id) == before


def test_usage_still_counts_on_a_closed_conversation():
    conversation = make_closed(BINDING)
    conversation.count_tokens(5, NOW.date())
    assert conversation.tokens_used == 5


@pytest.mark.parametrize("mode", [Mode.AWAITING_HUMAN, Mode.HUMAN])
def test_returning_to_the_bot_lets_go_of_the_holder_the_wait_and_the_hand_off(mode):
    conversation = make_conversation(BINDING, mode=mode, handoff_reason="the flow asked for a human", visitor_waiting_since=EARLIER, late_reply_run_id=new_id())
    conversation.return_to_bot(NOW)
    assert (conversation.mode, conversation.assigned_operator_id, conversation.handoff_at, conversation.visitor_waiting_since) == (Mode.BOT, None, None, None)
    assert (conversation.handoff_reason, conversation.late_reply_run_id, conversation.is_open) == ("", None, True)
