"""Behavior of the in-RAM holding registry for jobs waiting on a venv build."""

from manager.application.holding import JobHoldingRegistry
from tests.builders import make_manager_job


def test_a_held_job_is_returned_on_release():
    registry = JobHoldingRegistry()
    job = make_manager_job(execution_id="e1")

    registry.hold(1, job)

    assert registry.release(1) == [job]


def test_release_of_an_unknown_venv_returns_nothing():
    assert JobHoldingRegistry().release(99) == []


def test_release_removes_the_jobs():
    registry = JobHoldingRegistry()
    registry.hold(1, make_manager_job())

    registry.release(1)

    assert registry.release(1) == []


def test_several_jobs_on_one_venv_keep_their_order():
    registry = JobHoldingRegistry()
    first = make_manager_job(execution_id="e1")
    second = make_manager_job(execution_id="e2")

    registry.hold(1, first)
    registry.hold(1, second)

    assert registry.release(1) == [first, second]


def test_pending_venv_ids_lists_every_venv_with_waiting_jobs():
    registry = JobHoldingRegistry()
    registry.hold(1, make_manager_job())
    registry.hold(2, make_manager_job())

    assert sorted(registry.pending_venv_ids()) == [1, 2]


def test_pending_venv_ids_drops_a_venv_once_released():
    registry = JobHoldingRegistry()
    registry.hold(1, make_manager_job())

    registry.release(1)

    assert registry.pending_venv_ids() == []
