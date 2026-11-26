"""Tests for `TunnelConfigListener`, the consumer of the tunnel-config channel Django publishes to.

Redis is fakeredis on a shared `FakeServer`; flipping `server.connected` takes it down and
brings it back for every client at once, the way a Redis restart does.
"""

import asyncio
import json

import pytest
from fakeredis import FakeAsyncRedis, FakeServer
from loguru import logger
from redis.exceptions import ConnectionError as RedisConnectionError
from src.shared.models import (
    LocalhostConfigData,
    NgrokConfigData,
    WebhookConfigData,
    WebhookTriggerAuthData,
)

from app.core.settings import settings
from app.services import tunnel_config_listener as listener_module
from app.services.redis_service import RedisService
from app.services.tunnel_config_listener import TunnelConfigListener
from app.services.tunnel_registry import UnavailableWebhookPathError, UnregisteredWebhookPathError
from transport_secrets import seal, sealing_cryptographer

POLL_SECONDS = 0.02
# What `_secret_for` reports for the path of a config that failed to register.
UNAVAILABLE = "<unavailable>"
# Enough polls that the listener has certainly read from the dropped connection.
OUTAGE_SECONDS = 10 * POLL_SECONDS


@pytest.fixture(autouse=True)
def fast_listener_timing(monkeypatch):
    monkeypatch.setattr(listener_module, "INITIAL_RECONNECT_DELAY_SECONDS", 0.01)
    monkeypatch.setattr(listener_module, "MAX_RECONNECT_DELAY_SECONDS", 0.05)
    monkeypatch.setattr(listener_module, "INITIAL_SYNC_REQUEST_RETRY_SECONDS", 0.01)
    monkeypatch.setattr(listener_module, "MAX_SYNC_REQUEST_RETRY_SECONDS", 0.05)
    monkeypatch.setattr(listener_module, "MESSAGE_POLL_SECONDS", POLL_SECONDS)


@pytest.fixture
def fake_server():
    return FakeServer()


def _stop_redis(server: FakeServer) -> None:
    """Take Redis down the way a restart without persistence does: every client is cut off,
    every subscription and every key is gone. fakeredis keeps the subscriptions of cut-off
    clients by itself."""
    server.connected = False
    server.subscribers.clear()
    with server.lock:
        for database in server.dbs.values():
            database.clear()


@pytest.fixture
async def redis_service(fake_server):
    """The real RedisService, on a fake Redis the test can take down and bring back."""
    service = RedisService(
        host="unused", port=0, webhook_channel=settings.WEBHOOK_MESSAGE_CHANNEL, password=""
    )
    service.client = FakeAsyncRedis(server=fake_server, decode_responses=True)
    yield service
    await service.client.aclose()


class _FakeDjango:
    """Stands in for Django's Redis listener: answers every sync request by publishing the
    full set in `configs`, and resubscribes after a Redis drop like Django does.

    With `answers` False it receives requests but publishes nothing, the way Django's
    handler drops a request it fails on (Postgres still starting, say).
    """

    def __init__(self, server: FakeServer):
        self.configs = WebhookConfigData()
        self.answers = True
        self.requests_received = 0
        self._client = FakeAsyncRedis(server=server, decode_responses=True)
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._serve())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            await asyncio.wait([self._task])
        await self._client.aclose()

    async def _serve(self) -> None:
        while True:
            pubsub = self._client.pubsub()
            try:
                await pubsub.subscribe(settings.REQUEST_WEBHOOK_UPDATE_CHANNEL)
                while True:
                    request = await pubsub.get_message(
                        ignore_subscribe_messages=True, timeout=POLL_SECONDS
                    )
                    if request is None:
                        continue
                    self.requests_received += 1
                    if self.answers:
                        await self._client.publish(
                            settings.REDIS_TUNNEL_CONFIG_CHANNEL, self.configs.model_dump_json()
                        )
            except RedisConnectionError:
                await asyncio.sleep(POLL_SECONDS)
            finally:
                await pubsub.aclose()


@pytest.fixture
async def django(fake_server):
    """Django's side of the sync, not yet started."""
    fake_django = _FakeDjango(fake_server)
    yield fake_django
    await fake_django.stop()


@pytest.fixture
async def start_listener(redis_service, tunnel_registry):
    """Returns `start()`, which runs a listener in a task and returns (listener, task)."""
    tasks = []

    def start():
        listener = TunnelConfigListener(redis_service, tunnel_registry)
        task = asyncio.create_task(listener.run())
        tasks.append(task)
        return listener, task

    yield start
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


