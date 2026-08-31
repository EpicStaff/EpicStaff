from datetime import datetime
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from infrastructure.persistence.db_models import RealtimeSessionItem
from sqlalchemy.exc import SQLAlchemyError
from core.config import settings


engine = create_async_engine(settings.DATABASE_URL, echo=False)
SessionLocal = sessionmaker(
    autocommit=False, autoflush=False, bind=engine, class_=AsyncSession
)


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
    """
    async with SessionLocal() as db_session:
        try:
            realtime_session_item = RealtimeSessionItem(
                connection_key=connection_key,
                data=data,
                org_id=org_id,
                created_by_id=user_id,
                created_at=datetime.utcnow(),
            )
            db_session.add(realtime_session_item)
            await db_session.commit()
            await db_session.refresh(realtime_session_item)
            return realtime_session_item
        except SQLAlchemyError:
            await db_session.rollback()
            logger.exception("Error saving to DB")
