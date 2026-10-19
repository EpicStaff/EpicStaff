from datetime import timedelta

import pytest
from common.utils import new_id, utcnow
from domain.enums import Mode, Role
from domain.models import Message
from tests.factories import make_binding, make_conversation

BINDING = make_binding()
EARLIER = utcnow() - timedelta(hours=1)
NOW = utcnow()


@pytest.mark.parametrize("target", [Mode.AWAITING_HUMAN, Mode.HUMAN])
def test_leaving_bot_mode_sets_handoff_at_to_now(target):
    conversation = make_conversation(BINDING)
    conversation.change_mode(target, NOW)
    assert (conversation.mode, conversation.handoff_at) == (target, NOW)


@pytest.mark.parametrize(("source", "target"), [(Mode.AWAITING_HUMAN, Mode.HUMAN), (Mode.HUMAN, Mode.HUMAN), (Mode.HUMAN, Mode.AWAITING_HUMAN)])
def test_moving_between_human_modes_keeps_handoff_at(source, target):
    conversation = make_conversation(BINDING, mode=source, handoff_at=EARLIER)
    conversation.change_mode(target, NOW)
    assert (conversation.mode, conversation.handoff_at) == (target, EARLIER)


@pytest.mark.parametrize("source", [Mode.AWAITING_HUMAN, Mode.HUMAN])
def test_returning_to_bot_clears_handoff_at(source):
    conversation = make_conversation(BINDING, mode=source, handoff_at=EARLIER)
    conversation.change_mode(Mode.BOT, NOW)
    assert (conversation.mode, conversation.handoff_at) == (Mode.BOT, None)


def test_factory_hands_off_non_bot_conversations_unless_overridden():
    assert make_conversation(BINDING).handoff_at is None
    assert make_conversation(BINDING, mode="human").handoff_at is not None
    assert make_conversation(BINDING, mode="awaiting_human", handoff_at=EARLIER).handoff_at == EARLIER


# ---- the visitor's wait for a person and the last message's author ------------------------------

T = [NOW + timedelta(minutes=minute) for minute in range(8)]


def _message(conversation, role, at, author_user_id=None) -> Message:
    return Message(id=new_id(), conversation_id=conversation.id, role=role, content="x", actions=None, session_id=None, created_at=at, author_user_id=author_user_id)


def test_a_hand_off_starts_the_wait_now():
    conversation = make_conversation(BINDING)
    conversation.change_mode(Mode.AWAITING_HUMAN, NOW)
    assert conversation.visitor_waiting_since == NOW


@pytest.mark.parametrize("last_role", [None, Role.ASSISTANT, Role.OPERATOR], ids=["no message", "bot answered", "operator answered"])
def test_a_take_over_straight_from_the_bot_after_an_answer_starts_no_wait(last_role):
    conversation = make_conversation(BINDING, last_message_role=last_role, last_message_at=EARLIER if last_role else None)
    conversation.change_mode(Mode.HUMAN, NOW)
    assert conversation.visitor_waiting_since is None


# The visitor wrote and the bot's run was still going, or the run failed and left a system notice:
# nobody answered, so a person now holds an unanswered visitor.
@pytest.mark.parametrize("last_role", [Role.USER, Role.SYSTEM], ids=["visitor", "run-failure notice"])
def test_a_take_over_straight_from_the_bot_while_nobody_answered_starts_the_wait_at_the_last_message(last_role):
    conversation = make_conversation(BINDING, last_message_role=last_role, last_message_at=EARLIER)
    conversation.change_mode(Mode.HUMAN, NOW)
    assert (conversation.mode, conversation.visitor_waiting_since, conversation.handoff_at) == (Mode.HUMAN, EARLIER, NOW)


def test_a_hand_off_after_the_visitor_wrote_still_starts_the_wait_now():
    conversation = make_conversation(BINDING, last_message_role=Role.USER, last_message_at=EARLIER)
    conversation.change_mode(Mode.AWAITING_HUMAN, NOW)
    assert conversation.visitor_waiting_since == NOW


@pytest.mark.parametrize("source", [Mode.AWAITING_HUMAN, Mode.HUMAN], ids=["take over", "forced take over"])
def test_a_take_over_keeps_the_wait(source):
    conversation = make_conversation(BINDING, mode=source, visitor_waiting_since=EARLIER)
    conversation.change_mode(Mode.HUMAN, NOW)
    assert conversation.visitor_waiting_since == EARLIER


