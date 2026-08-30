from dataclasses import dataclass

import redis.asyncio as aioredis
from loguru import logger
from redis.backoff import ExponentialBackoff
from redis.exceptions import ResponseError
from redis.retry import Retry


@dataclass
class StreamMessage:
    stream: str
    message_id: str
    fields: dict[str, str]


class RedisStreamClient:
    def __init__(
        self,
        host: str,
        port: int,
        password: str | None = None,
        retry_attempts: int = 10,
        backoff_cap: int = 3,
        decode_responses: bool = True,
    ) -> None:
        self._host = host
        self._port = port
        self._password = password
        self._retry = Retry(
            backoff=ExponentialBackoff(cap=backoff_cap), retries=retry_attempts
        )
        self._decode_responses = decode_responses
        self._client: aioredis.Redis | None = None

    async def connect(self) -> None:
        url = f"redis://{self._host}:{self._port}"
        self._client = await aioredis.from_url(
            url,
            password=self._password,
            decode_responses=self._decode_responses,
            retry=self._retry,
        )
        logger.info("connected to redis at {}:{}", self._host, self._port)

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
            logger.info("redis connection closed")

    async def ping(self) -> bool:
        assert self._client is not None, "call connect() first"
        result = await self._client.ping()
        return bool(result)

    async def ensure_group(
        self,
        stream: str,
        group: str,
        start_id: str = "$",
        mkstream: bool = True,
    ) -> None:
        assert self._client is not None, "call connect() first"
        try:
            await self._client.xgroup_create(
                stream, group, id=start_id, mkstream=mkstream
            )
            logger.info("consumer group created: {} @ {}", group, stream)
        except ResponseError as error:
            if "BUSYGROUP" in str(error):
                logger.info("consumer group ensured: {} @ {}", group, stream)
            else:
                raise

    async def read(
        self,
        streams: dict[str, str],
        group: str,
        consumer: str,
        count: int = 10,
        block_ms: int = 5000,
    ) -> list[StreamMessage]:
        assert self._client is not None, "call connect() first"
        raw = await self._client.xreadgroup(
            groupname=group,
            consumername=consumer,
            streams=streams,
            count=count,
            block=block_ms,
        )
        messages: list[StreamMessage] = []

        if not raw:
            return messages

        for stream_name, entries in raw:
            for message_id, fields in entries:
                messages.append(
                    StreamMessage(
                        stream=stream_name, message_id=message_id, fields=fields
                    )
                )

        logger.debug(
            "read {} messages from streams {}", len(messages), list(streams.keys())
        )
        return messages

    async def ack(self, stream: str, group: str, *message_ids: str) -> int:
        assert self._client is not None, "call connect() first"
        count = await self._client.xack(stream, group, *message_ids)
        logger.debug("acked {} messages on {}/{}", count, stream, group)
        return count

    async def publish(
        self,
        stream: str,
        fields: dict[str, str],
        maxlen: int | None = 1_000_000,
        approximate: bool = True,
    ) -> str:
        assert self._client is not None, "call connect() first"
        message_id = await self._client.xadd(
            stream,
            fields,
            maxlen=maxlen,
            approximate=approximate,
        )
        logger.debug("published message to {}", stream)
        return message_id

    async def pending(self, stream: str, group: str) -> object:
        assert self._client is not None, "call connect() first"
        return await self._client.xpending(stream, group)
