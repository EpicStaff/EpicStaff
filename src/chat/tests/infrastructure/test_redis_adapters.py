import asyncio

import anyio

import fakeredis.aioredis
import pytest
from infrastructure.redis.counters import RedisRateLimiter
from infrastructure.redis.fanout import RedisFanout
from infrastructure.redis.tickets import RedisTickets, ticket_digest


@pytest.fixture
async def redis():
    client = fakeredis.aioredis.FakeRedis()
    yield client
    await client.aclose()


async def test_rate_limiter_counts_per_window(redis):
    limiter = RedisRateLimiter(redis)
    assert await limiter.hit("k", limit=2, window_seconds=60) is None
    assert await limiter.hit("k", limit=2, window_seconds=60) is None
    retry_after = await limiter.hit("k", limit=2, window_seconds=60)
    assert 1 <= retry_after <= 60
    assert 0 < await redis.ttl("k") <= 60


async def test_rate_limiter_restores_lost_expiry(redis):
    limiter = RedisRateLimiter(redis)
    await redis.set("k2", 5)
    retry_after = await limiter.hit("k2", limit=2, window_seconds=60)
    assert 1 <= retry_after <= 60
    assert 0 < await redis.ttl("k2") <= 60


class Clock:
    def __init__(self):
        self.now = 1_000_000.0

    def __call__(self):
        return self.now


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def leases(redis, clock):
    return RedisRateLimiter(redis, clock=clock)


async def test_stream_slots_are_capped_and_given_back(leases, redis):
    assert [await leases.acquire_slot("slots", 2, f"h{n}", lease_seconds=60) for n in range(3)] == [True, True, False]
    assert await redis.zcard("slots") == 2 and 0 < await redis.ttl("slots") <= 60  # a refusal takes nothing
    await leases.release_slot("slots", "h0")
    assert await leases.acquire_slot("slots", 2, "h3", lease_seconds=60) is True
    for holder in ("h1", "h1", "h3", "missing"):
        await leases.release_slot("slots", holder)
    assert await redis.zcard("slots") == 0  # releasing twice, or a slot never held, takes nothing else


async def test_an_unrenewed_lease_expires_and_frees_its_slot(leases, clock):
    assert await leases.acquire_slot("slots", 1, "crashed", lease_seconds=45) is True
    clock.now += 44
    assert await leases.acquire_slot("slots", 1, "next", lease_seconds=45) is False
    clock.now += 2  # the holder died: never renewed, never released
    assert await leases.acquire_slot("slots", 1, "next", lease_seconds=45) is True


async def test_a_crashed_holder_stops_counting_after_its_lease(leases, clock, redis):
    """The observed leak: one holder killed mid-stream, one still live; only the live one counts."""
    assert await leases.acquire_slot("user", 2, "killed", lease_seconds=45) is True
    assert await leases.acquire_slot("user", 2, "live", lease_seconds=45) is True
    for _ in range(4):
        clock.now += 15
        await leases.renew_slot("user", "live", lease_seconds=45)
    assert await leases.acquire_slot("user", 2, "new", lease_seconds=45) is True
    assert await redis.zrange("user", 0, -1) == [b"live", b"new"]  # the dead lease was pruned on acquire


async def test_renewal_keeps_a_slot_past_its_original_lease(leases, clock):
    assert await leases.acquire_slot("slots", 1, "live", lease_seconds=45) is True
    for _ in range(10):
        clock.now += 15
        await leases.renew_slot("slots", "live", lease_seconds=45)
    assert await leases.acquire_slot("slots", 1, "other", lease_seconds=45) is False


async def test_renewal_does_not_revive_an_expired_lease(leases, clock, redis):
    assert await leases.acquire_slot("slots", 1, "stalled", lease_seconds=45) is True
    clock.now += 46
    assert await leases.acquire_slot("slots", 1, "taker", lease_seconds=45) is True
    await leases.renew_slot("slots", "stalled", lease_seconds=45)
    assert await redis.zscore("slots", "stalled") is None


async def test_the_slot_key_outlives_its_latest_lease(leases, clock, redis):
    assert await leases.acquire_slot("slots", 2, "a", lease_seconds=45) is True
    await redis.expire("slots", 1)
    await leases.renew_slot("slots", "a", lease_seconds=45)
    assert 40 < await redis.ttl("slots") <= 45


async def test_concurrent_acquires_never_exceed_the_limit(leases, redis):
    results = await asyncio.gather(*(leases.acquire_slot("k", 5, f"h{n}", lease_seconds=45) for n in range(20)))
    assert results.count(True) == 5
    assert await redis.zcard("k") == 5


async def test_ticket_single_use(redis):
    tickets = RedisTickets(redis, ttl_seconds=60)
    ticket, expires_in = await tickets.issue({"kind": "conversation", "conversation_id": "abc"})
    assert expires_in == 60
    assert 0 < await redis.ttl(f"chat:ticket:{ticket_digest(ticket)}") <= 60
    assert await tickets.consume(ticket) == {"kind": "conversation", "conversation_id": "abc"}
    assert await tickets.consume(ticket) is None
    assert await tickets.consume("garbage") is None


async def test_fanout_delivers_and_idles(redis):
    fanout = RedisFanout(redis)
    received = []

    async def listen():
        async with fanout.listen("chat:conversation:1", idle_seconds=0.2) as messages:
            async for item in messages:
                received.append(item)
                if item and item["seq"] == 2:
                    return

    task = asyncio.create_task(listen())
    await asyncio.sleep(0.05)
    await fanout.publish("chat:conversation:1", {"seq": 1, "type": "x", "payload": {}})
    await asyncio.sleep(0.5)
    await fanout.publish("chat:conversation:1", {"seq": 2, "type": "y", "payload": {}})
    await asyncio.wait_for(task, timeout=3)
    assert received[0] == {"seq": 1, "type": "x", "payload": {}}
    assert None in received
    assert received[-1] == {"seq": 2, "type": "y", "payload": {}}



class CheckpointPubSub:
    """fakeredis cleanup never suspends, so it cannot show a cancelled cleanup; this one yields like a real socket."""

    def __init__(self):
        self.calls = []

    async def subscribe(self, channel):
        self.calls.append("subscribe")

    async def get_message(self, ignore_subscribe_messages, timeout):
        await asyncio.sleep(timeout)

    async def unsubscribe(self, channel):
        await asyncio.sleep(0)
        self.calls.append("unsubscribe")

    async def aclose(self):
        await asyncio.sleep(0)
        self.calls.append("aclose")


async def test_fanout_cleanup_survives_a_cancelled_scope():
    """A dropped SSE client cancels the anyio scope the stream runs in; the pubsub must still be released."""
    pubsub = CheckpointPubSub()
    fanout = RedisFanout(type("Redis", (), {"pubsub": lambda self: pubsub})())
    holder = {}

    async def park():
        with anyio.CancelScope() as scope:
            holder["scope"] = scope
            async with fanout.listen("chat:conversation:1", idle_seconds=10) as messages:
                async for _ in messages:
                    pass

    task = asyncio.create_task(park())
    await asyncio.sleep(0.05)
    holder["scope"].cancel()
    await asyncio.wait_for(task, timeout=2)
    assert pubsub.calls == ["subscribe", "unsubscribe", "aclose"]