def _hook(path: str, secret: str = "secret") -> LocalhostConfigData:
    auth = WebhookTriggerAuthData(kind="webhook", header_name="X-Key", secret=seal(secret))
    return LocalhostConfigData(name=path, org_id=1, auth=auth)


async def _secret_for(tunnel_registry, path: str) -> str | None:
    """The plaintext secret a request to `path` is checked against; None if unrouted,
    UNAVAILABLE if its config failed to register."""
    try:
        _, config = await tunnel_registry.resolve_by_path(path)
    except UnregisteredWebhookPathError:
        return None
    except UnavailableWebhookPathError:
        return UNAVAILABLE
    return sealing_cryptographer().decrypt(config.auth.secret)


async def _wait_for_routes(tunnel_registry, expected: dict[str, str | None], timeout=3.0):
    """Wait until each path routes with the given secret (None: not routed at all)."""
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        actual = {path: await _secret_for(tunnel_registry, path) for path in expected}
        if actual == expected:
            return
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError(f"routes are {actual}, expected {expected}")
        await asyncio.sleep(0.01)


async def test_startup_registers_the_full_config_set_django_sends(
    django, start_listener, tunnel_registry
):
    django.configs = WebhookConfigData(localhost_configs=[_hook("hook", "secret")])
    django.start()

    listener, _ = start_listener()

    await _wait_for_routes(tunnel_registry, {"hook": "secret"})
    assert listener.is_healthy()


async def test_configs_changed_during_a_redis_outage_are_applied_after_reconnecting(
    fake_server, django, start_listener, tunnel_registry
):
    django.configs = WebhookConfigData(
        localhost_configs=[_hook("rotated", "old-secret"), _hook("deleted")]
    )
    django.start()
    start_listener()
    await _wait_for_routes(tunnel_registry, {"rotated": "old-secret", "deleted": "secret"})

    _stop_redis(fake_server)
    # Changed while Redis is down: whatever Django publishes about it reaches no one.
    django.configs = WebhookConfigData(
        localhost_configs=[_hook("rotated", "new-secret"), _hook("added")]
    )
    await asyncio.sleep(OUTAGE_SECONDS)
    fake_server.connected = True

    await _wait_for_routes(
        tunnel_registry, {"rotated": "new-secret", "deleted": None, "added": "secret"}
    )


async def test_listener_started_while_redis_is_down_syncs_once_redis_and_django_are_up(
    fake_server, django, start_listener, tunnel_registry, monkeypatch
):
    monkeypatch.setattr(listener_module, "UNHEALTHY_AFTER_UNSYNCED_SECONDS", 0.1)
    _stop_redis(fake_server)

    listener, task = start_listener()
    await asyncio.sleep(OUTAGE_SECONDS)
    assert not listener.is_healthy()

    fake_server.connected = True
    # Redis is back but no Django is subscribed yet: the sync request is retried.
    await asyncio.sleep(OUTAGE_SECONDS)
    assert not listener.is_healthy()

    django.configs = WebhookConfigData(localhost_configs=[_hook("hook")])
    django.start()

    await _wait_for_routes(tunnel_registry, {"hook": "secret"})
    assert listener.is_healthy()
    assert not task.done()


async def _wait_until(condition, timeout=3.0):
    deadline = asyncio.get_running_loop().time() + timeout
    while not await condition():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("condition not met in time")
        await asyncio.sleep(0.01)


async def test_listener_stays_unhealthy_and_asks_again_while_django_drops_the_request(
    django, start_listener, tunnel_registry, monkeypatch
):
    monkeypatch.setattr(listener_module, "UNHEALTHY_AFTER_UNSYNCED_SECONDS", 0.1)
    django.answers = False
    django.configs = WebhookConfigData(localhost_configs=[_hook("hook")])
    django.start()

    listener, task = start_listener()

    async def asked_again():
        return django.requests_received >= 3

    await _wait_until(asked_again)
    await asyncio.sleep(0.1)
    assert not listener.is_healthy()
    assert not tunnel_registry.has_full_config_set()

    django.answers = True

    await _wait_for_routes(tunnel_registry, {"hook": "secret"})
    await _wait_until(_is_healthy(listener))
    assert not task.done()


def _is_healthy(listener):
    async def check():
        return listener.is_healthy()

    return check


