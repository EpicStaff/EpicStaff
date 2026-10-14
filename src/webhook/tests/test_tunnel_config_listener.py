"""Tests for `listen_redis`, the consumer of the tunnel-config channel Django publishes to."""

import json

from src.shared.models import LocalhostConfigData

from app.core.settings import settings
from app.main import listen_redis


class _FakePubSub:
    """Stand-in for the channel subscription: yields the given messages, then ends."""

    def __init__(self, messages):
        self._messages = messages

    async def listen(self):
        for message in self._messages:
            yield message


def _config_message(*configs: LocalhostConfigData) -> dict:
    payload = {"localhost_configs": [config.model_dump(mode="json") for config in configs]}
    return {"type": "message", "data": json.dumps(payload)}


async def _listen(redis_service, tunnel_registry, messages):
    async def subscribe(channel):
        assert channel == settings.REDIS_TUNNEL_CONFIG_CHANNEL
        return _FakePubSub(messages)

    redis_service.async_subscribe = subscribe
    await listen_redis(redis_service, tunnel_registry)


async def _published_tunnel_ids(redis_service) -> set[str]:
    return set(await redis_service.client.hgetall(settings.TUNNEL_URLS_HASH_KEY))


async def test_config_message_registers_its_tunnels(redis_service, tunnel_registry):
    config = LocalhostConfigData(name="hook", org_id=1)

    await _listen(redis_service, tunnel_registry, [_config_message(config)])

    assert await _published_tunnel_ids(redis_service) == {config.unique_id}


async def test_non_message_events_and_malformed_payloads_are_skipped(
    redis_service, tunnel_registry
):
    config = LocalhostConfigData(name="hook", org_id=1)
    messages = [
        {"type": "subscribe", "data": 1},
        {"type": "message", "data": "not-json"},
        {"type": "message", "data": json.dumps({"localhost_configs": [{"org_id": 1}]})},
        _config_message(config),
    ]

    await _listen(redis_service, tunnel_registry, messages)

    # A bad message neither stops the listener nor registers anything itself.
    assert await _published_tunnel_ids(redis_service) == {config.unique_id}
