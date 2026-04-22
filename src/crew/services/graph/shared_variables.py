
"""
Shared Variables Module for cross-session coordination.

Provides Redis-backed shared variables accessible via:
    variables.shared[access_key].variable_name

Features:
- Automatic scoping by access key
- Lazy load from Redis on first access
- Immediate write-through to Redis on updates
- Automatic session tracking and cleanup
- Observable wrappers for mutable types (list/dict)
- Synchronous API for user code (no await needed)
"""

import json
import asyncio
from typing import Any, Dict, Optional
from loguru import logger


class ObservableList(list):
    """List that triggers a callback on mutations for write-through to Redis."""

    def __init__(self, data, on_change_callback):
        super().__init__(data)
        self._on_change = on_change_callback

    def append(self, item):
        super().append(item)
        self._on_change()

    def extend(self, items):
        super().extend(items)
        self._on_change()

    def insert(self, index, item):
        super().insert(index, item)
        self._on_change()

    def remove(self, item):
        super().remove(item)
        self._on_change()

    def pop(self, index=-1):
        result = super().pop(index)
        self._on_change()
        return result

    def clear(self):
        super().clear()
        self._on_change()

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        self._on_change()

    def __delitem__(self, key):
        super().__delitem__(key)
        self._on_change()


class ObservableDict(dict):
    """Dict that triggers a callback on mutations for write-through to Redis."""

    def __init__(self, data, on_change_callback):
        super().__init__(data)
        self._on_change = on_change_callback

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        self._on_change()

    def __delitem__(self, key):
        super().__delitem__(key)
        self._on_change()

    def update(self, *args, **kwargs):
        super().update(*args, **kwargs)
        self._on_change()

    def pop(self, *args):
        result = super().pop(*args)
        self._on_change()
        return result

    def clear(self):
        super().clear()
        self._on_change()


