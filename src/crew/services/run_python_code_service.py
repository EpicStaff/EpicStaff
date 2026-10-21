import asyncio
import uuid
from typing import Any

import settings
from loguru import logger
from models.state import State
from pydantic import ValidationError
from services.graph.events import StopEvent
from services.redis_service import AsyncPubsubSubscriber, RedisService
from src.shared.bench_log import BENCH_LEVEL
from src.shared.models import CodeResultData, CodeTaskData, PythonCodeData
from src.shared.models.storage_scope import StorageCredentials
from src.shared.redis_keys import crew_code_result_channel
from utils.singleton_meta import SingletonMeta

# Matches the sandbox's own timeout exit code, so callers need no new branch.
TIMEOUT_RETURNCODE = 124
TIMEOUT_STDERR_MESSAGE = "Timed out waiting for the result"
# The session's StopEvent is a threading.Event and cannot be awaited, so a wait
# wakes up this often to check it.
STOP_CHECK_INTERVAL_S = 0.5


def build_state_globals(state: State) -> dict[str, Any]:
    """Build the `state` global that user Python code can read in the sandbox."""
    return {
        "state": {
            "variables": state["variables"].model_dump(),
            "state_history": state["state_history"],
        }
    }


class RunPythonCodeService(metaclass=SingletonMeta):
    def __init__(self, redis_service: RedisService):
        self.redis_service = redis_service
        self._result_channel = crew_code_result_channel(settings.CODE_RESULT_CHUNNEL)
        self._pending_results: dict[str, asyncio.Future[dict[str, Any]]] = {}

    async def subscribe_to_results(self) -> None:
        """Subscribe to crew's code-result channel; call once at startup, after Redis connects.

        `run_code` relies on this one subscription for every execution, so a failure
        here must stop crew rather than leave every execution to time out.
        """
        await self.redis_service.asubscribe(
            self._result_channel,
            subscriber=AsyncPubsubSubscriber(self._on_result_message),
        )

    async def run_code(
        self,
        python_code_data: PythonCodeData,
        inputs: dict[str, Any],
        additional_global_kwargs: dict[str, Any] | None = None,
        stop_event: StopEvent | None = None,
        storage_credentials: StorageCredentials | None = None,
    ) -> dict[str, Any]:
        """Publish the code to the sandbox and wait for its result on crew's result channel.

        The sandbox publishes the result to `crew_code_result_channel`, which only crew
        reads; the one subscription made by `subscribe_to_results` hands each result to
        the execution waiting for it. The result arrives over Redis pub/sub, which has no delivery guarantee. If none
        arrives within settings.CODE_RESULT_TIMEOUT, this returns a synthesized
        CodeResultData(returncode=TIMEOUT_RETURNCODE, result_data=None) instead of
        blocking forever -- the sandbox itself never produced this result, so callers
        must branch on returncode like they already do for every other non-zero outcome.
        CODE_RESULT_TIMEOUT is None means wait indefinitely.
        """
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
                code=code,
                execution_id=unique_task_id,
                entrypoint=entrypoint,
                func_kwargs=inputs,
                global_kwargs=merged_global_kwargs,
                use_storage=python_code_data.use_storage,
                storage_allowed_paths=python_code_data.storage_allowed_paths,
                storage_org_prefix=python_code_data.storage_org_prefix,
                session_id=python_code_data.session_id,
                secrets=python_code_data.secrets,
                org_id=python_code_data.org_id,
                storage_credentials=storage_credentials,
                reply_to_crew_channel=True,
            )
        except ValidationError:
            # Never log or return `error` itself: ValidationError's repr embeds the
            # constructor input, including `secrets` and `storage_credentials`.
            logger.error(
                "Invalid storage scope for code execution (execution_id={})", unique_task_id
            )
            return CodeResultData(
                execution_id=unique_task_id,
                stderr="Invalid storage scope for code execution.",
                stdout="",
                returncode=1,
            ).model_dump()

        # Registered before publishing, so a result that arrives at once is not missed.
        result_future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._pending_results[unique_task_id] = result_future
        try:
            await self.redis_service.apublish(
                settings.CODE_EXEC_CHANNEL, code_task_data.model_dump_json()
            )
            logger.log(
                BENCH_LEVEL,
                "bench {checkpoint}",
                checkpoint="sandbox_dispatched",
                session_id=code_task_data.session_id,
                execution_id=unique_task_id,
            )
            logger.debug("Waiting for code result {}", unique_task_id)
            return await self._await_result(unique_task_id, result_future, stop_event)
        finally:
            self._pending_results.pop(unique_task_id, None)

    async def _on_result_message(self, message: dict[str, Any]) -> None:
        try:
            code_result_data = CodeResultData.model_validate_json(message["data"])
        except ValidationError:
            # Never log the payload: it carries the user code's output.
            logger.error("Dropped an unparseable message on {}", self._result_channel)
            return
        result_future = self._pending_results.get(code_result_data.execution_id)
        if result_future is None or result_future.done():
            return
        result_future.set_result(code_result_data.model_dump())

    async def _await_result(
        self,
        execution_id: str,
        result_future: asyncio.Future[dict[str, Any]],
        stop_event: StopEvent | None,
    ) -> dict[str, Any]:
        event_loop = asyncio.get_running_loop()
        timeout = settings.CODE_RESULT_TIMEOUT
        deadline = None if timeout is None else event_loop.time() + timeout

        while not result_future.done():
            if stop_event is not None:
                stop_event.check_stop()
            wait_s = STOP_CHECK_INTERVAL_S
            if deadline is not None:
                remaining_s = deadline - event_loop.time()
                if remaining_s <= 0:
                    logger.error(
                        "No code result for execution ID {} after {} seconds; giving up.",
                        execution_id,
                        timeout,
                    )
                    return CodeResultData(
                        execution_id=execution_id,
                        returncode=TIMEOUT_RETURNCODE,
                        stdout="",
                        stderr=TIMEOUT_STDERR_MESSAGE,
                        result_data=None,
                    ).model_dump()
                wait_s = min(wait_s, remaining_s)
            await asyncio.wait({result_future}, timeout=wait_s)
        return result_future.result()
