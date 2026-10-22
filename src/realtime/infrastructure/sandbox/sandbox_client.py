"""HTTP intake client for the sandbox code-execution service.

realtime submits a code execution over HTTP (`POST /executions`) and receives its
result back on the Redis result channel, unchanged. The request body mirrors the
sandbox's own submit schema: the venv is addressed by `venv_id` (None means the
sandbox's default venv), and the storage credentials django mints for the realtime
chat are handed over here -- the sandbox mints none of its own and rejects a
storage execution that arrives without them.
"""

from typing import Any

import httpx
from src.shared.models import CodeTaskData


class SandboxExecutionClient:
    """Submits code executions to the sandbox HTTP intake."""

    def __init__(self, base_url: str, timeout: float | None = None, **httpx_options):
        self._client = httpx.AsyncClient(base_url=base_url, timeout=timeout, **httpx_options)

    async def close(self) -> None:
        await self._client.aclose()

    async def submit(self, code_task_data: CodeTaskData) -> dict:
        """Hand one execution to the sandbox and return its acceptance payload.

        Raises:
            httpx.HTTPError: The sandbox was unreachable, timed out, or rejected
                the submission. Nothing will arrive on the result channel.
        """
        response = await self._client.post("/executions", json=_submit_body(code_task_data))
        response.raise_for_status()
        return response.json()


def _submit_body(code_task_data: CodeTaskData) -> dict[str, Any]:
    """Render a `CodeTaskData` as the intake's request body.

    The intake types `global_kwargs`, `func_kwargs` and `storage_allowed_paths` as
    containers with an empty default, so the optional ones are sent empty rather
    than null. `timeout` carries the code's own execution timeout; None lets the
    sandbox apply its default.
    """
    storage_credentials = code_task_data.storage_credentials
    return {
        "execution_id": code_task_data.execution_id,
        "session_id": code_task_data.session_id,
        "code": code_task_data.code,
        "entrypoint": code_task_data.entrypoint,
        "global_kwargs": code_task_data.global_kwargs or {},
        "func_kwargs": code_task_data.func_kwargs or {},
        "secrets": code_task_data.secrets,
        "venv_id": code_task_data.venv_id,
        "use_storage": code_task_data.use_storage,
        "storage_allowed_paths": code_task_data.storage_allowed_paths or [],
        "storage_org_prefix": code_task_data.storage_org_prefix,
        "storage_credentials": (
            storage_credentials.model_dump() if storage_credentials is not None else None
        ),
        "timeout": code_task_data.execution_timeout,
    }
