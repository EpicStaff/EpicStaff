"""Behavior of the intake gate -- when a submission is refused with 503.

A job that would be queued is judged on the in-flight cap and, with no free worker
slot, also refused when the predicted queue wait, (queued + 1) / drain rate, exceeds the
queue timeout; a cold start (no drain rate yet) is judged on the cap only. A worker slot
is free while the executions in flight are fewer than the guaranteed slots the worker
reported, so a burst up to that many starts at once whatever the prediction says. A job that
would be held is judged on the held cap only, and held jobs never count toward the
in-flight cap -- otherwise one tenant's venv stuck building could lock out every org.
"""

import pytest

from manager.application.intake import IntakeGate
from manager.application.registry import ExecutionRegistry
from manager.domain.errors import SandboxOverloadedError

QUEUE_TIMEOUT = 10.0
# More guaranteed slots than any test puts in flight: a worker slot is always free.
PLENTY_OF_SLOTS = 1000


@pytest.fixture
def registry(clock) -> ExecutionRegistry:
    return ExecutionRegistry(clock=clock)


def build_gate(
    registry,
    *,
    guaranteed_slots: int | None = None,
    max_accepted: int = 300,
    max_held: int = 100,
) -> IntakeGate:
    return IntakeGate(
        registry,
        lambda: guaranteed_slots,
        max_accepted=max_accepted,
        max_held=max_held,
        queue_timeout=QUEUE_TIMEOUT,
    )


def drain_one_per_second(registry: ExecutionRegistry, clock) -> None:
    """Queue 20 jobs, then finish them one second apart: a drain rate of 20/19 per second.

    The sandbox is busy from the first job to the last completion -- 19 s -- and idle
    for the second after it, which the drain rate leaves out.
    """
    queue(registry, 20, prefix="done")
    for index in range(20):
        if index:
            clock.advance(1)
        registry.finish(f"done-{index}", ran=True)
    clock.advance(1)


def queue(registry: ExecutionRegistry, count: int, *, prefix: str = "queued") -> None:
    for index in range(count):
        registry.reserve(f"{prefix}-{index}")
        registry.mark_queued(f"{prefix}-{index}")


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

    build_gate(registry, guaranteed_slots=PLENTY_OF_SLOTS, max_accepted=2).admit(
            "caller", will_be_held=False
        )


def test_admit_refuses_at_the_cap_even_with_a_free_slot(registry):
    queue(registry, 2)
    reserve_caller(registry)

    with pytest.raises(SandboxOverloadedError) as raised:
        build_gate(registry, guaranteed_slots=PLENTY_OF_SLOTS, max_accepted=2).admit(
            "caller", will_be_held=False
        )

    assert raised.value.retry_after == 5


def test_a_held_job_is_admitted_while_the_in_flight_cap_is_full(registry):
    queue(registry, 2)
    reserve_caller(registry)

    build_gate(registry, max_accepted=2, max_held=2).admit("caller", will_be_held=True)


def test_a_held_job_is_refused_at_the_held_cap_with_a_30_second_retry_after(registry):
    hold(registry, 2)
    reserve_caller(registry)

    with pytest.raises(SandboxOverloadedError) as raised:
        build_gate(registry, guaranteed_slots=PLENTY_OF_SLOTS, max_held=2).admit(
            "caller", will_be_held=True
        )

    assert raised.value.retry_after == 30


def test_a_held_job_is_admitted_just_below_the_held_cap(registry):
    hold(registry, 1)
    reserve_caller(registry)

    build_gate(registry, max_held=2).admit("caller", will_be_held=True)


def test_a_job_to_queue_is_admitted_while_the_held_cap_is_full(registry):
    hold(registry, 2)
    reserve_caller(registry)

    build_gate(
        registry, guaranteed_slots=PLENTY_OF_SLOTS, max_accepted=2, max_held=2
    ).admit("caller", will_be_held=False)


def test_check_capacity_does_not_count_held_jobs(registry):
    hold(registry, 5)

    build_gate(registry, max_accepted=2, max_held=5).check_capacity()


def test_a_free_slot_admits_whatever_the_prediction(registry, clock):
    drain_one_per_second(registry, clock)
    queue(registry, 50)
    reserve_caller(registry)

    build_gate(registry, guaranteed_slots=PLENTY_OF_SLOTS).admit("caller", will_be_held=False)


def test_a_held_job_is_not_judged_on_the_prediction(registry, clock):
    drain_one_per_second(registry, clock)
    queue(registry, 50)
    reserve_caller(registry)

    build_gate(registry).admit("caller", will_be_held=True)


def test_a_cold_start_is_judged_on_the_cap_only(registry):
    queue(registry, 50)
    reserve_caller(registry)

    build_gate(registry).admit("caller", will_be_held=False)


def test_a_predicted_wait_within_the_queue_timeout_is_admitted(registry, clock):
    drain_one_per_second(registry, clock)
    # 9 ahead + the caller = 10 s at 1/s: exactly the timeout.
    queue(registry, 9)
    reserve_caller(registry)

    build_gate(registry).admit("caller", will_be_held=False)


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
        build_gate(registry).admit("caller", will_be_held=False)

    assert raised.value.retry_after == retry_after


def test_a_drain_that_stalled_refuses_what_it_once_admitted(registry, clock):
    """Every slot held by a long job: nothing finishes, so the rate decays and the
    prediction refuses instead of switching off."""
    drain_one_per_second(registry, clock)
    queue(registry, 5)
    reserve_caller(registry)
    build_gate(registry).admit("caller", will_be_held=False)

    # 20 completions over 79 s of work: about 0.25/s, so the caller and the 5 ahead
    # wait about 24 s.
    clock.advance(60)

    with pytest.raises(SandboxOverloadedError) as raised:
        build_gate(registry).admit("caller", will_be_held=False)

    assert raised.value.retry_after == 14


