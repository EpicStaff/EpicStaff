"""Tests for `listen_redis`, the tunnel-config channel consumer in `app.main`.

The original version of this file hand-published a message to a real Redis
instance and asserted nothing -- it exercised no webhook code and could only
ever fail on connection/auth. This replaces it with tests of the actual
consumer: `listen_redis` reads messages off the pubsub, parses them into
`WebhookConfigData`, and forwards them to `TunnelRegistry.register_many`.
"""

import json

from unittest.mock import AsyncMock

from app.main import listen_redis
from src.shared.models import WebhookConfigData


class _FakePubSub:
    """Minimal stand-in for `redis.client.PubSub`: yields pre-built messages
    from `.listen()`, then stops (mirroring an async generator exhausting)."""

    def __init__(self, messages):
        self._messages = messages

    async def listen(self):
        for message in self._messages:
            yield message


async def test_listen_redis_parses_config_and_registers_tunnels():
    payload = {
        "ngrok_configs": [
            {"name": "test", "org_id": 1, "auth_token": "token", "region": "eu"}
        ]
    }
    message = {"type": "message", "data": json.dumps(payload)}

    redis_service = AsyncMock()
    redis_service.async_subscribe.return_value = _FakePubSub([message])

    tunnel_registry = AsyncMock()

    await listen_redis(redis_service, tunnel_registry)

    redis_service.async_subscribe.assert_awaited_once()
    tunnel_registry.register_many.assert_awaited_once()

    registered_config = tunnel_registry.register_many.call_args.kwargs[
        "webhook_config_data"
    ]
    assert registered_config == WebhookConfigData(**payload)


async def test_listen_redis_ignores_non_message_events():
    subscribe_confirmation = {"type": "subscribe", "data": 1}

    redis_service = AsyncMock()
    redis_service.async_subscribe.return_value = _FakePubSub([subscribe_confirmation])

    tunnel_registry = AsyncMock()

    await listen_redis(redis_service, tunnel_registry)

    tunnel_registry.register_many.assert_not_awaited()


async def test_listen_redis_swallows_malformed_payload_without_registering():
    malformed_message = {"type": "message", "data": "not-json"}

    redis_service = AsyncMock()
    redis_service.async_subscribe.return_value = _FakePubSub([malformed_message])

    tunnel_registry = AsyncMock()

    # Must not raise -- `listen_redis` logs and continues on bad messages.
    await listen_redis(redis_service, tunnel_registry)

    tunnel_registry.register_many.assert_not_awaited()
