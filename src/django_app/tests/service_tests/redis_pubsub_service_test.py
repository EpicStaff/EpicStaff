import json

import pytest

from tables.models import GraphSessionMessage
from tables.services.redis_pubsub import RedisPubSub


class _StubRedisClient:
    def __init__(self, keyed_payloads: dict[str, dict]):
        self._keyed_payloads = keyed_payloads

    def keys(self, pattern):
        return list(self._keyed_payloads.keys())

    def get(self, key):
        return json.dumps(self._keyed_payloads[key])


def _message_with_token_usage(token_usage: dict) -> GraphSessionMessage:
    return GraphSessionMessage(message_data={"token_usage": token_usage})


def test_calculate_subgraph_token_usage_sums_cached_prompt_tokens():
    messages = [
        _message_with_token_usage(
            {
                "total_tokens": 100,
                "prompt_tokens": 60,
                "completion_tokens": 40,
                "successful_requests": 1,
                "cached_prompt_tokens": 20,
                "total_cost_usd": 0.0012,
            }
        ),
        _message_with_token_usage(
            {
                "total_tokens": 50,
                "prompt_tokens": 30,
                "completion_tokens": 20,
                "successful_requests": 1,
                "cached_prompt_tokens": 10,
                "total_cost_usd": 0.0008,
            }
        ),
    ]

    total_usage = RedisPubSub._calculate_subgraph_token_usage(messages)

    assert total_usage == pytest.approx(
        {
            "total_tokens": 150,
            "prompt_tokens": 90,
            "completion_tokens": 60,
            "successful_requests": 2,
            "cached_prompt_tokens": 30,
            "total_cost_usd": 0.002,
        }
    )


def test_calculate_subgraph_token_usage_defaults_missing_cached_prompt_tokens_to_zero():
    old_format_message = _message_with_token_usage(
        {
            "total_tokens": 100,
            "prompt_tokens": 60,
            "completion_tokens": 40,
            "successful_requests": 1,
        }
    )

    total_usage = RedisPubSub._calculate_subgraph_token_usage([old_format_message])

    assert total_usage["cached_prompt_tokens"] == 0
    assert total_usage["total_tokens"] == 100
    assert total_usage["total_cost_usd"] == 0


def test_calculate_total_token_usage_skips_empty_message_data_without_aborting():
    session_id = "session-1"
    keyed_payloads = {
        f"graph:message:{session_id}:1": {
            "message_data": {
                "token_usage": {
                    "total_tokens": 100,
                    "prompt_tokens": 60,
                    "completion_tokens": 40,
                    "successful_requests": 1,
                    "cached_prompt_tokens": 20,
                    "total_cost_usd": 0.0015,
                }
            }
        },
        f"graph:message:{session_id}:2": {"message_data": {}},
        f"graph:message:{session_id}:3": {
            "message_data": {
                "token_usage": {
                    "total_tokens": 50,
                    "prompt_tokens": 30,
                    "completion_tokens": 20,
                    "successful_requests": 1,
                    "cached_prompt_tokens": 10,
                    "total_cost_usd": 0.0005,
                }
            }
        },
    }

    redis_pubsub = RedisPubSub()
    redis_pubsub.redis_client = _StubRedisClient(keyed_payloads)

    total_usage = redis_pubsub._calculate_total_token_usage(session_id)

    assert total_usage == pytest.approx(
        {
            "total_tokens": 150,
            "prompt_tokens": 90,
            "completion_tokens": 60,
            "successful_requests": 2,
            "cached_prompt_tokens": 30,
            "total_cost_usd": 0.002,
        }
    )


def test_calculate_total_token_usage_defaults_missing_total_cost_usd_to_zero():
    session_id = "session-2"
    keyed_payloads = {
        f"graph:message:{session_id}:1": {
            "message_data": {
                "token_usage": {
                    "total_tokens": 100,
                    "prompt_tokens": 60,
                    "completion_tokens": 40,
                    "successful_requests": 1,
                    "cached_prompt_tokens": 20,
                }
            }
        },
    }

    redis_pubsub = RedisPubSub()
    redis_pubsub.redis_client = _StubRedisClient(keyed_payloads)

    total_usage = redis_pubsub._calculate_total_token_usage(session_id)

    assert total_usage["total_cost_usd"] == 0
    assert total_usage["total_tokens"] == 100
