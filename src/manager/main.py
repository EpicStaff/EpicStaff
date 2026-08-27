import asyncio
import os
import signal

from db.config import AsyncSessionLocal
from sqlalchemy import text

from repositories.session_repository import SessionRepository

from services.redis_service import RedisService
from services.session_timeout_service import SessionTimeoutService
from services.schedule_service import ScheduleService
from helpers.logger import logger


redis_service = RedisService()

session_repository = SessionRepository(AsyncSessionLocal)

session_timeout_service = SessionTimeoutService(
    redis_service=redis_service,
    session_schema_channel=os.environ.get("SESSION_SCHEMA_CHANNEL", "sessions:schema"),
    session_timeout_channel=os.environ.get(
        "SESSION_TIMEOUT_CHANNEL", "sessions:timeout"
    ),
    session_repository=session_repository,
)

schedule_service = ScheduleService(redis_service=redis_service)


async def test_database_connection():
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))

            result = await session.execute(
                text(
                    "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'tables_session')"
                )
            )
            table_exists = result.scalar()

            if not table_exists:
                logger.warning(
                    "tables_session table does not exist - check your database schema"
                )

            await session.commit()

        logger.info("Successfully connected to PostgreSQL database")
        return True

    except Exception as e:
        logger.error(f"Database connection failed: {e}")
        return False


async def main():
    """
    Starts redis subscribtion, starts SessionTimeoutService, connects to DB
    """
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop_event.set)

    db_connected = await test_database_connection()
    if not db_connected:
        logger.error("Failed to connect to database during startup")

    try:
        await redis_service.init_redis()
        logger.info("Redis subscription initialized successfully.")

        await session_timeout_service.start()
        logger.info("SessionTimeoutService started successfully.")

        await session_timeout_service.initial_check_all_sessions_for_timeout()
        logger.info("Start SessionTimeoutService initial timeout check.")

        await schedule_service.start()
        logger.info("ScheduleService started successfully.")

    except Exception as e:
        logger.error(f"Error during initialization: {e}")

    await stop_event.wait()
    await shutdown()


async def shutdown():
    if session_timeout_service:
        await session_timeout_service.stop()

    if schedule_service.scheduler.running:
        schedule_service.scheduler.shutdown(wait=False)
    if redis_service.aioredis_client:
        await redis_service.aioredis_client.close()


if __name__ == "__main__":
    asyncio.run(main())
