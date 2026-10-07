"""Provisions scoped storage access for an execution that asked for it.

Only acts when the job sets ``use_storage``. It mints short-lived credentials
through the port, records them on the context so they can be revoked after the run,
points the mutations file into the exec dir (which activates the wrapper's mutation
tail), and adds the ``STORAGE_*`` variables the in-sandbox storage library reads.
Missing org prefix or a provisioning failure fails the job rather than launching it
with broken or unscoped storage access.
"""

import json

from loguru import logger

from worker.application.context import ExecutionContext
from worker.application.ports.storage_credentials import AbstractStorageCredentials

__all__ = ["ProvisionStorageStep"]


class ProvisionStorageStep:
    def __init__(
        self,
        credentials: AbstractStorageCredentials,
        *,
        storage_endpoint: str,
        storage_bucket: str,
    ):
        self._credentials = credentials
        self._storage_endpoint = storage_endpoint
        self._storage_bucket = storage_bucket

    async def __call__(self, context: ExecutionContext) -> None:
        job = context.job
        if not job.use_storage:
            return

        if not job.storage_org_prefix:
            context.fail("storage_org_prefix is required when use_storage is set")
            return

        try:
            credentials = await self._credentials.provision(
                org_prefix=job.storage_org_prefix,
                allowed_paths=job.storage_allowed_paths,
            )
        except Exception as error:
            logger.error("Failed to provision scoped storage credentials: {}", error)
            context.fail(f"Failed to provision scoped storage credentials: {error}")
            return

        context.storage_credentials = credentials
        context.storage_mutations_path = context.exec_dir / "storage_mutations.json"

        context.env["STORAGE_ENDPOINT"] = self._storage_endpoint
        context.env["STORAGE_BUCKET_NAME"] = self._storage_bucket
        context.env["STORAGE_ACCESS_KEY"] = credentials.access_key
        context.env["STORAGE_SECRET_KEY"] = credentials.secret_key
        context.env["STORAGE_ALLOWED_PATHS"] = json.dumps(job.storage_allowed_paths)
        context.env["STORAGE_ORG_PREFIX"] = job.storage_org_prefix