def test_a_burst_after_a_quiet_hour_is_judged_on_the_rate_before_it(registry, clock):
    """The hour with nothing to run is not counted as a slow drain: at 20/19 per second
    the caller and the 9 ahead wait about 9.5 s, inside the queue timeout."""
    drain_one_per_second(registry, clock)
    clock.advance(3600)
    queue(registry, 9)
    reserve_caller(registry)

    build_gate(registry).admit("caller", will_be_held=False)


@pytest.mark.parametrize(
    ("reserved_by_others", "guaranteed_slots", "admitted"),
    [
        (0, 11, True),
        (0, 10, False),
        (1, 11, False),
        (1, 12, True),
        (0, None, False),
    ],
    ids=[
        "below-the-slots",
        "at-the-slots",
        "other-reservations-take-slots",
        "below-the-slots-with-a-reservation",
        "no-heartbeat-yet",
    ],
)
def test_a_free_worker_slot_admits_a_job_the_prediction_would_refuse(
    registry, clock, reserved_by_others, guaranteed_slots, admitted
):
    # 10 queued + the caller at 20/19 per second: about 10.5 s, over the queue timeout.
    drain_one_per_second(registry, clock)
    queue(registry, 10)
    for index in range(reserved_by_others):
        registry.reserve(f"other-{index}")
    reserve_caller(registry)
    gate = build_gate(registry, guaranteed_slots=guaranteed_slots)

    if admitted:
        gate.admit("caller", will_be_held=False)
    else:
        with pytest.raises(SandboxOverloadedError):
            gate.admit("caller", will_be_held=False)


def test_a_burst_right_after_a_heartbeat_gets_the_guaranteed_slots_and_no_more(
    registry, clock
):
    """The prediction alone admits 9 of the burst; the 16 guaranteed slots admit 16,
    and the 17th is judged on the prediction again."""
    drain_one_per_second(registry, clock)
    gate = build_gate(registry, guaranteed_slots=16)
    admitted = 0
    for index in range(20):
        execution_id = f"burst-{index}"
        registry.reserve(execution_id)
        try:
            gate.admit(execution_id, will_be_held=False)
        except SandboxOverloadedError:
            registry.forget(execution_id)
            continue
        registry.mark_queued(execution_id)
        admitted += 1

    assert admitted == 16


def test_a_re_post_of_an_id_still_being_admitted_is_refused(registry):
    registry.reserve("exec-1")

    with pytest.raises(SandboxOverloadedError) as raised:
        build_gate(registry).check_not_in_progress("exec-1")

    assert raised.value.retry_after == 1


def test_a_post_of_an_id_not_being_admitted_passes(registry):
    registry.reserve("exec-1")
    registry.mark_queued("exec-1")

    build_gate(registry).check_not_in_progress("exec-1")
    build_gate(registry).check_not_in_progress("exec-2")


def refuse_on_the_cap_before_the_body(gate: IntakeGate, registry, clock) -> None:
    queue(registry, 1)
    gate.check_capacity()


def refuse_on_the_cap_after_the_body(gate: IntakeGate, registry, clock) -> None:
    queue(registry, 1)
    reserve_caller(registry)
    gate.admit("caller", will_be_held=False)


def refuse_on_the_prediction(gate: IntakeGate, registry, clock) -> None:
    drain_one_per_second(registry, clock)
    queue(registry, 10)
    reserve_caller(registry)
    gate.admit("caller", will_be_held=False)


def refuse_on_the_held_cap(gate: IntakeGate, registry, clock) -> None:
    hold(registry, 1)
    gate.admit("caller", will_be_held=True)


def refuse_a_re_post_in_progress(gate: IntakeGate, registry, clock) -> None:
    reserve_caller(registry)
    gate.check_not_in_progress("caller")


def refusals_logged(checkpoints: list[dict]) -> list[dict]:
    return [item for item in checkpoints if item["checkpoint"] == "intake_refused"]


@pytest.mark.parametrize(
    ("refuse", "limits", "reason", "retry_after"),
    [
        (refuse_on_the_cap_before_the_body, {"max_accepted": 1}, "cap", 5),
        (refuse_on_the_cap_after_the_body, {"max_accepted": 1}, "cap", 5),
        (refuse_on_the_prediction, {}, "prediction", 1),
        (refuse_on_the_held_cap, {"max_held": 1}, "held_cap", 30),
        (refuse_a_re_post_in_progress, {}, "in_progress", 1),
    ],
)
def test_each_refusal_is_logged_once_with_its_reason_and_retry_after(
    registry, clock, checkpoints, refuse, limits, reason, retry_after
):
    with pytest.raises(SandboxOverloadedError):
        refuse(build_gate(registry, **limits), registry, clock)

    assert refusals_logged(checkpoints) == [
        {"checkpoint": "intake_refused", "reason": reason, "retry_after": retry_after}
    ]


def test_an_admitted_submission_is_not_logged_as_a_refusal(registry, checkpoints):
    gate = build_gate(registry, guaranteed_slots=PLENTY_OF_SLOTS)
    reserve_caller(registry)

    gate.check_not_in_progress("other")
    gate.check_capacity()
    gate.admit("caller", will_be_held=False)

    assert refusals_logged(checkpoints) == []
