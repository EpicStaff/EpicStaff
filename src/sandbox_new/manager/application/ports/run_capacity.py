"""The port intake uses to learn how many jobs the worker always starts at once.

A plain callable, not a class: intake needs one number and nothing else. The worker
reports it in its heartbeat; intake subtracts the executions in flight, so a job that
would start at once is never refused on a queue-wait prediction.
"""

from collections.abc import Callable

__all__ = ["WorkerSlots"]

# The worker's guaranteed slots, or None before the worker has reported them.
type WorkerSlots = Callable[[], int | None]
