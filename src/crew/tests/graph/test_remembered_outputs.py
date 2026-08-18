import types

import fakeredis
import pytest

from services.graph.remembered_outputs import (
    RememberedOutputsStore,
    format_remembered_outputs_preamble,
)


@pytest.fixture
def redis_service_stub():
    return types.SimpleNamespace(
        aioredis_client=fakeredis.FakeAsyncRedis(decode_responses=True)
    )


@pytest.fixture
def store(redis_service_stub):
    return RememberedOutputsStore(redis_service=redis_service_stub)


@pytest.mark.asyncio
async def test_fetch_all_returns_empty_list_when_key_missing(store):
    assert await store.fetch_all(session_id=1) == []


@pytest.mark.asyncio
async def test_store_then_fetch_roundtrip(store):
    await store.store(session_id=1, node_name="task_a", output="output_a")

    assert await store.fetch_all(session_id=1) == [("task_a", "output_a")]


@pytest.mark.asyncio
async def test_fetch_all_preserves_execution_order(store):
    await store.store(session_id=1, node_name="a", output="out_a")
    await store.store(session_id=1, node_name="b", output="out_b")
    await store.store(session_id=1, node_name="c", output="out_c")

    assert await store.fetch_all(session_id=1) == [
        ("a", "out_a"),
        ("b", "out_b"),
        ("c", "out_c"),
    ]


@pytest.mark.asyncio
async def test_reexecution_overwrites_value_keeps_first_seen_order(store):
    await store.store(session_id=1, node_name="a", output="v1")
    await store.store(session_id=1, node_name="b", output="out_b")
    await store.store(session_id=1, node_name="a", output="v2")

    assert await store.fetch_all(session_id=1) == [
        ("a", "v2"),
        ("b", "out_b"),
    ]


@pytest.mark.asyncio
async def test_store_sets_ttl(redis_service_stub):
    store = RememberedOutputsStore(redis_service=redis_service_stub, ttl_s=123)

    await store.store(session_id=1, node_name="a", output="out_a")

    ttl = await redis_service_stub.aioredis_client.ttl(store._key(1))
    assert 0 < ttl <= 123


@pytest.mark.asyncio
async def test_clear_deletes_key(store):
    await store.store(session_id=1, node_name="a", output="out_a")

    await store.clear(session_id=1)

    assert await store.fetch_all(session_id=1) == []


def test_format_preamble_empty_list_returns_empty_string():
    assert format_remembered_outputs_preamble([]) == ""


def test_format_preamble_exact_string_for_two_entries():
    preamble = format_remembered_outputs_preamble([("a", "out_a"), ("b", "out_b")])

    assert preamble == (
        "===== PREVIOUS TASKS OUTPUTS =====\n\n"
        "Task 'a':\nout_a\n\n"
        "Task 'b':\nout_b\n\n"
        "===== END PREVIOUS TASKS OUTPUTS =====\n\n"
    )
