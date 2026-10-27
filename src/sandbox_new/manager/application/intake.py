"""Admission control at the door: refuse work the sandbox cannot finish in time.

Four checks, all answered with `SandboxOverloadedError` (a 503 with `Retry-After`):

- A hard cap on executions in flight (reserved, queued or running), so a flood of
  submissions cannot grow memory without bound.
- A separate cap on held executions, those waiting for their venv to finish building.
  Held jobs never count toward the in-flight cap: one tenant whose venv rebuilds, or
  hangs while building, could otherwise fill every slot with jobs that cannot run and
  lock every other organization out. A held job that is released to the queue joins the
  in-flight count from then on.
- A queue-wait prediction for jobs that would be queued now: when no worker slot is
  free, the expected wait is the jobs ahead divided by the recent drain rate, and a job
  that would wait longer than the queue timeout is refused up front rather than failed
  later in the queue. With no drain rate yet (cold start) only the cap applies.
- A re-POST of an execution id whose first request is still being admitted: its outcome
  is not known yet, so the re-POST is told to come back rather than answered.

Every refusal is logged where it is made, as an `intake_refused` BENCH checkpoint with
its reason and Retry-After.
"""

import math
from typing import Literal

from loguru import logger
from src.shared.bench_log import BENCH_LEVEL

from manager.application.ports import FreeSlotProbe
from manager.application.registry import ExecutionRegistry
from manager.domain.errors import SandboxOverloadedError

__all__ = [
    "DEFAULT_RETRY_AFTER_SECONDS",
    "HELD_LIMIT_RETRY_AFTER_SECONDS",
    "MAX_RETRY_AFTER_SECONDS",
    "MIN_RETRY_AFTER_SECONDS",
    "SUBMISSION_IN_PROGRESS_RETRY_AFTER_SECONDS",
    "IntakeGate",
]

# Retry-After when there is no wait prediction to derive it from (a cap rejection).
DEFAULT_RETRY_AFTER_SECONDS = 5
# Retry-After when the held cap is reached. Held jobs leave only as venv builds finish,
# which takes far longer than a queue slot frees up, so the caller backs off longer.
HELD_LIMIT_RETRY_AFTER_SECONDS = 30
# A predicted Retry-After is never shorter than this, so a client does not spin.
MIN_RETRY_AFTER_SECONDS = 1
# Nor longer than this: the prediction gets less reliable the further out it looks.
MAX_RETRY_AFTER_SECONDS = 30
# A re-POST that arrives while the first request for its id is still being admitted is
# told to come back this soon: by then the first request has its outcome.
SUBMISSION_IN_PROGRESS_RETRY_AFTER_SECONDS = 1

type RefusalReason = Literal["cap", "prediction", "held_cap", "in_progress"]


class IntakeGate:
    def __init__(
        self,
        registry: ExecutionRegistry,
        has_free_slot: FreeSlotProbe,
        *,
        max_accepted: int,
        max_held: int,
        queue_timeout: float,
    ) -> None:
        self._registry = registry
        self._has_free_slot = has_free_slot
        self._max_accepted = max_accepted
        self._max_held = max_held
        self._queue_timeout = queue_timeout

    def check_not_in_progress(self, execution_id: str) -> None:
        """Refuse a re-POST while the first request for its id is still being admitted.

        That request may still be refused, so answering the re-POST QUEUED could promise
        a job that is never queued.

        Raises:
            SandboxOverloadedError: The id is reserved by a request not yet admitted.
        """
        if self._registry.is_reserved(execution_id):
            logger.info("Execution {} is still being admitted; re-POST told to retry", execution_id)
            raise self._refuse("in_progress", SUBMISSION_IN_PROGRESS_RETRY_AFTER_SECONDS)

    def check_capacity(self) -> None:
        """Refuse a request before its body is read when the in-flight cap is reached.

        Only the in-flight cap: before the body is read it is not known whether the job
        will be held, so the held cap is left to `admit`.

        Raises:
            SandboxOverloadedError: `max_accepted` executions are already in flight.
        """
        if self._registry.active_count >= self._max_accepted:
            raise self._refuse("cap", DEFAULT_RETRY_AFTER_SECONDS)

    def admit(self, *, will_be_held: bool) -> None:
        """Decide whether a submission that already holds a reservation may proceed.

        Args:
            will_be_held: Its venv is still building, so it waits outside the queue and
                its queue wait cannot be predicted yet; only the held cap applies.

        Raises:
            SandboxOverloadedError: The cap that applies to the job is reached, or the
                job would wait in the queue longer than the queue timeout.
        """
        if will_be_held:
            if self._registry.held_count >= self._max_held:
                raise self._refuse("held_cap", HELD_LIMIT_RETRY_AFTER_SECONDS)
            return
        # The caller's own reservation is already counted in active_count.
        if self._registry.active_count - 1 >= self._max_accepted:
            raise self._refuse("cap", DEFAULT_RETRY_AFTER_SECONDS)
        if self._has_free_slot():
            return
        drain_rate = self._registry.drain_rate()
        if drain_rate is None:
            return
        predicted_wait = (self._registry.queued_count + 1) / drain_rate
        if predicted_wait <= self._queue_timeout:
            return
        retry_after = math.ceil(predicted_wait - self._queue_timeout)
        raise self._refuse(
            "prediction", min(max(retry_after, MIN_RETRY_AFTER_SECONDS), MAX_RETRY_AFTER_SECONDS)
        )

    def _refuse(self, reason: RefusalReason, retry_after: int) -> SandboxOverloadedError:
        logger.log(
            BENCH_LEVEL,
            "bench {checkpoint}",
            checkpoint="intake_refused",
            reason=reason,
            retry_after=retry_after,
        )
        return SandboxOverloadedError(retry_after=retry_after)
