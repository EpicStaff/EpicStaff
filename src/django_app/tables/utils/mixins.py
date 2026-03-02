import os
import json
import time
from datetime import datetime

from typing import AsyncGenerator, AsyncIterable, Callable, Union
from abc import ABC, abstractmethod

from rest_framework import status
from rest_framework.response import Response
from rest_framework.decorators import action
from loguru import logger
from asgiref.sync import sync_to_async
from django.http import StreamingHttpResponse
from django.core.serializers.json import DjangoJSONEncoder
from django.views import View
from django.db import IntegrityError, transaction

from tables.models.knowledge_models.collection_models import DocumentMetadata
from tables.services.redis_service import RedisService
from functools import partial

ALLOWED_FILE_TYPES = {choice[0] for choice in DocumentMetadata.DocumentFileType.choices}
MAX_FILE_SIZE = 12 * 1024 * 1024  # 12MB


redis_service = RedisService()

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
        entities = await sync_to_async(list)(
            queryset
        )  # Convert queryset to a list asynchronously
        for entity in entities:
            yield entity  # Yield one entity at a time asynchronously

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
        self.last_ping = time.time()
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

    async def get(self, request, *args, **kwargs):
        test_mode = bool(request.GET.get("test", ""))
        logger.debug(f"Started SSE {'with' if test_mode else 'without'} test mode")
        return StreamingHttpResponse(
            self.event_stream(test_mode=test_mode),
            content_type="text/event-stream",
            headers={
                "Connection": "keep-alive",
                "Cache-Control": "no-cache",
                "Access-Control-Allow-Origin": "*",
                "X-Accel-Buffering": "no",
                "Transfer-Encoding": "chunked",
            },
        )


class DeepCopyMixin:
    """
    A mixin that can extend ModelSerializer class with deep copy functionality.
    Creates new action method: `copy`.

    Params:
        `copy_serializer_class`: A serializer class that used for creating copy of the entity (agent, crew, graph).
        `copy_deserializer_class`: A serializer class that used for creating entity from copied entity.
        `copy_serializer_response_class`: A serializer class that used in repose body.
    """

    copy_serializer_class = None
    copy_deserializer_class = None
    copy_serializer_response_class = None

    def get_copy_serializer_class(self):
        if not self.copy_serializer_class:
            raise NotImplementedError("Subclass must define copy_serializer_class")
        return self.copy_serializer_class

    def get_copy_deserializer_class(self):
        if not self.copy_deserializer_class:
            raise NotImplementedError("Subclass must define copy_deserializer_class")
        return self.copy_deserializer_class

    def get_copy_serializer_response_class(self):
        if not self.copy_serializer_response_class:
            raise NotImplementedError(
                "Subclass must define copy_serializer_response_class"
            )
        return self.copy_serializer_response_class

    @action(detail=True, methods=["post"], url_path="copy")
    def copy(self, request, pk: int):
        instance = self.get_object()
        new_instance = None
        serializer_class = self.get_copy_serializer_class()

        data = serializer_class(instance).data
        data = dict(data)

        deserializer_class = self.get_copy_deserializer_class()
        deserializer = deserializer_class(data=data)
        deserializer.is_valid(raise_exception=True)

        try:
            with transaction.atomic():
                new_instance = deserializer.save()
        except IntegrityError as e:
            return Response(
                {"message": f"Database error: {str(e)}"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except Exception as e:
            return Response(
                {
                    "message": f"Something went wrong while copying the instance. {str(e)}"
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        new_name = request.data.get("name") if isinstance(request.data, dict) else None
        current_name = getattr(new_instance, "name", None)

        if new_name and current_name:
            new_instance.name = new_name
            new_instance.save()

        response_serializer_class = self.get_copy_serializer_response_class()
        serializer = response_serializer_class(new_instance)

        return Response(serializer.data, status=status.HTTP_201_CREATED)
