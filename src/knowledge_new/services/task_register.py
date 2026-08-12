import asyncio
from pydantic import BaseModel
from utils import hash_dict

__all__ = ["TaskRegister", "task_register", "run_cancellable"]


class TaskRegister:
    def __init__(self):
        self._task: dict[str, asyncio.Task] = {}
        self._pending_to_cancel: set[str] = set()

    def register(self, key: str, task: asyncio.Task):
        if key in self._pending_to_cancel:
            self._pending_to_cancel.discard(key)
            task.cancel(msg="Cancelled before registration.")
        else:
            self._task[key] = task

    def discard(self, key: str):
        self._task.pop(key, None)

    def cancel(self, key: str, *, msg="") -> bool:
        task = self._task.get(key)
        if task is None:
            self._pending_to_cancel.add(key)
            return False
        return task.cancel(msg)

    def __contains__(self, key):
        return key in self._task


task_register = TaskRegister()


async def run_cancellable(request: BaseModel, coro):
    key = hash_dict(request.model_dump())
    if key in task_register:
        task_register.cancel(key)
    task_register.register(key, asyncio.current_task())
    try:
        return await coro
    finally:
        task_register.discard(key)
