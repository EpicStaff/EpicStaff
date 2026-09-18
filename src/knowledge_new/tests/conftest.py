# nltk's import-security hook (nltk/inisec.py) blocks any module it imports whose
# file resolves inside the current working directory. When pytest is invoked from
# this service's own directory, its `.venv` (and thus every third-party package's
# site-packages location) lives inside that cwd, so nltk's own dependencies
# (`regex`, `defusedxml`) get misidentified as untrusted local files and the
# `graphrag` import chain (graphrag.api -> nltk) fails to collect. Importing them
# here, before any test module reaches nltk indirectly, populates `sys.modules` so
# later `import regex` / `import defusedxml...` calls are served from cache instead
# of re-triggering nltk's blocked finder.
import defusedxml.ElementTree  # noqa: F401
import regex  # noqa: F401

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
