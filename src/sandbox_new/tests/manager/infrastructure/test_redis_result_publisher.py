"""Behavior of the Redis result publisher, against fakeredis.

The result payload shape is a contract with consumers that already exist (crew reads
``result_data``), so the assertions name every key. Mutations go to their own channel and
only when there is something to report.
"""

import json

import fakeredis.aioredis
import pytest

from common.contracts import ExecutionResultMessage, StorageMutationsMessage
from manager.infrastructure.transport.redis_result_publisher import RedisResultPublisher

RESULT_CHANNEL = "code:results"
MUTATION_CHANNEL = "storage:mutations"


async def next_payload(pubsub, *, attempts: int = 50) -> dict | None:
    """Poll the subscription until a message arrives, or give up.

    Proving a message is absent needs far fewer attempts than waiting for one: the
    publish is already awaited by the time we poll, so a handful of passes settles it.
    Polling the full count for every negative assertion would cost seconds per test.
    """
    for _ in range(attempts):
        message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.05)
        if message is not None:
            return json.loads(message["data"])
    return None


@pytest.fixture
async def redis():
    client = fakeredis.aioredis.FakeRedis()
    yield client
    await client.aclose()


@pytest.fixture
def publisher(redis) -> RedisResultPublisher:
    return RedisResultPublisher(
        redis, result_channel=RESULT_CHANNEL, mutation_channel=MUTATION_CHANNEL
    )


async def subscribe(redis, channel):
    pubsub = redis.pubsub()
    await pubsub.subscribe(channel)
    return pubsub


async def test_the_result_payload_uses_the_keys_consumers_already_read(redis, publisher):
    pubsub = await subscribe(redis, RESULT_CHANNEL)

    await publisher.publish(
        ExecutionResultMessage(
            execution_id="exec-1", result="42", stdout="out", stderr="err", returncode=0
        )
    )

    assert await next_payload(pubsub) == {
        "execution_id": "exec-1",
        "result_data": "42",
        "stdout": "out",
        "stderr": "err",
        "returncode": 0,
    }


async def test_mutations_are_published_on_their_own_channel(redis, publisher):
    results = await subscribe(redis, RESULT_CHANNEL)
    mutations = await subscribe(redis, MUTATION_CHANNEL)

    await publisher.publish(
        ExecutionResultMessage(
            execution_id="exec-1",
            mutations=StorageMutationsMessage(
                org_prefix="org1", session_id=7, mutations=[{"path": "docs/a.txt"}]
            ),
        )
    )

    assert await next_payload(results) is not None
    assert await next_payload(mutations) == {
        "execution_id": "exec-1",
        "org_prefix": "org1",
        "session_id": 7,
        "mutations": [{"path": "docs/a.txt"}],
    }


async def test_no_mutation_message_without_mutations(redis, publisher):
    mutations = await subscribe(redis, MUTATION_CHANNEL)

    await publisher.publish(ExecutionResultMessage(execution_id="exec-1"))

    assert await next_payload(mutations, attempts=5) is None


async def test_no_mutation_message_for_an_empty_mutation_list(redis, publisher):
    mutations = await subscribe(redis, MUTATION_CHANNEL)

    await publisher.publish(
        ExecutionResultMessage(
            execution_id="exec-1",
            mutations=StorageMutationsMessage(org_prefix="org1", session_id=7, mutations=[]),
        )
    )

    assert await next_payload(mutations, attempts=5) is None
