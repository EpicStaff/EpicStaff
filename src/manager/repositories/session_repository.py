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

    async def get_session_fields(self, session_id: int) -> dict | None:
        async def operation(session: AsyncSession):
            query = text(
                """
                SELECT status, status_updated_at, time_to_live
                FROM tables_session
                WHERE id = :session_id
                """
            )
            result = await session.execute(query, {"session_id": session_id})
            row = result.fetchone()
            if row:
                return {
                    "status": row.status,
                    "status_updated_at": row.status_updated_at,
                    "time_to_live": row.time_to_live,
                }
            return None

        try:
            return await self._execute_with_session(operation)
        except Exception:
            return None

    async def get_all_active_sessions(self) -> list[dict] | None:
        """
        Get all sessions with status 'run' or 'pending'
        """

        async def operation(session: AsyncSession):
            query = text(
                """
                SELECT id, status, status_updated_at, time_to_live
                FROM tables_session
                WHERE status IN ('run', 'pending', 'wait_for_user')
                AND time_to_live != 0
                """
            )
            result = await session.execute(query)
            rows = result.fetchall()
            return (
                [
                    {
                        "session_id": row.id,
                        "status": row.status,
                        "status_updated_at": row.status_updated_at,
                        "time_to_live": row.time_to_live,
                    }
                    for row in rows
                ]
                if rows
                else []
            )

        try:
            return await self._execute_with_session(operation)
        except Exception:
            return None
