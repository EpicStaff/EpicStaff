import asyncio

__all__ = ["TaskRegister", "task_register"]


class TaskRegister:
    def __init__(self):
        self._task: dict[str, asyncio.Task] = {}

    def register(self, key: str, task: asyncio.Task):
        self._task[key] = task

    def discard(self, key: str):
        self._task.pop(key, None)

    def cancel(self, key: str, *, msg="") -> bool:
        task = self._task.get(key)
        if task is None:
            return False
        return task.cancel(msg)

    def __contains__(self, key):
        return key in self._task


task_register = TaskRegister()
