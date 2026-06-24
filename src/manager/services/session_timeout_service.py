import json
import asyncio
from typing import Dict
from datetime import datetime, timezone

from services.redis_service import RedisService
from repositories.session_repository import SessionRepository

from helpers.logger import logger


class SessionTimeoutService:
    def __init__(
        self,
        redis_service: RedisService,
        session_schema_channel: str,
        session_timeout_channel: str,
        session_repository: SessionRepository,
        first_check_interval: int = 3,
    ):
        self.redis_service = redis_service
        self.session_schema_channel = session_schema_channel
        self.session_timeout_channel = session_timeout_channel

        self.first_check_interval = first_check_interval

        self.session_repository: SessionRepository = session_repository
        # Dictionary to track active session timeout tasks
        self.timeout_tasks_pool: Dict[int, asyncio.Task] = {}

    async def start(self):
        """
        Start the session timeout monitoring service
        """
        asyncio.create_task(self._listen_for_session_starts())
        logger.info("Session Timeout Service started.")

    async def initial_check_all_sessions_for_timeout(self):
        """
        Check all active sessions in the database for timeout
        """
        # TODO: cnahge to crew health_check in docker-compose.yaml
        await asyncio.sleep(90)  # ensures crew container is initialized
        try:
            active_sessions = await self.session_repository.get_all_active_sessions()

            if not active_sessions:
                logger.debug("No active sessions found for timeout checking")
                return

            logger.info(f"Checking {len(active_sessions)} active sessions for timeout")
            for session in active_sessions:
                session_id = session["session_id"]

                if session_id in self.timeout_tasks_pool:
                    continue

                status = session["status"]
                time_to_live = session["time_to_live"]
                last_update = session["status_updated_at"]
                time_elapsed = self._get_time_elapsed(last_update)

                if status in ["run", "pending", "wait_for_user"]:
                    if time_elapsed > time_to_live:
                        await self._publish_session_timeout(session_id)
                        logger.info(
                            f"Session {session_id} timed out during check all sessions"
                        )
                    else:
                        # If not timed out, create a monitoring task
                        timeout_task = asyncio.create_task(
                            self._monitor_session_timeout(session_id)
                        )
                        self.timeout_tasks_pool[session_id] = timeout_task
                        logger.info(
                            f"Started monitoring session {session_id} for timeout from initial check"
                        )

        except Exception as e:
            logger.error(f"Error checking all sessions for timeout: {e}")

    async def _listen_for_session_starts(self):
        """
        Asynchronously listen for new session start messages
        """
        while True:
            try:
                pubsub = await self.redis_service.async_subscribe(
                    self.session_schema_channel
                )
                async for message in pubsub.listen():
                    if message["type"] == "message":
                        try:
                            data = json.loads(message["data"].decode("utf-8"))
                            session_id = data.get("id")
                            if session_id is not None:
                                await self._handle_session_start(session_id)
                            else:
                                logger.warning(
                                    f"Can not get session ID from message: {message['data']}"
                                )
                        except Exception as e:
                            logger.error(f"Error processing session start message: {e}")
            except Exception as e:
                logger.error(
                    f"Redis session listener disconnected, reconnecting in 1s: {e}"
                )
                await asyncio.sleep(1)

    def _clean_timeout_tasks_pool(self, session_id: int) -> None:
        if session_id in self.timeout_tasks_pool:
            task = self.timeout_tasks_pool.pop(session_id)
            if not task.done() and not task.cancelled():
                task.cancel()

    async def _handle_session_start(self, session_id: int):
        """
        Handle a new session start by creating a timeout monitoring task
        """
        try:
            # Cancel any existing timeout task for this session
            self._clean_timeout_tasks_pool(session_id)

            # Create a new timeout monitoring task
            timeout_task = asyncio.create_task(
                self._monitor_session_timeout(session_id)
            )
            self.timeout_tasks_pool[session_id] = timeout_task
        except Exception as e:
            logger.error(f"Error handling session start: {e}")

    async def _monitor_session_timeout(self, session_id: int):
        """
        Monitor a specific session for timeout
        """
        try:
            logger.info(f"Start timeout monitoring task for session ID: {session_id}.")
            check_interval = self.first_check_interval
            while True:
                await asyncio.sleep(check_interval)
                session_data = await self._get_monitoring_data(session_id)
                if session_data is None:
                    logger.error(f"No session data found for session_id: {session_id}")

                status, time_to_live, last_update = session_data

                if time_to_live == 0:
                    logger.info(
                        f"Field 'time_to_live' for session ID: {session_id} is not set. Session timeout is not monitored."
                    )
                    break

                time_elapsed = self._get_time_elapsed(last_update)

                # If session is not in active state, stop monitoring
                if status not in ["run", "pending", "wait_for_user"]:
                    logger.info(
                        f"Session {session_id} no longer running. Stopping timeout monitoring."
                    )
                    self._clean_timeout_tasks_pool(session_id)
                    break

                if time_elapsed > time_to_live:
                    await self._publish_session_timeout(session_id)
                    logger.info(f"Session {session_id} timed out.")
                    self._clean_timeout_tasks_pool(session_id)
                    break
                else:
                    check_interval = time_to_live - time_elapsed + 3

        except asyncio.CancelledError:
            logger.info(f"Timeout monitoring for session {session_id} cancelled.")
        except Exception as e:
            logger.error(
                f"Error in session timeout monitoring for session {session_id}: {e}"
            )

    async def _get_monitoring_data(self, session_id: int) -> tuple:
        """
        Retrieve status, time_to_live, last_update from DB
        """
        try:
            session_data = await self.session_repository.get_session_fields(session_id)
            if session_data is not None:
                status = session_data.get("status")
                time_to_live = session_data.get("time_to_live")
                last_update = session_data.get("status_updated_at")
            else:
                logger.error("Error fetching session data")
            return status, time_to_live, last_update

        except Exception as e:
            logger.error(f"Error getting session status for {session_id}: {e}")
            return

    def _get_time_elapsed(self, last_update: datetime) -> float:
        """
        Calculate the elapsed time (in seconds) since the last update.
        """
        now = datetime.now(timezone.utc)
        return (now - last_update).total_seconds()

    async def _publish_session_timeout(self, session_id: int):
        """
        Publish a timeout message for a specific session
        """
        try:
            timeout_message = {
                "session_id": session_id,
                "action": "timeout",
            }

            # Publish to crew
            await self.redis_service.async_publish(
                self.session_timeout_channel, timeout_message
            )

            logger.info(f"Published timeout message for session {session_id}")
        except Exception as e:
            logger.error(
                f"Error publishing timeout message for session {session_id}: {e}"
            )

    async def stop(self):
        """
        Stop all active timeout monitoring tasks
        """
        for task in self.timeout_tasks_pool.values():
            task.cancel()
        self.timeout_tasks_pool.clear()
