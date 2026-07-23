"""
Fixtures for knowledge worker tests.

Mocks: Redis (RedisService.publish is intercepted - no real or fake network
hop is needed to verify *what* NaiveRAGStrategy publishes and *when*), plus
DB access via lightweight in-memory doubles (FakeUnitOfWork /
FakeNaiveRagStorage) standing in for the real Postgres-backed UnitOfWork.
Real: NaiveRAGStrategy's own control flow (process_rag_indexing,
update_naive_rag_status, progress-event derivation).
"""

import pytest

from utils.singleton_meta import SingletonMeta
from services.redis_service import RedisService


@pytest.fixture(autouse=True)
def _reset_redis_singleton():
    """RedisService is a process-wide singleton (SingletonMeta). Reset it
    around every test so tests don't leak state into one another."""
    SingletonMeta._instances.pop(RedisService, None)
    yield
    SingletonMeta._instances.pop(RedisService, None)


@pytest.fixture
def published_messages(monkeypatch):
    """
    Captures every (channel, message) published via RedisService.publish(),
    in call order, without touching a real Redis connection.
    """
    captured: list[tuple[str, dict]] = []

    def _fake_publish(self, channel, message):
        captured.append((channel, message))

    monkeypatch.setattr(RedisService, "publish", _fake_publish)
    # Construct the singleton now so RedisService() calls made deep inside
    # NaiveRAGStrategy resolve to this same (patched) instance.
    RedisService(host="localhost", port=6379, password=None)
    return captured
