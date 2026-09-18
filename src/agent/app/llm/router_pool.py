"""
RouterPool: process-singleton pool of ``litellm.Router`` instances.

Each unique (model, api_key, base_url, api_version, rpm) combination gets its
own Router so LiteLLM's in-memory rpm counter accumulates correctly across
calls sharing the same deployment config. Each Router holds a single deployment,
so cooldowns are disabled — they provide no fallback benefit and would turn
transient failures into a ~60 s "no deployments available" outage.
"""

from __future__ import annotations

import asyncio
import hashlib
import json

from litellm.router import Router


class RouterPool:
    """Lazy-building pool of ``litellm.Router`` instances keyed by config hash.

    Thread-safe via ``asyncio.Lock``; double-checked locking avoids acquiring
    the lock on every call once a Router is cached.
    """

    def __init__(self) -> None:
        self._routers: dict[str, Router] = {}
        self._lock: asyncio.Lock = asyncio.Lock()

    def _key(self, model: str, model_config: dict, rpm: int | None) -> str:
        payload = {
            "model": model,
            "api_key": model_config.get("api_key"),
            "base_url": model_config.get("base_url"),
            "api_version": model_config.get("api_version"),
            "rpm": rpm,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

    async def get(self, model: str, model_config: dict, rpm: int | None) -> Router:
        """Return a cached Router for this config, constructing one if needed."""
        key = self._key(model, model_config, rpm)

        if key in self._routers:
            return self._routers[key]

        async with self._lock:
            if key in self._routers:
                return self._routers[key]

            litellm_params: dict = {
                "model": model,
                **{
                    k: model_config[k]
                    for k in ("api_key", "base_url", "api_version")
                    if k in model_config
                },
            }

            if rpm is not None:
                litellm_params["rpm"] = rpm

            deployment = {
                "model_name": key[:12],
                "litellm_params": litellm_params,
            }

            # Single deployment per router — cooldowns give no fallback benefit and
            # turn transient failures into a ~60 s "no deployments available" outage.
            router = Router(model_list=[deployment], disable_cooldowns=True)
            self._routers[key] = router

        return router


_POOL: RouterPool | None = None


def get_router_pool() -> RouterPool:
    """Return the process-singleton ``RouterPool``, constructing it on first call."""
    global _POOL

    if _POOL is None:
        _POOL = RouterPool()

    return _POOL
