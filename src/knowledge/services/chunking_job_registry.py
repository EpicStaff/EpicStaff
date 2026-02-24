import asyncio
from dataclasses import dataclass
from typing import Dict
from loguru import logger

from services.cancellation_token import CancellationToken


@dataclass
class ChunkingJob:
    """Represents a running chunking job."""

    chunking_job_id: str
    document_config_id: int
    task: asyncio.Task
    token: CancellationToken


class ChunkingJobRegistry:
    """
    In-memory registry for tracking running chunking jobs.

    Implements "last request wins" - cancels existing job when new arrives
    for the same document_config_id.

    Thread-safe through asyncio.Lock for concurrent access.
    """

    def __init__(self):
        # Key: document_config_id, Value: ChunkingJob
        self._jobs: Dict[int, ChunkingJob] = {}
        self._lock = asyncio.Lock()

    async def register_job(
        self,
        document_config_id: int,
        chunking_job_id: str,
        task: asyncio.Task,
    ) -> CancellationToken:
        """
        Register a new chunking job, cancelling any existing job for the same config.

        Args:
            document_config_id: ID of the document config being processed
            chunking_job_id: Unique ID for this job
            task: The asyncio.Task running the job

        Returns:
            CancellationToken for the new job (pass this to workers)
        """
        async with self._lock:
            # Check if there's an existing job for this config
            if document_config_id in self._jobs:
                existing = self._jobs[document_config_id]
                # Cancel via token (thread-safe, workers will see this)
                existing.token.cancel()
                # Also cancel the asyncio task
                existing.task.cancel()
                logger.info(
                    f"Cancelled existing chunking job {existing.chunking_job_id} "
                    f"for config {document_config_id}"
                )

            # Create token for the new job
            token = CancellationToken(chunking_job_id)

            # Register the new job
            self._jobs[document_config_id] = ChunkingJob(
                chunking_job_id=chunking_job_id,
                document_config_id=document_config_id,
                task=task,
                token=token,
            )

            logger.debug(
                f"Registered chunking job {chunking_job_id} "
                f"for config {document_config_id}"
            )

            return token

    async def unregister_job(
        self, document_config_id: int, chunking_job_id: str
    ) -> None:
        """
        Remove a job from the registry when it completes (success or failure).

        Only removes if the job_id matches the currently registered job.
        This prevents a cancelled job from unregistering a newer job.

        Args:
            document_config_id: ID of the document config
            chunking_job_id: ID of the job requesting unregister
        """
        async with self._lock:
            if document_config_id in self._jobs:
                job = self._jobs[document_config_id]
                # Only unregister if it's the SAME job (not a newer one)
                if job.chunking_job_id == chunking_job_id:
                    self._jobs.pop(document_config_id)
                    logger.debug(
                        f"Unregistered chunking job {chunking_job_id} "
                        f"for config {document_config_id}"
                    )
                else:
                    logger.debug(
                        f"Skipped unregister for job {chunking_job_id} "
                        f"(current job is {job.chunking_job_id})"
                    )



# Singleton instance
chunking_job_registry = ChunkingJobRegistry()
