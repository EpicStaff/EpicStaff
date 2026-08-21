from __future__ import annotations

import asyncio
import uuid
from typing import TYPE_CHECKING

import redis.asyncio as aioredis
from loguru import logger

from shared.models.tools import CodeResultData, CodeTaskData

if TYPE_CHECKING:
    pass


class SandboxClient:
    def __init__(
        self,
        host: str,
        port: int,
        password: str | None,
        request_channel: str,
        result_channel: str,
    ) -> None:
        self._host = host
        self._port = port
        self._password = password
        self._request_channel = request_channel
        self._result_channel = result_channel
        self._redis: aioredis.Redis | None = None
        self._pubsub: aioredis.client.PubSub | None = None
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
        self._reader_task = asyncio.create_task(self._reader_loop())
        self._started = True
        logger.info("SandboxClient started, subscribed to {}", self._result_channel)

    async def stop(self) -> None:
        if not self._started:
            return

        if self._reader_task is not None:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass

        error = ConnectionError("SandboxClient stopped")

        for future in self._pending.values():
            if not future.done():
                future.set_exception(error)

        self._pending.clear()

        if self._pubsub is not None:
            await self._pubsub.close()

        if self._redis is not None:
            await self._redis.aclose()

        self._started = False
        logger.info("SandboxClient stopped")

    async def submit(
        self, task: CodeTaskData, *, timeout: float | None = None
    ) -> CodeResultData:
        assert (
            self._redis is not None
        ), "SandboxClient.start() must be called before submit()"
        execution_id = str(uuid.uuid4())
        task = task.model_copy(update={"execution_id": execution_id})

        loop = asyncio.get_running_loop()
        future: asyncio.Future[CodeResultData] = loop.create_future()
        self._pending[execution_id] = future

        try:
            await self._redis.publish(self._request_channel, task.model_dump_json())

            if timeout is not None:
                return await asyncio.wait_for(asyncio.shield(future), timeout=timeout)

            return await future

        finally:
            self._pending.pop(execution_id, None)

    async def _reader_loop(self) -> None:
        assert (
            self._pubsub is not None
        ), "SandboxClient.start() must be called before _reader_loop"
        try:
            async for message in self._pubsub.listen():
                if message["type"] != "message":
                    continue

                data = message["data"]

                if isinstance(data, bytes):
                    data = data.decode()

                try:
                    result = CodeResultData.model_validate_json(data)
                except Exception as parse_error:
                    logger.warning(
                        "SandboxClient: failed to parse pubsub message: {}", parse_error
                    )
                    continue

                future = self._pending.get(result.execution_id)

                if future is not None and not future.done():
                    future.set_result(result)

        except asyncio.CancelledError:
            raise

        except Exception as error:
            logger.error("SandboxClient reader loop failed: {}", error)
            connection_error = ConnectionError(
                f"SandboxClient reader loop failed: {error}"
            )

            for future in self._pending.values():
                if not future.done():
                    future.set_exception(connection_error)

            self._pending.clear()