async def test_sync_requests_back_off_while_django_does_not_answer(
    django, start_listener, monkeypatch
):
    monkeypatch.setattr(listener_module, "INITIAL_SYNC_REQUEST_RETRY_SECONDS", 0.02)
    monkeypatch.setattr(listener_module, "MAX_SYNC_REQUEST_RETRY_SECONDS", 10.0)
    monkeypatch.setattr(listener_module, "MESSAGE_POLL_SECONDS", 0.005)
    django.answers = False
    django.start()

    start_listener()
    await asyncio.sleep(0.6)

    # Doubling from 0.02s fits about 5 requests into 0.6s; a fixed interval would send 30.
    assert 2 <= django.requests_received <= 8


async def test_tunnel_urls_lost_with_a_redis_restart_are_written_again(
    fake_server, redis_service, django, start_listener, tunnel_registry
):
    config = _hook("hook")
    django.configs = WebhookConfigData(localhost_configs=[config])
    django.start()
    start_listener()
    await _wait_for_routes(tunnel_registry, {"hook": "secret"})
    published_url = await redis_service.client.hget(settings.TUNNEL_URLS_HASH_KEY, config.unique_id)
    assert published_url

    _stop_redis(fake_server)
    await asyncio.sleep(OUTAGE_SECONDS)
    fake_server.connected = True

    async def url_written_again():
        return (
            await redis_service.client.hget(settings.TUNNEL_URLS_HASH_KEY, config.unique_id)
            == published_url
        )

    await _wait_until(url_written_again)


async def test_unexpected_error_is_logged_and_the_listener_recovers(
    django, start_listener, tunnel_registry, monkeypatch
):
    register_many = tunnel_registry.register_many
    calls = 0

    async def register_many_failing_once(webhook_config_data):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("bug while applying configs")
        await register_many(webhook_config_data=webhook_config_data)

    monkeypatch.setattr(tunnel_registry, "register_many", register_many_failing_once)
    logged = []
    sink_id = logger.add(logged.append, level="ERROR", format="{message}")
    django.configs = WebhookConfigData(localhost_configs=[_hook("hook")])
    django.start()
    try:
        listener, task = start_listener()

        await _wait_for_routes(tunnel_registry, {"hook": "secret"})
        await _wait_until(_is_healthy(listener))
    finally:
        logger.remove(sink_id)

    assert not task.done()
    errors = [message for message in logged if message.record["exception"] is not None]
    assert len(errors) == 1
    assert "bug while applying configs" in str(errors[0].record["exception"].value)


async def test_malformed_messages_are_skipped_without_stopping_the_listener(
    redis_service, django, start_listener, tunnel_registry
):
    django.configs = WebhookConfigData(localhost_configs=[_hook("initial")])
    django.start()
    start_listener()
    await _wait_for_routes(tunnel_registry, {"initial": "secret"})

    for raw_message in [
        "not-json",
        json.dumps({"localhost_configs": [{"org_id": 1}]}),
        WebhookConfigData(localhost_configs=[_hook("hook")]).model_dump_json(),
    ]:
        await redis_service.client.publish(settings.REDIS_TUNNEL_CONFIG_CHANNEL, raw_message)

    await _wait_for_routes(tunnel_registry, {"initial": None, "hook": "secret"})


@pytest.mark.parametrize("redis_up", [True, False], ids=["while-subscribed", "while-reconnecting"])
async def test_cancellation_stops_the_listener(fake_server, django, start_listener, redis_up):
    django.start()
    if not redis_up:
        _stop_redis(fake_server)
    _, task = start_listener()
    await asyncio.sleep(OUTAGE_SECONDS)

    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=1)


def _ngrok_hook(auth_token: str, secret: str) -> NgrokConfigData:
    auth = WebhookTriggerAuthData(kind="webhook", header_name="X-Key", secret=seal(secret))
    return NgrokConfigData(name="hook", org_id=1, auth_token=auth_token, auth=auth)


