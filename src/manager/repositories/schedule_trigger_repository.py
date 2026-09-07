from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from db.config import AsyncSessionLocal
from helpers.logger import logger
from src.shared.models import ScheduleTriggerNodePayload


class ScheduleTriggerNodeRepository:
    """Read schedule nodes via raw SQL through SQLAlchemy async.

    Read-only: writes to tables_scheduletriggernode go through Django
    (Manager publishes 'deactivate'/'run_session' on schedule_channel).
    """

    def __init__(self, session_factory=None):
        self.session_factory = session_factory or AsyncSessionLocal

    async def _execute_with_session(self, operation):
        """Run an operation in a session with automatic commit/rollback."""
        async with self.session_factory() as session:
            try:
                result = await operation(session)
                await session.commit()
                return result
            except SQLAlchemyError as exc:
                await session.rollback()
                logger.error(f"[ScheduleRepo] DB error: {exc}")
                raise
            except Exception as exc:
                await session.rollback()
                logger.error(f"[ScheduleRepo] Unexpected error: {exc}")
                raise

    async def get_all_active_schedule_nodes(
        self,
    ) -> list[ScheduleTriggerNodePayload] | None:
        """Return all schedule nodes with is_active=true.

        Empty list when there are none; None on DB error (caller decides retry).
        """

        async def operation(session: AsyncSession):
            query = text(
                """
                SELECT
                    id, node_name, graph_id, is_active, timezone, run_mode,
                    start_date_time, every, unit, weekdays,
                    end_type, end_date_time, max_runs, current_runs
                FROM tables_scheduletriggernode
                WHERE is_active = true
                """
            )
            result = await session.execute(query)
            return [
                ScheduleTriggerNodePayload.model_validate(row)
                for row in result.fetchall()
            ]

        try:
            return await self._execute_with_session(operation)
        except Exception:
            logger.exception("[ScheduleRepo] Failed to get active schedule nodes")
            return None
