"""Reads the storage changes the execution wrote and records them on the context.

Only a clean, storage-enabled run leaves a mutations file. This step reads and
models it; the orchestrator publishes it after the run. A missing, unreadable or
empty file is treated as "no mutations". A file the child replaced with a symlink, a
FIFO or an oversized file is tampering, not a reporting problem, so it fails the run.
"""

import json

from loguru import logger

from worker.application.context import ExecutionContext
from worker.domain.models import StorageMutations
from worker.infrastructure.execution.control_files import (
    UnsafeControlFileError,
    read_control_file,
)

__all__ = ["CaptureMutationsStep"]


class CaptureMutationsStep:
    def __init__(self, *, max_bytes: int):
        self._max_bytes = max_bytes

    async def __call__(self, context: ExecutionContext) -> None:
        job = context.job
        if not job.use_storage or context.returncode != 0:
            return

        path = context.storage_mutations_path
        if path is None:
            return

        try:
            text = read_control_file(path, max_bytes=self._max_bytes)
            if text is None:
                return
            mutations = json.loads(text)
        except UnsafeControlFileError as error:
            logger.error("Rejected storage mutations file of {}: {}", job.execution_id, error)
            context.fail(f"Rejected the storage mutations file: {error}.")
            return
        except Exception:
            logger.exception("Failed to read storage mutations for {}", job.execution_id)
            return

        if not mutations:
            return

        context.storage_mutations = StorageMutations(
            execution_id=job.execution_id,
            org_prefix=job.storage_org_prefix,
            session_id=job.session_id,
            mutations=mutations,
        )
