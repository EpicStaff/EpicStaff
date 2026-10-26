import asyncio
import uuid
from collections.abc import Awaitable
from functools import partial
from typing import Any

import settings
from foundation.clients.sandbox import (
    ExecutionRequest,
    SandboxClient,
    SandboxExecutionLostError,
    SandboxResultTimeoutError,
)
from foundation.transport.http import ClientError
from loguru import logger
from models.state import State
from pydantic import ValidationError
from services.graph.events import StopEvent
from services.redis_service import AsyncPubsubSubscriber, RedisService
from src.shared.bench_log import BENCH_LEVEL
from src.shared.models import CodeResultData, PythonCodeData
from src.shared.models.storage_scope import StorageCredentials
from src.shared.redis_keys import crew_code_result_channel
from utils.singleton_meta import SingletonMeta

# Matches the sandbox's own timeout exit code, so callers need no new branch.
TIMEOUT_RETURNCODE = 124
TIMEOUT_STDERR_MESSAGE = "Timed out waiting for the result"
# The session's StopEvent is a threading.Event and cannot be awaited, so the submit
# and the result wait wake up this often to check it.
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
    # sandbox_client is Optional only so the singleton's other construction sites
    # (CDT subgraphs do `RunPythonCodeService(redis_service=...)`) stay valid; the
    # real client is injected once in main.py at startup, before any run_code call.
    def __init__(self, redis_service: RedisService, sandbox_client: SandboxClient | None = None):
        self.redis_service = redis_service
        self.sandbox_client = sandbox_client
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
        """Submit the code to the sandbox and wait for its result on crew's result channel.

        The submission goes over HTTP; the sandbox publishes the result to
        `crew_code_result_channel`, which only crew reads, and the one subscription made
        by `subscribe_to_results` hands each result to the execution waiting for it.
        Every way the execution can fail without a result -- the sandbox stayed full,
        refused it, lost it, or became unreachable -- returns a synthesized
        CodeResultData with returncode 1 and the reason as stderr. No result within
        settings.CODE_RESULT_TIMEOUT (None waits as long as the sandbox still has the
        execution) returns returncode TIMEOUT_RETURNCODE. Callers branch on returncode
        like they already do for every other non-zero outcome.

        Raises:
            StopSession: `stop_event` was set while submitting or waiting for the result;
                the submit or the wait is cancelled.
        """
        additional_global_kwargs = additional_global_kwargs or {}
        global_kwargs = python_code_data.global_kwargs or {}
        merged_global_kwargs = {
            **global_kwargs,
            **additional_global_kwargs,
        }
        if python_code_data.org_id is not None:
            merged_global_kwargs["org_id"] = python_code_data.org_id

        execution_id = str(uuid.uuid4())
        execution_request = ExecutionRequest(
            execution_id=execution_id,
            session_id=python_code_data.session_id,
            code=python_code_data.code,
            entrypoint=python_code_data.entrypoint,
            global_kwargs=merged_global_kwargs,
            func_kwargs=inputs,
            secrets=python_code_data.secrets,
            venv_id=python_code_data.venv_id,
            use_storage=python_code_data.use_storage,
            storage_allowed_paths=python_code_data.storage_allowed_paths or [],
            storage_org_prefix=python_code_data.storage_org_prefix,
            storage_credentials=(
                storage_credentials.model_dump() if storage_credentials is not None else None
            ),
            timeout=python_code_data.execution_timeout,
            reply_to_crew_channel=True,
        )

        # Registered before submitting, so a result that arrives at once is not missed.
        result_future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._pending_results[execution_id] = result_future
        try:
            # A full sandbox is retried for up to its queue timeout; a stop must not wait that out.
            submitting = self.sandbox_client.submit(
                execution_request,
                on_rejected=partial(_log_rejected, python_code_data.session_id, execution_id),
            )
            await _until_stopped(submitting, stop_event)
            logger.log(
                BENCH_LEVEL,
                "bench {checkpoint}",
                checkpoint="sandbox_dispatched",
                session_id=python_code_data.session_id,
                execution_id=execution_id,
            )
            logger.debug("Waiting for code result {}", execution_id)
            return await self.sandbox_client.wait_for_result(
                execution_id,
                _until_stopped(result_future, stop_event),
                backstop=settings.CODE_RESULT_TIMEOUT,
            )
        except SandboxResultTimeoutError:
            logger.error(
                "No code result for execution ID {} after {} seconds; giving up.",
                execution_id,
                settings.CODE_RESULT_TIMEOUT,
            )
            return _failed_result(execution_id, TIMEOUT_RETURNCODE, TIMEOUT_STDERR_MESSAGE)
        except ClientError as error:
            if isinstance(error, SandboxExecutionLostError):
                logger.log(
                    BENCH_LEVEL,
                    "bench {checkpoint}",
                    checkpoint="sandbox_lost",
                    session_id=python_code_data.session_id,
                    execution_id=execution_id,
                )
            # The class name only: the message is for the user, who gets it as stderr.
            logger.error("Code execution {} failed ({})", execution_id, type(error).__name__)
            return _failed_result(execution_id, 1, str(error))
        finally:
            self._pending_results.pop(execution_id, None)

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


async def _until_stopped[T](awaitable: Awaitable[T], stop_event: StopEvent | None) -> T:
    """Await `awaitable`, checking `stop_event` every STOP_CHECK_INTERVAL_S.

    Raises:
        StopSession: `stop_event` was set first; `awaitable` is cancelled.
    """
    task = asyncio.ensure_future(awaitable)
    try:
        while not task.done():
            if stop_event is not None:
                stop_event.check_stop()
            await asyncio.wait({task}, timeout=STOP_CHECK_INTERVAL_S)
        return task.result()
    finally:
        task.cancel()


def _log_rejected(
    session_id: int | None, execution_id: str, attempt: int, retry_after_s: float
) -> None:
    logger.log(
        BENCH_LEVEL,
        "bench {checkpoint}",
        checkpoint="sandbox_rejected",
        session_id=session_id,
        execution_id=execution_id,
        attempt=attempt,
        retry_after_s=round(retry_after_s, 3),
    )


def _failed_result(execution_id: str, returncode: int, stderr: str) -> dict[str, Any]:
    """A result for an execution the sandbox never produced one for."""
    return CodeResultData(
        execution_id=execution_id,
        returncode=returncode,
        stdout="",
        stderr=stderr,
        result_data=None,
    ).model_dump()
