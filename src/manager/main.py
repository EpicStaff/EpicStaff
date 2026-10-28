import asyncio
import signal
from zoneinfo import ZoneInfo

import settings
from db.config import AsyncSessionLocal
from helpers.chat_retention_client import ChatRetentionClient
from helpers.logger import logger
from repositories.retention_repository import RetentionRepository
from repositories.session_repository import SessionRepository
from repositories.temp_storage_account_repository import TempStorageAccountRepository
from services.audit_export_cleanup_service import (
    ExportCleanupService,
    build_export_redis_client,
)
from services.redis_service import RedisService
from services.retention_service import RetentionService
from services.schedule_service import ScheduleService
from services.session_timeout_service import SessionTimeoutService
from services.storage_account_cleanup_service import StorageAccountCleanupService
from sqlalchemy import text

redis_service = RedisService(
    settings.REDIS_HOST,
    settings.REDIS_PORT,
    settings.REDIS_USER,
    settings.REDIS_PASSWORD,
)
redis_export_service = build_export_redis_client()

session_repository = SessionRepository(AsyncSessionLocal)

session_timeout_service = SessionTimeoutService(
    redis_service=redis_service,
    session_timeout_channel=settings.SESSION_TIMEOUT_CHANNEL,
    session_repository=session_repository,
    sweep_interval_seconds=settings.SESSION_TIMEOUT_SWEEP_INTERVAL_SECONDS,
)

schedule_service = ScheduleService(redis_service=redis_service)
export_cleanup_service = ExportCleanupService(
    redis_client=redis_export_service,
    sweep_interval_seconds=settings.AUDITOR_EXPORT_SWEEP_INTERVAL_SECONDS,
    export_data_dir=settings.AUDITOR_EXPORT_DATA_DIR,
)

temp_storage_account_repository = TempStorageAccountRepository(AsyncSessionLocal)
storage_account_cleanup_service = StorageAccountCleanupService(
    repository=temp_storage_account_repository,
    timezone=ZoneInfo(settings.TIMEZONE),
)

retention_service = RetentionService(
    repository=RetentionRepository(AsyncSessionLocal),
    chat_client=(
        ChatRetentionClient(settings.CHAT_UPSTREAM_URL, settings.CHAT_INTERNAL_API_KEY)
        if settings.CHAT_ENABLED
        else None
    ),
    policy=settings.RETENTION_POLICY,
    timezone=ZoneInfo(settings.TIMEZONE),
)


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
                logger.warning("tables_session table does not exist - check your database schema")

            await session.commit()

        logger.info("Successfully connected to PostgreSQL database")
        return True

    except Exception as e:
        logger.error(f"Database connection failed: {e}")
        return False


async def main():
    """Connect to the DB and Redis, then start the schedule, cleanup, retention, session-timeout and export-cleanup services."""
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

        await schedule_service.start()
        logger.info("ScheduleService started successfully.")

        await storage_account_cleanup_service.start()
        logger.info("StorageAccountCleanupService started successfully.")

        await retention_service.start()
        logger.info("RetentionService started successfully.")

        await session_timeout_service.start()
        logger.info("SessionTimeoutService started successfully.")

        await export_cleanup_service.start()
        logger.info("ExportCleanupService started successfully.")

    except Exception as e:
        logger.error(f"Error during initialization: {e}")

    await stop_event.wait()
    await shutdown()


async def shutdown():
    if session_timeout_service:
        await session_timeout_service.stop()

    if schedule_service.scheduler.running:
        schedule_service.scheduler.shutdown(wait=False)
    storage_account_cleanup_service.stop()
    retention_service.stop()
    if redis_service.aioredis_client:
        await redis_service.aioredis_client.close()
    await export_cleanup_service.stop()
    await redis_export_service.aclose()


if __name__ == "__main__":
    asyncio.run(main())
