from __future__ import annotations

import asyncio
import contextlib
import uuid

import redis.asyncio as aioredis
from loguru import logger

from app.sandbox.http_client import AsyncClient
from shared.models.tools import CodeResultData, CodeTaskData


class SandboxClient:
    """Submits code executions to sandbox_new over HTTP; receives results on Redis.

    Intake is `POST /executions` (sandbox_new's HTTP API). Results come back on the
    shared Redis result channel and are matched to their pending request by
    execution_id, exactly as before.
    """

    def __init__(
        self,
        host: str,
        port: int,
        password: str | None,
        result_channel: str,
        sandbox_base_url: str,
        sandbox_timeout: float,
    ) -> None:
        self._host = host
        self._port = port
        self._password = password
        self._result_channel = result_channel
        self._sandbox_base_url = sandbox_base_url
        self._sandbox_timeout = sandbox_timeout
        self._redis: aioredis.Redis | None = None
        self._pubsub: aioredis.client.PubSub | None = None
        self._http: AsyncClient | None = None
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
        self._http = AsyncClient(base_url=self._sandbox_base_url, timeout=self._sandbox_timeout)
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

    async def submit(self, task: CodeTaskData, *, timeout: float | None = None) -> CodeResultData:
        assert self._http is not None, "SandboxClient.start() must be called before submit()"
        execution_id = str(uuid.uuid4())

        loop = asyncio.get_running_loop()
        future: asyncio.Future[CodeResultData] = loop.create_future()
        self._pending[execution_id] = future

        try:
            await self._http.request(
                "POST",
                "/executions",
                json={
                    "execution_id": execution_id,
                    "venv_id": task.venv_id,
                    "session_id": task.session_id,
                    "code": task.code,
                    "entrypoint": task.entrypoint,
                    "func_kwargs": task.func_kwargs or {},
                    "global_kwargs": task.global_kwargs or {},
                    "secrets": task.secrets,
                    "use_storage": task.use_storage,
                    "storage_allowed_paths": task.storage_allowed_paths or [],
                    "storage_org_prefix": task.storage_org_prefix,
                    "timeout": None,
                },
            )

            if timeout is not None:
                return await asyncio.wait_for(asyncio.shield(future), timeout=timeout)

            return await future

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
