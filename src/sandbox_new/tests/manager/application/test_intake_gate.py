"""Behavior of the intake gate -- when a submission is refused with 503.

A job that would be queued is judged on the in-flight cap and, with no free worker
slot, also refused when the predicted queue wait, (queued + 1) / drain rate, exceeds the
queue timeout; a cold start (no drain rate yet) is judged on the cap only. A job that
would be held is judged on the held cap only, and held jobs never count toward the
in-flight cap -- otherwise one tenant's venv stuck building could lock out every org.
"""

import pytest

from manager.application.intake import IntakeGate
from manager.application.registry import ExecutionRegistry
from manager.domain.errors import SandboxOverloadedError

QUEUE_TIMEOUT = 10.0


@pytest.fixture
def registry(clock) -> ExecutionRegistry:
    return ExecutionRegistry(clock=clock)


def build_gate(
    registry, *, free_slot: bool = False, max_accepted: int = 300, max_held: int = 100
) -> IntakeGate:
    return IntakeGate(
        registry,
        lambda: free_slot,
        max_accepted=max_accepted,
        max_held=max_held,
        queue_timeout=QUEUE_TIMEOUT,
    )


def drain_one_per_second(registry: ExecutionRegistry, clock) -> None:
    """Record 20 real completions one second apart, then a second: a drain rate of 1/s."""
    for index in range(20):
        registry.reserve(f"done-{index}")
        registry.finish(f"done-{index}", ran=True)
        clock.advance(1)


def queue(registry: ExecutionRegistry, count: int) -> None:
    for index in range(count):
        registry.reserve(f"queued-{index}")
        registry.mark_queued(f"queued-{index}")


def hold(registry: ExecutionRegistry, count: int) -> None:
    for index in range(count):
        registry.reserve(f"held-{index}")
        registry.mark_held(f"held-{index}")


def reserve_caller(registry: ExecutionRegistry) -> None:
    registry.reserve("caller")


def test_check_capacity_refuses_at_the_cap_with_the_default_retry_after(registry):
    queue(registry, 2)

    with pytest.raises(SandboxOverloadedError) as raised:
        build_gate(registry, max_accepted=2).check_capacity()

    assert raised.value.retry_after == 5


def test_check_capacity_lets_a_request_through_below_the_cap(registry):
    queue(registry, 1)

    build_gate(registry, max_accepted=2).check_capacity()


def test_admit_does_not_count_the_callers_own_reservation(registry):
    queue(registry, 1)
    reserve_caller(registry)

    build_gate(registry, free_slot=True, max_accepted=2).admit(will_be_held=False)


def test_admit_refuses_at_the_cap_even_with_a_free_slot(registry):
    queue(registry, 2)
    reserve_caller(registry)

    with pytest.raises(SandboxOverloadedError) as raised:
        build_gate(registry, free_slot=True, max_accepted=2).admit(will_be_held=False)

    assert raised.value.retry_after == 5


def test_a_held_job_is_admitted_while_the_in_flight_cap_is_full(registry):
    queue(registry, 2)
    reserve_caller(registry)

    build_gate(registry, max_accepted=2, max_held=2).admit(will_be_held=True)


def test_a_held_job_is_refused_at_the_held_cap_with_a_30_second_retry_after(registry):
    hold(registry, 2)
    reserve_caller(registry)

    with pytest.raises(SandboxOverloadedError) as raised:
        build_gate(registry, free_slot=True, max_held=2).admit(will_be_held=True)

    assert raised.value.retry_after == 30


def test_a_held_job_is_admitted_just_below_the_held_cap(registry):
    hold(registry, 1)
    reserve_caller(registry)

    build_gate(registry, max_held=2).admit(will_be_held=True)


def test_a_job_to_queue_is_admitted_while_the_held_cap_is_full(registry):
    hold(registry, 2)
    reserve_caller(registry)

    build_gate(registry, free_slot=True, max_accepted=2, max_held=2).admit(will_be_held=False)


def test_check_capacity_does_not_count_held_jobs(registry):
    hold(registry, 5)

    build_gate(registry, max_accepted=2, max_held=5).check_capacity()


def test_a_free_slot_admits_whatever_the_prediction(registry, clock):
    drain_one_per_second(registry, clock)
    queue(registry, 50)
    reserve_caller(registry)

    build_gate(registry, free_slot=True).admit(will_be_held=False)


def test_a_held_job_is_not_judged_on_the_prediction(registry, clock):
    drain_one_per_second(registry, clock)
    queue(registry, 50)
    reserve_caller(registry)

    build_gate(registry).admit(will_be_held=True)


def test_a_cold_start_is_judged_on_the_cap_only(registry):
    queue(registry, 50)
    reserve_caller(registry)

    build_gate(registry).admit(will_be_held=False)


def test_a_predicted_wait_within_the_queue_timeout_is_admitted(registry, clock):
    drain_one_per_second(registry, clock)
    # 9 ahead + the caller = 10 s at 1/s: exactly the timeout.
    queue(registry, 9)
    reserve_caller(registry)

    build_gate(registry).admit(will_be_held=False)


@pytest.mark.parametrize(
    ("queued", "retry_after"),
    [(10, 1), (12, 3), (100, 30)],
    ids=["just-over-is-at-least-1", "overshoot-rounded-up", "capped-at-30"],
)
def test_a_predicted_wait_over_the_queue_timeout_is_refused(
    registry, clock, queued, retry_after
):
    drain_one_per_second(registry, clock)
    queue(registry, queued)
    reserve_caller(registry)

    with pytest.raises(SandboxOverloadedError) as raised:
        build_gate(registry).admit(will_be_held=False)

    assert raised.value.retry_after == retry_after


def test_a_drain_that_stalled_refuses_what_it_once_admitted(registry, clock):
    """Every slot held by a long job: nothing finishes, so the rate decays and the
    prediction refuses instead of switching off."""
    drain_one_per_second(registry, clock)
    queue(registry, 5)
    reserve_caller(registry)
    build_gate(registry).admit(will_be_held=False)

    # 20 completions over 80 s: 0.25/s, so the caller and the 5 ahead wait 24 s.
    clock.advance(60)

    with pytest.raises(SandboxOverloadedError) as raised:
        build_gate(registry).admit(will_be_held=False)

    assert raised.value.retry_after == 14
