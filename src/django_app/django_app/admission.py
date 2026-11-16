import asyncio
import math

from asgiref.sync import markcoroutinefunction
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.http import JsonResponse
from utils.logger import logger

# The compose healthcheck polls it: liveness must not depend on load.
HEALTH_CHECK_PATH_PREFIX = "/ht/"


class RequestAdmissionMiddleware:
    """Cap the requests this process runs at once; a request past the cap waits for a slot.

    Under ASGI every sync view runs in a thread of its own and nothing bounds how many,
    so a burst starts more threads than the database pool has connections and the
    surplus fails after waiting for one. Here the surplus waits on the event loop
    instead, for at most REQUEST_ADMISSION_TIMEOUT seconds (None: no limit); a request
    still waiting then gets a 503 with Retry-After.

    A Django middleware, not an ASGI wrapper: Django reads the whole request body before
    any middleware runs, so a client trickling its body holds no slot. A request holds
    its slot until the view's work has finished, even when the client has gone, but not
    while a streamed response (SSE) streams.

    Async only: the semaphore lives on the event loop, and a dual-capable middleware
    would run in sync mode here, above the sync-only PluginRequestScopeMiddleware.
    Django builds it once per handler, so the slots are per process.

    It sits right after CorsMiddleware, which answers a preflight without reaching it and
    adds the CORS headers to its 503, so a browser can read the refusal.
    """

    async_capable = True
    sync_capable = False

    def __init__(self, get_response):
        max_concurrent_requests = settings.MAX_CONCURRENT_REQUESTS
        # Checked here, not in settings: only a process serving HTTP builds middleware,
        # while the Redis workers load the same settings with a smaller pool.
        _check_cap_fits_pool(
            max_concurrent_requests, settings.DATABASES["default"]["OPTIONS"]["pool"]["max_size"]
        )
        self.get_response = get_response
        self._slots = asyncio.Semaphore(max_concurrent_requests)
        self._timeout = settings.REQUEST_ADMISSION_TIMEOUT
        # Without a timeout no request is ever refused, so it has no Retry-After.
        self._retry_after = None if self._timeout is None else retry_after_seconds(self._timeout)
        markcoroutinefunction(self)

    async def __call__(self, request):
        if request.path.startswith(HEALTH_CHECK_PATH_PREFIX):
            return await self.get_response(request)
        try:
            async with asyncio.timeout(self._timeout):
                await self._slots.acquire()
        except TimeoutError:
            logger.warning("No request slot freed up in time; answered 503: {}", request.path)
            return self._busy_response()
        # When the client disconnects, Django cancels this call, but a sync view keeps
        # running in its thread with its database connection: the shield lets the work
        # finish, and the slot is released only then.
        work = asyncio.create_task(self.get_response(request))
        work.add_done_callback(self._release_slot)
        return await asyncio.shield(work)

    def _release_slot(self, work: asyncio.Task) -> None:
        # Retrieved here too: once the caller has been cancelled, nothing awaits the work.
        if not work.cancelled():
            work.exception()
        self._slots.release()

    def _busy_response(self) -> JsonResponse:
        # The project's error envelope, as utils/exception_handler.py renders it.
        return JsonResponse(
            {
                "status_code": 503,
                "code": "server_busy",
                "message": "The server is busy. Please retry shortly.",
            },
            status=503,
            headers={"Retry-After": str(self._retry_after)},
        )


def retry_after_seconds(admission_timeout: float) -> int:
    """Return the Retry-After for a request refused after waiting `admission_timeout` seconds.

    Whole seconds, as the header takes, rounded up and at least 1, so a client does not
    retry before a waiter could have been admitted.
    """
    return max(1, math.ceil(admission_timeout))


def _check_cap_fits_pool(max_concurrent_requests: int, pool_max_size: int | None) -> None:
    # SSE replays, websocket consumers and the upload stream use the same pool outside any
    # slot, so the admitted requests must leave them connections.
    if pool_max_size is None or max_concurrent_requests >= pool_max_size:
        raise ImproperlyConfigured(
            "DJANGO_SGI_MAX_CONCURRENT_REQUESTS must be below DJANGO_DB_POOL_MAX_SIZE, to leave "
            "connections for streams, websockets and uploads; got "
            f"DJANGO_SGI_MAX_CONCURRENT_REQUESTS={max_concurrent_requests} and "
            f"DJANGO_DB_POOL_MAX_SIZE={pool_max_size}."
        )