async def test_a_config_that_fails_to_register_is_retried_without_making_the_listener_unhealthy(
    redis_service, django, start_listener, tunnel_registry, ngrok_environment, monkeypatch
):
    """One organization's broken config must not flip the health of the whole service; the
    set is requested again until the config registers, and no longer once it has."""
    monkeypatch.setattr(listener_module, "UNHEALTHY_AFTER_UNSYNCED_SECONDS", 0.1)
    # Retries must not stop while this test waits for them; the cap has its own tests.
    monkeypatch.setattr(listener_module, "MAX_CONSECUTIVE_SETS_WITH_FAILURES", 1000)
    django.configs = WebhookConfigData(
        ngrok_configs=[_ngrok_hook(seal("old-token"), "old-secret")],
        localhost_configs=[_hook("rotated", "old-secret"), _hook("deleted")],
    )
    django.start()
    listener, task = start_listener()
    await _wait_for_routes(
        tunnel_registry, {"hook": "old-secret", "rotated": "old-secret", "deleted": "secret"}
    )
    await _wait_until(_is_healthy(listener))

    # The rotated ngrok token cannot be used, so the tunnel fails to restart.
    django.configs = WebhookConfigData(
        ngrok_configs=[_ngrok_hook("gAAAAAforged-ngrok-token", "new-secret")],
        localhost_configs=[_hook("rotated", "new-secret")],
    )
    await redis_service.client.publish(
        settings.REDIS_TUNNEL_CONFIG_CHANNEL, django.configs.model_dump_json()
    )

    await _wait_for_routes(
        tunnel_registry, {"hook": UNAVAILABLE, "rotated": "new-secret", "deleted": None}
    )
    requests_after_failure = django.requests_received

    async def asked_again():
        return django.requests_received >= requests_after_failure + 3

    await _wait_until(asked_again)
    await asyncio.sleep(0.1)
    assert listener.is_healthy()

    django.configs = WebhookConfigData(
        ngrok_configs=[_ngrok_hook(seal("new-token"), "new-secret")],
        localhost_configs=[_hook("rotated", "new-secret")],
    )

    await _wait_for_routes(tunnel_registry, {"hook": "new-secret", "rotated": "new-secret"})
    # A request already sent may still be answered; after that, no more are sent.
    requests_after_registering = django.requests_received + 1
    await asyncio.sleep(0.2)
    assert django.requests_received <= requests_after_registering
    assert listener.is_healthy()
    assert not task.done()


async def test_configs_that_keep_failing_are_retried_with_backoff(
    django, start_listener, tunnel_registry, ngrok_environment, monkeypatch
):
    monkeypatch.setattr(listener_module, "INITIAL_SYNC_REQUEST_RETRY_SECONDS", 0.02)
    monkeypatch.setattr(listener_module, "MAX_SYNC_REQUEST_RETRY_SECONDS", 10.0)
    monkeypatch.setattr(listener_module, "MESSAGE_POLL_SECONDS", 0.005)
    # A cap of 5 would bound a fixed interval too; this test is about the interval.
    monkeypatch.setattr(listener_module, "MAX_CONSECUTIVE_SETS_WITH_FAILURES", 1000)
    django.configs = WebhookConfigData(
        ngrok_configs=[_ngrok_hook("gAAAAAforged-ngrok-token", "secret")]
    )
    django.start()

    start_listener()
    await asyncio.sleep(0.6)

    # Doubling from 0.02s fits about 5 requests into 0.6s; a fixed interval would send 30.
    assert 2 <= django.requests_received <= 8


async def test_requests_for_a_config_that_keeps_failing_stop_after_five_sets_in_a_row(
    django, start_listener, tunnel_registry, ngrok_environment
):
    """A config only a change in Django can heal must not make the listener ask Django for
    the full set forever; the stop is logged once, naming the config."""
    failing = _ngrok_hook("gAAAAAforged-ngrok-token", "secret")
    django.configs = WebhookConfigData(ngrok_configs=[failing])
    logged = []
    sink_id = logger.add(logged.append, level="ERROR", format="{message}")
    try:
        django.start()
        listener, task = start_listener()

        async def asked_five_times():
            return django.requests_received >= 5

        await _wait_until(asked_five_times)
        await asyncio.sleep(0.3)
    finally:
        logger.remove(sink_id)

    assert django.requests_received == 5
    stop_errors = [message for message in logged if "no longer requesting" in message]
    assert len(stop_errors) == 1
    assert failing.unique_id in stop_errors[0]
    assert await _secret_for(tunnel_registry, "hook") == UNAVAILABLE
    assert listener.is_healthy()
    assert not task.done()


