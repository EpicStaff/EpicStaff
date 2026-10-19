"""HTTP intake client for the sandbox code-execution service.

django_app submits a code execution over HTTP (`POST /executions`) and receives
its result back on the Redis result channel, unchanged. The request body mirrors
the sandbox's own submit schema: the venv is addressed by `venv_id` (None means
the sandbox's default venv), and the storage credentials django mints for the run
are handed over here -- the sandbox mints none of its own and rejects a storage
execution that arrives without them.
"""

from typing import Any

from django.conf import settings
from foundation.transport.http import Client
from src.shared.models import CodeTaskData


class SandboxExecutionClient(Client):
    """Submits code executions to the sandbox HTTP intake."""

    def __init__(
        self,
        base_url: str | None = None,
        timeout: float | None = None,
        **httpx_options,
    ):
        super().__init__(
            base_url=base_url or f"http://{settings.SANDBOX_HOST}:{settings.SANDBOX_PORT}",
            timeout=timeout if timeout is not None else settings.SANDBOX_CLIENT_TIMEOUT,
            **httpx_options,
        )

    def submit(self, code_task_data: CodeTaskData) -> dict:
        """Hand one execution to the sandbox and return its acceptance payload.

        Raises:
            ClientError: The sandbox timed out or rejected the submission.
            httpx.HTTPError: The sandbox could not be reached at all; the transport
                translates only timeouts and non-2xx responses, so a connection
                failure arrives untranslated.

        Nothing arrives on the result channel in either case.
        """
        response = self.post(url="/executions", json=_submit_body(code_task_data))
        return response.json()


def _submit_body(code_task_data: CodeTaskData) -> dict[str, Any]:
    """Render a `CodeTaskData` as the intake's request body.

    The intake types `global_kwargs`, `func_kwargs` and `storage_allowed_paths` as
    containers with an empty default, so the optional ones are sent empty rather
    than null. `timeout` is left to the sandbox's own execution timeout.
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
        "timeout": None,
    }
