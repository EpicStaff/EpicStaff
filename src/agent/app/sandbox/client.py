from __future__ import annotations

import asyncio
import contextlib
import uuid
from functools import partial

import redis.asyncio as aioredis
from foundation.clients.sandbox import ExecutionRequest, SandboxExecutionLostError
from foundation.clients.sandbox import SandboxClient as SandboxHttpClient
from loguru import logger

from shared.bench_log import BENCH_LEVEL
from shared.models.tools import CodeResultData, CodeTaskData


class SandboxClient:
    """Submits code executions to sandbox_new over HTTP; receives results on Redis.

    Intake is `POST /executions` (sandbox_new's HTTP API), through the shared
    foundation client, which retries a full sandbox and watches over each pending
    execution. Results come back on the shared Redis result channel and are matched
    to their pending request by execution_id. The task's storage credentials are
    minted upstream and only passed through here; sandbox_new rejects a task with
    `use_storage` set and no credentials.
    """

    def __init__(
        self,
        host: str,
        port: int,
        password: str | None,
        result_channel: str,
        sandbox_base_url: str,
        sandbox_timeout: float,
        queue_timeout: float,
        code_result_timeout: float | None,
    ) -> None:
        self._host = host
        self._port = port
        self._password = password
        self._result_channel = result_channel
        self._sandbox_base_url = sandbox_base_url
        self._sandbox_timeout = sandbox_timeout
        self._queue_timeout = queue_timeout
        self._code_result_timeout = code_result_timeout
        self._redis: aioredis.Redis | None = None
        self._pubsub: aioredis.client.PubSub | None = None
        self._http: SandboxHttpClient | None = None
        self._reader_task: asyncio.Task | None = None
        self._pending: dict[str, asyncio.Future[CodeResultData]] = {}
        self._started = False

    async def start(self) -> None:
        if self._started:
            return

        redis_conn = aioredis.Redis(
            host=self._host,
            port=self._port,
            password=self._password,
        )
        self._redis = redis_conn
        pubsub = redis_conn.pubsub()
        self._pubsub = pubsub
        await pubsub.subscribe(self._result_channel)
        self._http = SandboxHttpClient(
            queue_timeout=self._queue_timeout,
            base_url=self._sandbox_base_url,
            timeout=self._sandbox_timeout,
        )
        self._reader_task = asyncio.create_task(self._reader_loop())
        self._started = True
        logger.info("SandboxClient started, subscribed to {}", self._result_channel)

    async def stop(self) -> None:
        if not self._started:
            return

        if self._reader_task is not None:
            self._reader_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._reader_task

        error = ConnectionError("SandboxClient stopped")

        for future in self._pending.values():
            if not future.done():
                future.set_exception(error)

        self._pending.clear()

        if self._http is not None:
            await self._http.aclose()

        if self._pubsub is not None:
            await self._pubsub.close()

        if self._redis is not None:
            await self._redis.aclose()

        self._started = False
        logger.info("SandboxClient stopped")

    async def submit(self, task: CodeTaskData) -> CodeResultData:
        """Run `task` in the sandbox and return its result.

        The task gets a fresh execution id; its own is ignored.

        Raises:
            ClientError: The sandbox stayed full, refused or lost the execution, could
                not be reached, or no result arrived within `code_result_timeout`.
                The message is fit to show the user.
            ConnectionError: The client stopped, or its result listener failed,
                while the execution was pending.
        """
        assert self._http is not None, "SandboxClient.start() must be called before submit()"
        execution_id = str(uuid.uuid4())

        loop = asyncio.get_running_loop()
        future: asyncio.Future[CodeResultData] = loop.create_future()
        self._pending[execution_id] = future

        try:
            await self._http.submit(
                ExecutionRequest(
                    execution_id=execution_id,
                    session_id=task.session_id,
                    code=task.code,
                    entrypoint=task.entrypoint,
                    global_kwargs=task.global_kwargs or {},
                    func_kwargs=task.func_kwargs or {},
                    secrets=task.secrets,
                    venv_id=task.venv_id,
                    use_storage=task.use_storage,
                    storage_allowed_paths=task.storage_allowed_paths or [],
                    storage_org_prefix=task.storage_org_prefix,
                    storage_credentials=(
                        task.storage_credentials.model_dump()
                        if task.storage_credentials is not None
                        else None
                    ),
                    timeout=task.execution_timeout,
                ),
                on_rejected=partial(_log_rejected, task.session_id, execution_id),
            )
            logger.log(
                BENCH_LEVEL,
                "bench {checkpoint}",
                checkpoint="sandbox_dispatched",
                session_id=task.session_id,
                execution_id=execution_id,
            )
            return await self._http.wait_for_result(
                execution_id, future, backstop=self._code_result_timeout
            )
        except SandboxExecutionLostError:
            logger.log(
                BENCH_LEVEL,
                "bench {checkpoint}",
                checkpoint="sandbox_lost",
                session_id=task.session_id,
                execution_id=execution_id,
            )
            raise
        finally:
            self._pending.pop(execution_id, None)

    async def _reader_loop(self) -> None:
        assert self._pubsub is not None, "SandboxClient.start() must be called before _reader_loop"
        try:
            async for message in self._pubsub.listen():
                if message["type"] != "message":
                    continue

                data = message["data"]

                if isinstance(data, bytes):
                    data = data.decode()

                try:
                    result = CodeResultData.model_validate_json(data)
                except Exception as error:
                    logger.warning("SandboxClient: failed to parse pubsub message: {}", error)
                    continue

                future = self._pending.get(result.execution_id)

                if future is not None and not future.done():
                    future.set_result(result)

        except asyncio.CancelledError:
            raise

        except Exception as error:
            logger.error("SandboxClient reader loop failed: {}", error)
            connection_error = ConnectionError(f"SandboxClient reader loop failed: {error}")

            for future in self._pending.values():
                if not future.done():
                    future.set_exception(connection_error)

            self._pending.clear()


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
