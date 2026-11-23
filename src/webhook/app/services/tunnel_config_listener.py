import asyncio
import time

from fastapi import Request
from loguru import logger
from pydantic import ValidationError
from redis.asyncio.client import PubSub
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import RedisError
from src.shared.models import WebhookConfigData

from app.core.settings import settings
from app.services.redis_service import RedisService
from app.services.tunnel_registry import ConfigsFailedToRegisterError, TunnelRegistry

INITIAL_RECONNECT_DELAY_SECONDS = 1.0
MAX_RECONNECT_DELAY_SECONDS = 30.0
# How long to wait for Django's answer before asking again. Django's own listener
# resubscribes about a second after a Redis restart, and its handler drops a request it
# fails on (Postgres still starting, say), so an unanswered request is not final. The same
# backoff paces the requests that retry configs which failed to register.
INITIAL_SYNC_REQUEST_RETRY_SECONDS = 2.0
MAX_SYNC_REQUEST_RETRY_SECONDS = 30.0
# How many config sets in a row may still have configs that failed to register before the
# listener stops requesting the set again. A config that keeps failing mostly has an ngrok
# token that is missing, undecryptable or rejected by ngrok, which only a change in Django
# heals, and Django publishes that change by itself; one failing because ngrok is
# unreachable is retried by the periodic full sync below. Five sets span about 30s of the
# backoff above, longer than a brief Redis failure that fails a localhost tunnel's
# registration.
MAX_CONSECUTIVE_SETS_WITH_FAILURES = 5
# How long one read waits for a message. Bounds how late a subscription whose socket was
# closed is noticed when no message is arriving to fail on. A half-open connection (the
# peer gone without closing the socket, a dropped network path) reads as an idle channel;
# the pings below catch that.
MESSAGE_POLL_SECONDS = 1.0
# After this long without receiving anything on the subscription, the listener pings Redis
# on it, and drops it as dead when nothing arrives within SUBSCRIPTION_PONG_TIMEOUT_SECONDS
# of the ping. So a silent subscription, during which rotations and deletions Django
# publishes are lost, is resynced at most about 40s after it went silent. redis-py's own
# `health_check_interval` does not do this for pub/sub: it sends the PING but never waits
# for the reply.
SUBSCRIPTION_PING_INTERVAL_SECONDS = 30.0
SUBSCRIPTION_PONG_TIMEOUT_SECONDS = 10.0
# The full set is requested again this long after the last one was applied, even while the
# subscription is healthy. Django publishes a change once, after commit, and only logs a
# failed publish, so without this a rotation whose publish failed would leave the old
# secret accepted until the next change or reconnect.
FULL_SYNC_INTERVAL_SECONDS = 300.0
# Longer than a Redis restart takes, so the health check fails only on a real outage.
UNHEALTHY_AFTER_UNSYNCED_SECONDS = 60.0


