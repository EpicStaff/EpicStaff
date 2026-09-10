"""Publishes the trusted storage-access scope a publisher already knows for a
`CodeTaskData`, before that task is published to `code_exec_tasks`.

This is the first echelon of defense in the storage_credentials design:
`sandbox` never claims its own `org_id`/`storage_org_prefix`.
Only a trusted publisher (`crew`, `agent`, `realtime`, django's "Test run")
writes this scope, keyed by `execution_id`, for the credential issuer running
in `django_app` to read back via `GETDEL` when it mints a temporary MinIO
service account.

Two entry points exist only because publishers use different Redis clients
(sync for django's "Test run", async for others); both
share the same key/JSON/TTL (`CREDENTIAL_SCOPE_TTL_SECONDS`), so two thin
siblings beat one function branching on client type.
"""

import json

from redis import Redis
from redis.asyncio import Redis as AsyncRedis

from ..models.tools import CodeTaskData
from .constants import CREDENTIAL_SCOPE_TTL_SECONDS

CREDENTIAL_SCOPE_KEY_PREFIX = "storage_credential_scope"


def _scope_key(execution_id: str) -> str:
    return f"{CREDENTIAL_SCOPE_KEY_PREFIX}:{execution_id}"


def _build_scope_payload(code_task_data: CodeTaskData) -> str:
    if not code_task_data.use_storage:
        raise ValueError(
            "publish_credential_scope called for a task with use_storage=False; "
            "callers must only call this when use_storage=True."
        )
    if not code_task_data.org_id or not code_task_data.storage_org_prefix:
        raise ValueError(
            "use_storage=True requires both org_id and storage_org_prefix to be "
            "set before publishing a code execution task."
        )
    return json.dumps(
        {
            "org_id": code_task_data.org_id,
            "storage_org_prefix": code_task_data.storage_org_prefix,
            "storage_allowed_paths": code_task_data.storage_allowed_paths,
        }
    )


def publish_credential_scope(redis_client: Redis, code_task_data: CodeTaskData) -> None:
    """Sync variant, for publishers running outside an event loop (django's
    "Test run"). No-op when `use_storage` is False."""
    if not code_task_data.use_storage:
        return
    redis_client.set(
        _scope_key(code_task_data.execution_id),
        _build_scope_payload(code_task_data),
        nx=True,
        ex=CREDENTIAL_SCOPE_TTL_SECONDS,
    )


async def publish_credential_scope_async(
    redis_client: AsyncRedis, code_task_data: CodeTaskData
) -> None:
    """Async variant, for `crew`, `agent`, and `realtime`. No-op when
    `use_storage` is False."""
    if not code_task_data.use_storage:
        return
    await redis_client.set(
        _scope_key(code_task_data.execution_id),
        _build_scope_payload(code_task_data),
        nx=True,
        ex=CREDENTIAL_SCOPE_TTL_SECONDS,
    )
