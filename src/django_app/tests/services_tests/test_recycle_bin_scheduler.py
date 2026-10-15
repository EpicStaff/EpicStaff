from unittest import mock

import pytest
from filelock import FileLock

from tables.utils import recycle_bin_scheduler


@pytest.fixture
def lock_file(tmp_path, monkeypatch):
    path = tmp_path / "purge.lock"
    monkeypatch.setattr(recycle_bin_scheduler, "_lock_path", lambda: path)
    monkeypatch.setattr(recycle_bin_scheduler, "_purge_owner_lock", None)
    yield path
    if recycle_bin_scheduler._purge_owner_lock is not None:
        recycle_bin_scheduler._purge_owner_lock.release()


@pytest.fixture
def scheduler_class(monkeypatch):
    fake = mock.MagicMock()
    monkeypatch.setattr(recycle_bin_scheduler, "BackgroundScheduler", fake)
    return fake


def test_the_first_worker_schedules_the_daily_purge(lock_file, scheduler_class):
    assert recycle_bin_scheduler.start_recycle_bin_purge_if_owner() is True

    scheduler = scheduler_class.return_value
    job = scheduler.add_job.call_args.kwargs
    assert (job["trigger"], job["hour"], job["id"]) == ("cron", 3, "recycle_bin_purge")
    scheduler.start.assert_called_once()


def test_another_worker_holding_the_lock_wins(lock_file, scheduler_class):
    # A separate lock object on the same file stands in for another worker process.
    other_worker = FileLock(str(lock_file), is_singleton=False)
    other_worker.acquire(timeout=0)
    try:
        assert recycle_bin_scheduler.start_recycle_bin_purge_if_owner() is False
    finally:
        other_worker.release()

    scheduler_class.return_value.add_job.assert_not_called()


@pytest.mark.django_db
def test_a_failing_run_does_not_raise():
    with mock.patch(
        "tables.services.recycle_bin.purge_service.PurgeService.purge_expired",
        side_effect=RuntimeError("boom"),
    ):
        recycle_bin_scheduler.run_recycle_bin_purge()
