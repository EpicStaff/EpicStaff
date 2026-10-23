"""Runs an execution's steps in order and keeps the worker alive on failure.

A step is anything callable as ``async (context) -> None`` -- a class instance with an
async ``__call__`` or a plain async function. Steps mutate the shared
``ExecutionContext`` instead of returning values. Running stops at the first step
that marks the context complete (a refusal or the final capture) and a raised
exception is caught and turned into a failure outcome, honoring the rule that the
worker returns errors rather than crashing on them.
"""

from typing import Protocol, runtime_checkable

from worker.application.context import ExecutionContext

__all__ = ["Pipeline", "Step"]


@runtime_checkable
class Step(Protocol):
    async def __call__(self, context: ExecutionContext) -> None: ...


class Pipeline:
    def __init__(self) -> None:
        self._steps: list[Step] = []

    def register(self, step: Step) -> "Pipeline":
        self._steps.append(step)
        return self

    async def run(self, context: ExecutionContext) -> ExecutionContext:
        for step in self._steps:
            try:
                await step(context)
            except Exception as error:
                context.fail(error)
                break
            if context.completed:
                break

        if not context.completed:
            context.fail(RuntimeError("Execution pipeline produced no result."))

        return context
