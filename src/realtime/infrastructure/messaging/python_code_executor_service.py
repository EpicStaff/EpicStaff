import asyncio
import uuid
from typing import Any

from core import config
from domain.ports.i_python_code_executor_service import IPythonCodeExecutorService
from domain.ports.i_redis_messaging_service import IRedisMessagingService
from foundation.transport.http import ClientError
from loguru import logger
from pydantic import ValidationError
from src.shared.models import (
    CodeResultData,
    CodeTaskData,
    ExecutionRequest,
    PythonCodeData,
    StorageCredentials,
)
from src.shared.sandbox_errors import SandboxError
from utils.singleton_meta import SingletonMeta

from infrastructure.sandbox.sandbox_client import SandboxClient


class PythonCodeExecutorService(IPythonCodeExecutorService, metaclass=SingletonMeta):
    def __init__(self, redis_service: IRedisMessagingService, sandbox_client: SandboxClient):
        self.redis_service = redis_service
        self.sandbox_client = sandbox_client

    async def run_code(
        self,
        python_code_data: PythonCodeData,
        inputs: dict[str, Any],
        additional_global_kwargs: dict[str, Any] | None = None,
        storage_credentials: StorageCredentials | None = None,
    ) -> dict:
        additional_global_kwargs = additional_global_kwargs or {}
        code = python_code_data.code
        entrypoint = python_code_data.entrypoint

        global_kwargs = python_code_data.global_kwargs or {}

        merged_global_kwargs = {
            **global_kwargs,
            **additional_global_kwargs,
        }
        if python_code_data.org_id is not None:
            merged_global_kwargs["org_id"] = python_code_data.org_id

        unique_task_id = str(uuid.uuid4())
        try:
            code_task_data = CodeTaskData(
                venv_id=python_code_data.venv_id,
                code=code,
                execution_id=unique_task_id,
                entrypoint=entrypoint,
                func_kwargs=inputs,
                global_kwargs=merged_global_kwargs,
                use_storage=python_code_data.use_storage,
                storage_allowed_paths=python_code_data.storage_allowed_paths,
                storage_org_prefix=python_code_data.storage_org_prefix,
                org_id=python_code_data.org_id,
                storage_credentials=storage_credentials,
                secrets=python_code_data.secrets,
                execution_timeout=python_code_data.execution_timeout,
            )
        except ValidationError:
            # Never log or return `error` itself: pydantic's ValidationError
            # repr embeds the full constructor input, including `secrets`
            # plaintext (see CodeTaskData.log_summary(), which exists for
            # exactly this reason).
            logger.error(
                "Invalid storage scope for code execution (execution_id={})", unique_task_id
            )
            return CodeResultData(
                execution_id=unique_task_id,
                stderr="Invalid storage scope for code execution.",
                stdout="",
                returncode=1,
            ).model_dump()

        # Subscribe before submitting so a fast result is never missed. Every exit
        # closes it: one subscription per execution would otherwise outlive the call.
        pubsub = await self.redis_service.async_subscribe(config.CODE_RESULT_CHANNEL)
        try:
            await self.sandbox_client.submit(_execution_request(code_task_data))
            logger.info("Waiting for code_results")
            return await self.sandbox_client.wait_for_result(
                unique_task_id,
                _read_result(pubsub, unique_task_id),
                backstop=config.REALTIME_CODE_RESULT_TIMEOUT,
            )
        except (SandboxError, ClientError) as error:
            # The class name only: the message is for the user, who gets it as stderr.
            logger.error(
                "Code execution failed (execution_id={}, {})",
                unique_task_id,
                type(error).__name__,
            )
            return CodeResultData(
                execution_id=unique_task_id,
                stderr=str(error),
                stdout="",
                returncode=1,
            ).model_dump()
        finally:
            await pubsub.aclose()


async def _read_result(pubsub, execution_id: str) -> dict:
    while True:
        message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
        if message:
            code_result_data = CodeResultData.model_validate_json(message["data"])
            if code_result_data.execution_id == execution_id:
                return code_result_data.model_dump()
        await asyncio.sleep(0.1)


def _execution_request(code_task_data: CodeTaskData) -> ExecutionRequest:
    storage_credentials = code_task_data.storage_credentials
    return ExecutionRequest(
        execution_id=code_task_data.execution_id,
        session_id=code_task_data.session_id,
        code=code_task_data.code,
        entrypoint=code_task_data.entrypoint,
        global_kwargs=code_task_data.global_kwargs or {},
        func_kwargs=code_task_data.func_kwargs or {},
        secrets=code_task_data.secrets,
        venv_id=code_task_data.venv_id,
        use_storage=code_task_data.use_storage,
        storage_allowed_paths=code_task_data.storage_allowed_paths or [],
        storage_org_prefix=code_task_data.storage_org_prefix,
        storage_credentials=(
            storage_credentials.model_dump() if storage_credentials is not None else None
        ),
        timeout=code_task_data.execution_timeout,
    )
