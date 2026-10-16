"""
ConcurrencyLimiter: caps in-flight LLM calls per deployment config.

``max_rpm`` is applied as a concurrency cap: at most ``max_rpm`` calls run at
once for the same (model, api_key, base_url, api_version, max_rpm). This is the
behaviour litellm's Router gave it (one ``asyncio.Semaphore(rpm)`` per
deployment); it is not a per-minute rate limit.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from contextlib import AbstractAsyncContextManager, nullcontext


class ConcurrencyLimiter:
    """Process-wide registry of one semaphore per deployment config.

    Entries are never evicted; a semaphore is a few hundred bytes and the
    number of distinct configs a worker sees is small.
    """

    def __init__(self) -> None:
        self._semaphores: dict[str, asyncio.Semaphore] = {}

    def slot(self, model_config: dict, max_concurrent: int | None) -> AbstractAsyncContextManager:
        """Return an async context manager that holds one call slot for this config.

        ``max_concurrent`` None or 0 means no cap.
        """
        if not max_concurrent:
            return nullcontext()

        key = self._key(model_config, max_concurrent)
        # No await between lookup and insert, so concurrent first calls cannot build two.
        semaphore = self._semaphores.get(key)

        if semaphore is None:
            semaphore = self._semaphores[key] = asyncio.Semaphore(max_concurrent)

        return semaphore

    @staticmethod
    def _key(model_config: dict, max_concurrent: int) -> str:
        payload = {
            "model": model_config.get("model"),
            "api_key": model_config.get("api_key"),
            "base_url": model_config.get("base_url"),
            "api_version": model_config.get("api_version"),
            "rpm": max_concurrent,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


_LIMITER = ConcurrencyLimiter()


def get_concurrency_limiter() -> ConcurrencyLimiter:
    """Return the process-wide ``ConcurrencyLimiter``."""
    return _LIMITER
