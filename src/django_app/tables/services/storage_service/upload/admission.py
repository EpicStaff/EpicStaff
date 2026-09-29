import asyncio
import contextlib
from collections import Counter

from django.conf import settings
from tables.exceptions import OrgUploadLimitReached, UploadSlotsBusy


class UploadAdmission:
    """Per-worker gate on streaming uploads: a global slot limit plus a per-org cap.
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
        """Hold one upload slot for `org_id` for the block; released on every exit."""
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


_admission: UploadAdmission | None = None


def get_upload_admission() -> UploadAdmission:
    """This worker's gate over running uploads, built from settings on first use."""
    global _admission
    if _admission is None:
        _admission = UploadAdmission(
            max_concurrency=settings.UPLOAD_MAX_CONCURRENCY,
            per_org_limit=settings.UPLOAD_MAX_CONCURRENCY_PER_ORG,
            slot_timeout=settings.UPLOAD_SLOT_TIMEOUT,
        )
    return _admission
