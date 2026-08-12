import asyncio
from concurrent.futures.process import ProcessPoolExecutor

from api.routes import KnowledgeController
from litestar import Litestar
from loguru import logger
from main import start_workers
from services.processing_run import set_process_pool
from settings import settings


async def _on_startup(app: Litestar) -> None:
    pool = ProcessPoolExecutor(settings.MAX_PROCESS_WORKERS)
    set_process_pool(pool)
    app.state.process_pool = pool
    app.state.workers_task = asyncio.create_task(start_workers())
    logger.info("knowledge_new started (HTTP + Redis workers in one process)")


async def _on_shutdown(app: Litestar) -> None:
    task = getattr(app.state, "workers_task", None)
    if task is not None:
        task.cancel()
    pool = getattr(app.state, "process_pool", None)
    if pool is not None:
        pool.shutdown(cancel_futures=True)
    set_process_pool(None)


app = Litestar(
    route_handlers=[KnowledgeController],
    on_startup=[_on_startup],
    on_shutdown=[_on_shutdown],
)
