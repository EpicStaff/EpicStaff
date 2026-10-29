INITIAL_DELAY_SECONDS = 1.0
MAXIMUM_DELAY_SECONDS = 300.0
FAILURE_RESTARTS = 10
STABLE_AFTER_SECONDS = 60.0


class RestartPolicy:
    """When to restart a plugin process that stopped on its own, and when to give up.

    - Backoff: 1 s before the first restart, doubling for each further restart in a row,
      at most 5 minutes. A process that stayed healthy for a minute (`mark_stable`) starts the
      count over, so backoff follows unhealthy restarts only.
    - Failed: after 10 restarts in a row with no stable run between them, the next stop leaves
      the process stopped (`failed`) instead of restarting it, whatever the timing. One stable
      run resets the count, so a plugin that runs fine for a while and then crashes is given
      its ten restarts again.
    """

    def __init__(
        self,
        *,
        initial_delay: float = INITIAL_DELAY_SECONDS,
        maximum_delay: float = MAXIMUM_DELAY_SECONDS,
        failure_restarts: int = FAILURE_RESTARTS,
    ):
        self._initial_delay = initial_delay
        self._maximum_delay = maximum_delay
        self._failure_restarts = failure_restarts
        self._consecutive_unstable = 0
        self.restarts = 0
        """Restarts since the last deliberate start, as the node reports them."""

    def next_delay(self) -> float | None:
        """Record that the process stopped on its own.

        Returns:
            Seconds to wait before restarting it, or None when it has reached `failed` (ten
            restarts in a row without a stable run between them).
        """
        if self._consecutive_unstable >= self._failure_restarts:
            return None
        delay = min(self._initial_delay * 2**self._consecutive_unstable, self._maximum_delay)
        self._consecutive_unstable += 1
        self.restarts += 1
        return delay

    def mark_stable(self) -> None:
        """The process stayed healthy long enough: the next restart waits 1 s and the count resets."""
        self._consecutive_unstable = 0

    def reset(self) -> None:
        """A deliberate start: forget every earlier restart."""
        self._consecutive_unstable = 0
        self.restarts = 0
