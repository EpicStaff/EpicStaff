"""
RetryPolicy: exponential backoff with jitter for transient LiteLLM errors.

Retryable exceptions are resolved at import time so a missing class in the
installed LiteLLM version degrades to ``litellm.APIError`` with a warning
rather than crashing on import.
"""

from __future__ import annotations

import asyncio
import random
from typing import Awaitable, Callable, TypeVar

import litellm
from litellm.exceptions import APIError as LiteLLMAPIError
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


RETRYABLE: tuple[type[BaseException], ...] = _resolve_exception_classes(
    _RETRYABLE_NAMES
)
NON_RETRYABLE: tuple[type[BaseException], ...] = _resolve_exception_classes(
    _NON_RETRYABLE_NAMES
)


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

        Non-retryable exceptions re-raise immediately.  Last attempt re-raises
        whatever the final exception was.
        """
        for attempt in range(self._max_retries + 1):
            try:
                return await func(*args, **kwargs)

            except NON_RETRYABLE as error:
                raise error

            except RETRYABLE as error:
                if attempt == self._max_retries:
                    raise error

                delay = min(
                    self._base_delay * (2**attempt) + random.uniform(0, self._jitter),
                    self._max_delay,
                )
                await asyncio.sleep(delay)

            except Exception as error:
                raise error

        raise AssertionError("unreachable: retry loop must return or raise")
