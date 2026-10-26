"""In-process job dispatcher: the manager-to-worker side of the transport.

A dumb transport adapter. The manager hands a domain ``Job`` whose venv the
orchestrator has already gated to COMPLETED; this only encodes it into the wire
``ExecutionJobMessage`` (carrying the built ``venv_hash``, not the id -- the worker
knows nothing about the database) and enqueues it. The readiness decision lives in
``JobOrchestrator``; it must not be duplicated here.

It also logs the ``exec_queued`` BENCH checkpoint: only the queue's owner can read the
depth the job joined at, and every dispatch -- direct or released from holding -- ends
here.
"""

import asyncio

from common.contracts import ExecutionJobMessage, StorageCredentialsMessage
from loguru import logger
from src.shared.bench_log import BENCH_LEVEL

from manager.application.ports import AbstractJobDispatcher
from manager.domain.models import Job

__all__ = ["QueueJobDispatcher"]


class QueueJobDispatcher(AbstractJobDispatcher):
    def __init__(self, queue: asyncio.Queue[ExecutionJobMessage]):
        self._queue = queue

    async def dispatch(self, job: Job):
        message = ExecutionJobMessage(
            execution_id=job.execution_id,
            venv_hash=job.venv_hash,
            code=job.code,
            entrypoint=job.entrypoint,
            func_kwargs=job.func_kwargs,
            global_kwargs=job.global_kwargs,
            secrets=job.secrets,
            use_storage=job.use_storage,
            storage_allowed_paths=job.storage_allowed_paths,
            storage_org_prefix=job.storage_org_prefix,
            storage_credentials=(
                None
                if job.storage_credentials is None
                else StorageCredentialsMessage(
                    access_key=job.storage_credentials.access_key,
                    secret_key=job.storage_credentials.secret_key,
                )
            ),
            session_id=job.session_id,
            timeout=job.timeout,
            reply_to_crew_channel=job.reply_to_crew_channel,
            queue_deadline=job.queue_deadline,
        )
        await self._queue.put(message)
        logger.log(
            BENCH_LEVEL,
            "bench {checkpoint}",
            checkpoint="exec_queued",
            session_id=job.session_id,
            execution_id=job.execution_id,
            queued=self._queue.qsize(),
        )
