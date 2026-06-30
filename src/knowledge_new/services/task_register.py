import asyncio

__all__ = ["task_register"]


class TaskRegister:
    """In-memory registry of in-flight handler tasks keyed by request hash.

    Cancellable handlers register their running `asyncio.Task` while processing a
    request; an out-of-band cancel request looks the task up by the same key and
    cancels it, raising `asyncio.CancelledError` inside the running handler.
    """

    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task] = {}

    def register(self, key: str, task: asyncio.Task | None) -> None:
        if task is not None:
            self._tasks[key] = task

    def discard(self, key: str) -> None:
        self._tasks.pop(key, None)

    def cancel(self, key: str) -> bool:
        """Cancel the task registered under `key`. Returns whether a cancel was requested."""
        task = self._tasks.get(key)
        if task is None or task.done():
            return False
        return task.cancel()


task_register = TaskRegister()
