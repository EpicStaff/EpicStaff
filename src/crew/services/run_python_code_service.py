import uuid
import asyncio
from typing import Any

from loguru import logger
from utils.psutil_wrapper import psutil_wrapper
from utils.singleton_meta import SingletonMeta
from services.redis_service import AsyncPubsubSubscriber, RedisService
from models.request_models import CodeResultData, CodeTaskData, PythonCodeData


class RunPythonCodeService(metaclass=SingletonMeta):
    def __init__(self, redis_service: RedisService):
        self.redis_service = redis_service

    async def run_code(
        self,
        python_code_data: PythonCodeData,
        inputs: dict[str, Any],
        additional_global_kwargs: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        additional_global_kwargs = additional_global_kwargs or {}
        venv_name = python_code_data.venv_name
        code = python_code_data.code
        entrypoint = python_code_data.entrypoint
        libraries = python_code_data.libraries

        global_kwargs = python_code_data.global_kwargs or {}

        unique_task_id = str(uuid.uuid4())
        code_task_data = CodeTaskData(
            venv_name=venv_name,
            libraries=libraries,
            code=code,
            execution_id=unique_task_id,
            entrypoint=entrypoint,
            func_kwargs=inputs,
            global_kwargs={
                **global_kwargs,
                **additional_global_kwargs,
            },
        )
        callback_receiver = RunPythonCallbackReceiver(execution_id=unique_task_id)

        subscriber = AsyncPubsubSubscriber(callback_receiver.callback)
        await self.redis_service.asubscribe("code_results", subscriber=subscriber)

        total_len = 0
        for g in self.redis_service._async_pubsub_groups.values():
            total_len += len(g._subscribers)
        await self.redis_service.apublish(
            "code_exec_tasks", code_task_data.model_dump()
        )
        logger.info("Waiting for code_results")

        while True:
            if callback_receiver.results is not None:
                self.redis_service.unsubscribe("code_results", subscriber=subscriber)
                return callback_receiver.results

            await asyncio.sleep(0.001)


class RunPythonCallbackReceiver:
    def __init__(self, execution_id: str):
        self.execution_id = execution_id
        self.results: dict[str, Any] | None = None

    # @psutil_wrapper
    async def callback(self, message: dict[str, Any]):
        code_result_data = CodeResultData.model_validate_json(message["data"])
        if code_result_data.execution_id == self.execution_id:
            self.results = code_result_data.model_dump()
            logger.info(f"Received code result for execution ID: {self.execution_id}")
