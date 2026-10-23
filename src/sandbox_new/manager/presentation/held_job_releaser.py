"""Periodically releases held jobs whose venv has finished building.

Venvs build out of band (the scheduled build task), so held jobs are released by
polling rather than by hooking into the build: every ``interval`` seconds the
orchestrator checks each waiting venv and dispatches the jobs whose venv is now
COMPLETED. A failing pass is logged and the loop carries on.
"""

import asyncio

from loguru import logger

from manager.application.orchestrators import JobOrchestrator

__all__ = ["HeldJobReleaser"]


class HeldJobReleaser:
    def __init__(self, orchestrator: JobOrchestrator, *, interval: float):
        self._orchestrator = orchestrator
        self._interval = interval

    async def run(self) -> None:
        while True:
            await asyncio.sleep(self._interval)
            try:
                await self._orchestrator.flush_pending()
            except Exception:
                logger.exception("Held-job release pass failed")
