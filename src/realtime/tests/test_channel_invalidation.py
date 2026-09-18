"""Coverage for the `realtime_channels:invalidate` cross-process cache
invalidation contract (`api/main.py::_handle_channel_invalidation_message`,
`_channel_cache`, `get_channel_config`).

Without this, Django flipping `RealtimeChannel.is_active` off (or deleting
the channel) would keep being served from `_channel_cache` for up to
`_CHANNEL_TTL` (60s), since nothing evicted the stale entry early.
"""

import json

import httpx
import pytest


TOKEN = "chan-tok-under-test"


@pytest.mark.asyncio
async def test_invalidation_message_evicts_only_the_targeted_cache_entry():
    from api.main import _channel_cache, _handle_channel_invalidation_message

    _channel_cache[TOKEN] = ({"realtime_agent": 1}, 12345.0)
    _channel_cache["other-token"] = ({"realtime_agent": 2}, 12345.0)

    _handle_channel_invalidation_message(json.dumps({"token": TOKEN}))

    assert TOKEN not in _channel_cache
    assert "other-token" in _channel_cache


@pytest.mark.asyncio
async def test_evicted_entry_is_refetched_from_django_not_served_stale(monkeypatch):
    """After eviction, `get_channel_config()` must hit Django again rather
    than silently reusing whatever was in the dict a moment ago."""
    from api.main import _channel_cache, _handle_channel_invalidation_message
    import api.main as main

    stale_payload = {"realtime_agent": 1, "stale": True}
    fresh_payload = {"realtime_agent": 1, "stale": False}
    _channel_cache[TOKEN] = (stale_payload, main.asyncio.get_event_loop().time())

    _handle_channel_invalidation_message(json.dumps({"token": TOKEN}))
    assert TOKEN not in _channel_cache

    class _FakeResponse:
        is_success = True
        status_code = 200

        def json(self):
            return fresh_payload

        @property
        def text(self):
            return json.dumps(fresh_payload)

    class _FakeAsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, *args, **kwargs):
            return _FakeResponse()

    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **kw: _FakeAsyncClient())

    result = await main.get_channel_config(TOKEN)

    assert result == fresh_payload
    assert _channel_cache[TOKEN][0] == fresh_payload


@pytest.mark.asyncio
async def test_invalidation_message_with_malformed_payload_does_not_raise():
    from api.main import _handle_channel_invalidation_message

    # Must not propagate — this runs inside the long-lived listener loop.
    _handle_channel_invalidation_message("not-json")