async def test_a_change_django_publishes_after_retries_stopped_starts_them_over(
    redis_service, django, start_listener, tunnel_registry, ngrok_environment
):
    django.configs = WebhookConfigData(
        ngrok_configs=[_ngrok_hook("gAAAAAforged-ngrok-token", "secret")]
    )
    django.start()
    start_listener()

    async def asked_five_times():
        return django.requests_received >= 5

    await _wait_until(asked_five_times)
    await asyncio.sleep(0.2)
    assert django.requests_received == 5

    # Django publishes a change of the config, which still cannot register.
    django.configs = WebhookConfigData(
        ngrok_configs=[_ngrok_hook("gAAAAAforged-ngrok-token", "changed-secret")]
    )
    await redis_service.client.publish(
        settings.REDIS_TUNNEL_CONFIG_CHANNEL, django.configs.model_dump_json()
    )

    async def asked_again():
        return django.requests_received > 5

    await _wait_until(asked_again)

    # Fixed in Django without a publish: one of the resumed retries registers it.
    django.configs = WebhookConfigData(
        ngrok_configs=[_ngrok_hook(seal("token"), "changed-secret")]
    )
    await _wait_for_routes(tunnel_registry, {"hook": "changed-secret"})


async def test_tunnel_urls_lost_with_a_redis_restart_come_back_while_another_config_fails(
    fake_server, redis_service, django, start_listener, tunnel_registry, ngrok_environment,
    monkeypatch,
):
    """The tunnel URLs Django hands out must not stay lost for every organization because
    one organization's config keeps failing to register, and that config does not make
    the resubscribed listener unhealthy."""
    monkeypatch.setattr(listener_module, "UNHEALTHY_AFTER_UNSYNCED_SECONDS", 0.1)
    working = _hook("working")
    django.configs = WebhookConfigData(
        ngrok_configs=[_ngrok_hook("gAAAAAforged-ngrok-token", "secret")],
        localhost_configs=[working],
    )
    django.start()
    listener, _ = start_listener()
    await _wait_for_routes(tunnel_registry, {"hook": UNAVAILABLE, "working": "secret"})
    published_url = await redis_service.client.hget(
        settings.TUNNEL_URLS_HASH_KEY, working.unique_id
    )
    assert published_url

    _stop_redis(fake_server)
    await asyncio.sleep(OUTAGE_SECONDS)
    fake_server.connected = True

    async def url_written_again():
        return (
            await redis_service.client.hget(settings.TUNNEL_URLS_HASH_KEY, working.unique_id)
            == published_url
        )

    await _wait_until(url_written_again)
    await asyncio.sleep(0.15)
    assert listener.is_healthy()
    assert await _secret_for(tunnel_registry, "hook") == UNAVAILABLE


class _SilenceablePubSub:
    """A real fakeredis subscription that can go silent the way a half-open connection does:
    no error is raised, nothing published arrives, and a ping gets no reply."""

    def __init__(self, pubsub, silent: bool):
        self._pubsub = pubsub
        self.silent = silent

    async def subscribe(self, *channels):
        return await self._pubsub.subscribe(*channels)

    async def get_message(self, ignore_subscribe_messages=False, timeout=0.0):
        if self.silent:
            await asyncio.sleep(timeout)
            return None
        message = await self._pubsub.get_message(
            ignore_subscribe_messages=ignore_subscribe_messages, timeout=timeout
        )
        # A read already waiting when the link went silent gets nothing either.
        return None if self.silent else message

    async def ping(self):
        if not self.silent:
            await self._pubsub.ping()

    async def aclose(self):
        await self._pubsub.aclose()


class _SubscriptionLink:
    """The network path of the listener's subscriptions, which the test can cut silently."""

    def __init__(self, open_pubsub):
        self._open_pubsub = open_pubsub
        self._subscriptions: list[_SilenceablePubSub] = []
        self.new_subscriptions_silent = False

    def pubsub(self) -> _SilenceablePubSub:
        subscription = _SilenceablePubSub(self._open_pubsub(), self.new_subscriptions_silent)
        self._subscriptions.append(subscription)
        return subscription

    def go_silent(self) -> None:
        """Make every subscription opened so far silent; Redis itself stays reachable."""
        for subscription in self._subscriptions:
            subscription.silent = True


@pytest.fixture
def subscription_link(redis_service, monkeypatch):
    link = _SubscriptionLink(redis_service.client.pubsub)
    monkeypatch.setattr(redis_service.client, "pubsub", link.pubsub)
    return link


