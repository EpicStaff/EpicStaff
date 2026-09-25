import asyncio
import contextlib
from collections import Counter

from tables.exceptions import OrgUploadLimitReached, UploadSlotsBusy


class UploadAdmission:
    """Decides which streaming uploads of this worker may run.

    At most `max_concurrency` run at once. One organization holds at most
    `per_org_limit` of them, counting its uploads still waiting for a slot, so it
    cannot line up behind a full worker; below `max_concurrency` it also cannot
    fill every slot. A waiter gives up after `slot_timeout` seconds (None: never).

    Lives on the worker's single event loop, so the counters need no lock."""

    def __init__(self, *, max_concurrency: int, per_org_limit: int, slot_timeout: float):
        self._slots = asyncio.Semaphore(max_concurrency)
        self._per_org_limit = per_org_limit
        self._slot_timeout = slot_timeout
        self._uploads_by_org: Counter[int] = Counter()

    def uploads_of(self, org_id: int) -> int:
        """Uploads of `org_id` running or waiting for a slot."""
        return self._uploads_by_org[org_id]

    @contextlib.asynccontextmanager
    async def admit(self, org_id: int):
        """Hold one slot for `org_id` for the duration of the block.

        OrgUploadLimitReached (429) when the org is at its limit, UploadSlotsBusy
        (503) when no slot frees up in time. Both counters are given back on every
        exit: success, error, and cancellation (client disconnect)."""
        if self._uploads_by_org[org_id] >= self._per_org_limit:
            raise OrgUploadLimitReached(wait=self._slot_timeout)
        self._uploads_by_org[org_id] += 1
        try:
            try:
                async with asyncio.timeout(self._slot_timeout):
                    await self._slots.acquire()
            except TimeoutError:
                raise UploadSlotsBusy(retry_after=self._slot_timeout) from None
            try:
                yield
            finally:
                self._slots.release()
        finally:
            self._uploads_by_org[org_id] -= 1
            if not self._uploads_by_org[org_id]:
                del self._uploads_by_org[org_id]
