"""Abandoned pending connections are reported to Django as ended, best-effort."""

import asyncio

import pytest

import infrastructure.persistence.connection_repository as repo_module
from application.pending_connection_sweeper import PendingConnectionSweeper
from infrastructure.persistence.connection_repository import ConnectionRepository
from utils.singleton_meta import SingletonMeta
from tests.infrastructure.test_connection_repository import _make_data

pytestmark = pytest.mark.asyncio


class RecordingEndClient:
    """Stands in for the Django HTTP call; records what would have been reported."""

    def __init__(self):
        self.reported: list[tuple[str, float, str]] = []

    async def end_chat(self, connection_key, duration, end_reason):
        self.reported.append((connection_key, duration, end_reason))


@pytest.fixture
def clock(monkeypatch):
    now = {"now": 1000.0}
    monkeypatch.setattr(repo_module.time, "monotonic", lambda: now["now"])
    return now


@pytest.fixture
def repository():
    """A fresh repository per test; it is a singleton, so the instance cache is cleared."""
    SingletonMeta._instances.pop(ConnectionRepository, None)
    yield ConnectionRepository(max_connections_per_org=2, max_connections=10, ttl_seconds=5)
    SingletonMeta._instances.pop(ConnectionRepository, None)


def _sweeper(repository, end_client) -> PendingConnectionSweeper:
    return PendingConnectionSweeper(repository, end_client, interval_seconds=60)


async def test_expired_unused_key_is_reported_as_a_zero_length_timeout_without_any_new_traffic(
    repository, clock
):
    repository.save_connection("abandoned", _make_data("abandoned"))
    end_client = RecordingEndClient()
    clock["now"] += 5

    await _sweeper(repository, end_client).sweep_once()

    assert end_client.reported == [("abandoned", 0, "timeout")]


async def test_a_live_key_is_not_reported(repository, clock):
    repository.save_connection("waiting", _make_data("waiting"))
    end_client = RecordingEndClient()
    clock["now"] += 4.9

    await _sweeper(repository, end_client).sweep_once()

    assert end_client.reported == []
    assert repository.get_connection("waiting") is not None


async def test_a_key_evicted_by_the_org_cap_is_reported(repository):
    for key in ("a1", "a2", "a3"):
        repository.save_connection(key, _make_data(key, org_id=1))
    end_client = RecordingEndClient()

    await _sweeper(repository, end_client).sweep_once()

    assert end_client.reported == [("a1", 0, "timeout")]


async def test_a_consumed_key_is_not_reported(repository, clock):
    repository.save_connection("attached", _make_data("attached"))
    repository.delete_connection("attached")
    end_client = RecordingEndClient()
    clock["now"] += 5

    await _sweeper(repository, end_client).sweep_once()

    assert end_client.reported == []


async def test_a_key_is_reported_only_once(repository, clock):
    repository.save_connection("abandoned", _make_data("abandoned"))
    end_client = RecordingEndClient()
    clock["now"] += 5
    sweeper = _sweeper(repository, end_client)

    await sweeper.sweep_once()
    await sweeper.sweep_once()

    assert len(end_client.reported) == 1


async def test_a_key_saved_again_after_expiring_is_not_reported(repository, clock):
    repository.save_connection("same", _make_data("same"))
    clock["now"] += 5
    assert repository.get_connection("same") is None
    end_client = RecordingEndClient()

    repository.save_connection("same", _make_data("same"))
    await _sweeper(repository, end_client).sweep_once()

    assert end_client.reported == []
    assert repository.get_connection("same") is not None


async def test_every_dropped_key_is_reported_in_one_sweep(repository, clock):
    for key in ("a1", "a2"):
        repository.save_connection(key, _make_data(key, org_id=1))
    repository.save_connection("b1", _make_data("b1", org_id=2))
    end_client = RecordingEndClient()
    clock["now"] += 5

    await _sweeper(repository, end_client).sweep_once()

    assert sorted(key for key, _, _ in end_client.reported) == ["a1", "a2", "b1"]


async def test_run_sweeps_repeatedly_on_its_interval(repository, clock):
    end_client = RecordingEndClient()
    sweeper = PendingConnectionSweeper(repository, end_client, interval_seconds=0.01)
    repository.save_connection("abandoned", _make_data("abandoned"))
    clock["now"] += 5

    task = asyncio.create_task(sweeper.run())
    try:
        await asyncio.wait_for(_until(lambda: end_client.reported), timeout=2)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    assert end_client.reported == [("abandoned", 0, "timeout")]


async def _until(condition):
    while not condition():
        await asyncio.sleep(0.005)