@pytest.fixture
def fast_subscription_pings(monkeypatch):
    monkeypatch.setattr(listener_module, "SUBSCRIPTION_PING_INTERVAL_SECONDS", 0.1)
    monkeypatch.setattr(listener_module, "SUBSCRIPTION_PONG_TIMEOUT_SECONDS", 0.1)


async def test_a_subscription_gone_silent_is_noticed_and_the_change_it_lost_is_applied(
    redis_service, django, start_listener, tunnel_registry, subscription_link,
    fast_subscription_pings,
):
    """A half-open subscription raises no error; a rotation Django publishes over it is lost,
    and the old secret must not stay accepted for longer than the ping deadline."""
    django.configs = WebhookConfigData(localhost_configs=[_hook("hook", "old-secret")])
    django.start()
    listener, task = start_listener()
    await _wait_for_routes(tunnel_registry, {"hook": "old-secret"})
    requests_before_silence = django.requests_received

    subscription_link.go_silent()
    django.configs = WebhookConfigData(localhost_configs=[_hook("hook", "new-secret")])
    await redis_service.client.publish(
        settings.REDIS_TUNNEL_CONFIG_CHANNEL, django.configs.model_dump_json()
    )

    # Silent for 0.1s, then 0.1s without a pong: well inside a second.
    await _wait_for_routes(tunnel_registry, {"hook": "new-secret"}, timeout=1.0)
    assert django.requests_received > requests_before_silence
    assert listener.is_healthy()
    assert not task.done()


async def test_a_quiet_subscription_that_answers_pings_is_kept(
    django, start_listener, tunnel_registry, subscription_link, monkeypatch
):
    monkeypatch.setattr(listener_module, "SUBSCRIPTION_PING_INTERVAL_SECONDS", 0.05)
    monkeypatch.setattr(listener_module, "SUBSCRIPTION_PONG_TIMEOUT_SECONDS", 0.05)
    django.configs = WebhookConfigData(localhost_configs=[_hook("hook")])
    django.start()
    listener, _ = start_listener()
    await _wait_for_routes(tunnel_registry, {"hook": "secret"})
    # Let a sync request still in flight (e.g. one sent before the fake Django subscribed)
    # be counted before taking the baseline.
    await asyncio.sleep(2 * POLL_SECONDS)
    requests_once_synced = django.requests_received

    # Ten ping intervals with nothing published.
    await asyncio.sleep(0.5)

    # A resubscribe would have asked Django for the set again.
    assert django.requests_received == requests_once_synced
    assert listener.is_healthy()


async def test_the_listener_turns_unhealthy_while_its_subscriptions_stay_silent(
    django, start_listener, tunnel_registry, subscription_link, fast_subscription_pings,
    monkeypatch,
):
    monkeypatch.setattr(listener_module, "UNHEALTHY_AFTER_UNSYNCED_SECONDS", 0.3)
    django.configs = WebhookConfigData(localhost_configs=[_hook("hook", "old-secret")])
    django.start()
    listener, task = start_listener()
    await _wait_for_routes(tunnel_registry, {"hook": "old-secret"})

    subscription_link.new_subscriptions_silent = True
    subscription_link.go_silent()

    async def unhealthy():
        return not listener.is_healthy()

    await _wait_until(unhealthy, timeout=2.0)

    subscription_link.new_subscriptions_silent = False
    django.configs = WebhookConfigData(localhost_configs=[_hook("hook", "new-secret")])

    await _wait_for_routes(tunnel_registry, {"hook": "new-secret"})
    await _wait_until(_is_healthy(listener))
    assert not task.done()


async def test_a_change_whose_publish_never_arrived_is_applied_by_the_periodic_full_sync(
    django, start_listener, tunnel_registry, monkeypatch
):
    """Django publishes a change once and only logs a failed publish; the subscription itself
    stays healthy, so only the periodic full sync brings the change in."""
    monkeypatch.setattr(listener_module, "FULL_SYNC_INTERVAL_SECONDS", 0.2)
    django.configs = WebhookConfigData(localhost_configs=[_hook("hook", "old-secret")])
    django.start()
    listener, _ = start_listener()
    await _wait_for_routes(tunnel_registry, {"hook": "old-secret"})

    # Rotated in Django; its publish never reached Redis.
    django.configs = WebhookConfigData(localhost_configs=[_hook("hook", "new-secret")])

    await _wait_for_routes(tunnel_registry, {"hook": "new-secret"}, timeout=1.0)
    assert listener.is_healthy()
