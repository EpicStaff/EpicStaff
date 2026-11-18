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


def assign(registry: ExecutionRegistry, execution_id: str, *, boot_id: str = "boot-1") -> None:
    registry.reserve(execution_id)
    registry.mark_queued(execution_id)
    registry.mark_assigned(execution_id, boot_id=boot_id)


def test_an_assigned_execution_still_reports_queued(registry):
    assign(registry, "exec-1")

    assert registry.status("exec-1") is ExecutionStatus.QUEUED
    assert registry.queued_count == 1
    assert registry.active_count == 1


def test_boots_with_assignments_lists_each_run_holding_jobs(registry):
    assign(registry, "exec-1", boot_id="boot-1")
    assign(registry, "exec-2", boot_id="boot-2")

    assert registry.boots_with_assignments() == {"boot-1", "boot-2"}

    registry.settle_assignment("exec-2")
    assert registry.boots_with_assignments() == {"boot-1"}


def test_releasing_a_boots_assignments_keeps_them_answering_queued(registry):
    assign(registry, "exec-1", boot_id="boot-1")
    assign(registry, "exec-2", boot_id="boot-2")

    released = registry.release_assignments_of_boots({"boot-1"})

    assert [item.execution_id for item in released] == ["exec-1"]
    assert registry.release_assignments_of_boots({"boot-1"}) == []
    assert registry.status("exec-1") is ExecutionStatus.QUEUED
    assert registry.boots_with_assignments() == {"boot-2"}


def test_assignments_of_other_worker_runs_are_released(registry):
    assign(registry, "exec-old", boot_id="boot-1")
    assign(registry, "exec-current", boot_id="boot-2")

    released = registry.release_assignments_not_from("boot-2")

    assert [item.execution_id for item in released] == ["exec-old"]
    assert registry.release_assignments_not_from("boot-2") == []
    assert registry.status("exec-old") is ExecutionStatus.QUEUED


def test_a_released_assignment_carries_its_result_routing_hints(registry):
    registry.reserve("exec-1")
    registry.mark_queued("exec-1")
    registry.mark_assigned("exec-1", boot_id="boot-1", session_id=7, reply_to_crew_channel=True)

    released = registry.release_assignments_not_from("boot-2")

    assert released == [("exec-1", 7, True)]


def test_an_assignment_unreported_twice_is_released_with_its_hints(registry, clock):
    registry.reserve("exec-1")
    registry.mark_queued("exec-1")
    registry.mark_assigned("exec-1", boot_id="boot-1", session_id=7, reply_to_crew_channel=True)
    clock.advance(31.0)

    assert registry.release_unreported_assignments("boot-1", set(), min_age=30.0) == []
    assert registry.release_unreported_assignments("boot-1", set(), min_age=30.0) == [
        ("exec-1", 7, True)
    ]


def test_a_single_missed_report_is_forgiven_once_the_job_is_reported_again(registry, clock):
    """A beat composed before the pull response arrived accounts for one miss; the next
    beat reports the job and must reset the count."""
    assign(registry, "exec-1")
    clock.advance(31.0)

    registry.release_unreported_assignments("boot-1", set(), min_age=30.0)
    registry.release_unreported_assignments("boot-1", {"exec-1"}, min_age=30.0)

    assert registry.release_unreported_assignments("boot-1", set(), min_age=30.0) == []


def test_a_reported_assignment_is_kept(registry, clock):
    assign(registry, "exec-1")

    clock.advance(31.0)

    assert registry.release_unreported_assignments("boot-1", {"exec-1"}, min_age=30.0) == []


def test_a_young_unreported_assignment_is_spared(registry, clock):
    assign(registry, "exec-1")

    clock.advance(29.9)

    assert registry.release_unreported_assignments("boot-1", set(), min_age=30.0) == []


def test_a_settled_assignment_answers_queued_until_finish(registry):
    assign(registry, "exec-1")

    assert registry.settle_assignment("exec-1") is True
    assert registry.status("exec-1") is ExecutionStatus.QUEUED

    registry.finish("exec-1", ran=True)
    assert registry.status("exec-1") is ExecutionStatus.DONE


def test_settling_an_unassigned_execution_is_refused(registry):
    assert registry.settle_assignment("exec-404") is False


def test_a_settled_assignment_is_no_longer_released_by_its_boots_death(registry):
    assign(registry, "exec-1")
    registry.settle_assignment("exec-1")

    assert registry.release_assignments_not_from("boot-2") == []


def test_a_finished_assignment_answers_done(registry):
    assign(registry, "exec-1")

    registry.finish("exec-1", ran=True)

    assert registry.status("exec-1") is ExecutionStatus.DONE
    assert (registry.active_count, registry.queued_count) == (0, 0)


def test_a_forgotten_assignment_is_unknown(registry):
    assign(registry, "exec-1")

    registry.forget("exec-1")

    assert registry.status("exec-1") is None
    assert registry.active_count == 0


def test_active_count_excluding_leaves_out_an_assigned_execution(registry):
    assign(registry, "exec-1")

    assert registry.active_count_excluding("exec-1") == 0


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


@pytest.mark.parametrize(
    ("excluded", "expected"),
    [("reserved", 1), ("queued", 1), ("held", 2), ("done", 2), ("unknown", 2)],
)
def test_active_count_excluding_leaves_out_only_that_active_execution(
    registry, excluded, expected
):
    for execution_id in ("reserved", "held", "queued", "done"):
        registry.reserve(execution_id)
    registry.mark_held("held")
    registry.mark_queued("queued")
    registry.finish("done", ran=True)

    assert registry.active_count_excluding(excluded) == expected


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
