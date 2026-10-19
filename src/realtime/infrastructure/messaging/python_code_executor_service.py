import asyncio
import uuid
from typing import Any

import httpx
from core import config
from domain.ports.i_python_code_executor_service import IPythonCodeExecutorService
from domain.ports.i_redis_messaging_service import IRedisMessagingService
from loguru import logger
from pydantic import ValidationError
from src.shared.models import CodeResultData, CodeTaskData, PythonCodeData, StorageCredentials
from utils.singleton_meta import SingletonMeta

from infrastructure.sandbox.sandbox_client import SandboxExecutionClient


class PythonCodeExecutorService(IPythonCodeExecutorService, metaclass=SingletonMeta):
    _SUBMIT_FAILED_STDERR = "Could not reach the code sandbox for this run."

    def __init__(
        self, redis_service: IRedisMessagingService, sandbox_client: SandboxExecutionClient
    ):
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
        venv_name = python_code_data.venv_name
        code = python_code_data.code
        entrypoint = python_code_data.entrypoint
        libraries = python_code_data.libraries

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
                venv_name=venv_name,
                libraries=libraries,
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
            try:
                await self.sandbox_client.submit(code_task_data)
            except httpx.HTTPError as error:
                # The class name, never the error: an httpx error keeps the request
                # that raised it, and that request body carries secret plaintext.
                # A rejected submit produces no result, so the wait below would never
                # end -- fail the tool call now instead.
                logger.error(
                    "Failed to submit code execution to the sandbox (execution_id={}, {})",
                    unique_task_id,
                    type(error).__name__,
                )
                return CodeResultData(
                    execution_id=unique_task_id,
                    stderr=self._SUBMIT_FAILED_STDERR,
                    stdout="",
                    returncode=1,
                ).model_dump()
            logger.info("Waiting for code_results")

            while True:
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if message:
                    code_result_data = CodeResultData.model_validate_json(message["data"])
                    if code_result_data.execution_id == unique_task_id:
                        return code_result_data.model_dump()
                await asyncio.sleep(0.1)
        finally:
            await pubsub.aclose()
