"""Recording stand-ins for every transport port on both sides of the seam.

Each one records what it was handed and can be told to fail, which is how the tests
cover the "transport broke" branches without a real queue or broker.
"""

import asyncio

from common.contracts import ExecutionResultMessage
from manager.application.ports import AbstractJobDispatcher, AbstractJobFailureSink
from manager.domain.models import Job as ManagerJob
from manager.infrastructure.transport.result_publisher import AbstractResultPublisher
from worker.application.ports import AbstractJobSource, AbstractResultSink, UndecodableJobError
from worker.domain.models import ExecutionResult, Job as WorkerJob, StorageMutations

__all__ = [
    "FakeJobDispatcher",
    "FakeJobFailureSink",
    "FakeJobSource",
    "FakeResultPublisher",
    "FakeResultSink",
]


class FakeJobDispatcher(AbstractJobDispatcher):
    def __init__(self) -> None:
        self.dispatched: list[ManagerJob] = []
        self.fail_next: Exception | None = None

    async def dispatch(self, job: ManagerJob) -> None:
        if self.fail_next is not None:
            error, self.fail_next = self.fail_next, None
            raise error
        self.dispatched.append(job)


class FakeJobFailureSink(AbstractJobFailureSink):
    def __init__(self) -> None:
        self.failures: list[tuple[str, str, bool]] = []

    async def fail(
        self, execution_id: str, message: str, *, reply_to_crew_channel: bool
    ) -> None:
        self.failures.append((execution_id, message, reply_to_crew_channel))


class FakeJobSource(AbstractJobSource):
    """Hands out the prepared jobs in order, then blocks forever.

    Blocking rather than raising matches the real source: ``JobConsumer`` loops on
    ``get()``, so a source that raised on exhaustion would turn a normal idle worker
    into an error path. An ``UndecodableJobError`` among the prepared items is raised
    in its turn, the way the real source reports a message it could not decode.
    """

    def __init__(self, *jobs: WorkerJob | UndecodableJobError) -> None:
        self._pending = list(jobs)
        self.gets = 0

    async def get(self) -> WorkerJob:
        self.gets += 1
        if self._pending:
            item = self._pending.pop(0)
            if isinstance(item, UndecodableJobError):
                raise item
            return item
        await asyncio.Event().wait()
        raise AssertionError("unreachable")


class FakeResultSink(AbstractResultSink):
    def __init__(self) -> None:
        self.sent: list[tuple[ExecutionResult, StorageMutations | None]] = []
        self.failures_left = 0

    async def send(
        self, result: ExecutionResult, mutations: StorageMutations | None = None
    ) -> None:
        if self.failures_left > 0:
            self.failures_left -= 1
            raise RuntimeError("result queue is gone")
        self.sent.append((result, mutations))


class FakeResultPublisher(AbstractResultPublisher):
    def __init__(self) -> None:
        self.published: list[ExecutionResultMessage] = []
        self.fail_for: set[str] = set()

    async def publish(self, result: ExecutionResultMessage) -> None:
        if result.execution_id in self.fail_for:
            raise RuntimeError(f"publish failed for {result.execution_id}")
        self.published.append(result)