class TunnelConfigListener:
    """Keep the tunnel registry in step with Django's webhook configs across Redis drops.

    Every message on the tunnel-config channel carries Django's full config set, and
    `register_many` replaces the registry with it. Pub/sub keeps no messages, so whatever
    Django published while this listener was not subscribed is lost: after every subscribe,
    the first one included, the listener asks Django to publish the full set again, and
    keeps asking at a growing interval until a config set arrives and is applied. A
    subscription that goes silent without an error (a half-open connection) is dropped
    after an unanswered ping and resubscribed the same way. Once synced, the listener
    still asks for the full set every FULL_SYNC_INTERVAL_SECONDS, which bounds how long
    a change whose publish Django failed to deliver stays unapplied.

    A set counts as applied even when some of its configs failed to register: everything
    else of it is served, and the listener is synced. It still keeps requesting the set at
    the same growing interval until one registers in full, so the failed configs are
    retried, but stops after MAX_CONSECUTIVE_SETS_WITH_FAILURES such sets in a row. The
    next set that arrives after the stop (normally one Django publishes on a change, but a
    late answer to an earlier request counts too, as does the periodic full sync), or the
    resync after a reconnect, starts the retries over.
    """

    def __init__(self, redis_service: RedisService, tunnel_registry: TunnelRegistry):
        self._redis_service = redis_service
        self._tunnel_registry = tunnel_registry
        # None once a config set was applied on the current subscription; otherwise when
        # the listener last lost (or has not yet had) a synced subscription.
        self._unsynced_since: float | None = time.monotonic()

    def is_healthy(self) -> bool:
        """Return False once the listener has gone too long without a synced subscription.

        Synced means a config set from Django was applied after the current subscription
        began, even one some configs of which failed to register: those are one
        organization's bad data, and their paths answer as unavailable by themselves.
        Delivering the sync request is not enough, since Django may drop it. A listener
        that stopped for good (cancelled) stays unsynced, so it turns unhealthy as well.
        """
        if self._unsynced_since is None:
            return True
        return time.monotonic() - self._unsynced_since < UNHEALTHY_AFTER_UNSYNCED_SECONDS

    async def run(self) -> None:
        """Subscribe, sync with Django and apply configs until cancelled.

        Any error ends the current subscription: a Redis error is a dropped connection, any
        other exception a bug, logged with its traceback. Either way the listener
        resubscribes after a delay that doubles from INITIAL_RECONNECT_DELAY_SECONDS up to
        MAX_RECONNECT_DELAY_SECONDS and restarts from the initial delay once a subscription
        has synced.
        """
        reconnect_delay = INITIAL_RECONNECT_DELAY_SECONDS
        try:
            while True:
                try:
                    await self._listen_until_disconnected()
                except RedisError as error:
                    reconnect_delay = self._lose_sync(reconnect_delay)
                    logger.warning(
                        "Tunnel config listener lost Redis ({}: {}); resubscribing in {}s.",
                        type(error).__name__,
                        error,
                        reconnect_delay,
                    )
                except Exception:
                    reconnect_delay = self._lose_sync(reconnect_delay)
                    logger.exception(
                        "Tunnel config listener failed on an unexpected error; "
                        "resubscribing in {}s.",
                        reconnect_delay,
                    )
                await asyncio.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * 2, MAX_RECONNECT_DELAY_SECONDS)
        except asyncio.CancelledError:
            logger.info("Tunnel config listener was cancelled.")
            raise
        finally:
            self._lose_sync(reconnect_delay)

    def _lose_sync(self, reconnect_delay: float) -> float:
        """Mark the listener unsynced; return the delay to wait before resubscribing.

        The delay restarts from the initial one when the lost subscription had synced.
        """
        if self._unsynced_since is not None:
            return reconnect_delay
        self._unsynced_since = time.monotonic()
        return INITIAL_RECONNECT_DELAY_SECONDS

    async def _listen_until_disconnected(self) -> None:
        """Run one subscription; returns only by raising, a dropped connection as RedisError.

        A subscription that stops receiving anything, pings included, counts as dropped
        (see SUBSCRIPTION_PING_INTERVAL_SECONDS). Requests Django's full config set once
        subscribed, and again, at a growing interval, for as long as no set was applied or
        the last one applied had configs that failed to register, up to
        MAX_CONSECUTIVE_SETS_WITH_FAILURES of those; otherwise FULL_SYNC_INTERVAL_SECONDS
        after the last set applied.
        """
        pubsub = self._redis_service.client.pubsub()
        try:
            # Subscribed before the sync request, so Django's answer cannot be missed.
            await pubsub.subscribe(settings.REDIS_TUNNEL_CONFIG_CHANNEL)
            logger.info(
                "Subscribed to channel '{}' for registering webhook tunnels.",
                settings.REDIS_TUNNEL_CONFIG_CHANNEL,
            )
            loop = asyncio.get_running_loop()
            watchdog = _SubscriptionWatchdog(pubsub)
            retry_seconds = INITIAL_SYNC_REQUEST_RETRY_SECONDS
            receiver_count = await self._request_full_sync()
            # Whether the next request is a retry: no set was applied on this subscription
            # yet, or the last one had configs that failed to register and the retries
            # have not stopped. Otherwise it is the periodic full sync.
            retrying = True
            next_request_at = loop.time() + retry_seconds
            sets_with_failures_in_a_row = 0
            while True:
                message = await pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=MESSAGE_POLL_SECONDS
                )
                if message is not None:
                    watchdog.received()
                failed_ids = await self._apply_config_set(message)
                if failed_ids is not None:
                    self._mark_synced()
                    if failed_ids:
                        sets_with_failures_in_a_row += 1
                    if (
                        not failed_ids
                        or sets_with_failures_in_a_row >= MAX_CONSECUTIVE_SETS_WITH_FAILURES
                    ):
                        if failed_ids:
                            logger.error(
                                "Configs {} failed to register in {} config sets in a row; "
                                "no longer requesting the set until Django publishes a "
                                "change or the periodic full sync in {}s.",
                                failed_ids,
                                sets_with_failures_in_a_row,
                                FULL_SYNC_INTERVAL_SECONDS,
                            )
                        # Counted afresh from the next set that arrives.
                        sets_with_failures_in_a_row = 0
                        retry_seconds = INITIAL_SYNC_REQUEST_RETRY_SECONDS
                        retrying = False
                        next_request_at = loop.time() + FULL_SYNC_INTERVAL_SECONDS
                    elif not retrying:
                        retrying = True
                        next_request_at = loop.time() + retry_seconds
                await watchdog.check()
                if loop.time() < next_request_at:
                    continue
                if not retrying:
                    logger.info(
                        "Requesting Django's full config set, as every {}s.",
                        FULL_SYNC_INTERVAL_SECONDS,
                    )
                    next_request_at = loop.time() + FULL_SYNC_INTERVAL_SECONDS
                else:
                    if self._unsynced_since is None:
                        logger.info(
                            "Requesting Django's full config set again to retry the configs "
                            "that failed to register."
                        )
                    else:
                        logger.warning(
                            "No webhook config set from Django applied {}s after the sync "
                            "request (it reached {} subscribers); requesting again.",
                            retry_seconds,
                            receiver_count,
                        )
                    retry_seconds = min(retry_seconds * 2, MAX_SYNC_REQUEST_RETRY_SECONDS)
                    next_request_at = loop.time() + retry_seconds
                receiver_count = await self._request_full_sync()
        finally:
            await pubsub.aclose()

    def _mark_synced(self) -> None:
        if self._unsynced_since is not None:
            self._unsynced_since = None
            logger.info("Webhook configs synced with Django.")

    async def _request_full_sync(self) -> int:
        return await self._redis_service.client.publish(settings.REQUEST_WEBHOOK_UPDATE_CHANNEL, "")

    async def _apply_config_set(self, message: dict | None) -> list[str] | None:
        """Apply the config set `message` carries, if it is one.

        Returns:
            None when no config set was applied; otherwise the ids of its configs that
            failed to register, empty when it registered in full.
        """
        if message is None or message["type"] != "message":
            return None
        logger.debug("Received webhook config message")
        try:
            webhook_config_data = WebhookConfigData.model_validate_json(message["data"])
        except ValidationError as error:
            # One malformed message must not end the subscription; the next full set
            # replaces whatever it would have carried.
            logger.error("Skipping malformed webhook config message: {}", error)
            return None
        failed_ids: list[str] = []
        try:
            await self._tunnel_registry.register_many(webhook_config_data=webhook_config_data)
        except ConfigsFailedToRegisterError as error:
            failed_ids = error.failed_ids
        # After every applied set, failed configs or not: Redis may have restarted and lost
        # the URLs, while the set left every unchanged tunnel running without writing its
        # URL again.
        await self._tunnel_registry.republish_tunnel_urls()
        return failed_ids


