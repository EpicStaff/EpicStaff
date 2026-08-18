from __future__ import annotations

import asyncio
from uuid import uuid4

import redis.asyncio as aioredis
from loguru import logger

from app.knowledge.target import KnowledgeSearchTarget
from shared.models.knowledge import (
    BaseKnowledgeSearchMessage,
    BaseKnowledgeSearchMessageResponse,
)


class KnowledgeClient:
    def __init__(
        self,
        host: str,
        port: int,
        password: str | None,
        request_channel: str,
        response_channel: str,
    ) -> None:
        self._host = host
        self._port = port
        self._password = password
        self._request_channel = request_channel
        self._response_channel = response_channel
        self._redis: aioredis.Redis | None = None
        self._pubsub: aioredis.client.PubSub | None = None
        self._reader_task: asyncio.Task | None = None
        self._pending: dict[
            str, asyncio.Future[BaseKnowledgeSearchMessageResponse]
        ] = {}
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
        await pubsub.subscribe(self._response_channel)
        self._reader_task = asyncio.create_task(self._reader_loop())
        self._started = True
        logger.info("KnowledgeClient started, subscribed to {}", self._response_channel)

    async def stop(self) -> None:
        if not self._started:
            return

        if self._reader_task is not None:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass

        error = ConnectionError("KnowledgeClient stopped")

        for future in self._pending.values():
            if not future.done():
                future.set_exception(error)

        self._pending.clear()

        if self._pubsub is not None:
            await self._pubsub.close()

        if self._redis is not None:
            await self._redis.aclose()

        self._started = False
        logger.info("KnowledgeClient stopped")

    async def search(
        self, target: KnowledgeSearchTarget, query: str, *, timeout: float
    ) -> BaseKnowledgeSearchMessageResponse:
        assert (
            self._redis is not None
        ), "KnowledgeClient.start() must be called before search()"

        search_uuid = str(uuid4())
        msg = BaseKnowledgeSearchMessage(
            collection_id=target.collection_id,
            rag_id=target.rag_id,
            rag_type=target.rag_type,
            uuid=search_uuid,
            query=query,
            rag_search_config=target.search_config,
        )

        loop = asyncio.get_running_loop()
        future: asyncio.Future[BaseKnowledgeSearchMessageResponse] = (
            loop.create_future()
        )
        self._pending[search_uuid] = future

        try:
            await self._redis.publish(self._request_channel, msg.model_dump_json())
            return await asyncio.wait_for(asyncio.shield(future), timeout=timeout)

        finally:
            self._pending.pop(search_uuid, None)

    async def _reader_loop(self) -> None:
        assert (
            self._pubsub is not None
        ), "KnowledgeClient.start() must be called before _reader_loop"
        try:
            async for message in self._pubsub.listen():
                if message["type"] != "message":
                    continue

                data = message["data"]

                if isinstance(data, bytes):
                    data = data.decode()

                try:
                    resp = BaseKnowledgeSearchMessageResponse.model_validate_json(data)
                except Exception as parse_error:
                    logger.warning(
                        "KnowledgeClient: failed to parse pubsub message: {}",
                        parse_error,
                    )
                    continue

                future = self._pending.get(resp.uuid)

                if future is not None and not future.done():
                    future.set_result(resp)

        except asyncio.CancelledError:
            raise

        except Exception as error:
            logger.error("KnowledgeClient reader loop failed: {}", error)
            connection_error = ConnectionError(
                f"KnowledgeClient reader loop failed: {error}"
            )

            for future in self._pending.values():
                if not future.done():
                    future.set_exception(connection_error)

            self._pending.clear()
