import asyncio
import json
import os

from loguru import logger
from rest_framework.views import APIView
from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi
from asgiref.sync import sync_to_async

from tables.utils.mixins import SSEMixin
from tables.models.session_models import Session
from tables.models.vector_models import MemoryDatabase
from tables.models.graph_models import GraphSessionMessage
from tables.services.redis_service import RedisService


redis_service = RedisService()


class RunSessionSSEViewSwagger(APIView):
    @swagger_auto_schema(
        operation_summary="Subscribe to real-time updates via SSE",
        operation_description="""
            Starts a **Server-Sent Events (SSE)** stream for a given run session.

            This endpoint continuously pushes the following event types:
            - **messages**: New or historical graph session messages
            - **status**: Session status updates
            - **memory**: Memory entries related to this session
            - **fatal-error**: If view crushes, so the frontend could close the connection

            Note: This is a streaming endpoint and won't produce a visible response in Swagger UI.
            For testing, use the `?test=true` query param to receive a few finite sample events.
        """,
        manual_parameters=[
            openapi.Parameter(
                name="test",
                in_=openapi.IN_QUERY,
                type=openapi.TYPE_BOOLEAN,
                description="If true, returns 3 sample events and closes the stream. Useful for Swagger.",
                required=False,
            )
        ],
        produces=["text/event-stream"],
        responses={
            200: openapi.Response(
                description="SSE stream of real-time events (text/event-stream)",
                schema=openapi.Schema(
                    type=openapi.TYPE_STRING,
                    description="SSE-formatted text stream. Events include `messages`, `status`, and `memory`.",
                    example="event: messages\ndata: {...}\n\n",
                ),
            )
        },
    )
    def get(self, request, *args, **kwargs):
        pass  # Just for docs


class RunSessionSSEView(SSEMixin):
    session_status_channel_name = os.environ.get(
        "SESSION_STATUS_CHANNEL", "sessions:session_status"
    )
    graph_messages_channel_name = os.environ.get(
        "GRAPH_MESSAGE_UPDATE_CHANNEL", "graph:message:update"
    )
    memory_updates_channel_name = os.environ.get(
        "MEMORY_UPDATE_CHANNEL", "memory:update"
    )

    def __init__(self):
        super().__init__()
        self.handlers = {
            self.session_status_channel_name: self._handle_session_statuses,
            self.graph_messages_channel_name: self._handle_graph_session_messages,
            self.memory_updates_channel_name: self._handle_memory_updates,
        }

    def __log(self, event, state, data):
        logger.debug(
            f"{self.__class__.__name__} sends event {event} {state} data: {data}"
        )

    async def _generate_initial_graph_session_messages(self, session_id):
        # 1. Get recent Redis entries for this session.
        from_redis = []
        redis_uuids = set()

        keys = [
            key
            async for key in redis_service.async_redis_client.scan_iter(
                f"graph:message:{session_id}:*"
            )
        ]
        values = await redis_service.async_redis_client.mget(keys) if keys else []

        for val in values:
            if not val:
                continue

            try:
                item = json.loads(val)
            except (json.JSONDecodeError, AttributeError):
                continue

            if item.get("uuid") in redis_uuids:
                continue

            from_redis.append(item)
            redis_uuids.add(item.get("uuid"))

        # 2. Lazy DB queryset excluding records already found in Redis.
        from_db = (
            GraphSessionMessage.objects.filter(session_id=session_id)
            .exclude(uuid__in=redis_uuids)
            .values()
        )

        # 3. Yield Redis messages
        for message in from_redis:
            yield message

        # 4. Yield DB messages lazily using sync_to_async generator wrapper
        async for data in self.async_orm_generator(from_db):
            yield data

    async def _handle_graph_session_messages(self, data):
        redis_key = f"graph:message:{data['session_id']}:{data['uuid']}"
        redis_data = await redis_service.async_redis_client.get(redis_key)

        if redis_data:
            self.__log(event="messages", state="update", data=data["uuid"])
            yield {"event": "messages", "data": json.loads(redis_data)}

    async def _handle_session_statuses(self, data):
        self.__log(event="status", state="update", data=data["status"])
        yield {
            "event": "status",
            "data": {
                "status": data["status"],
                "status_data": data.get("status_data", {}),
            },
        }

    async def _handle_memory_updates(self, data):
        queryset = MemoryDatabase.objects.filter(id=data["uuid"]).values(
            "id", "payload"
        )
        exists = await sync_to_async(queryset.exists)()
        if not exists:
            yield {"event": "memory-delete", "data": data["uuid"]}
        else:
            # Yield memo lazily using sync_to_async generator wrapper
            async for memo in self.async_orm_generator(queryset):
                self.__log(event="memory", state="update", data=memo["id"])
                yield {
                    "event": "memory",
                    "data": memo,
                }

    async def get_initial_data(self):
        # Graph Session Messages
        session_id = self.kwargs["session_id"]
        async for message in self._generate_initial_graph_session_messages(session_id):
            self.__log(event="messages", state="initial", data=message["uuid"])
            yield {"event": "messages", "data": message}

        # Session Statuses
        queryset = (
            Session.objects.only("id", "status", "status_data")
            .filter(id=session_id)
            .values()
        )
        async for session in self.async_orm_generator(queryset):
            self.__log(event="status", state="initial", data=session["status"])
            yield {
                "event": "status",
                "data": {
                    "status": session["status"],
                    "status_data": session.get("status_data", {}),
                },
            }

        # Memories
        queryset = MemoryDatabase.objects.filter(payload__run_id=session_id).values(
            "id", "payload"
        )
        async for memo in self.async_orm_generator(queryset):
            self.__log(event="memory", state="initial", data=memo["id"])
            yield {
                "event": "memory",
                "data": memo,
            }

    async def get_live_updates(self):
        session_id = self.kwargs["session_id"]

        async for message in redis_service.redis_get_message(
            channels=[
                self.graph_messages_channel_name,
                self.session_status_channel_name,
                self.memory_updates_channel_name,
            ]
        ):
            if not message:
                # No message, sleep a bit and loop
                await asyncio.sleep(0.1)
                continue

            if message.get("type") != "message":
                continue

            try:
                data = json.loads(message["data"])
                if str(data.get("session_id")) != str(session_id):
                    continue

                if message.get("channel") in self.handlers:
                    async for i in self.handlers[message.get("channel")](data):
                        yield i

            except Exception as e:
                logger.exception(f"Error processing live update: {e}")
                continue

    async def get(self, request, *args, **kwargs):
        """
        SSE stream for real-time run session updates.
        Returns events:
            - messages: for graph session messages
            - status: for session statuses
            - memory: for memories

        Append ?test=true to the URL for a finite sample response
        """
        logger.info("Started run session SSE")
        return await super().get(request, *args, **kwargs)
