"""
RetryPolicy: exponential backoff with jitter for transient LiteLLM errors,
or the provider's Retry-After when the error carries one.

Retryable exceptions are resolved at import time so a missing class in the
installed LiteLLM version degrades to ``litellm.APIError`` with a warning
rather than crashing on import.
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable
from typing import TypeVar

import litellm
from litellm.exceptions import APIError as LiteLLMAPIError
from litellm.utils import _get_retry_after_from_exception_header
from loguru import logger

T = TypeVar("T")

_RETRYABLE_NAMES = (
    "RateLimitError",
    "APIConnectionError",
    "Timeout",
    "InternalServerError",
    "ServiceUnavailableError",
)

_NON_RETRYABLE_NAMES = (
    "AuthenticationError",
    "BadRequestError",
    "ContextWindowExceededError",
    "ContentPolicyViolationError",
    "NotFoundError",
)


def _resolve_exception_classes(
    names: tuple[str, ...],
) -> tuple[type[BaseException], ...]:
    resolved = []

    for name in names:
        cls = getattr(litellm, name, None)

        if cls is None:
            logger.warning(
                "litellm.{} not found in installed version; falling back to litellm.APIError",
                name,
            )
            cls = LiteLLMAPIError

        resolved.append(cls)

    return tuple(resolved)


RETRYABLE: tuple[type[BaseException], ...] = _resolve_exception_classes(_RETRYABLE_NAMES)
NON_RETRYABLE: tuple[type[BaseException], ...] = _resolve_exception_classes(_NON_RETRYABLE_NAMES)


def _retry_after_seconds(error: BaseException) -> int | None:
    # Same header lookup order as litellm's Router.
    headers = getattr(error, "litellm_response_headers", None) or getattr(
        getattr(error, "response", None), "headers", None
    )

    if headers is None:
        return None

    retry_after = _get_retry_after_from_exception_header(headers)
    return retry_after if retry_after and retry_after > 0 else None


class RetryPolicy:
    """Exponential backoff with jitter over a fixed retryable exception list.

    ``max_retries=0`` makes ``aretry`` a single pass — any exception re-raises.
    """

    def __init__(
        self,
        max_retries: int = 5,
        base_delay: float = 1.0,
        max_delay: float = 30.0,
        jitter: float = 0.5,
    ) -> None:
        self._max_retries = max_retries
        self._base_delay = base_delay
        self._max_delay = max_delay
        self._jitter = jitter

    @property
    def max_retries(self) -> int:
        return self._max_retries

    @property
    def base_delay(self) -> float:
        return self._base_delay

    @property
    def max_delay(self) -> float:
        return self._max_delay

    @property
    def jitter(self) -> float:
        return self._jitter

    def with_max_retries(self, max_retries: int) -> RetryPolicy:
        """Return a copy with a different ``max_retries``; other fields unchanged."""
        return RetryPolicy(
            max_retries=max_retries,
            base_delay=self._base_delay,
            max_delay=self._max_delay,
            jitter=self._jitter,
        )

    async def aretry(self, func: Callable[..., Awaitable[T]], *args, **kwargs) -> T:
        """Call ``await func(*args, **kwargs)``, retrying on retryable exceptions.

        Waits the error's Retry-After when present, else the exponential
        backoff; both capped at ``max_delay``.  Non-retryable exceptions
        re-raise immediately.  Last attempt re-raises whatever the final
        exception was.
        """
        for attempt in range(self._max_retries + 1):
            try:
                return await func(*args, **kwargs)

            except NON_RETRYABLE:
                raise

            except RETRYABLE as error:
                if attempt == self._max_retries:
                    raise

                delay = _retry_after_seconds(error)

                if delay is None:
                    delay = self._base_delay * (2**attempt) + random.uniform(0, self._jitter)

                await asyncio.sleep(min(delay, self._max_delay))

            except Exception:
                raise

        raise AssertionError("unreachable: retry loop must return or raise")
