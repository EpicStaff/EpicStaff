from datetime import UTC, datetime

from core import config
from loguru import logger
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from infrastructure.persistence.db_models import RealtimeSessionItem
from infrastructure.persistence.event_redaction import redact_event_for_storage

engine = create_async_engine(config.DATABASE_URL, echo=False)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, class_=AsyncSession)


async def get_db():
    async with SessionLocal() as session:
        yield session


async def save_realtime_session_item_to_db(
    data, connection_key, org_id: int | None = None, user_id: int | None = None
):
    """Save data to the database.

    `user_id` maps to `created_by_id` — populated for browser /chats sessions
    (a real authenticated user started them) and left `None` for Twilio voice
    calls, which have no end-user identity to attribute to.

    Unless `config.PERSIST_RAW_AUDIO` is on, every event passes through
    `redact_event_for_storage` here, so audio does not reach the table regardless
    of which handler calls this. Audio-only events are then not stored and the
    function returns None.
    """
    if not config.PERSIST_RAW_AUDIO:
        data = redact_event_for_storage(data)
        if data is None:
            return None

    async with SessionLocal() as db_session:
        try:
            realtime_session_item = RealtimeSessionItem(
                connection_key=connection_key,
                data=data,
                org_id=org_id,
                created_by_id=user_id,
                created_at=datetime.now(UTC),
            )
            db_session.add(realtime_session_item)
            await db_session.commit()
            await db_session.refresh(realtime_session_item)
            return realtime_session_item
        except SQLAlchemyError:
            await db_session.rollback()
            logger.exception("Error saving to DB")
