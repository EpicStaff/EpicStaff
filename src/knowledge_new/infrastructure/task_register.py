import asyncio

__all__ = ["TaskRegister", "task_register"]


class TaskRegister:
    def __init__(self):
        self._tasks: dict[str, asyncio.Task] = {}

    def register(self, key: str, task: asyncio.Task):
        if (registered_task := self._tasks.get(key)) is not None:
            registered_task.cancel()
        self._tasks[key] = task
        task.add_done_callback(lambda *args: self._discard_if_current(key, task))

    def cancel(self, key: str, *, msg="") -> bool:
        if (task := self._tasks.get(key)) is not None:
            return task.cancel(msg)
        return False

    def _discard_if_current(self, key: str, task: asyncio.Task):
        if self._tasks.get(key) is task:
            del self._tasks[key]