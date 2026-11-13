"""The standalone worker process: pulls jobs from the manager and runs them.

No HTTP server, no database, no Redis -- the worker initiates every connection it has:
long-polling ``GET /worker/jobs`` when its run gate has a free slot, posting each result
back to ``POST /worker/results`` and heartbeating ``POST /worker/heartbeat`` in between.
The boot id generated here rides on every request; the manager fails the jobs assigned
to any earlier boot the moment it sees a new one, so a restart surfaces its lost jobs
within seconds, and the heartbeat keeps a saturated worker from reading as dead.

The runners are supervised the way the manager's are: one that ends takes the process
down (SIGTERM), and the container's restart policy brings it back with a new boot id.
"""

import asyncio
import uuid

from common.bootstrap.logging import configure_logging
from common.runner import Runner, supervise
from foundation.transport.http import AsyncClient
from loguru import logger

from worker import settings
from worker.bootstrap.di import build_admission_gate, build_job_consumer
from worker.infrastructure.transport.http_job_source import HttpJobSource
from worker.infrastructure.transport.http_result_sink import HttpResultSink
from worker.presentation.heartbeat import Heartbeat
from worker.presentation.run_gate_sampler import RunGateSampler


async def main() -> None:
    boot_id = str(uuid.uuid4())
    logger.info("Sandbox worker starting; boot id {}", boot_id)
    client = AsyncClient(
        base_url=settings.MANAGER_URL,
        headers={
            "Authorization": f"Bearer {settings.INTERNAL_TOKEN}",
            "X-Worker-Boot-Id": boot_id,
        },
    )
    admission_gate = build_admission_gate()
    job_consumer = build_job_consumer(
        job_source=HttpJobSource(client),
        result_sink=HttpResultSink(client),
        gate=admission_gate,
    )
    runners: dict[str, Runner] = {
        "admission gate": admission_gate,
        "job consumer": job_consumer,
        "heartbeat": Heartbeat(client, job_consumer.held_execution_ids),
        "run-gate sampler": RunGateSampler(admission_gate),
    }
    tasks = []
    for name, runner in runners.items():
        task = asyncio.create_task(runner.run(), name=name)
        supervise(task)
        tasks.append(task)
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    configure_logging()
    asyncio.run(main())
