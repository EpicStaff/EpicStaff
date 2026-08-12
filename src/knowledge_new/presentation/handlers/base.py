import abc
import asyncio
from typing import Any

from common.utils import hash_dict
from infrastructure.task_register import task_register
from loguru import logger
from pydantic import BaseModel
from src.shared.communication import Consumer, Message, Producer

type Payload = dict[str, Any]


class AbstractHandler[TRequest: BaseModel, TResponse: BaseModel](abc.ABC):
    """Generic async request handler that consumes from a channel and optionally produces responses.

    Attributes:
        consumer_channel: Channel name this handler subscribes to.
        producer_channel: Channel name responses are published to. `None` for fire-and-forget handlers.
        request_class: Pydantic model class used to deserialise incoming payloads.
        response_class: Pydantic model class for the response. `None` when no response is produced.
    """

    consumer_channel: str
    producer_channel: str | None = None
    request_class: type[TRequest]
    response_class: type[TResponse] | None = None

    def __init__(self, producer: Producer, consumer: Consumer):
        self.producer = producer
        self.consumer = consumer

    @abc.abstractmethod
    async def handle(self, request: TRequest) -> TResponse | None:
        """Process `request` and return a response, or `None` for fire-and-forget.

        Args:
            request: Deserialised request payload.
        """

    async def run(self):
        """Consume messages from `consumer_channel` and dispatch each as a background task.

        Note:
            Each message is handled concurrently via `asyncio.create_task`; errors in
            individual tasks are logged and do not stop the consumer loop.
        """
        async for msg in self.consumer.astream(self.consumer_channel):
            asyncio.create_task(self._run(msg.payload))  # noqa: RUF006

    async def _run(self, payload: Payload):
        try:
            request = self.request_class(**payload)
            logger.info("{} received request {}", type(self).__name__, request)
            response = await self._invoke(request)
            if response is not None:
                message = Message(payload=response.model_dump())
                await self.producer.asend(self.producer_channel, message)
        except Exception as e:
            logger.exception("{} failed: {}", type(self).__name__, e)

    async def _invoke(self, request: TRequest) -> TResponse | None:
        return await self.handle(request)


class AbstractCancellableHandler[TRequest: BaseModel, TResponse: BaseModel](
    AbstractHandler[TRequest, TResponse],
    abc.ABC,
):
    async def _invoke(self, request: TRequest) -> TResponse | None:
        key = hash_dict(request.model_dump())
        if key in task_register:
            task_register.cancel(key)
            logger.info("Superseded previous request {} by a newer one.", request)
        task_register.register(key, asyncio.current_task())
        try:
            return await self.handle(request)
        finally:
            task_register.discard(key)
