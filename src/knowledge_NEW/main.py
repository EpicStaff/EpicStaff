import asyncio

from concurrent.futures.process import ProcessPoolExecutor

from handlers import IndexHandler, PrechunkHandler, SearchHandler
from settings import settings
from services.processing_run import set_process_pool
from src.shared.communication import (
    Consumer,
    Producer,
    Message,
    brokers,
    storages,
)

async def main():
    process_pool = ProcessPoolExecutor(settings.MAX_PROCESS_WORKERS)
    set_process_pool(process_pool)

    broker = brokers.RedisPubSubBroker(settings.BROKER_DNS)
    storage = storages.RedisStorage(settings.STORAGE_DNS)
    producer = Producer(broker, storage)
    consumer = Consumer(broker, storage)

    handlers = [
        PrechunkHandler,
        IndexHandler,
        SearchHandler,
    ]

    handler_tasks = [
        asyncio.create_task(h(producer, consumer).run())
        for h in handlers
    ]

    await asyncio.gather(*handler_tasks)


if __name__ == "__main__":
    asyncio.run(main())
