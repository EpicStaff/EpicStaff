"""
Unit tests for RetryPolicy.

asyncio.sleep is monkeypatched to avoid real delays; recorded calls verify
that backoff grows correctly.
"""

from __future__ import annotations

import asyncio

import litellm
import pytest

from app.llm.retry import RetryPolicy


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_litellm_exception(exception_type: type[Exception]) -> Exception:
    """Instantiate a LiteLLM exception with required positional args."""
    try:
        return exception_type("transient", llm_provider="openai", model="gpt-4o")
    except TypeError:
        return exception_type("transient")


def make_raiser(exception_type: type[Exception], times: int):
    """Return an async function that raises ``exception_type`` for the first
    ``times`` calls, then returns ``"ok"``."""
    call_count = [0]

    async def func():
        call_count[0] += 1
        if call_count[0] <= times:
            raise _make_litellm_exception(exception_type)
        return "ok"

    return func


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_success_on_first_call_no_sleep(monkeypatch):
    """Successful call never sleeps."""
    slept = []
    monkeypatch.setattr(
        asyncio, "sleep", lambda d: slept.append(d) or asyncio.coroutine(lambda: None)()
    )

    async def succeed():
        return "ok"

    result = await RetryPolicy().aretry(succeed)
    assert result == "ok"
    assert slept == []


async def test_retries_rate_limit_error_up_to_max_retries(monkeypatch):
    """RateLimitError retried up to max_retries; final attempt raises."""
    slept = []

    async def fake_sleep(delay):
        slept.append(delay)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    policy = RetryPolicy(max_retries=3, base_delay=1.0, max_delay=30.0, jitter=0.0)
    raiser = make_raiser(litellm.RateLimitError, 99)

    with pytest.raises(litellm.RateLimitError):
        await policy.aretry(raiser)

    assert len(slept) == 3


async def test_backoff_grows_exponentially(monkeypatch):
    """Delay doubles each attempt: 1, 2, 4, ..."""
    slept = []

    async def fake_sleep(delay):
        slept.append(delay)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    policy = RetryPolicy(max_retries=4, base_delay=1.0, max_delay=30.0, jitter=0.0)
    raiser = make_raiser(litellm.RateLimitError, 99)

    with pytest.raises(litellm.RateLimitError):
        await policy.aretry(raiser)

    assert slept[0] == pytest.approx(1.0)
    assert slept[1] == pytest.approx(2.0)
    assert slept[2] == pytest.approx(4.0)
    assert slept[3] == pytest.approx(8.0)


async def test_backoff_capped_at_max_delay(monkeypatch):
    """Delay never exceeds max_delay."""
    slept = []

    async def fake_sleep(delay):
        slept.append(delay)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    policy = RetryPolicy(max_retries=5, base_delay=10.0, max_delay=15.0, jitter=0.0)
    raiser = make_raiser(litellm.RateLimitError, 99)

    with pytest.raises(litellm.RateLimitError):
        await policy.aretry(raiser)

    assert all(d <= 15.0 for d in slept)


async def test_does_not_retry_authentication_error(monkeypatch):
    """AuthenticationError raises immediately without sleep."""
    slept = []

    async def fake_sleep(delay):
        slept.append(delay)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    raiser = make_raiser(litellm.AuthenticationError, 1)

    with pytest.raises(litellm.AuthenticationError):
        await RetryPolicy(max_retries=3).aretry(raiser)

    assert slept == []


async def test_does_not_retry_bad_request_error(monkeypatch):
    """BadRequestError raises immediately without sleep."""
    slept = []

    async def fake_sleep(delay):
        slept.append(delay)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    raiser = make_raiser(litellm.BadRequestError, 1)

    with pytest.raises(litellm.BadRequestError):
        await RetryPolicy(max_retries=3).aretry(raiser)

    assert slept == []


async def test_does_not_retry_context_window_exceeded(monkeypatch):
    """ContextWindowExceededError raises immediately without sleep."""
    slept = []

    async def fake_sleep(delay):
        slept.append(delay)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    raiser = make_raiser(litellm.ContextWindowExceededError, 1)

    with pytest.raises(litellm.ContextWindowExceededError):
        await RetryPolicy(max_retries=3).aretry(raiser)

    assert slept == []


async def test_max_retries_zero_no_retry(monkeypatch):
    """max_retries=0 makes a single attempt with no sleep on failure."""
    slept = []

    async def fake_sleep(delay):
        slept.append(delay)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    policy = RetryPolicy(max_retries=0)
    raiser = make_raiser(litellm.RateLimitError, 1)

    with pytest.raises(litellm.RateLimitError):
        await policy.aretry(raiser)

    assert slept == []


async def test_max_retries_zero_succeeds(monkeypatch):
    """max_retries=0 returns the value when the single call succeeds."""
    slept = []
    monkeypatch.setattr(
        asyncio, "sleep", lambda d: slept.append(d) or asyncio.coroutine(lambda: None)()
    )

    policy = RetryPolicy(max_retries=0)

    async def succeed():
        return "done"

    result = await policy.aretry(succeed)
    assert result == "done"
    assert slept == []


async def test_with_max_retries_returns_copy():
    """with_max_retries returns a new instance; original unchanged."""
    original = RetryPolicy(max_retries=3, base_delay=2.0)
    copy = original.with_max_retries(7)

    assert copy.max_retries == 7
    assert original.max_retries == 3
    assert copy.base_delay == original.base_delay
    assert copy is not original


async def test_retries_succeed_on_nth_attempt(monkeypatch):
    """Raises N-1 times then succeeds; result is returned."""
    slept = []

    async def fake_sleep(delay):
        slept.append(delay)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    policy = RetryPolicy(max_retries=4, base_delay=1.0, max_delay=30.0, jitter=0.0)
    raiser = make_raiser(litellm.APIConnectionError, 2)

    result = await policy.aretry(raiser)
    assert result == "ok"
    assert len(slept) == 2


async def test_retries_all_retryable_types(monkeypatch):
    """All five retryable types trigger the retry path."""
    from app.llm.retry import RETRYABLE

    for exc_type in RETRYABLE:
        slept = []

        async def fake_sleep(delay):
            slept.append(delay)

        monkeypatch.setattr(asyncio, "sleep", fake_sleep)

        policy = RetryPolicy(max_retries=1, base_delay=1.0, max_delay=30.0, jitter=0.0)
        raiser = make_raiser(exc_type, 99)

        with pytest.raises(exc_type):
            await policy.aretry(raiser)

        assert len(slept) == 1, f"Expected 1 sleep for {exc_type}, got {len(slept)}"
