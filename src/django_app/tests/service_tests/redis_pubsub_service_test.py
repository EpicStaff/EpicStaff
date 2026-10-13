import fakeredis
import pytest

from tables.services.session_token_usage import (
    MessageTokenUsage,
    SessionTokenUsageCounter,
    sum_token_usage,
)

# None of these tests touch the database themselves, but tests/conftest.py has an
# autouse `heal_builtin_roles` fixture that queries the Role table before every
# db test. Without a test that pulls in the `db` fixture, pytest-django never
# swaps the connection to the test database, so that query (and any future one
# added here) would hit the real dev database instead.
pytestmark = pytest.mark.django_db


def _with_token_usage(token_usage: dict) -> dict:
    return {"message_type": "agent", "token_usage": token_usage}


def test_sum_token_usage_sums_cached_prompt_tokens():
    total_usage = sum_token_usage(
        [
            _with_token_usage(
                {
                    "total_tokens": 100,
                    "prompt_tokens": 60,
                    "completion_tokens": 40,
                    "successful_requests": 1,
                    "cached_prompt_tokens": 20,
                    "total_cost_usd": 0.0012,
                }
            ),
            _with_token_usage(
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
    )

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


def test_sum_token_usage_defaults_missing_fields_to_zero():
    old_format_message = _with_token_usage(
        {
            "total_tokens": 100,
            "prompt_tokens": 60,
            "completion_tokens": 40,
            "successful_requests": 1,
        }
    )

    total_usage = sum_token_usage([old_format_message])

    assert total_usage["cached_prompt_tokens"] == 0
    assert total_usage["total_tokens"] == 100
    assert total_usage["total_cost_usd"] == 0


def test_sum_token_usage_reads_output_token_usage_and_skips_messages_without_any():
    total_usage = sum_token_usage(
        [
            {"message_type": "finish", "output": {"token_usage": {"total_tokens": 7}}},
            {"message_type": "finish", "output": "plain text"},
            {},
            None,
        ]
    )

    assert total_usage["total_tokens"] == 7


def _message_usage(session_id, message_uuid, total_tokens, total_cost_usd=0.0):
    return MessageTokenUsage(
        session_id=session_id,
        message_uuid=message_uuid,
        token_usage=sum_token_usage(
            [_with_token_usage({"total_tokens": total_tokens, "total_cost_usd": total_cost_usd})]
        ),
    )


def test_counter_adds_per_session_and_reads_back_the_totals():
    redis_client = fakeredis.FakeRedis(decode_responses=True)
    counter = SessionTokenUsageCounter(redis_client)

    counter.add_once([_message_usage(1, "a", 100, 0.0015)])
    counter.add_once([_message_usage(1, "b", 50, 0.0005), _message_usage(2, "c", 50)])

    assert counter.read(1) == pytest.approx(
        {
            "total_tokens": 150,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "successful_requests": 0,
            "cached_prompt_tokens": 0,
            "total_cost_usd": 0.002,
        }
    )
    assert counter.read(2)["total_tokens"] == 50
    assert counter.read(3)["total_tokens"] == 0


def test_counter_adds_a_message_once_however_often_it_is_offered():
    counter = SessionTokenUsageCounter(fakeredis.FakeRedis(decode_responses=True))

    counter.add_once([_message_usage(1, "a", 100), _message_usage(1, "a", 100)])
    counter.add_once([_message_usage(1, "a", 100), _message_usage(1, "b", 7)])

    assert counter.read(1)["total_tokens"] == 107


def test_counter_does_not_count_a_message_a_concurrent_caller_counted_meanwhile(monkeypatch):
    server = fakeredis.FakeServer()
    counter = SessionTokenUsageCounter(fakeredis.FakeRedis(server=server, decode_responses=True))
    concurrent_counter = SessionTokenUsageCounter(
        fakeredis.FakeRedis(server=server, decode_responses=True)
    )
    message_usage = _message_usage(1, "a", 100)
    find_uncounted = SessionTokenUsageCounter._uncounted
    calls = []

    def concurrent_caller_counts_first(pipeline, message_usages):
        uncounted = find_uncounted(pipeline, message_usages)
        calls.append(len(uncounted))
        if len(calls) == 1:
            # Between this caller's check and its write, another one counts the message.
            concurrent_counter.add_once([message_usage])
        return uncounted

    monkeypatch.setattr(
        SessionTokenUsageCounter, "_uncounted", staticmethod(concurrent_caller_counts_first)
    )

    counter.add_once([message_usage])

    assert counter.read(1)["total_tokens"] == 100
    # This caller's first check, the concurrent caller's, then this caller's retry.
    assert calls == [1, 1, 0]
