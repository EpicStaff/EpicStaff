"""In-RAM record of every execution the sandbox has accepted and not yet forgotten.

Holds execution ids, states, timestamps and the result-routing hints a failure result
needs -- never a job payload, so nothing here can leak code, secrets or credentials. It
answers the status endpoint, rejects a second submission of a known id, feeds admission
control (how many executions are in flight, how many are held, how fast the queue
drains) and releases the assignments of worker runs that are gone. What the manager
knows about the worker itself (boot ids, contact, parked polls) lives in
``worker_contact.py``; this module only remembers which run each job was handed to.
Lives only in memory: a restart forgets everything, and a producer asking about a
forgotten id gets a 404 and fails fast instead of waiting.
"""

import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import NamedTuple

from manager.domain.enums import ExecutionStatus
from manager.domain.errors import ExecutionNotFoundError

__all__ = [
    "DRAIN_SAMPLE_SIZE",
    "MIN_DRAIN_SAMPLES",
    "TOMBSTONE_SECONDS",
    "ExecutionRegistry",
    "LostJob",
]


class LostJob(NamedTuple):
    """What a failure result needs about an assigned job its worker no longer holds."""

    execution_id: str
    session_id: int | None
    reply_to_crew_channel: bool


@dataclass
class _Assignment:
    """One job handed to a worker run, and how often that run failed to report it."""

    boot_id: str
    assigned_at: float
    lost: LostJob
    missed_reports: int = field(default=0)


# How long a finished execution still answers DONE before it is forgotten.
TOMBSTONE_SECONDS = 60.0
# The drain rate is measured over this many most recent completions; older ones are
# dropped as new ones arrive, so the record never grows past it.
DRAIN_SAMPLE_SIZE = 20
# Fewer real completions than this is a cold start: no drain rate yet.
MIN_DRAIN_SAMPLES = 5
# Heartbeat reports a job must be absent from, consecutively, before its assignment is
# released as a lost hand-off. Two: the second beat is composed only after the first was
# answered, so it post-dates any manager-side stall that delayed processing the first.
MISSED_REPORTS_TO_RELEASE = 2


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
        # Handed to a worker. Producers still see QUEUED; the distinction exists so a
        # vanished worker's jobs can be failed instead of waiting forever.
        self._assigned: dict[str, _Assignment] = {}
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
        if (
            execution_id in self._queued
            or execution_id in self._reserved
            or execution_id in self._assigned
        ):
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

    def mark_assigned(
        self,
        execution_id: str,
        *,
        boot_id: str,
        session_id: int | None = None,
        reply_to_crew_channel: bool = False,
    ) -> None:
        """Record that a worker took the execution; producers keep seeing QUEUED.

        There is no per-job deadline: a legitimate run may take hours, so the job is
        held against the worker run's liveness instead -- its boot id vanishing or
        going silent (per ``WorkerContact``) is what releases it.

        Args:
            boot_id: The worker run that took it.
            session_id: Routing hint echoed on the failure result if the job is lost.
            reply_to_crew_channel: Same; picks the channel the failure is published on.
        """
        self._queued.discard(execution_id)
        lost = LostJob(execution_id, session_id, reply_to_crew_channel)
        self._assigned[execution_id] = _Assignment(boot_id, self._clock(), lost)

    def boots_with_assignments(self) -> set[str]:
        """The worker runs currently holding jobs; the sweeper asks `WorkerContact`
        which of them went silent."""
        return {assignment.boot_id for assignment in self._assigned.values()}

    def release_assignments_of_boots(self, boot_ids: set[str]) -> list[LostJob]:
        """Return the jobs assigned to these worker runs, so the caller can fail them.

        Released ids move back to queued and keep answering QUEUED until their failure
        result lands and `finish` records them, so a polling producer never sees a 404 gap.
        """
        lost = [
            execution_id
            for execution_id, assignment in self._assigned.items()
            if assignment.boot_id in boot_ids
        ]
        return self._release_assignments(lost)

    def release_assignments_not_from(self, boot_id: str) -> list[LostJob]:
        """Return the executions assigned to any other worker run: that run is gone."""
        orphaned = [
            execution_id
            for execution_id, assignment in self._assigned.items()
            if assignment.boot_id != boot_id
        ]
        return self._release_assignments(orphaned)

    def release_unreported_assignments(
        self, boot_id: str, reported_ids: set[str], *, min_age: float
    ) -> list[LostJob]:
        """Return this run's assigned jobs it says it does not hold.

        The worker's heartbeat reports the execution ids it is actually running. An
        assignment missing from that report was lost on the way to the worker (its pull
        response never arrived), and nothing else would ever release it: the run keeps
        heartbeating, so it never goes silent. Two guards keep a live hand-off safe:
        ``min_age`` spares assignments younger than a couple of heartbeats, and release
        needs ``MISSED_REPORTS_TO_RELEASE`` consecutive missing reports -- a beat
        composed before the pull response arrived, delivered late through a manager
        stall, can account for one miss but not two.
        """
        now = self._clock()
        lost = []
        for execution_id, assignment in self._assigned.items():
            if assignment.boot_id != boot_id:
                continue
            if execution_id in reported_ids:
                assignment.missed_reports = 0
                continue
            if now - assignment.assigned_at <= min_age:
                continue
            assignment.missed_reports += 1
            if assignment.missed_reports >= MISSED_REPORTS_TO_RELEASE:
                lost.append(execution_id)
        return self._release_assignments(lost)

    def settle_assignment(self, execution_id: str) -> bool:
        """Take the execution back from its worker: its result just arrived.

        False when the id is not assigned -- a late or duplicate result whose job was
        already failed or finished; the caller must drop that result, not publish it.
        The settled id answers QUEUED until `finish` records the published result.
        """
        entry = self._assigned.pop(execution_id, None)
        if entry is None:
            return False
        self._queued.add(execution_id)
        return True

    def _release_assignments(self, execution_ids: list[str]) -> list[LostJob]:
        released = []
        for execution_id in execution_ids:
            released.append(self._assigned.pop(execution_id).lost)
            self._queued.add(execution_id)
        return released

    def forget(self, execution_id: str) -> None:
        """Drop the execution as if it had never been submitted."""
        self._reserved.discard(execution_id)
        self._held.discard(execution_id)
        self._queued.discard(execution_id)
        self._assigned.pop(execution_id, None)
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
        return len(self._reserved) + len(self._queued) + len(self._assigned)

    def active_count_excluding(self, execution_id: str) -> int:
        """`active_count` without this execution, so a caller can leave out its own reservation."""
        is_active = (
            execution_id in self._reserved
            or execution_id in self._queued
            or execution_id in self._assigned
        )
        return self.active_count - 1 if is_active else self.active_count

    @property
    def held_count(self) -> int:
        """Executions waiting for their venv to finish building."""
        return len(self._held)

    @property
    def queued_count(self) -> int:
        """Executions handed to the worker queue and not yet DONE, assigned/running included."""
        return len(self._queued) + len(self._assigned)

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
