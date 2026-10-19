from datetime import timedelta

import pytest
from common.utils import utcnow
from domain.enums import BindingStyle, OnResponseTimeout, RunState
from tests.factories import make_binding, make_closed, make_conversation

NOW = utcnow()
RESPONSE_TIME, CLOSE_AFTER = 600, 86_400
SUPPORT = make_binding(style=BindingStyle.SUPPORT, response_time_seconds=RESPONSE_TIME, close_after_seconds=CLOSE_AFTER)
ONGOING = make_binding(style=BindingStyle.ONGOING, response_time_seconds=RESPONSE_TIME, close_after_seconds=CLOSE_AFTER)


# ---- response time: when a waiting visitor is overdue -------------------------------------------

@pytest.mark.parametrize("mode", ["awaiting_human", "human"])
@pytest.mark.parametrize("binding", [SUPPORT, ONGOING], ids=["support", "ongoing"])
def test_a_waiting_visitor_is_due_the_response_time_after_the_wait_began(mode, binding):
    waiting_since = NOW - timedelta(hours=1)
    conversation = make_conversation(binding, mode=mode, visitor_waiting_since=waiting_since)
    assert binding.response_due_at(conversation) == waiting_since + timedelta(seconds=RESPONSE_TIME)


@pytest.mark.parametrize("action", list(OnResponseTimeout))
def test_the_deadline_is_the_same_whatever_the_desk_does_then(action):
    # The inbox's overdue mark and the hand-back read one deadline; the action only picks what happens.
    binding = make_binding(on_response_timeout=action, response_time_seconds=RESPONSE_TIME)
    conversation = make_conversation(binding, mode="awaiting_human", visitor_waiting_since=NOW)
    assert binding.response_due_at(conversation) == NOW + timedelta(seconds=RESPONSE_TIME)


NOBODY_DUE = {
    "with the bot": lambda: make_conversation(SUPPORT),
    "held and answered": lambda: make_conversation(SUPPORT, mode="human", visitor_waiting_since=None),
    "a test": lambda: make_conversation(SUPPORT, mode="awaiting_human", is_test=True),
    "closed while waiting": lambda: make_closed(SUPPORT, mode="awaiting_human"),
}


@pytest.mark.parametrize("conversation", NOBODY_DUE.values(), ids=NOBODY_DUE.keys())
def test_nobody_is_due_when_nobody_waits_or_the_conversation_is_closed_or_a_test(conversation):
    assert SUPPORT.response_due_at(conversation()) is None


# ---- close after: when a Support conversation is idle --------------------------------------------

@pytest.mark.parametrize("mode", ["bot", "awaiting_human", "human"])
def test_a_support_conversation_closes_the_close_after_time_past_its_last_message(mode):
    last_message_at = NOW - timedelta(days=2)
    conversation = make_conversation(SUPPORT, mode=mode, last_message_at=last_message_at)
    assert SUPPORT.idle_close_at(conversation) == last_message_at + timedelta(seconds=CLOSE_AFTER)


NEVER_IDLE = {
    "on an ongoing desk": lambda: (ONGOING, make_conversation(ONGOING, last_message_at=NOW)),
    "silent": lambda: (SUPPORT, make_conversation(SUPPORT)),
    "a test": lambda: (SUPPORT, make_conversation(SUPPORT, is_test=True, last_message_at=NOW)),
    "already closed": lambda: (SUPPORT, make_closed(SUPPORT, last_message_at=NOW)),
    "the bot is answering": lambda: (SUPPORT, make_conversation(SUPPORT, last_message_at=NOW, run_state=RunState.RUNNING, active_since=NOW)),
    "the bot's run is starting": lambda: (SUPPORT, make_conversation(SUPPORT, last_message_at=NOW, run_state=RunState.STARTING, active_since=NOW)),
}


@pytest.mark.parametrize("case", NEVER_IDLE.values(), ids=NEVER_IDLE.keys())
def test_a_conversation_never_closes_as_idle_when(case):
    binding, conversation = case()
    assert binding.idle_close_at(conversation) is None
