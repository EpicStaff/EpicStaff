from db.config import AsyncSessionLocal
from helpers.logger import logger
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

# Each query is a PK-join against one of the three owner tables, scoped to
# rows whose owner has reached a terminal state. TemporaryStorageAccount's
# CheckConstraint guarantees exactly one FK column is non-null per row, so
# an INNER JOIN on one FK naturally only ever matches the rows owned by
# that table -- no extra "AND <other_fk> IS NULL" filtering is needed.
_BATCH_DELETE_QUERIES = {
    "session": text(
        """
        WITH batch AS (
            SELECT t.id
            FROM storage_credentials_temp_account t
            JOIN tables_session s ON t.session_id = s.id
            WHERE s.finished_at IS NOT NULL
            LIMIT :batch_size
        )
        DELETE FROM storage_credentials_temp_account t
        USING batch
        WHERE t.id = batch.id
        """
    ),
    "python_code_result": text(
        """
        WITH batch AS (
            SELECT t.id
            FROM storage_credentials_temp_account t
            JOIN tables_pythoncoderesult p ON t.python_code_result_id = p.execution_id
            WHERE p.finished_at IS NOT NULL
            LIMIT :batch_size
        )
        DELETE FROM storage_credentials_temp_account t
        USING batch
        WHERE t.id = batch.id
        """
    ),
    "realtime_agent_chat": text(
        """
        WITH batch AS (
            SELECT t.id
            FROM storage_credentials_temp_account t
            JOIN realtime_agent_chat r ON t.realtime_agent_chat_id = r.id
            WHERE r.ended_at IS NOT NULL
            LIMIT :batch_size
        )
        DELETE FROM storage_credentials_temp_account t
        USING batch
        WHERE t.id = batch.id
        """
    ),
}


class TempStorageAccountRepository:
    """Backstop cleanup for `storage_credentials_temp_account`.

    Pure Postgres housekeeping -- never touches MinIO/RustFS. Opportunistic
    deletion (on a successful revoke) and FK CASCADE already remove most
    rows; this only picks up what those two miss (a failed revoke, a lost
    status signal).
    """

    def __init__(self, session_factory=None):
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

    async def _delete_batch(self, owner: str, batch_size: int) -> int:
        async def operation(session: AsyncSession):
            result = await session.execute(_BATCH_DELETE_QUERIES[owner], {"batch_size": batch_size})
            return result.rowcount or 0

        return await self._execute_with_session(operation)

    async def delete_finished_accounts(self, batch_size: int = 500) -> dict[str, int]:
        """Delete rows whose owner (session/test-run/realtime chat) has
        finished, in batches, one owner at a time. Returns the number of
        rows deleted per owner."""
        deleted: dict[str, int] = {}
        for owner in _BATCH_DELETE_QUERIES:
            total_for_owner = 0
            while True:
                removed = await self._delete_batch(owner, batch_size)
                total_for_owner += removed
                if removed < batch_size:
                    break
            deleted[owner] = total_for_owner
        return deleted
