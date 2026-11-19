"""Hands an execution the storage access its job already carries.

Only acts when the job sets ``use_storage``. The credentials are issued upstream
and travel on the job; this step neither mints nor revokes them. It points the
mutations file into the exec dir (which activates the wrapper's mutation tail) and
adds the ``STORAGE_*`` variables the in-sandbox storage library reads. A job that
asks for storage without an org prefix or without credentials is failed rather than
launched with broken or unscoped access.
"""

import json

from loguru import logger
from src.shared.sandbox_errors import SANDBOX_SERVER_ERROR_MESSAGE

from worker.application.context import ExecutionContext

__all__ = ["ConfigureStorageStep"]


class ConfigureStorageStep:
    def __init__(self, *, storage_endpoint: str, storage_bucket: str):
        self._storage_endpoint = storage_endpoint
        self._storage_bucket = storage_bucket

    async def __call__(self, context: ExecutionContext) -> None:
        job = context.job
        if not job.use_storage:
            return

        if not job.storage_org_prefix:
            logger.error(
                "Job {} asks for storage without storage_org_prefix; refusing to execute it.",
                job.execution_id,
            )
            context.fail(SANDBOX_SERVER_ERROR_MESSAGE)
            return

        credentials = job.storage_credentials
        if credentials is None:
            logger.error(
                "Job {} asks for storage without storage_credentials; refusing to execute it.",
                job.execution_id,
            )
            context.fail(SANDBOX_SERVER_ERROR_MESSAGE)
            return

        context.storage_mutations_path = context.exec_dir / "storage_mutations.json"

        context.env["STORAGE_ENDPOINT"] = self._storage_endpoint
        context.env["STORAGE_BUCKET_NAME"] = self._storage_bucket
        context.env["STORAGE_ACCESS_KEY"] = credentials.access_key
        context.env["STORAGE_SECRET_KEY"] = credentials.secret_key
        context.env["STORAGE_ALLOWED_PATHS"] = json.dumps(job.storage_allowed_paths)
        context.env["STORAGE_ORG_PREFIX"] = job.storage_org_prefix
        context.env["STORAGE_OWN_PATHS"] = json.dumps(credentials.own_paths)
        if credentials.shared_actions is not None:
            context.env["STORAGE_ALLOWED_ACTIONS"] = json.dumps(credentials.shared_actions)
