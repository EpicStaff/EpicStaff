import asyncio
import contextlib
import json
import time
from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator, AsyncIterable, Callable
from datetime import datetime
from functools import partial

from asgiref.sync import sync_to_async
from django.core.serializers.json import DjangoJSONEncoder
from django.http import JsonResponse, StreamingHttpResponse
from django.views import View
from loguru import logger
from rbac.identity.tickets import sse_ticket_service
from tables.services.redis_service import RedisService
from tables.utils.memory_trim import read_rss_mb, start_periodic_malloc_trim

redis_service = RedisService()


_active_sse_count: int = 0


def _log_sse_state(action: str, view_name: str) -> None:
    rss_mb = read_rss_mb()
    pool = redis_service.async_redis_client.connection_pool
    redis_used = len(getattr(pool, "_in_use_connections", []) or [])
    redis_avail = len(getattr(pool, "_available_connections", []) or [])
    logger.info(
        f"SSE {action} | view={view_name} active={_active_sse_count} "
        f"rss={rss_mb:.1f}MB redis_used={redis_used} redis_avail={redis_avail}"
    )


class SSEMixin(View, ABC):
    """
    A reusable mixin to stream server-sent events (SSE).
    Override `get_initial_data()` and `get_live_updates()` in your view, and
    `get_channels()` when the live updates come from Redis pub/sub.
    """

    ping_interval = 15  # seconds

    def get_channels(self) -> list[str]:
        """Return the Redis channels whose messages `get_live_updates()` receives.

        The stream subscribes to them before `get_initial_data()` runs, so nothing
        published in between is lost. Default: none, and `get_live_updates()`
        gets ``pubsub=None``.
        """
        return []

    async def async_orm_generator(self, queryset):
        async for entity in queryset.aiterator(chunk_size=200):
            yield entity

    @abstractmethod
    async def get_initial_data(self):
        """
        Overwrite this function with generator yielding initial data
        Each item should be either:
            - a dict with optional 'event' and required 'data' keys
            - or any JSON-serializable primitive (str, int, etc)
        """

    @abstractmethod
    async def get_live_updates(self, pubsub):
        """
        Overwrite this function with generator yielding updates in while True loop
        `pubsub` is subscribed to `get_channels()`, or None when that is empty.
        Each item should be either:
            - a dict with optional 'event' and required 'data' keys
            - or any JSON-serializable primitive (str, int, etc)
        """

    async def sort_by_timestamp(self, messages: list[dict]) -> list[dict]:
        """
        Sort a list of messages by their 'timestamp' field in ascending order.
        """
        return sorted(
            messages,
            key=lambda m: datetime.fromisoformat(m["timestamp"]),
        )

    async def _data_generator(
        self,
        callback: Callable[[], AsyncIterable[dict | str | int | float | bool | None]],
    ) -> AsyncGenerator[str, None]:
        """
        SSE data generator.

        Args:
            callback: A callable returning an async iterable of items.
                Each item should be either:
                    - a dict with optional 'event' and required 'data' keys
                    - or any JSON-serializable primitive (str, int, etc)

        Yields:
            str: Server-Sent Events (SSE) formatted strings.
        """

        items = callback().__aiter__()
        next_item = None
        last_sent = time.monotonic()
        try:
            while True:
                if next_item is None:
                    next_item = asyncio.ensure_future(items.__anext__())

                # The live-update generator blocks inside one __anext__ until Redis
                # delivers something, so the ping is timed from outside it. asyncio.wait
                # leaves the pending __anext__ running when the timeout expires; wait_for
                # would cancel it and break the generator.
                done, _ = await asyncio.wait(
                    {next_item},
                    timeout=max(0.0, self.ping_interval - (time.monotonic() - last_sent)),
                )
                if not done:
                    last_sent = time.monotonic()
                    yield ": ping\n\n"
                    continue

                try:
                    item = next_item.result()
                except StopAsyncIteration:
                    return
                finally:
                    next_item = None

                logger.debug(f"_data_generator item: {item}")
                last_sent = time.monotonic()
                if isinstance(item, dict):
                    if "event" in item:
                        yield f"event: {item['event']}\n"

                    yield f"data: {json.dumps(item.get('data', ''), cls=DjangoJSONEncoder)}\n\n"

                else:
                    yield f"data: {json.dumps(item, cls=DjangoJSONEncoder)}\n\n"
        finally:
            # An async generator cannot be closed while its __anext__ is still running.
            if next_item is not None:
                next_item.cancel()
                with contextlib.suppress(asyncio.CancelledError, StopAsyncIteration):
                    await next_item
            await items.aclose()

    async def event_stream(self, test_mode=False):
        start_periodic_malloc_trim()
        global _active_sse_count
        _active_sse_count += 1
        view_name = self.__class__.__name__
        _log_sse_state("OPEN", view_name)

        pubsub = None
        try:
            channels = self.get_channels()
            if channels and not test_mode:
                pubsub = redis_service.async_redis_client.pubsub()
                await pubsub.subscribe(*channels)

            # aclosing: the inner generator holds a pending read and the pubsub;
            # closing it here, not whenever it is garbage-collected, releases them.
            async with contextlib.aclosing(
                self._data_generator(self.get_initial_data)
            ) as initial_frames:
                async for data in initial_frames:
                    yield data

            if test_mode:
                for i in range(3):
                    yield f"data: test event #{i + 1}\n\n"
                return

            async with contextlib.aclosing(
                self._data_generator(partial(self.get_live_updates, pubsub))
            ) as live_frames:
                async for data in live_frames:
                    logger.debug(f"event_stream data: {data}")
                    yield data

        except (GeneratorExit, KeyboardInterrupt):
            # The client is gone: nothing can be sent any more, and yielding
            # after GeneratorExit raises RuntimeError and skips the cleanup.
            logger.info("SSE stream {} closed by the client", view_name)
            raise
        except Exception as e:
            logger.error(f"Sending fatal-error event due to error: {e}")
            yield "\n\nevent: fatal-error\ndata: unexpected error\n\n"
        finally:
            if pubsub is not None:
                try:
                    await pubsub.unsubscribe()
                    await pubsub.aclose()
                except Exception as e:
                    logger.warning(f"Error closing SSE pubsub: {e}")

            _active_sse_count -= 1
            _log_sse_state("CLOSE", view_name)

    async def authorize(self, request, *args, **kwargs):
        """Optional post-ticket authorization hook. Runs after the SSE ticket
        resolves to `self.user`. Return an HttpResponse to deny (short-circuit
        the stream), or None to proceed. Default: allow."""
        return

    async def get(self, request, *args, **kwargs):
        ticket = request.GET.get("ticket", "")
        user = await sync_to_async(sse_ticket_service.consume)(ticket)
        if user is None:
            return JsonResponse(
                {
                    "status_code": 401,
                    "code": "invalid_sse_ticket",
                    "message": "Invalid or expired SSE ticket.",
                },
                status=401,
            )
        self.user = user

        auth_response = await self.authorize(request, *args, **kwargs)
        if auth_response is not None:
            return auth_response

        test_mode = bool(request.GET.get("test", ""))
        logger.debug(f"Started SSE {'with' if test_mode else 'without'} test mode")
        return StreamingHttpResponse(
            self.event_stream(test_mode=test_mode),
            content_type="text/event-stream",
            headers={
                "Connection": "keep-alive",
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Transfer-Encoding": "chunked",
            },
        )
