import asyncio
import contextlib

from helpers.logger import logger
from repositories.session_repository import SessionRepository

from services.redis_service import RedisService


class SessionTimeoutService:
    """Expire sessions that outlived their time_to_live.

    One periodic sweep asks the database for overdue sessions and publishes a
    timeout message for each on session_timeout_channel; crew then sets the
    status to 'expired'. A session that is still overdue on the next sweep (crew
    was down or has not processed the message yet) is published again, which is
    safe: crew marks it expired whether or not the session is in its pool.
    """

    def __init__(
        self,
        redis_service: RedisService,
        session_timeout_channel: str,
        session_repository: SessionRepository,
        sweep_interval_seconds: float,
    ):
        self.redis_service = redis_service
        self.session_timeout_channel = session_timeout_channel
        self.session_repository = session_repository
        self.sweep_interval_seconds = sweep_interval_seconds
        self._task: asyncio.Task | None = None

    async def start(self):
        """Start the sweep loop in the background; returns immediately."""
        self._task = asyncio.create_task(self._sweep_loop())
        logger.info("Session timeout sweep started (every {} s)", self.sweep_interval_seconds)

    async def stop(self):
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _sweep_loop(self):
        while True:
            try:
                await self.sweep_once()
            except Exception:
                # The database or Redis being briefly unavailable must not stop
                # timeout enforcement for good; the next tick retries.
                logger.exception("Session timeout sweep failed")
            await asyncio.sleep(self.sweep_interval_seconds)

    async def sweep_once(self):
        """Publish a timeout message for every overdue session."""
        overdue_session_ids = await self.session_repository.get_overdue_session_ids()
        for session_id in overdue_session_ids:
            await self.redis_service.async_publish(
                self.session_timeout_channel,
                {"session_id": session_id, "action": "timeout"},
            )
        if overdue_session_ids:
            logger.info("Published timeout for {} overdue sessions", len(overdue_session_ids))
            logger.debug("Overdue session ids: {}", overdue_session_ids)
