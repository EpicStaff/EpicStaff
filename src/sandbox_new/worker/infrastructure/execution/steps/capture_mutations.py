"""Reads the storage changes the execution wrote and records them on the context.

Only a clean, storage-enabled run leaves a mutations file. This step reads and
models it; the orchestrator publishes it after the run. An unreadable or empty file
is treated as "no mutations" -- it never fails the execution, which already
succeeded.
"""

import json

from loguru import logger

from worker.application.context import ExecutionContext
from worker.domain.models import StorageMutations

__all__ = ["CaptureMutationsStep"]


class CaptureMutationsStep:
    async def __call__(self, context: ExecutionContext) -> None:
        job = context.job
        if not job.use_storage or context.returncode != 0:
            return

        path = context.storage_mutations_path
        if path is None or not path.exists():
            return

        try:
            mutations = json.loads(path.read_text(encoding="utf-8"))
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
