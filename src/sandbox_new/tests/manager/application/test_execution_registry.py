"""Behavior of the execution registry.

It is what the status endpoint answers from, what makes a re-POST idempotent, and what
admission control counts. A finished execution answers DONE for a minute and is then
forgotten; only completions that really ran feed the drain rate.
"""

import pytest

from manager.application.registry import ExecutionRegistry
from manager.domain.enums import ExecutionStatus
from manager.domain.errors import ExecutionNotFoundError


@pytest.fixture
def registry(clock) -> ExecutionRegistry:
    return ExecutionRegistry(clock=clock)


def finish_ran(registry: ExecutionRegistry, count: int, *, ran: bool = True) -> None:
    for index in range(count):
        execution_id = f"done-{ran}-{index}"
        registry.reserve(execution_id)
        registry.mark_queued(execution_id)
        registry.finish(execution_id, ran=ran)


def test_a_second_reservation_of_the_same_id_is_refused(registry):
    assert registry.reserve("exec-1") is True

    assert registry.reserve("exec-1") is False


def test_a_reserved_execution_reports_queued(registry):
    registry.reserve("exec-1")

    assert registry.status("exec-1") is ExecutionStatus.QUEUED


@pytest.mark.parametrize(
    ("mark", "expected"),
    [("mark_held", ExecutionStatus.HELD), ("mark_queued", ExecutionStatus.QUEUED)],
)
def test_a_marked_execution_reports_its_state(registry, mark, expected):
    registry.reserve("exec-1")

    getattr(registry, mark)("exec-1")

    assert registry.get_status("exec-1") is expected


def test_a_finished_execution_answers_done_for_a_minute(registry, clock):
    registry.reserve("exec-1")
    registry.finish("exec-1", ran=True)

    clock.advance(59.9)

    assert registry.status("exec-1") is ExecutionStatus.DONE
    assert registry.reserve("exec-1") is False


def test_a_finished_execution_is_unknown_after_a_minute(registry, clock):
    registry.reserve("exec-1")
    registry.finish("exec-1", ran=True)

    clock.advance(60.1)

    assert registry.status("exec-1") is None
    assert registry.reserve("exec-1") is True


def test_an_unknown_execution_raises_not_found(registry):
    with pytest.raises(ExecutionNotFoundError):
        registry.get_status("exec-404")


def test_a_forgotten_execution_is_unknown(registry):
    registry.reserve("exec-1")
    registry.mark_queued("exec-1")

    registry.forget("exec-1")

    assert registry.status("exec-1") is None
    assert registry.active_count == 0


def test_held_executions_are_counted_apart_from_the_active_ones(registry):
    for execution_id in ("reserved", "held", "queued", "done"):
        registry.reserve(execution_id)
    registry.mark_held("held")
    registry.mark_queued("queued")
    registry.finish("done", ran=True)

    assert registry.active_count == 2
    assert registry.held_count == 1
    assert registry.queued_count == 1


def test_a_released_held_execution_moves_to_the_active_count(registry):
    registry.reserve("exec-1")
    registry.mark_held("exec-1")

    registry.mark_queued("exec-1")

    assert (registry.active_count, registry.held_count) == (1, 0)


def test_releasing_a_held_execution_moves_it_to_the_queue(registry):
    registry.reserve("exec-1")
    registry.mark_held("exec-1")

    registry.mark_queued("exec-1")

    assert registry.status("exec-1") is ExecutionStatus.QUEUED
    assert registry.queued_count == 1
    assert registry.active_count == 1


def finish_one_every(
    registry: ExecutionRegistry, clock, count: int, seconds: float, *, prefix: str = "done"
) -> None:
    """Finish ``count`` executions that ran, ``seconds`` apart, ending on the last one."""
    for index in range(count):
        if index:
            clock.advance(seconds)
        registry.reserve(f"{prefix}-{index}")
        registry.mark_queued(f"{prefix}-{index}")
        registry.finish(f"{prefix}-{index}", ran=True)


@pytest.mark.parametrize(
    ("completions", "expected"),
    [(0, None), (4, None), (5, 5 / 4), (20, 20 / 19)],
    ids=["none", "four-is-a-cold-start", "five-is-enough", "twenty"],
)
def test_the_drain_rate_needs_five_completions_that_ran(registry, clock, completions, expected):
    finish_one_every(registry, clock, completions, 1.0)

    assert registry.drain_rate() == expected


def test_completions_that_did_not_run_do_not_feed_the_drain_rate(registry, clock):
    finish_one_every(registry, clock, 4, 1.0)
    finish_ran(registry, 20, ran=False)

    assert registry.drain_rate() is None


def test_completions_all_at_this_instant_give_no_drain_rate(registry):
    finish_ran(registry, 20)

    assert registry.drain_rate() is None


def test_a_slow_but_steady_drain_still_has_a_rate(registry, clock):
    finish_one_every(registry, clock, 6, 5.0)

    assert registry.drain_rate() == 6 / 25


def test_the_drain_rate_decays_while_nothing_finishes(registry, clock):
    finish_one_every(registry, clock, 20, 1.0)

    clock.advance(81)

    assert registry.drain_rate() == 20 / 100


def test_only_the_last_twenty_completions_are_kept(registry, clock):
    """Nothing reads the rate while a slot is free, so the record must bound itself."""
    finish_one_every(registry, clock, 1000, 60.0, prefix="slow")
    clock.advance(1)
    finish_one_every(registry, clock, 20, 1.0, prefix="fast")

    assert registry.drain_rate() == 20 / 19

