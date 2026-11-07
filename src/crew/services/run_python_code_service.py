import asyncio
import json
import uuid
from collections.abc import Awaitable
from functools import partial
from typing import Any

import settings
from clients.sandbox import SandboxClient
from foundation.transport.http import ClientError
from foundation.utils.error_reference import log_with_reference
from loguru import logger
from models.state import State
from pydantic import ValidationError
from services.graph.events import StopEvent
from services.redis_service import AsyncPubsubSubscriber, RedisService
from src.shared.bench_log import BENCH_LEVEL
from src.shared.models import (
    CodeFailure,
    CodeFailureCode,
    CodeResultData,
    ExecutionRequest,
    PythonCodeData,
)
from src.shared.models.storage_scope import StorageCredentials
from src.shared.public_error import PublicErrorMessage, build_public_error_message
from src.shared.redis_keys import crew_code_result_channel
from src.shared.sandbox_errors import (
    SandboxError,
    SandboxExecutionLostError,
    SandboxResultTimeoutError,
)
from utils.singleton_meta import SingletonMeta

# The session's StopEvent is a threading.Event and cannot be awaited, so the submit
# and the result wait wake up this often to check it.
STOP_CHECK_INTERVAL_S = 0.5
RESULT_TIMEOUT_TEXT = (
    "The code's result didn't arrive in time. Try again or contact your administrator."
)


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
        self._pending_results: dict[str, asyncio.Future[CodeResultData]] = {}

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
    ) -> CodeResultData:
        """Submit the code to the sandbox and wait for its result on crew's result channel.

        The submission goes over HTTP; the sandbox publishes the result to
        `crew_code_result_channel`, which only crew reads, and the one subscription made
        by `subscribe_to_results` hands each result to the execution waiting for it.
        Every way the execution can fail without a result -- the sandbox stayed full,
        refused it, lost it, or became unreachable -- logs the raw reason under a new
        reference and returns a result crew makes up, failed with `sandbox_error`, whose
        detail cites the reference and whose `reference` is set. The reason never reaches
        the result: it can be the sandbox's raw error body. No result within
        settings.CODE_RESULT_TIMEOUT (None waits as long as the sandbox still has the
        execution) returns a result failed with `result_timeout`. Either way the result
        holds the invariant every sandbox result holds: it failed exactly when `failure`
        is set, and its stderr is `failure.detail`.

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
        if python_code_data.session_id is not None:
            merged_global_kwargs["session_id"] = python_code_data.session_id

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
        result_future: asyncio.Future[CodeResultData] = asyncio.get_running_loop().create_future()
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
            return _failed_result(
                execution_id,
                CodeFailure(code=CodeFailureCode.RESULT_TIMEOUT, detail=RESULT_TIMEOUT_TEXT),
            )
        except (SandboxError, ClientError) as error:
            if isinstance(error, SandboxExecutionLostError):
                logger.log(
                    BENCH_LEVEL,
                    "bench {checkpoint}",
                    checkpoint="sandbox_lost",
                    session_id=python_code_data.session_id,
                    execution_id=execution_id,
                )
            reference = log_with_reference(
                "Code execution {execution_id} failed: {error_type}: {error} "
                "(session_id={session_id})",
                execution_id=execution_id,
                error_type=type(error).__name__,
                error=str(error),
                session_id=python_code_data.session_id,
            )
            return _sandbox_error_result(execution_id, reference)
        finally:
            self._pending_results.pop(execution_id, None)

    async def _on_result_message(self, message: dict[str, Any]) -> None:
        """Hand a result to the execution waiting for it.

        A result that doesn't validate fails its execution at once with `sandbox_error`,
        rather than leaving it to wait for the backstop, when its execution id can still
        be read. The payload is never logged: it carries the user code's output.
        """
        try:
            code_result_data = CodeResultData.model_validate_json(message["data"])
        except ValidationError as error:
            self._fail_on_invalid_result(message["data"], error)
            return
        result_future = self._pending_results.get(code_result_data.execution_id)
        if result_future is None or result_future.done():
            return
        result_future.set_result(code_result_data)

    def _fail_on_invalid_result(self, data: str, error: ValidationError) -> None:
        execution_id = _raw_execution_id(data)
        result_future = self._pending_results.get(execution_id) if execution_id else None
        if result_future is None or result_future.done():
            logger.error("Dropped an unparseable message on {}", self._result_channel)
            return
        # Field paths and error kinds only: the input of a validation error is the payload.
        reference = log_with_reference(
            "Code result for execution {execution_id} failed validation: {error_type} {problems}",
            execution_id=execution_id,
            error_type=type(error).__name__,
            problems=[
                (".".join(str(part) for part in problem["loc"]), problem["type"])
                for problem in error.errors()
            ],
        )
        result_future.set_result(_sandbox_error_result(execution_id, reference))


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


def _raw_execution_id(data: str) -> str | None:
    """Return the execution id of a result payload that didn't validate, if it has one."""
    try:
        payload = json.loads(data)
    except ValueError:
        return None
    execution_id = payload.get("execution_id") if isinstance(payload, dict) else None
    return execution_id if isinstance(execution_id, str) else None


def _sandbox_error_result(execution_id: str, reference: str) -> CodeResultData:
    """A result failed with `sandbox_error`, whose reason is logged under `reference`."""
    return _failed_result(
        execution_id,
        CodeFailure(
            code=CodeFailureCode.SANDBOX_ERROR,
            detail=build_public_error_message(PublicErrorMessage.NODE_EXECUTION_FAILED, reference),
        ),
        reference=reference,
    )


def _failed_result(
    execution_id: str, failure: CodeFailure, reference: str | None = None
) -> CodeResultData:
    """A result for an execution the sandbox never produced one for."""
    return CodeResultData(
        execution_id=execution_id,
        returncode=1,
        stdout="",
        stderr=failure.detail,
        result_data=None,
        failure=failure,
        reference=reference,
    )