def _json_serializer(obj):
    """Custom JSON serializer that handles ObservableList/ObservableDict and shared-variable proxies."""
    if isinstance(obj, ObservableList):
        return list(obj)
    if isinstance(obj, ObservableDict):
        return dict(obj)
    if isinstance(obj, SharedVariables):
        return {}
    if isinstance(obj, SharedVariableScope):
        return dict(obj._cache)
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def _run_async(coro):
    """Run an async coroutine from synchronous code.

    Handles the case where an event loop is already running
    (e.g. inside LangGraph async execution) by using a thread.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(asyncio.run, coro)
            return future.result(timeout=10)
    else:
        return asyncio.run(coro)


_DEFAULT_TTL = 3600  # 1 hour


class SharedVariableScope:
    """Proxy for variables.shared[access_key].

    Intercepts attribute access to lazily load from Redis and
    immediately write back on assignment.
    """

    def __init__(self, access_key: str, session_id: int, redis_service):
        object.__setattr__(self, "_access_key", str(access_key))
        object.__setattr__(self, "_session_id", str(session_id))
        object.__setattr__(self, "_redis_service", redis_service)
        object.__setattr__(self, "_cache", {})

    # --- helpers -----------------------------------------------------------

    def _var_key(self, name: str) -> str:
        return f"shared_var:{self._access_key}:{name}"

    def _redis(self):
        """Return the sync Redis client."""
        return self._redis_service.sync_redis_client

    async def _aredis(self):
        """Return the async Redis client."""
        return self._redis_service.aioredis_client

    def _wrap_mutable(self, name: str, value):
        """Wrap lists/dicts with observable proxies for auto-save."""
        if isinstance(value, list) and not isinstance(value, ObservableList):
            return ObservableList(value, lambda: self._save(name))
        if isinstance(value, dict) and not isinstance(value, ObservableDict):
            return ObservableDict(value, lambda: self._save(name))
        return value

    def _save(self, name: str):
        """Write-through: save cached value to Redis immediately (sync)."""
        var_id = self._var_key(name)
        value = self._cache.get(name)
        if value is not None:
            raw = json.dumps(value, default=_json_serializer)
            self._redis().set(f"{var_id}:data", raw, ex=_DEFAULT_TTL)

    def atomic_list_append(self, name: str, items: list) -> list:
        """Atomically append items to a shared list variable.
        Uses a Redis lock to serialize the read-modify-write cycle."""
        r = self._redis()
        key = f"{self._var_key(name)}:data"
        with r.lock(f"{key}:lock", timeout=5):
            raw = r.get(key)
            current = json.loads(raw) if raw else []
            current.extend(items)
            r.set(key, json.dumps(current, default=_json_serializer), ex=_DEFAULT_TTL)
        self._register_session_sync(self._var_key(name))
        self._cache[name] = self._wrap_mutable(name, current)
        return current

    def claim(self, name: str, value, ttl: int = None) -> bool:
        """Atomically claim a variable using Redis SET NX (first-writer-wins).
        Returns True if this call set the value, False if already set."""
        r = self._redis()
        key = f"{self._var_key(name)}:data"
        raw = json.dumps(value, default=_json_serializer)
        result = r.set(key, raw, nx=True, ex=ttl or _DEFAULT_TTL)
        if result:
            self._register_session_sync(self._var_key(name))
            self._cache[name] = self._wrap_mutable(name, value)
        return bool(result)

    def release(self, name: str) -> bool:
        """Delete a shared variable key (e.g. release a claim).
        Returns True if the key existed and was deleted."""
        r = self._redis()
        key = f"{self._var_key(name)}:data"
        result = r.delete(key)
        self._cache.pop(name, None)
        return bool(result)

    def _register_session_sync(self, var_id: str):
        """Register this session as using this variable (sync)."""
        r = self._redis()
        r.sadd(f"{var_id}:sessions", self._session_id)
        r.sadd(f"session:{self._session_id}:variables", var_id)
        r.set(f"session:{self._session_id}:status", "active", nx=True, ex=_DEFAULT_TTL)

    # --- explicit async API (used by set_output_variables) ------------------

    async def set(self, name: str, value: Any):
        """Async setter – writes value to Redis and updates cache."""
        value = self._wrap_mutable(name, value)
        var_id = self._var_key(name)
        raw = json.dumps(value, default=_json_serializer)
        r = self._redis_service.aioredis_client
        await r.set(f"{var_id}:data", raw, ex=_DEFAULT_TTL)
        await r.sadd(f"{var_id}:sessions", self._session_id)
        await r.sadd(f"session:{self._session_id}:variables", var_id)
        await r.set(f"session:{self._session_id}:status", "active", nx=True, ex=_DEFAULT_TTL)
        self._cache[name] = value

    async def get(self, name: str) -> Any:
        """Async getter – reads value from Redis (cache-aware)."""
        cache = object.__getattribute__(self, "_cache")
        if name in cache:
            return cache[name]

        var_id = self._var_key(name)
        r = self._redis_service.aioredis_client
        raw = await r.get(f"{var_id}:data")
        if raw is not None:
            value = json.loads(raw)
            value = self._wrap_mutable(name, value)
            await r.sadd(f"{var_id}:sessions", self._session_id)
            await r.sadd(f"session:{self._session_id}:variables", var_id)
            cache[name] = value
            return value
        return None

    # --- proxy interface ---------------------------------------------------

    # Methods that exist on the class itself and must not fall through to Redis
    _RESERVED = frozenset({"set", "get"})

    def __getattr__(self, name: str):
        if name.startswith("_"):
            return object.__getattribute__(self, name)

        # Never proxy our own explicit methods
        if name in SharedVariableScope._RESERVED:
            return object.__getattribute__(self, name)

        cache = object.__getattribute__(self, "_cache")
        if name in cache:
            return cache[name]

        # Load from Redis
        var_id = self._var_key(name)
        raw = self._redis().get(f"{var_id}:data")

        if raw is not None:
            value = json.loads(raw)
            value = self._wrap_mutable(name, value)
            self._register_session_sync(var_id)
            cache[name] = value
            return value

        return None

    def __setattr__(self, name: str, value):
        if name.startswith("_"):
            object.__setattr__(self, name, value)
            return

        value = self._wrap_mutable(name, value)
        var_id = self._var_key(name)
        raw = json.dumps(value, default=_json_serializer)
        self._redis().set(f"{var_id}:data", raw, ex=_DEFAULT_TTL)
        self._register_session_sync(var_id)
        self._cache[name] = value

    def _clear_cache(self):
        """Drop all cached values so next access re-reads from Redis."""
        object.__getattribute__(self, "_cache").clear()

    def model_dump(self) -> dict:
        """Return cached shared variables as a plain dict."""
        return dict(self._cache)

    def __repr__(self):
        return f"<SharedVariableScope access_key={self._access_key!r}>"

    def __deepcopy__(self, memo):
        return self

    def __copy__(self):
        return self


class SharedVariables:
    """Top-level proxy for variables.shared.

    Usage:
        shared = SharedVariables(session_id=123, redis_service=redis_svc)
        state["variables"]["shared"] = shared

        # In user code:
        variables.shared[chat_id].active_followers
    """

    def __init__(self, session_id: int, redis_service):
        self._session_id = session_id
        self._redis_service = redis_service
        self._scopes: Dict[str, SharedVariableScope] = {}

    def __getitem__(self, access_key: str) -> SharedVariableScope:
        key = str(access_key)
        if key not in self._scopes:
            self._scopes[key] = SharedVariableScope(
                access_key=key,
                session_id=self._session_id,
                redis_service=self._redis_service,
            )
        return self._scopes[key]

    def _clear_cache(self):
        """Drop cached values in all scopes so next access re-reads from Redis."""
        for scope in self._scopes.values():
            scope._clear_cache()

    def model_dump(self) -> dict:
        """Return all cached scopes as a plain dict of dicts."""
        return {k: v.model_dump() for k, v in self._scopes.items()}

    def __repr__(self):
        return f"<SharedVariables session_id={self._session_id}>"

    def __deepcopy__(self, memo):
        return self

    def __copy__(self):
        return self


async def cleanup_session(
    session_id: int,
    redis_service,
    status: str = "completed",
):
    """Clean up shared variables when a session ends.

    Steps:
    1. Mark session as completed/failed
    2. Get all variables this session used
    3. For each variable, check if any sessions are still active
    4. If no active sessions remain, delete the variable
    """
    r = redis_service.aioredis_client
    sid = str(session_id)

    try:
        # 1. Mark session status
        await r.set(f"session:{sid}:status", status, ex=_DEFAULT_TTL)

        # 2. Get variables this session used
        var_ids = await r.smembers(f"session:{sid}:variables")
        if not var_ids:
            return

        for var_id in var_ids:
            # 3. Get all sessions using this variable
            session_ids = await r.smembers(f"{var_id}:sessions")

            # 4. Check if any are still active
            active_count = 0
            for other_sid in session_ids:
                s = await r.get(f"session:{other_sid}:status")
                if s == "active":
                    active_count += 1

            # 5. If no active sessions, clean up session metadata only.
            # Variable data is NOT deleted here — it expires naturally via TTL.
            # Deleting eagerly caused a race where a later session (e.g. leader
            # at end-stage) still needs the data written by a now-finished session.
            if active_count == 0:
                await r.delete(f"{var_id}:sessions")
                for other_sid in session_ids:
                    await r.delete(f"session:{other_sid}:status")
                    await r.delete(f"session:{other_sid}:variables")

        # Clean up this session's metadata if not already done
        await r.delete(f"session:{sid}:variables")

    except Exception as e:
        logger.warning(f"Error cleaning up shared variables for session {session_id}: {e}")


# ---------------------------------------------------------------------------
# Monkey-patch json.JSONEncoder.default so that SharedVariables,
# SharedVariableScope, ObservableList, and ObservableDict are serializable
# by *any* json.dumps() call without requiring a custom `default=` argument.
# This keeps the fix self-contained in this module.
# ---------------------------------------------------------------------------
_original_json_default = json.JSONEncoder.default


def _patched_json_default(self, obj):
    if isinstance(obj, SharedVariables):
        return {}
    if isinstance(obj, SharedVariableScope):
        return {}
    if isinstance(obj, ObservableList):
        return list(obj)
    if isinstance(obj, ObservableDict):
        return dict(obj)
    return _original_json_default(self, obj)


json.JSONEncoder.default = _patched_json_default
