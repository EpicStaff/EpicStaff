import asyncio
import sys
from concurrent.futures.process import ProcessPoolExecutor
from typing import Callable, Any, Awaitable

from loguru import logger

from models import PrechunkRequest, IndexRequest, SearchRequest
from settings import settings
from database.unit_of_work import AbstractUnitOfWork, SQLAlchemyUnitOfWork
from orchestrators.indexing import build_indexer
from orchestrators.prechunking import build_prechunker
from orchestrators.searching import build_search
from services.processing_run import set_process_pool
from src.shared.communication import Consumer, Producer, Message, brokers, storages


logger.remove()
logger.add(sys.stderr, level="DEBUG")

type Payload = dict[str, Any]
type Handler = Callable[[Payload, AbstractUnitOfWork], Awaitable[Payload | None]]


async def handle_prechunk(payload: Payload, uow: AbstractUnitOfWork) -> Payload:
    request = PrechunkRequest(**payload)
    logger.info("handle prechunk request={}", request)
    prechunker = build_prechunker(request.rag_strategy)
    response = await prechunker.chunk(request, uow)
    return response.model_dump()


async def handle_index(payload: Payload, uow: AbstractUnitOfWork) -> None:
    request = IndexRequest(**payload)
    logger.info("handle index request={}", request)
    indexer = build_indexer(request.rag_strategy)
    await indexer.index(request, uow)
    return None


async def handle_search(payload: Payload, uow: AbstractUnitOfWork) -> Payload:
    request = SearchRequest(**payload)
    logger.info("handle search request={}", request)
    search = build_search(request.search_config.rag_strategy)
    response = await search.search(request, uow)
    return response.model_dump()


async def run_handler(
    handler: Callable[[Payload, AbstractUnitOfWork], Awaitable[Payload | None]],
    consumer: Consumer,
    consumer_channel: str,
    producer: Producer,
    producer_channel: str,
):
    async for msg in consumer.areceive(consumer_channel):
        asyncio.create_task(
            wrap_handler(
                handler,
                msg,
                producer,
                producer_channel,
            )
        )


async def wrap_handler(
    handler: Callable[[Payload, AbstractUnitOfWork], Awaitable[Payload | None]],
    message: Message,
    producer: Producer,
    producer_channel: str,
):
    uow = SQLAlchemyUnitOfWork()
    try:
        payload = await handler(message.payload, uow)
    except Exception as e:
        logger.error(
            "{} failed (channel={}, msg_id={}). Error: {}",
            handler.__name__,
            producer_channel,
            message.id,
            e,
        )
        return
    else:
        if payload is not None:
            await producer.asend(
                channel=producer_channel,
                message=Message(payload=payload),
            )


async def main():
    process_pool = ProcessPoolExecutor(settings.MAX_PROCESS_WORKERS)
    set_process_pool(process_pool)

    broker = brokers.RedisPubSubBroker(settings.BROKER_DNS)
    storage = storages.RedisStorage(settings.STORAGE_DNS)
    producer = Producer(broker, storage)
    consumer = Consumer(broker, storage)

    search_handler = asyncio.create_task(
        run_handler(
            handler=handle_search,
            consumer=consumer,
            consumer_channel=settings.SEARCH_REQUEST_CHANNEL,
            producer=producer,
            producer_channel=settings.SEARCH_RESPONSE_CHANNEL,
        )
    )
    index_handler = asyncio.create_task(
        run_handler(
            handler=handle_index,
            consumer=consumer,
            consumer_channel=settings.INDEX_REQUEST_CHANNEL,
            producer=producer,
            producer_channel="none",
        )
    )
    prechunk_handler = asyncio.create_task(
        run_handler(
            handler=handle_prechunk,
            consumer=consumer,
            consumer_channel=settings.PRECHUNK_REQUEST_CHANNEL,
            producer=producer,
            producer_channel=settings.PRECHUNK_RESPONSE_CHANNEL,
        )
    )

    await asyncio.gather(
        search_handler,
        index_handler,
        prechunk_handler,
    )


if __name__ == "__main__":
    asyncio.run(main())
