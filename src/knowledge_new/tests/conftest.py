import asyncio
import os
from concurrent.futures import ProcessPoolExecutor
from typing import Any

from infrastructure.processing_run import set_process_pool


async def offload_to_process(make_coro) -> tuple[Any, int]:
    """Run an extractor coroutine through a real ProcessPoolExecutor.

    `make_coro` is called while the pool is installed so the work is offloaded.
    Returns (result, worker_pid); the global pool is always reset afterwards.
    """
    loop = asyncio.get_running_loop()
    with ProcessPoolExecutor(max_workers=1) as pool:
        set_process_pool(pool)
        try:
            result = await make_coro()
            worker_pid = await loop.run_in_executor(pool, os.getpid)
        finally:
            set_process_pool(None)
    return result, worker_pid