@pytest.mark.parametrize("source", [Mode.AWAITING_HUMAN, Mode.HUMAN])
def test_returning_to_the_bot_ends_the_wait(source):
    conversation = make_conversation(BINDING, mode=source, visitor_waiting_since=EARLIER)
    conversation.change_mode(Mode.BOT, NOW)
    assert conversation.visitor_waiting_since is None


def test_entering_awaiting_human_always_leaves_the_visitor_waiting():
    answered = make_conversation(BINDING, mode="human", visitor_waiting_since=None)
    answered.change_mode(Mode.AWAITING_HUMAN, NOW)
    assert answered.visitor_waiting_since == NOW


def test_a_visitor_message_after_the_operator_answered_starts_the_wait_at_the_message():
    conversation = make_conversation(BINDING, mode="human", visitor_waiting_since=None)
    conversation.record_message(_message(conversation, Role.USER, T[1]))
    assert conversation.visitor_waiting_since == T[1]


@pytest.mark.parametrize("mode", [Mode.AWAITING_HUMAN, Mode.HUMAN])
def test_a_later_visitor_message_keeps_the_earliest_wait(mode):
    conversation = make_conversation(BINDING, mode=mode, visitor_waiting_since=T[0])
    conversation.record_message(_message(conversation, Role.USER, T[1]))
    assert conversation.visitor_waiting_since == T[0]


def test_a_visitor_message_to_the_bot_starts_no_wait():
    conversation = make_conversation(BINDING)
    conversation.record_message(_message(conversation, Role.USER, T[1]))
    assert conversation.visitor_waiting_since is None


def test_an_operator_reply_ends_the_wait():
    conversation = make_conversation(BINDING, mode="human", visitor_waiting_since=T[0])
    conversation.record_message(_message(conversation, Role.OPERATOR, T[1], author_user_id=1))
    assert conversation.visitor_waiting_since is None


@pytest.mark.parametrize("role", [Role.ASSISTANT, Role.SYSTEM])
@pytest.mark.parametrize("waiting_since", [None, T[0]], ids=["not waiting", "waiting"])
def test_bot_and_system_messages_leave_the_wait_as_it_is(role, waiting_since):
    conversation = make_conversation(BINDING, mode="human", visitor_waiting_since=waiting_since)
    conversation.record_message(_message(conversation, role, T[1]))
    assert conversation.visitor_waiting_since == waiting_since


@pytest.mark.parametrize("is_test", [False, True], ids=["visitor", "test conversation"])
def test_the_wait_through_a_hand_off_take_over_reply_and_release(is_test):
    conversation = make_conversation(BINDING, is_test=is_test)

    def step(apply):
        apply()
        return conversation.visitor_waiting_since

    assert step(lambda: conversation.record_message(_message(conversation, Role.USER, T[0]))) is None
    assert step(lambda: conversation.change_mode(Mode.AWAITING_HUMAN, T[1])) == T[1]
    assert step(lambda: conversation.record_message(_message(conversation, Role.USER, T[2]))) == T[1]
    assert step(lambda: conversation.change_mode(Mode.HUMAN, T[3])) == T[1]
    assert step(lambda: conversation.record_message(_message(conversation, Role.OPERATOR, T[4], author_user_id=1))) is None
    assert step(lambda: conversation.record_message(_message(conversation, Role.USER, T[5]))) == T[5]
    assert step(lambda: conversation.record_message(_message(conversation, Role.USER, T[6]))) == T[5]
    assert step(lambda: conversation.change_mode(Mode.BOT, T[7])) is None


def test_an_operator_reply_is_recorded_with_its_author():
    conversation = make_conversation(BINDING, mode="human")
    conversation.record_message(_message(conversation, Role.OPERATOR, T[1], author_user_id=7))
    assert (conversation.last_message_at, conversation.last_message_role, conversation.last_message_author_user_id) == (T[1], Role.OPERATOR, 7)


@pytest.mark.parametrize("role", [Role.USER, Role.ASSISTANT, Role.SYSTEM])
def test_any_other_message_leaves_no_author(role):
    conversation = make_conversation(BINDING, mode="human", last_message_role=Role.OPERATOR, last_message_author_user_id=7)
    conversation.record_message(_message(conversation, role, T[1]))
    assert (conversation.last_message_at, conversation.last_message_role, conversation.last_message_author_user_id) == (T[1], role, None)


def test_operator_ids_are_the_holder_and_the_last_author():
    assert make_conversation(BINDING).operator_ids == set()
    assert make_conversation(BINDING, mode="human", assigned_operator_id=2, last_message_author_user_id=7).operator_ids == {2, 7}
    assert make_conversation(BINDING, mode="human", assigned_operator_id=2, last_message_author_user_id=2).operator_ids == {2}
