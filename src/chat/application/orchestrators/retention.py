from collections.abc import Callable
from datetime import datetime

from loguru import logger

from application.ports import AbstractUnitOfWork

# Conversations deleted per transaction, with everything they own.
PURGE_BATCH = 500


class RetentionOrchestrator:
    """Deletes the closed conversations an organization's retention policy has expired."""

    def __init__(
        self, uow_factory: Callable[[], AbstractUnitOfWork], *, batch_size: int = PURGE_BATCH
    ):
        self._uow = uow_factory
        self._batch_size = batch_size

    async def purge_conversations(self, org_id: int, older_than: datetime) -> int:
        """Delete the org's closed conversations silent since before `older_than`, with what
        they own.

        One transaction per batch, committed before the next starts: a purge interrupted part
        way keeps what it already deleted, and the next one takes the rest. Open conversations,
        closed ones whose run's callback is still owed, and rows another transaction holds right
        now are left alone.

        Returns:
            How many conversations were deleted.
        """
        total = 0
        try:
            while True:
                async with self._uow() as uow:
                    deleted = await uow.conversations.delete_inactive_batch(
                        org_id, older_than, self._batch_size
                    )
                    await uow.commit()
                total += deleted
                if deleted < self._batch_size:
                    break
        finally:
            # Logged even when a later batch fails: the batches before it are already gone.
            logger.info(
                "Retention purge deleted {} conversations of org {} inactive before {}",
                total,
                org_id,
                older_than.isoformat(),
            )
        return total
