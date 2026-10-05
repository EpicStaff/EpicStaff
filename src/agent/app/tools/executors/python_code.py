from __future__ import annotations

import uuid

from pydantic import ValidationError

from app.sandbox.client import SandboxClient
from shared.models.agent_service import ToolResult
from shared.models.tools import CodeTaskData, PythonCodeToolData


class PythonCodeToolExecutor:
    """Executes a Python-code tool via the sandbox service.

    Storage wiring (use_storage, storage_allowed_paths, storage_org_prefix,
    session_id) is carried on ``data.python_code``, populated Django-side
    per graph/session.
    """

    def __init__(
        self, sandbox: SandboxClient, data: PythonCodeToolData, storage_credentials=None
    ) -> None:
        self._sandbox = sandbox
        self._data = data
        self._storage_credentials = storage_credentials

    async def __call__(self, args: dict) -> ToolResult:
        python_code = self._data.python_code

        # `global_kwargs` is author-editable and reaches the code as globals(),
        # where tools read `org_id`. The typed `org_id` is resolved from the
        # graph on the Django side, so it must win over a same-named key here
        # (the crew's RunPythonCodeService does the same).
        global_kwargs = python_code.global_kwargs
        if python_code.org_id is not None:
            global_kwargs = {**(global_kwargs or {}), "org_id": python_code.org_id}

        try:
            task = CodeTaskData(
                venv_name=python_code.venv_name,
                libraries=python_code.libraries,
                code=python_code.code,
                execution_id=str(uuid.uuid4()),
                entrypoint=python_code.entrypoint,
                func_kwargs=args,
                global_kwargs=global_kwargs,
                use_storage=python_code.use_storage,
                storage_allowed_paths=python_code.storage_allowed_paths,
                storage_org_prefix=python_code.storage_org_prefix,
                session_id=python_code.session_id,
                org_id=python_code.org_id,
                secrets=python_code.secrets,
                storage_credentials=self._storage_credentials,
            )
        except ValidationError as error:
            return ToolResult(
                tool_call_id="",
                content=f"Invalid storage scope for code execution: {error}",
                is_error=True,
            )

        try:
            result = await self._sandbox.submit(task)
        except Exception as error:
            return ToolResult(
                tool_call_id="",
                content=f"Sandbox transport error: {error}",
                is_error=True,
            )

        if result.returncode != 0 or result.stderr:
            return ToolResult(
                tool_call_id="",
                content=result.stderr or result.stdout or "Sandbox returned non-zero",
                is_error=True,
            )

        return ToolResult(
            tool_call_id="",
            content=result.result_data or "",
            is_error=False,
        )
