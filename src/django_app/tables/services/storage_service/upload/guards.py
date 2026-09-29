import asyncio
import contextlib

from django.conf import settings
from tables.exceptions import StorageUnavailable, UploadDurationExceeded, UploadIdleTimeout
from tables.services.storage_service.base import StorageUnreachable
from utils.logger import logger


@contextlib.contextmanager
def storage_errors_as_unavailable():
    """Object storage down, timing out or failing on its side (StorageUnreachable)
    is an outage, not a bug in this request: StorageUnavailable (503). Any other
    storage error (bad credentials, missing bucket) is a misconfiguration and
    stays an unexpected error."""
    try:
        yield
    except StorageUnreachable as exc:
        logger.exception("Streaming upload failed: object storage unreachable")
        raise StorageUnavailable() from exc


async def within_time_limits(chunks):
    """Pass `chunks` through, aborting when the client sends nothing for
    UPLOAD_IDLE_TIMEOUT (slow-loris guard) or the upload outlives
    UPLOAD_MAX_DURATION (kept under the object storage's stale-upload expiry,
    which would otherwise drop the parts of a still-running multipart upload).

    Only time spent waiting for the client counts as idle: while a part goes
    to object storage nothing is read, and the client is merely back-pressured."""
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
