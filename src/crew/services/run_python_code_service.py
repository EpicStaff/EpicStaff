import asyncio
import uuid
from typing import Any

import settings
from clients.sandbox import SandboxClient
from loguru import logger
from models.state import State
from services.graph.events import StopEvent
from services.redis_service import AsyncPubsubSubscriber, RedisService
from src.shared.models import CodeResultData, PythonCodeData
from src.shared.models.storage_scope import StorageCredentials
from utils.singleton_meta import SingletonMeta

# Matches the sandbox's own timeout exit code, so callers need no new branch.
TIMEOUT_RETURNCODE = 124
TIMEOUT_STDERR_MESSAGE = "Timed out waiting for the result"


def build_state_globals(state: State) -> dict[str, Any]:
    """Build the `state` global that user Python code can read in the sandbox."""
    return {
        "state": {
            "variables": state["variables"].model_dump(),
            "state_history": state["state_history"],
        }
    }


class RunPythonCodeService(metaclass=SingletonMeta):
    # sandbox_client is Optional only so the singleton's other construction sites
    # (CDT subgraphs do `RunPythonCodeService(redis_service=...)`) stay valid; the
    # real client is injected once in main.py at startup, before any run_code call.
    def __init__(self, redis_service: RedisService, sandbox_client: SandboxClient | None = None):
        self.redis_service = redis_service
        self.sandbox_client = sandbox_client

    async def run_code(
        self,
        python_code_data: PythonCodeData,
        inputs: dict[str, Any],
        additional_global_kwargs: dict[str, Any] | None = None,
        stop_event: StopEvent | None = None,
        storage_credentials: StorageCredentials | None = None,
    ) -> dict[str, Any]:
        """Publish the code to the sandbox and wait for its result on the code-results channel.

        The result arrives over Redis pub/sub, which has no delivery guarantee. If none
        arrives within settings.CODE_RESULT_TIMEOUT, this returns a synthesized
        CodeResultData(returncode=TIMEOUT_RETURNCODE, result_data=None) instead of
        blocking forever -- the sandbox itself never produced this result, so callers
        must branch on returncode like they already do for every other non-zero outcome.
        CODE_RESULT_TIMEOUT is None means wait indefinitely.
        """
        additional_global_kwargs = additional_global_kwargs or {}
        global_kwargs = python_code_data.global_kwargs or {}
        merged_global_kwargs = {
            **global_kwargs,
            **additional_global_kwargs,
        }
        if python_code_data.org_id is not None:
            merged_global_kwargs["org_id"] = python_code_data.org_id

        unique_task_id = str(uuid.uuid4())
        callback_receiver = RunPythonCallbackReceiver(execution_id=unique_task_id)
        subscriber = AsyncPubsubSubscriber(callback_receiver.callback)

        # Subscribe before submitting so a fast result is never missed.
        await self.redis_service.asubscribe(settings.CODE_RESULT_CHUNNEL, subscriber=subscriber)

        try:
            try:
                await self.sandbox_client.submit(
                    execution_id=unique_task_id,
                    venv_id=python_code_data.venv_id,
                    session_id=python_code_data.session_id,
                    code=python_code_data.code,
                    entrypoint=python_code_data.entrypoint,
                    func_kwargs=inputs,
                    global_kwargs=merged_global_kwargs,
                    secrets=python_code_data.secrets,
                    use_storage=python_code_data.use_storage,
                    storage_allowed_paths=python_code_data.storage_allowed_paths or [],
                    storage_org_prefix=python_code_data.storage_org_prefix,
                    timeout=None,
                )
            except Exception as error:
                # The result will never arrive, so do not wait on it: fail the node now.
                logger.exception("Sandbox submit failed for {}", unique_task_id)
                return {
                    "execution_id": unique_task_id,
                    "result_data": None,
                    "stdout": "",
                    "stderr": f"Sandbox submit failed: {error}",
                    "returncode": 1,
                }

            logger.info("Waiting for code_results")

            event_loop = asyncio.get_running_loop()
            timeout = settings.CODE_RESULT_TIMEOUT
            deadline = None if timeout is None else event_loop.time() + timeout

            while True:
                if callback_receiver.results is not None:
                    return callback_receiver.results
                if stop_event is not None:
                    stop_event.check_stop()
                if deadline is not None and event_loop.time() >= deadline:
                    logger.error(
                        "No code result for execution ID {} after {} seconds; giving up.",
                        unique_task_id,
                        timeout,
                    )
                    return CodeResultData(
                        execution_id=unique_task_id,
                        returncode=TIMEOUT_RETURNCODE,
                        stdout="",
                        stderr=TIMEOUT_STDERR_MESSAGE,
                        result_data=None,
                    ).model_dump()
                await asyncio.sleep(0.001)
        finally:
            self.redis_service.unsubscribe(settings.CODE_RESULT_CHUNNEL, subscriber=subscriber)


class RunPythonCallbackReceiver:
    def __init__(self, execution_id: str):
        self.execution_id = execution_id
        self.results: dict[str, Any] | None = None

    async def callback(self, message: dict[str, Any]):
        code_result_data = CodeResultData.model_validate_json(message["data"])
        if code_result_data.execution_id == self.execution_id:
            self.results = code_result_data.model_dump()
            logger.info(f"Received code result for execution ID: {self.execution_id}")
