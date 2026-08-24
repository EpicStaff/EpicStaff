"""Unit tests for TokenUsageAccumulator."""

from __future__ import annotations

import pytest

from app.usage import TokenUsageAccumulator
from shared.models.agent_service import TokenUsage


def test_add_sums_all_five_fields():
    accumulator = TokenUsageAccumulator()

    accumulator.add(
        {
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
            "cached_prompt_tokens": 3,
            "total_cost_usd": 0.001,
        }
    )
    accumulator.add(
        {
            "prompt_tokens": 20,
            "completion_tokens": 8,
            "total_tokens": 28,
            "cached_prompt_tokens": 4,
            "total_cost_usd": 0.002,
        }
    )

    assert accumulator.prompt_tokens == 30
    assert accumulator.completion_tokens == 13
    assert accumulator.total_tokens == 43
    assert accumulator.cached_prompt_tokens == 7
    assert accumulator.total_cost_usd == pytest.approx(0.003)


def test_add_missing_keys_default_to_zero():
    accumulator = TokenUsageAccumulator()

    accumulator.add({})

    assert accumulator.prompt_tokens == 0
    assert accumulator.completion_tokens == 0
    assert accumulator.total_tokens == 0
    assert accumulator.cached_prompt_tokens == 0
    assert accumulator.total_cost_usd == 0.0


def test_add_total_tokens_falls_back_to_prompt_plus_completion():
    accumulator = TokenUsageAccumulator()

    accumulator.add({"prompt_tokens": 7, "completion_tokens": 2})

    assert accumulator.total_tokens == 9


def test_to_token_usage_carries_all_five_fields():
    accumulator = TokenUsageAccumulator()
    accumulator.add(
        {
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
            "cached_prompt_tokens": 3,
            "total_cost_usd": 0.001,
        }
    )

    usage = accumulator.to_token_usage()

    assert usage == TokenUsage(
        prompt_tokens=10,
        completion_tokens=5,
        total_tokens=15,
        cached_prompt_tokens=3,
        total_cost_usd=0.001,
    )


def test_consume_delta_fresh_accumulator_returns_zeros():
    accumulator = TokenUsageAccumulator()

    delta = accumulator.consume_delta()

    assert delta == {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "cached_prompt_tokens": 0,
        "total_cost_usd": 0.0,
    }


def test_consume_delta_first_call_returns_everything():
    accumulator = TokenUsageAccumulator()
    accumulator.add(
        {
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
            "cached_prompt_tokens": 3,
            "total_cost_usd": 0.001,
        }
    )

    delta = accumulator.consume_delta()

    assert delta["prompt_tokens"] == 10
    assert delta["completion_tokens"] == 5
    assert delta["total_tokens"] == 15
    assert delta["cached_prompt_tokens"] == 3
    assert delta["total_cost_usd"] == pytest.approx(0.001)


def test_consume_delta_second_call_returns_only_new_usage():
    accumulator = TokenUsageAccumulator()
    accumulator.add(
        {
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
            "cached_prompt_tokens": 3,
            "total_cost_usd": 0.001,
        }
    )
    accumulator.consume_delta()

    accumulator.add(
        {
            "prompt_tokens": 4,
            "completion_tokens": 2,
            "total_tokens": 6,
            "cached_prompt_tokens": 1,
            "total_cost_usd": 0.0005,
        }
    )
    delta = accumulator.consume_delta()

    assert delta["prompt_tokens"] == 4
    assert delta["completion_tokens"] == 2
    assert delta["total_tokens"] == 6
    assert delta["cached_prompt_tokens"] == 1
    assert delta["total_cost_usd"] == pytest.approx(0.0005)


def test_consume_delta_snapshot_advances_even_when_return_value_discarded():
    accumulator = TokenUsageAccumulator()
    accumulator.add(
        {
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
            "cached_prompt_tokens": 3,
            "total_cost_usd": 0.001,
        }
    )
    accumulator.consume_delta()  # return value discarded

    delta = accumulator.consume_delta()

    assert delta == {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "cached_prompt_tokens": 0,
        "total_cost_usd": 0.0,
    }
