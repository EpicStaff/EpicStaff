"""Tells the manager this worker run is alive and what it holds, every few seconds.

A saturated worker neither pulls (no free slot) nor, during a long run, posts anything,
so without this beat the manager would eventually declare it lost and fail jobs that
are still legitimately running. The beat also carries the execution ids the worker
actually holds: the manager reconciles its assignments against that list and releases
the ones whose pull response never arrived -- nothing else could, since this run keeps
beating and never goes silent. It carries the worker's guaranteed slots too: the
manager admits a job at once while its executions in flight are fewer than that.

The first beat goes out at start, not one interval later, so the manager learns the
guaranteed slots before the first burst of jobs arrives.

A failed beat is logged by exception type and the loop carries on -- the pull and
result paths handle a manager that is really gone. The loop runs supervised: if it
somehow ends, the process restarts, which is the safe side (a worker that cannot prove
it is alive is treated as dead anyway).
"""

import asyncio
from collections.abc import Callable

from common.contracts import WorkerHeartbeatMessage
from foundation.transport.http import AsyncClient
from foundation.transport.http.errors import ClientError
from loguru import logger

__all__ = ["HEARTBEAT_INTERVAL_SECONDS", "Heartbeat"]

# Six of these fit in the manager's silence threshold (60 s), so a few lost beats never
# read as a dead worker.
HEARTBEAT_INTERVAL_SECONDS = 10.0


class Heartbeat:
    """Beat every `interval` seconds, starting at once.

    Args:
        guaranteed_slots: Executions the worker's admission gate always starts at once,
            whatever the load (the gate's floor).
    """

    def __init__(
        self,
        client: AsyncClient,
        held_execution_ids: Callable[[], set[str]],
        *,
        guaranteed_slots: int,
        interval: float = HEARTBEAT_INTERVAL_SECONDS,
    ):
        self._client = client
        self._held_execution_ids = held_execution_ids
        self._guaranteed_slots = guaranteed_slots
        self._interval = interval

    async def run(self) -> None:
        while True:
            beat = WorkerHeartbeatMessage(
                execution_ids=sorted(self._held_execution_ids()),
                guaranteed_slots=self._guaranteed_slots,
            )
            try:
                await self._client.request(
                    "POST",
                    "/worker/heartbeat",
                    content=beat.model_dump_json(),
                    headers={"Content-Type": "application/json"},
                )
            except ClientError as error:
                logger.warning("Heartbeat failed ({})", type(error).__name__)
            await asyncio.sleep(self._interval)
