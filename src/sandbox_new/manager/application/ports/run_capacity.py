"""The port intake uses to ask the worker whether it could start a job right now.

A plain callable, not a class: intake needs one yes/no answer and nothing else. The
worker's admission gate supplies it, so a job that would start at once is never refused
on a queue-wait prediction.
"""

from collections.abc import Callable

__all__ = ["FreeSlotProbe"]

type FreeSlotProbe = Callable[[], bool]
