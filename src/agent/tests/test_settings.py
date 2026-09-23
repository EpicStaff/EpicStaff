"""
Tests for the AGENT_RESULT_STREAM_TTL validation in settings.
"""

from __future__ import annotations

import pytest
from settings import whole_seconds_at_least_one


def test_accepts_whole_seconds():
    assert whole_seconds_at_least_one("AGENT_RESULT_STREAM_TTL", 3600.0) == 3600


def test_truncates_fractional_seconds_above_one():
    assert whole_seconds_at_least_one("AGENT_RESULT_STREAM_TTL", 1.5) == 1


@pytest.mark.parametrize("seconds", [None, 0.0, 0.5, -1.0])
def test_rejects_none_and_sub_second_values(seconds):
    with pytest.raises(ValueError, match="AGENT_RESULT_STREAM_TTL"):
        whole_seconds_at_least_one("AGENT_RESULT_STREAM_TTL", seconds)
