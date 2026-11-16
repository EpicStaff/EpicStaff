"""Fixtures and helpers for driving `RecycleBinPurgeRequestConsumer` over a fake Redis stream.

The fixtures are exposed to `tests/services_tests/` by its conftest; test modules import the
helpers by name.
"""

import fakeredis
import pytest

from src.shared.redis_streams import (
    RECYCLE_BIN_PURGE_CONSUMER_GROUP,
    RECYCLE_BIN_PURGE_REQUESTED_AT_FIELD,
    RECYCLE_BIN_PURGE_STREAM,
)
from tables.services.recycle_bin.purge_request_consumer import RecycleBinPurgeRequestConsumer
from tables.services.recycle_bin.purge_service import PurgeService
from utils.logger import logger


@pytest.fixture
def redis_client():
    client = fakeredis.FakeRedis(decode_responses=True)
    yield client
    client.close()


@pytest.fixture
def purge_calls(monkeypatch):
    """Replaces the purge itself (tested in test_recycle_bin_purge.py) and records each run."""
    calls = []

    def fake_purge_expired(*args, **kwargs):
        calls.append(1)
        return {"tables.Graph": 2, "tables.Agent": 1}

    monkeypatch.setattr(PurgeService, "purge_expired", fake_purge_expired)
    return calls


@pytest.fixture
def logged():
    records = []
    sink_id = logger.add(lambda message: records.append(message.record), level="INFO")
    yield records
    logger.remove(sink_id)


def request_purge(redis_client, requested_at="2026-01-01T03:00:00+00:00"):
    redis_client.xadd(RECYCLE_BIN_PURGE_STREAM, {RECYCLE_BIN_PURGE_REQUESTED_AT_FIELD: requested_at})


def pending_count(redis_client) -> int:
    return redis_client.xpending(RECYCLE_BIN_PURGE_STREAM, RECYCLE_BIN_PURGE_CONSUMER_GROUP)[
        "pending"
    ]


def start_consumer(redis_client, name="host-a") -> RecycleBinPurgeRequestConsumer:
    consumer = RecycleBinPurgeRequestConsumer(redis_client, name, sleep=lambda _seconds: None)
    consumer.start()
    return consumer
