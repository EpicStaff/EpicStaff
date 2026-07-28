import asyncio
from concurrent.futures.process import ProcessPoolExecutor

from handlers import IndexHandler, PrechunkHandler, SearchHandler
from handlers.cancel_handler import CancelHandler
from loguru import logger
from services.processing_run import set_process_pool
from settings import settings
from src.shared.communication import Consumer, Producer, brokers, storages
from services.prompt_patching import patch_graphrag_prompts


async def main():
    patch_graphrag_prompts()
    process_pool = ProcessPoolExecutor(settings.MAX_PROCESS_WORKERS)
    set_process_pool(process_pool)

    broker = brokers.RedisPubSubBroker(settings.BROKER_DNS)
    storage = storages.RedisStorage(settings.STORAGE_DNS)
    producer = Producer(broker, storage)
    consumer = Consumer(broker, storage)

    handlers = [PrechunkHandler, IndexHandler, SearchHandler, CancelHandler]
    logger.info("knowledge_new started; handlers: {}", [h.__name__ for h in handlers])

    handler_tasks = [asyncio.create_task(h(producer, consumer).run()) for h in handlers]

    await asyncio.gather(*handler_tasks)


if __name__ == "__main__":
    asyncio.run(main())
