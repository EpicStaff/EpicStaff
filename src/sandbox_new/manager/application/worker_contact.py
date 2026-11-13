"""What the manager knows about the worker as a counterpart: who called, and when.

One place for every fact that is about the WORKER rather than about executions: which
run (boot id) is the live one, when each run was last heard from, and how many of its
long-polls are parked waiting for work. The execution registry stays about executions;
the worker-loss sweeper combines the two ("which boots hold assignments" from the
registry, "which of them went silent" from here).

Liveness is judged from contact alone, never from how long a job runs -- job duration
is unknown by design (a legitimate run may take hours). A worker run proves it is alive
by reaching any /worker endpoint; a run that restarts shows up as a new boot id, and
one that hangs stops making contact.
"""

import time
from collections.abc import Callable

__all__ = ["SUPERSEDED_BOOT_MEMORY_SECONDS", "WorkerContact"]

# How long a superseded boot id is still refused. Covers the longest a zombie request of
# that run can stay in flight: one long-poll (~25 s) plus client and network timeouts.
SUPERSEDED_BOOT_MEMORY_SECONDS = 60.0


class WorkerContact:
    """Track the worker's boot ids, their last contact, and the parked long-polls.

    Every method is synchronous, like the execution registry's, so callers that check
    and record without awaiting in between cannot race one another.
    """

    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        # Worker run's boot id -> the clock reading of its latest contact.
        self._last_seen: dict[str, float] = {}
        # Any worker contact at all; starts at creation so a fresh manager does not
        # declare the worker lost before it had a chance to say hello.
        self._last_worker_contact = self._clock()
        # The newest worker run, and when each older run was superseded. A request from
        # a superseded run is a zombie (a long poll whose connection died); zombies are
        # remembered by AGE, not count, because a crash loop can supersede any number of
        # runs while one zombie is still in flight.
        self._current_boot_id: str | None = None
        self._superseded_boot_ids: dict[str, float] = {}
        # Long-polls currently parked on the job queue under the live boot id. With the
        # worker taking a run-gate slot before it pulls, a waiting poller IS a free
        # slot, which makes this the intake's free-slot probe.
        self._waiting_pollers = 0

    def record_seen(self, boot_id: str) -> None:
        """Note that this worker run just made contact; its assigned jobs are alive."""
        now = self._clock()
        self._last_seen[boot_id] = now
        self._last_worker_contact = now

    def accept_boot(self, boot_id: str) -> bool:
        """Say whether a request under this boot id may be served a job.

        The first request of a new run supersedes the current one; False means the id
        belongs to a recently superseded run -- a zombie long-poll whose connection
        died -- and a job must not be handed to it. Superseded ids are remembered by
        age: a zombie outlives its run by one long-poll plus network timeouts at most,
        while a crash loop can supersede any number of runs in that same window.
        """
        now = self._clock()
        if boot_id == self._current_boot_id:
            return True
        superseded_at = self._superseded_boot_ids.get(boot_id)
        if superseded_at is not None and now - superseded_at <= SUPERSEDED_BOOT_MEMORY_SECONDS:
            return False
        self._superseded_boot_ids = {
            old_id: at
            for old_id, at in self._superseded_boot_ids.items()
            if now - at <= SUPERSEDED_BOOT_MEMORY_SECONDS
        }
        if self._current_boot_id is not None:
            self._superseded_boot_ids[self._current_boot_id] = now
        self._current_boot_id = boot_id
        return True

    def boot_is_silent(self, boot_id: str, silence_threshold: float) -> bool:
        """True when this run has not been heard from for longer than the threshold.

        A run that never made contact at all counts as silent: an assignment can only
        exist because its run once pulled, so no record here means the record is long
        gone -- or the state is inconsistent, and failing the job is the safe answer.
        """
        return self._clock() - self._last_seen.get(boot_id, 0.0) > silence_threshold

    def worker_is_silent(self, silence_threshold: float) -> bool:
        """True when no worker run at all has made contact for longer than the threshold.

        Counted from this object's creation before the first contact, so a fresh
        manager gives the worker the same grace to say hello.
        """
        return self._clock() - self._last_worker_contact > silence_threshold

    def add_waiting_poller(self) -> None:
        """One more long-poll is parked on the job queue under the live boot id."""
        self._waiting_pollers += 1

    def remove_waiting_poller(self) -> None:
        self._waiting_pollers = max(0, self._waiting_pollers - 1)

    @property
    def waiting_pollers(self) -> int:
        """Long-polls waiting for a job right now; each one is a free worker slot."""
        return self._waiting_pollers
