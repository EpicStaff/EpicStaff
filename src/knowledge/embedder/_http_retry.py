import time
from typing import Callable, Iterable, Tuple, Type

import httpx


def request_with_retry(
    request_fn: Callable[[], httpx.Response],
    *,
    max_attempts: int,
    retryable_statuses: Iterable[int],
    transient_exceptions: Tuple[Type[Exception], ...] = (),
    initial_delay: float = 0.5,
    max_delay: float = 8.0,
) -> httpx.Response:
    """Run `request_fn` with exponential-backoff retries on transient failures.

    Retries when `request_fn` raises one of `transient_exceptions`, or when it
    returns a response whose status code is in `retryable_statuses`. The last
    attempt's result is always returned/raised as-is (callers are expected to
    call `response.raise_for_status()` themselves), so a final attempt that
    still failed with a retryable status code surfaces via that call.

    Args:
        request_fn: Zero-arg callable that performs a single HTTP request.
        max_attempts: Total number of attempts (including the first), >= 1.
        retryable_statuses: HTTP status codes that should trigger a retry.
        transient_exceptions: Exception types that should trigger a retry.
        initial_delay: Base delay (seconds) for exponential backoff.
        max_delay: Upper bound (seconds) for the backoff delay.
    """
    retryable_statuses = set(retryable_statuses)

    for attempt in range(max_attempts):
        is_last_attempt = attempt == max_attempts - 1
        try:
            response = request_fn()
        except transient_exceptions:
            if is_last_attempt:
                raise
        else:
            if response.status_code not in retryable_statuses or is_last_attempt:
                return response

        delay = min(initial_delay * (2**attempt), max_delay)
        time.sleep(delay)

    raise AssertionError("unreachable: max_attempts must be >= 1")
