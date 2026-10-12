from db.config import AsyncSessionLocal
from helpers.logger import logger
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession


class SessionRepository:
    def __init__(self, session_factory=None):
        """
        Initialize with optional session factory.
        """
        self.session_factory = session_factory or AsyncSessionLocal

    async def _execute_with_session(self, operation):
        async with self.session_factory() as session:
            try:
                result = await operation(session)
                await session.commit()
                return result
            except SQLAlchemyError as e:
                await session.rollback()
                logger.error(f"DB error: {e}")
                raise
            except Exception as e:
                await session.rollback()
                logger.error(f"Unexpected error: {e}")
                raise

    async def get_overdue_session_ids(self) -> list[int]:
        """Return ids of active sessions whose time_to_live has elapsed.

        A session is overdue when more than time_to_live seconds have passed
        since status_updated_at; time_to_live = 0 means the session never
        expires. status_updated_at is only bumped by Session.save(), not by
        crew's status updates (those use .update()), so in practice it is
        usually the session's creation or last save(). Database errors
        propagate so the caller can retry later.
        """

        async def operation(session: AsyncSession) -> list[int]:
            query = text(
                """
                SELECT id
                FROM tables_session
                WHERE status IN ('run', 'pending', 'wait_for_user')
                AND time_to_live != 0
                AND status_updated_at + make_interval(secs => time_to_live) < now()
                """
            )
            result = await session.execute(query)
            return list(result.scalars().all())

        return await self._execute_with_session(operation)
