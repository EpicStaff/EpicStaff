"""RetryPolicy: exponential backoff for transient LiteLLM errors.

asyncio.sleep is replaced to record the backoff instead of waiting.
"""

from __future__ import annotations

import asyncio

import httpx
import litellm
import pytest
from app.llm.retry import RetryPolicy


def _litellm_error(exception_type: type[Exception]) -> Exception:
    try:
        return exception_type("transient", llm_provider="openai", model="gpt-4o")
    except TypeError:
        return exception_type("transient")


def failing(exception_type: type[Exception], times: int):
    """An LLM call that raises `exception_type` `times` times, then returns "ok"."""
    calls = [0]

    async def call():
        calls[0] += 1
        if calls[0] <= times:
            raise _litellm_error(exception_type)
        return "ok"

    return call


@pytest.fixture
def slept(monkeypatch) -> list[float]:
    delays: list[float] = []

    async def fake_sleep(delay):
        delays.append(delay)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    return delays


ALWAYS = 99


@pytest.mark.parametrize(
    ("error", "failures", "max_retries", "expected_sleeps", "raises"),
    [
        pytest.param(litellm.RateLimitError, 0, 3, 0, False, id="success-first-try"),
        pytest.param(litellm.APIConnectionError, 2, 4, 2, False, id="succeeds-after-retries"),
        pytest.param(litellm.RateLimitError, ALWAYS, 3, 3, True, id="gives-up-after-max-retries"),
        pytest.param(litellm.RateLimitError, ALWAYS, 0, 0, True, id="no-retries-configured"),
        pytest.param(litellm.RateLimitError, 0, 0, 0, False, id="no-retries-success"),
        *[
            pytest.param(error, ALWAYS, 1, 1, True, id=f"retryable-{error.__name__}")
            for error in (
                litellm.RateLimitError, litellm.APIConnectionError, litellm.Timeout,
                litellm.InternalServerError, litellm.ServiceUnavailableError,
            )
        ],
        *[
            pytest.param(error, 1, 3, 0, True, id=f"not-retryable-{error.__name__}")
            for error in (litellm.AuthenticationError, litellm.BadRequestError, litellm.ContextWindowExceededError)
        ],
    ],
)
async def test_which_errors_are_retried_and_how_often(slept, error, failures, max_retries, expected_sleeps, raises):
    policy = RetryPolicy(max_retries=max_retries, base_delay=1.0, max_delay=30.0, jitter=0.0)

    if raises:
        with pytest.raises(error):
            await policy.aretry(failing(error, failures))
    else:
        assert await policy.aretry(failing(error, failures)) == "ok"

    assert len(slept) == expected_sleeps


@pytest.mark.parametrize(
    ("base_delay", "max_delay", "expected"),
    [(1.0, 30.0, [1.0, 2.0, 4.0, 8.0, 16.0]), (10.0, 15.0, [10.0, 15.0, 15.0, 15.0, 15.0])],
    ids=["doubles", "capped"],
)
async def test_backoff_doubles_up_to_the_cap(slept, base_delay, max_delay, expected):
    policy = RetryPolicy(max_retries=5, base_delay=base_delay, max_delay=max_delay, jitter=0.0)

    with pytest.raises(litellm.RateLimitError):
        await policy.aretry(failing(litellm.RateLimitError, ALWAYS))

    assert slept == pytest.approx(expected)


@pytest.mark.parametrize(
    ("retry_after", "expected"),
    [("7", [7]), ("120", [30.0]), ("soon", [1.0]), (None, [1.0])],
    ids=["header-used", "header-capped", "unparseable-falls-back", "no-header"],
)
async def test_retry_after_header_overrides_backoff(slept, retry_after, expected):
    error = litellm.RateLimitError("throttled", llm_provider="openai", model="gpt-4o")
    error.litellm_response_headers = httpx.Headers({"retry-after": retry_after} if retry_after else {})
    calls = [0]

    async def call():
        calls[0] += 1
        if calls[0] == 1:
            raise error
        return "ok"

    policy = RetryPolicy(max_retries=1, base_delay=1.0, max_delay=30.0, jitter=0.0)

    assert await policy.aretry(call) == "ok"
    assert slept == pytest.approx(expected)
