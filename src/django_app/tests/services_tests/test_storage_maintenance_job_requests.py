"""The storage maintenance stream carries two jobs, and each batch runs each named job once.

An entry without a job field is a recycle-bin purge, as every entry was before the storage
measurement shared the stream. An entry naming `storage_measurement` runs the store
measurement; however many of them pile up, a batch measures once. An entry naming a job
nobody knows is logged and dropped, never run as a purge. Every entry of a batch is
acknowledged, whether its job ran, failed or was unknown.

Real consumer group on fakeredis and the real measurement over an in-memory store; only the
purge itself is replaced (tested in test_recycle_bin_purge.py).
"""

from datetime import timedelta

import pytest
from django.utils import timezone

from src.shared.redis_streams import (
    RECYCLE_BIN_PURGE_JOB_FIELD,
    RECYCLE_BIN_PURGE_REQUESTED_AT_FIELD,
    RECYCLE_BIN_PURGE_STREAM,
    STORAGE_MEASUREMENT_JOB,
)
from tables.models import OrganizationStorageUsage
from tables.services.recycle_bin import purge_request_consumer as consumer_module
from tables.services.storage_service import usage_measurement
from tests.services_tests.test_recycle_bin_purge_request_consumer import (  # noqa: F401
    _consumer,
    _pending_count,
    _request_purge,
    logged,
    purge_calls,
    redis_client,
)
from tests.storage_tests.in_memory_backend import InMemoryStorageBackend

pytestmark = pytest.mark.django_db


class CountingBackend(InMemoryStorageBackend):
    def __init__(self, listings: list, **kwargs):
        super().__init__(**kwargs)
        self.listings = listings

    def total_size(self, prefix: str) -> int:
        self.listings.append(self.organization_prefix)
        return super().total_size(prefix)


@pytest.fixture(autouse=True)
def keep_the_test_transaction(monkeypatch):
    """Closing connections inside the test's transaction would doom it for every later query."""
    monkeypatch.setattr(consumer_module, "close_old_connections", lambda: None)


@pytest.fixture
def store_listings(monkeypatch):
    """Each organization prefix the measurement lists, in order."""
    listings: list[str] = []
    monkeypatch.setattr(
        usage_measurement,
        "get_storage_backend",
        lambda organization_prefix: CountingBackend(listings, organization_prefix=organization_prefix),
    )
    return listings


@pytest.fixture
def due_org(default_org):
    OrganizationStorageUsage.objects.create(
        organization=default_org, measure_until=timezone.now() + timedelta(hours=1)
    )
    return default_org


def _request(redis_client, job: str) -> None:  # noqa: F811
    redis_client.xadd(
        RECYCLE_BIN_PURGE_STREAM,
        {
            RECYCLE_BIN_PURGE_REQUESTED_AT_FIELD: "2026-01-01T03:00:00+00:00",
            RECYCLE_BIN_PURGE_JOB_FIELD: job,
        },
    )


def test_a_measurement_request_measures_and_never_purges(
    redis_client, purge_calls, store_listings, due_org  # noqa: F811
):
    consumer = _consumer(redis_client)
    _request(redis_client, STORAGE_MEASUREMENT_JOB)

    assert consumer.process_new(block_milliseconds=None) == 1

    assert store_listings == [f"org_{due_org.pk}/"]
    assert OrganizationStorageUsage.objects.get(organization=due_org).measured_at is not None
    assert purge_calls == []
    assert _pending_count(redis_client) == 0


def test_a_mixed_backlog_runs_one_measurement_and_one_purge_and_acknowledges_all(
    redis_client, purge_calls, store_listings, due_org  # noqa: F811
):
    consumer = _consumer(redis_client)
    for _ in range(3):
        _request(redis_client, STORAGE_MEASUREMENT_JOB)
    _request_purge(redis_client)
    _request_purge(redis_client)

    assert consumer.process_new(block_milliseconds=None) == 5

    assert store_listings == [f"org_{due_org.pk}/"]
    assert len(purge_calls) == 1
    assert _pending_count(redis_client) == 0


def test_an_unknown_job_is_logged_and_dropped_never_purged(
    redis_client, purge_calls, store_listings, due_org, logged  # noqa: F811
):
    consumer = _consumer(redis_client)
    _request(redis_client, "defragment")

    assert consumer.process_new(block_milliseconds=None) == 1

    assert purge_calls == []
    assert store_listings == []
    assert any(
        record["level"].name == "WARNING" and "defragment" in record["message"]
        for record in logged
    )
    assert _pending_count(redis_client) == 0


def test_a_failing_measurement_is_logged_and_the_purge_of_its_batch_still_runs(
    redis_client, purge_calls, monkeypatch, logged  # noqa: F811
):
    def measurement_fails():
        raise RuntimeError("database is gone")

    monkeypatch.setattr(consumer_module, "measure_due_organizations", measurement_fails)
    consumer = _consumer(redis_client)
    _request(redis_client, STORAGE_MEASUREMENT_JOB)
    _request_purge(redis_client)

    consumer.process_new(block_milliseconds=None)

    assert len(purge_calls) == 1
    assert any(
        record["level"].name == "ERROR" and "measurement failed" in record["message"]
        for record in logged
    )
    assert _pending_count(redis_client) == 0
    assert consumer.process_new(block_milliseconds=None) == 0
