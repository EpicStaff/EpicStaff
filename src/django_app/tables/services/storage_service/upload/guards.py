import asyncio
import contextlib

from django.conf import settings
from tables.exceptions import StorageUnavailable, UploadDurationExceeded, UploadIdleTimeout
from tables.services.storage_service.base import StorageUnreachable
from utils.logger import logger


@contextlib.contextmanager
def storage_errors_as_unavailable():
    """Turn StorageUnreachable into StorageUnavailable (503); other storage errors propagate."""
    try:
        yield
    except StorageUnreachable as exc:
        logger.exception("Streaming upload failed: object storage unreachable")
        raise StorageUnavailable() from exc


async def within_time_limits(chunks):
    """Pass `chunks` through, aborting on client idle time (slow-loris guard) or total duration.
    Only waiting for the client counts as idle, not time spent sending a part to storage."""
    loop = asyncio.get_running_loop()
    idle_timeout = settings.UPLOAD_IDLE_TIMEOUT
    max_duration = settings.UPLOAD_MAX_DURATION
    deadline = loop.time() + max_duration
    iterator = aiter(chunks)
    while True:
        remaining = deadline - loop.time()
        if remaining <= 0:
            raise UploadDurationExceeded(max_duration)
        try:
            async with asyncio.timeout(min(idle_timeout, remaining)):
                chunk = await anext(iterator)
        except StopAsyncIteration:
            return
        except TimeoutError:
            if remaining <= idle_timeout:
                raise UploadDurationExceeded(max_duration) from None
            raise UploadIdleTimeout(idle_timeout) from None
        yield chunk
