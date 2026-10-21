"""
Tests for the duration validation in settings.
"""

from __future__ import annotations

import pytest
from settings import positive_seconds, whole_seconds_at_least_one


@pytest.mark.parametrize(("seconds", "expected"), [(3600.0, 3600), (1.5, 1)])
def test_accepts_at_least_one_second_truncated_to_whole_seconds(seconds, expected):
    assert whole_seconds_at_least_one("AGENT_RESULT_STREAM_TTL", seconds) == expected


@pytest.mark.parametrize("seconds", [None, 0.0, 0.5, -1.0])
def test_rejects_none_and_sub_second_values(seconds):
    with pytest.raises(ValueError, match="AGENT_RESULT_STREAM_TTL"):
        whole_seconds_at_least_one("AGENT_RESULT_STREAM_TTL", seconds)


def test_drop_unsupported_llm_params_is_parsed_as_bool():
    # litellm ignores a non-bool drop_params, so a "True" string would still raise UnsupportedParamsError.
    import settings

    assert isinstance(settings.AGENT_DROP_UNSUPPORTED_LLM_PARAMS, bool)


@pytest.mark.parametrize("seconds", [0.001, 1.0, 300.0])
def test_positive_seconds_accepts_any_duration_above_zero(seconds):
    assert positive_seconds("AGENT_MCP_DESCRIBE_CACHE_TTL", seconds) == seconds


@pytest.mark.parametrize("seconds", [None, 0.0, -1.0])
def test_positive_seconds_rejects_none_zero_and_negative(seconds):
    with pytest.raises(ValueError, match="AGENT_MCP_DESCRIBE_CACHE_TTL"):
        positive_seconds("AGENT_MCP_DESCRIBE_CACHE_TTL", seconds)


def test_new_durations_are_parsed_as_seconds():
    # A "1s"/"5m" string reaching asyncio.sleep or the cache expiry would fail at runtime.
    import settings

    for value in (
        settings.AGENT_REDIS_READ_RETRY_INITIAL_DELAY,
        settings.AGENT_REDIS_READ_RETRY_MAX_DELAY,
        settings.AGENT_MCP_DESCRIBE_CACHE_TTL,
    ):
        assert isinstance(value, float)
