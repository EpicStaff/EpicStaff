import asyncio
import ctypes
import json
import os
import time
from abc import ABC, abstractmethod
from datetime import datetime
from functools import partial
from typing import AsyncGenerator, AsyncIterable, Callable, Union

from django.core.serializers.json import DjangoJSONEncoder
from asgiref.sync import sync_to_async
from django.http import JsonResponse, StreamingHttpResponse
from django.conf import settings
from django.views import View
from loguru import logger

from tables.models.knowledge_models.collection_models import DocumentMetadata
from tables.services.redis_service import RedisService
from tables.services.rbac.sse_ticket_service import SseTicketService

ALLOWED_FILE_TYPES = {choice[0] for choice in DocumentMetadata.DocumentFileType.choices}
MAX_FILE_SIZE = 20 * 1024 * 1024  # 20MB


redis_service = RedisService()


_active_sse_count: int = 0

try:
    _libc = ctypes.CDLL("libc.so.6")
except Exception:
    _libc = None


def _malloc_trim_and_log() -> None:
    if _libc is None:
        return

    try:
        _libc.malloc_trim(0)
        rss_after = _read_rss_mb()
        logger.info(f"After malloc_trim(0): rss={rss_after:.1f}MB")
    except Exception as e:
        logger.warning(f"malloc_trim failed: {e}")


_TRIM_INTERVAL_SECONDS = int(os.environ.get("MALLOC_TRIM_INTERVAL_SECONDS", "60"))
_trim_task_started = False


async def _periodic_malloc_trim() -> None:
    logger.info(
        f"Periodic malloc_trim task started (interval={_TRIM_INTERVAL_SECONDS}s)"
    )
    while True:
        try:
            await asyncio.sleep(_TRIM_INTERVAL_SECONDS)
            await asyncio.to_thread(_malloc_trim_and_log)
        except asyncio.CancelledError:
            logger.info("Periodic malloc_trim task cancelled")
            raise
        except Exception as e:
            logger.warning(f"Periodic malloc_trim iteration failed: {e}")


def _ensure_trim_task() -> None:
    global _trim_task_started
    if _trim_task_started:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(_periodic_malloc_trim())
    _trim_task_started = True


def _read_rss_mb() -> float:
    try:
        with open(f"/proc/{os.getpid()}/status", "r") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    kb = int(line.split()[1])
                    return kb / 1024
    except Exception:
        return -1.0
    return -1.0


def _log_sse_state(action: str, view_name: str) -> None:
    rss_mb = _read_rss_mb()
    pool = redis_service.async_redis_client.connection_pool
    redis_used = len(getattr(pool, "_in_use_connections", []) or [])
    redis_avail = len(getattr(pool, "_available_connections", []) or [])
    logger.info(
        f"SSE {action} | view={view_name} active={_active_sse_count} "
        f"rss={rss_mb:.1f}MB redis_used={redis_used} redis_avail={redis_avail}"
    )


session_status_channel_name = os.environ.get(
    "SESSION_STATUS_CHANNEL", "sessions:session_status"
)
graph_messages_channel_name = os.environ.get(
    "GRAPH_MESSAGE_UPDATE_CHANNEL", "graph:message:update"
)
memory_updates_channel_name = os.environ.get("MEMORY_UPDATE_CHANNEL", "memory:update")


class SSEMixin(View, ABC):
    """
    A reusable mixin to stream server-sent events (SSE).
    Override `get_initial_data()` and `get_live_updates()` in your view.
    """

    ping_interval = 15  # seconds
    last_ping = None

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
        pass

    @abstractmethod
    async def get_live_updates(self, pubsub):
        """
        Overwrite this function with generator yielding updates in while True loop
        Each item should be either:
            - a dict with optional 'event' and required 'data' keys
            - or any JSON-serializable primitive (str, int, etc)
        """
        pass

    async def sort_by_timestamp(self, messages: list[dict]) -> list[dict]:
        """
        Sort a list of messages by their 'timestamp' field in ascending order.
        """
        return sorted(
            messages,
            key=lambda m: datetime.fromisoformat(m["timestamp"].replace("Z", "+00:00")),
        )

    async def _data_generator(
        self,
        callback: Callable[[], AsyncIterable[Union[dict, str, int, float, bool, None]]],
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

        async for item in callback():
            logger.debug(f"_data_generator item: {item}")
            if isinstance(item, dict):
                if "event" in item:
                    yield f"event: {item['event']}\n"

                self.last_ping = time.time()
                yield f"data: {json.dumps(item.get('data', ''), cls=DjangoJSONEncoder)}\n\n"

            else:
                self.last_ping = time.time()
                yield f"data: {json.dumps(item, cls=DjangoJSONEncoder)}\n\n"

        # Yield a ping message if needed.
        if time.time() - self.last_ping > self.ping_interval:
            self.last_ping = time.time()
            yield ": ping\n\n"

    async def event_stream(self, test_mode=False):
        _ensure_trim_task()
        global _active_sse_count
        _active_sse_count += 1
        view_name = self.__class__.__name__
        _log_sse_state("OPEN", view_name)

        self.last_ping = time.time()
        pubsub = None
        try:
            channels = [
                session_status_channel_name,
                graph_messages_channel_name,
                memory_updates_channel_name,
            ]
            pubsub = redis_service.async_redis_client.pubsub()
            await pubsub.subscribe(*channels)

            async for data in self._data_generator(self.get_initial_data):
                yield data

            if test_mode:
                for i in range(3):
                    yield f"data: test event #{i + 1}\n\n"
                raise GeneratorExit()

            async for data in self._data_generator(
                partial(self.get_live_updates, pubsub)
            ):
                logger.debug(f"event_stream data: {data}")
                yield data

        except (GeneratorExit, KeyboardInterrupt):
            logger.warning("Sending fatal-error event due to manual stop")
            yield "\n\nevent: fatal-error\ndata: event stream was stopped manually\n\n"
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

    async def get(self, request, *args, **kwargs):
        ticket = request.GET.get("ticket", "")
        user = await sync_to_async(SseTicketService().consume)(ticket)
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