class _SubscriptionWatchdog:
    """Turn a subscription that has gone silent into a ConnectionError.

    On a half-open connection every read just times out, exactly as on a channel nobody
    publishes to, so only a reply that fails to arrive tells the two apart.
    """

    def __init__(self, pubsub: PubSub):
        self._pubsub = pubsub
        self._loop = asyncio.get_running_loop()
        self._last_received_at = self._loop.time()
        self._ping_sent_at: float | None = None

    def received(self) -> None:
        """Note that the subscription delivered something: a message, a pong, anything."""
        self._last_received_at = self._loop.time()
        self._ping_sent_at = None

    async def check(self) -> None:
        """Ping a subscription silent for too long; raise once a ping went unanswered.

        Raises:
            redis.exceptions.ConnectionError: Nothing arrived within
                SUBSCRIPTION_PONG_TIMEOUT_SECONDS of a ping.
        """
        now = self._loop.time()
        if self._ping_sent_at is not None:
            if now - self._ping_sent_at >= SUBSCRIPTION_PONG_TIMEOUT_SECONDS:
                raise RedisConnectionError(
                    f"No reply on the subscription within {SUBSCRIPTION_PONG_TIMEOUT_SECONDS}s "
                    "of a ping; treating the connection as dead."
                )
            return
        if now - self._last_received_at >= SUBSCRIPTION_PING_INTERVAL_SECONDS:
            # The deadline runs from the ping, not from the last message: applying a config
            # set can take longer than the timeout, and the reply queues behind whatever
            # arrived in the meantime.
            await self._pubsub.ping()
            self._ping_sent_at = now


def get_tunnel_config_listener(request: Request) -> TunnelConfigListener:
    """Return the listener the app started on startup."""
    return request.app.state.tunnel_config_listener
