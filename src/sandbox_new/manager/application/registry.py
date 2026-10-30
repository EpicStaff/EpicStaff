"""In-RAM record of every execution the sandbox has accepted and not yet forgotten.

Holds execution ids, states and timestamps only -- never a job payload, so nothing here
can leak code, secrets or credentials. It answers the status endpoint, rejects a second
submission of a known id, and feeds admission control (how many executions are in
flight, how many are held, how fast the queue drains). Lives only in memory: a restart
forgets everything, and a producer asking about a forgotten id gets a 404 and fails fast
instead of waiting.
"""

import time
from collections import deque
from collections.abc import Callable

from manager.domain.enums import ExecutionStatus
from manager.domain.errors import ExecutionNotFoundError

__all__ = [
    "DRAIN_SAMPLE_SIZE",
    "MIN_DRAIN_SAMPLES",
    "TOMBSTONE_SECONDS",
    "ExecutionRegistry",
]

# How long a finished execution still answers DONE before it is forgotten.
TOMBSTONE_SECONDS = 60.0
# The drain rate is measured over this many most recent completions; older ones are
# dropped as new ones arrive, so the record never grows past it.
DRAIN_SAMPLE_SIZE = 20
# Fewer real completions than this is a cold start: no drain rate yet.
MIN_DRAIN_SAMPLES = 5


class ExecutionRegistry:
    """Track each accepted execution from reservation to a short-lived DONE tombstone.

    Every method is synchronous, so a caller that checks and reserves an id without
    awaiting in between cannot race another request for the same id.
    """

    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        # Accepted, but not yet held or queued: the venv is still being looked up.
        self._reserved: set[str] = set()
        self._held: set[str] = set()
        self._queued: set[str] = set()
        # Execution id -> moment its tombstone expires. Every tombstone lives equally
        # long, so insertion order is expiry order and eviction only looks at the front.
        self._done: dict[str, float] = {}
        # Moments of the most recent completions that ran, oldest first.
        self._completions: deque[float] = deque(maxlen=DRAIN_SAMPLE_SIZE)

    def status(self, execution_id: str) -> ExecutionStatus | None:
        """Return where the execution is, or None when the sandbox does not know it.

        A reservation reports QUEUED: it is accepted and on its way to the queue.
        """
        self._evict_expired_tombstones()
        if execution_id in self._done:
            return ExecutionStatus.DONE
        if execution_id in self._held:
            return ExecutionStatus.HELD
        if execution_id in self._queued or execution_id in self._reserved:
            return ExecutionStatus.QUEUED
        return None

    def get_status(self, execution_id: str) -> ExecutionStatus:
        """Return where the execution is.

        Raises:
            ExecutionNotFoundError: The sandbox does not know the execution.
        """
        status = self.status(execution_id)
        if status is None:
            raise ExecutionNotFoundError(execution_id)
        return status

    def is_reserved(self, execution_id: str) -> bool:
        """True while the submission that claimed the id has not been held or queued yet."""
        return execution_id in self._reserved

    def reserve(self, execution_id: str) -> bool:
        """Claim the id for a new submission; False when it is already known, DONE included."""
        if self.status(execution_id) is not None:
            return False
        self._reserved.add(execution_id)
        return True

    def mark_held(self, execution_id: str) -> None:
        self._reserved.discard(execution_id)
        self._held.add(execution_id)

    def mark_queued(self, execution_id: str) -> None:
        self._reserved.discard(execution_id)
        self._held.discard(execution_id)
        self._queued.add(execution_id)

    def forget(self, execution_id: str) -> None:
        """Drop the execution as if it had never been submitted."""
        self._reserved.discard(execution_id)
        self._held.discard(execution_id)
        self._queued.discard(execution_id)
        self._done.pop(execution_id, None)

    def finish(self, execution_id: str, *, ran: bool) -> None:
        """Record that the execution's result was handed on; it answers DONE for a while.

        Args:
            ran: The worker really executed it. Only these completions feed the drain
                rate: a job failed before it ran freed no worker slot.
        """
        now = self._clock()
        self.forget(execution_id)
        self._done[execution_id] = now + TOMBSTONE_SECONDS
        self._evict_expired_tombstones()
        if ran:
            self._completions.append(now)

    @property
    def active_count(self) -> int:
        """Executions accepted, not held and not yet DONE: reserved, queued or running.

        Held executions are left out: they wait on a venv build, not on a worker, and
        are counted apart by `held_count`.
        """
        return len(self._reserved) + len(self._queued)

    def active_count_excluding(self, execution_id: str) -> int:
        """`active_count` without this execution, so a caller can leave out its own reservation."""
        is_active = execution_id in self._reserved or execution_id in self._queued
        return self.active_count - 1 if is_active else self.active_count

    @property
    def held_count(self) -> int:
        """Executions waiting for their venv to finish building."""
        return len(self._held)

    @property
    def queued_count(self) -> int:
        """Executions handed to the worker queue and not yet DONE, running ones included."""
        return len(self._queued)

    def drain_rate(self) -> float | None:
        """Executions completed per second, from the oldest recent completion until now.

        The span ends now rather than at the latest completion, so the rate decays while
        nothing finishes (every slot held by a long job) and the queue-wait prediction
        refuses work instead of switching off. None on a cold start: fewer than
        `MIN_DRAIN_SAMPLES` completions, or none of them before now.
        """
        if len(self._completions) < MIN_DRAIN_SAMPLES:
            return None
        elapsed = self._clock() - self._completions[0]
        if elapsed <= 0:
            return None
        return len(self._completions) / elapsed

    def _evict_expired_tombstones(self) -> None:
        now = self._clock()
        while self._done:
            oldest_id, expires_at = next(iter(self._done.items()))
            if expires_at > now:
                return
            del self._done[oldest_id]
