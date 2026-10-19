from datetime import date, timedelta

import pytest
from application.orchestrators.budgets import NEW_DESK_RULES, BindingLimits, exhausted_reason, run_token_budget
from domain.errors import BudgetAboveCapError, DurationAboveCapError
from tests.factories import make_binding, make_conversation

LIMITS = BindingLimits(
    deployment_defaults={"token_budget_per_conversation": 100, "daily_token_budget": 1000, "response_time_seconds": 600, "close_after_seconds": 86_400},
    caps={"token_budget_per_conversation": 500, "daily_token_budget": 5000, "response_time_seconds": 86_400, "close_after_seconds": 2_592_000},
)
DAY = date(2026, 10, 10)


def test_largest_allowed_budgets_still_exhaust():
    binding = make_binding(max_turns=200, token_budget_per_conversation=1_000_000, daily_token_budget=50_000_000)
    assert exhausted_reason(binding, make_conversation(binding, tokens_today=1_000_000), daily_tokens=0) == "conversation_token_budget"
    assert exhausted_reason(binding, make_conversation(binding), daily_tokens=50_000_000) == "daily_token_budget"
    assert run_token_budget(binding) == 1_000_000


def test_turns_then_conversation_then_daily():
    binding = make_binding(max_turns=2, token_budget_per_conversation=100, daily_token_budget=1000)
    assert exhausted_reason(binding, make_conversation(binding, turns_today=2), 0) == "max_turns"
    assert exhausted_reason(binding, make_conversation(binding, turns_today=1, tokens_today=100), 0) == "conversation_token_budget"
    assert exhausted_reason(binding, make_conversation(binding, turns_today=1, tokens_today=50), 1000) == "daily_token_budget"
    assert exhausted_reason(binding, make_conversation(binding, turns_today=1, tokens_today=50), 999) is None


def test_per_conversation_limits_ignore_lifetime_totals():
    binding = make_binding(max_turns=2, token_budget_per_conversation=100)
    conversation = make_conversation(binding, turns=50, tokens_used=10_000, turns_today=0, tokens_today=0)
    assert exhausted_reason(binding, conversation, 0) is None


def test_a_run_gets_the_whole_conversation_budget_and_only_the_next_run_is_blocked():
    binding = make_binding(max_turns=200, token_budget_per_conversation=200_000)
    nearly_spent = make_conversation(binding, tokens_today=194_579)
    assert exhausted_reason(binding, nearly_spent, 0) is None
    assert run_token_budget(binding) == 200_000  # not the 5_421 left
    assert exhausted_reason(binding, make_conversation(binding, tokens_today=200_000), 0) == "conversation_token_budget"


def test_a_new_day_restarts_todays_counters_but_not_the_lifetime_totals():
    binding = make_binding(max_turns=2, token_budget_per_conversation=100)
    conversation = make_conversation(binding, usage_day=DAY, turns=2, turns_today=2, tokens_used=100, tokens_today=100)
    assert exhausted_reason(binding, conversation, 0) == "max_turns"
    conversation.roll_usage_day(DAY)
    assert (conversation.turns_today, conversation.tokens_today) == (2, 100)
    conversation.roll_usage_day(DAY + timedelta(days=1))
    assert (conversation.usage_day, conversation.turns_today, conversation.tokens_today) == (DAY + timedelta(days=1), 0, 0)
    assert (conversation.turns, conversation.tokens_used) == (2, 100)
    assert exhausted_reason(binding, conversation, 0) is None


def test_an_earlier_today_never_rolls_the_counters_back():
    conversation = make_conversation(make_binding(), usage_day=DAY, tokens_today=40, turns_today=2)
    conversation.roll_usage_day(DAY - timedelta(days=1))
    assert (conversation.usage_day, conversation.tokens_today, conversation.turns_today) == (DAY, 40, 2)


def test_counting_rolls_the_day_first_and_adds_to_both_totals():
    binding = make_binding()
    conversation = make_conversation(binding, usage_day=DAY, turns=3, turns_today=3, tokens_used=40, tokens_today=40)
    conversation.count_tokens(7, DAY)
    conversation.count_turn(DAY)
    assert (conversation.tokens_used, conversation.tokens_today, conversation.turns, conversation.turns_today) == (47, 47, 4, 4)
    conversation.count_tokens(5, DAY + timedelta(days=1))
    conversation.count_turn(DAY + timedelta(days=1))
    assert (conversation.tokens_used, conversation.tokens_today, conversation.turns, conversation.turns_today) == (52, 5, 5, 1)


def test_limits_accept_values_up_to_the_cap_and_ignore_absent_ones():
    LIMITS.check({"token_budget_per_conversation": 500, "daily_token_budget": 5000})
    LIMITS.check({"name": "x"})


@pytest.mark.parametrize(("name", "value", "cap"), [("token_budget_per_conversation", 501, 500), ("daily_token_budget", 5001, 5000)])
def test_limits_reject_a_budget_above_its_cap(name, value, cap):
    with pytest.raises(BudgetAboveCapError) as error:
        LIMITS.check({name: value})
    assert error.value.extra == {"field": name, "max": cap}


def test_limits_accept_durations_up_to_the_cap():
    LIMITS.check({"response_time_seconds": 86_400, "close_after_seconds": 2_592_000})


@pytest.mark.parametrize(("name", "value", "cap"), [("response_time_seconds", 86_401, 86_400), ("close_after_seconds", 2_592_001, 2_592_000)])
def test_limits_reject_a_duration_above_its_cap(name, value, cap):
    with pytest.raises(DurationAboveCapError) as error:
        LIMITS.check({name: value})
    assert (error.value.code, error.value.status_code, error.value.extra) == ("duration_above_cap", 400, {"field": name, "max": cap})
    assert error.value.message == f"`{name}` cannot exceed {cap} seconds on this deployment."


def test_with_defaults_fills_only_the_absent_or_null_fields_from_the_deployment_and_the_new_desk_rules():
    filled = LIMITS.with_defaults({"name": "Desk", "daily_token_budget": 7, "response_time_seconds": None, "handback_message": "", "style": "ongoing"})
    assert filled == {
        "name": "Desk", "token_budget_per_conversation": 100, "daily_token_budget": 7, "response_time_seconds": 600, "close_after_seconds": 86_400,
        "style": "ongoing", "on_response_timeout": "handback", "handback_message": "",  # an empty notice is a choice, not an omission
    }


def test_the_defaults_are_the_deployments_budgets_and_durations_plus_the_new_desk_rules():
    assert LIMITS.defaults == {**NEW_DESK_RULES, "token_budget_per_conversation": 100, "daily_token_budget": 1000, "response_time_seconds": 600, "close_after_seconds": 86_400}
    assert (NEW_DESK_RULES["style"], NEW_DESK_RULES["on_response_timeout"]) == ("support", "handback") and NEW_DESK_RULES["handback_message"]
