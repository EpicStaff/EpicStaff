from tables.models import GraphSessionMessage
from tables.services.redis_pubsub import RedisPubSub


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
            }
        ),
        _message_with_token_usage(
            {
                "total_tokens": 50,
                "prompt_tokens": 30,
                "completion_tokens": 20,
                "successful_requests": 1,
                "cached_prompt_tokens": 10,
            }
        ),
    ]

    total_usage = RedisPubSub._calculate_subgraph_token_usage(messages)

    assert total_usage == {
        "total_tokens": 150,
        "prompt_tokens": 90,
        "completion_tokens": 60,
        "successful_requests": 2,
        "cached_prompt_tokens": 30,
    }


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
