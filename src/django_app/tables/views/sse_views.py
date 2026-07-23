import asyncio
import json
import os
import copy

from loguru import logger
from rest_framework.views import APIView
from drf_spectacular.utils import (
    extend_schema,
    OpenApiResponse,
    OpenApiParameter,
    inline_serializer,
)
from rest_framework import serializers as drf_serializers
from asgiref.sync import sync_to_async

from django.conf import settings

from tables.utils.mixins import SSEMixin
from tables.models.session_models import Session
from tables.models.vector_models import MemoryDatabase
from tables.models.graph_models import GraphSessionMessage
from tables.models.knowledge_models import NaiveRag, SourceCollection
from tables.services.redis_service import RedisService
from tables.services.knowledge_services.collection_status_service import (
    CollectionStatusService,
)
from tables.swagger_schemas.sessions_schema import RUN_SESSION_SSE_GET
from src.shared.models import RagIndexingProgressMessage, COLLECTION_STATUS_UPLOADING


redis_service = RedisService()


class RunSessionSSEViewSwagger(APIView):
    @extend_schema(**RUN_SESSION_SSE_GET)
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

    _sse_filter_enabled = False

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

        from_redis = await self.sort_by_timestamp(from_redis)
        # 2. Lazy DB queryset excluding records already found in Redis.
        from_db = (
            GraphSessionMessage.objects.filter(session_id=session_id)
            .exclude(uuid__in=redis_uuids)
            .order_by("id")
            .values()
        )

        # 3. Yield Redis messages
        for message in from_redis:
            yield message

        # 4. Yield DB messages lazily using sync_to_async generator wrapper
        async for data in self.async_orm_generator(from_db):
            yield data

    def _should_filter_message(self, message_data: dict) -> bool:
        """Check if a message should be filtered out for external consumers.
        Only applies when sse_filter=true query param is set.
        Standard messages (start, finish, error) always pass through."""
        if not self._sse_filter_enabled:
            return False
        if not isinstance(message_data, dict):
            return False
        msg_type = message_data.get("message_type", "")
        if msg_type in ("start", "error"):
            return False
        if msg_type == "finish":
            return message_data.get("sse_visible") is False
        return message_data.get("sse_visible") is False

    async def _handle_graph_session_messages(self, data):
        redis_key = f"graph:message:{data['session_id']}:{data['uuid']}"
        redis_data = await redis_service.async_redis_client.get(redis_key)

        if redis_data:
            parsed = json.loads(redis_data)
            if self._should_filter_message(parsed.get("message_data", {})):
                return
            logger.debug(f"_handle_graph_session_messages: {redis_data}")
            yield {"event": "messages", "data": parsed}

    async def _handle_session_statuses(self, data):
        self.__log(event="status", state="update", data=data["status"])
        yield {
            "event": "status",
            "data": {
                "session_id": data["session_id"],
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
            if self._should_filter_message(message.get("message_data", {})):
                continue
            self.__log(event="messages", state="initial", data=message["uuid"])
            message["message_data"] = self._trim_base64_file_data(
                message["message_data"]
            )
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
                    "session_id": session["id"],
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

    async def get_live_updates(self, pubsub):
        session_id = self.kwargs["session_id"]
        async for message in redis_service.redis_get_message(
            channels=[
                self.graph_messages_channel_name,
                self.session_status_channel_name,
                self.memory_updates_channel_name,
            ],
            pubsub=pubsub,
        ):
            if not message:
                # No message, sleep a bit and loop
                await asyncio.sleep(0.05)
                continue

            if message.get("type") != "message":
                continue

            try:
                data = json.loads(message["data"])
                if str(data.get("session_id")) != str(session_id):
                    continue

                if message.get("channel") in self.handlers:
                    async for i in self.handlers[message.get("channel")](data):
                        logger.debug(f"get_live_updates data: {i}")
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
        logger.info(f"Started run session SSE (sse_filter={self._sse_filter_enabled})")
        return await super().get(request, *args, **kwargs)

    def _trim_base64_file_data(self, message_data: dict) -> dict:
        """Trim base64 file data in message content to reduce payload size."""
        trimmed_data = copy.deepcopy(message_data)

        def trim_data_fields(obj):
            """Recursively traverse and trim 'base64_data' fields."""
            if isinstance(obj, dict):
                for key, value in obj.items():
                    if (
                        key == "base64_data"
                        and isinstance(value, str)
                        and len(value) > 50
                    ):
                        obj[key] = value[:50]
                    else:
                        trim_data_fields(value)
            elif isinstance(obj, list):
                for item in obj:
                    trim_data_fields(item)

        trim_data_fields(trimmed_data)
        return trimmed_data


class FilteredRunSessionSSEView(RunSessionSSEView):
    """SSE endpoint for external consumers (EpicChat widget).
    Always filters out messages where sse_visible=false.
    Standard messages (start, finish, error) always pass through."""

    _sse_filter_enabled = True


class CollectionIndexingSSEView(SSEMixin):
    """
    SSE stream for live NaiveRag indexing progress of one SourceCollection.

    GET /api/source-collections/subscribe/<collection_id>/?ticket=...

    Emits a single event type:
        - indexing: RagIndexingProgressMessage payload (see
          src/shared/models/knowledge.py), scoped to this collection_id.
          `collection_status` is always one of the CollectionStatus
          vocabulary values (empty/uploading/completed/warning/failed).

    On connect, replays the collection's current derived status (if any
    NaiveRag has ever been indexed for it) so a late subscriber immediately
    sees state instead of waiting for the next Redis message. The stream
    closes itself once a terminal event (collection_status != "uploading")
    is observed, mirroring how the knowledge worker always publishes exactly
    one terminal progress event per indexing run.
    """

    channels = [settings.KNOWLEDGE_INDEXING_PROGRESS_CHANNEL]

    async def _get_current_snapshot(self, collection_id: int) -> tuple[int, str] | None:
        """
        Resolve (naive_rag_id, collection_status) for the "primary" NaiveRag
        of this collection - the most recently updated one, since in
        practice a collection has at most one NaiveRag configuration.

        Returns None if the collection has no NaiveRag yet (nothing to
        replay).
        """

        def _query():
            try:
                collection = SourceCollection.objects.prefetch_related(
                    "documents", "rag_types__naive_rags", "rag_types__graph_rags"
                ).get(collection_id=collection_id)
            except SourceCollection.DoesNotExist:
                return None

            naive_rag = (
                NaiveRag.objects.filter(
                    base_rag_type__source_collection_id=collection_id
                )
                .order_by("-updated_at")
                .first()
            )
            if naive_rag is None:
                return None

            return (
                naive_rag.naive_rag_id,
                CollectionStatusService.get_collection_status(collection),
            )

        return await sync_to_async(_query)()

    async def get_initial_data(self):
        collection_id = self.kwargs["collection_id"]
        snapshot = await self._get_current_snapshot(collection_id)
        if snapshot is None:
            return

        naive_rag_id, collection_status = snapshot
        logger.debug(
            f"CollectionIndexingSSEView initial snapshot: collection_id={collection_id}, "
            f"naive_rag_id={naive_rag_id}, collection_status={collection_status}"
        )
        yield {
            "event": "indexing",
            "data": RagIndexingProgressMessage(
                collection_id=collection_id,
                rag_id=naive_rag_id,
                rag_type="naive",
                collection_status=collection_status,
            ).model_dump(),
        }

    async def get_live_updates(self, pubsub):
        collection_id = self.kwargs["collection_id"]

        async for message in redis_service.redis_get_message(
            channels=self.channels,
            pubsub=pubsub,
        ):
            if not message:
                await asyncio.sleep(0.05)
                continue

            if message.get("type") != "message":
                continue

            try:
                data = json.loads(message["data"])
            except (TypeError, json.JSONDecodeError) as e:
                logger.warning(f"Invalid indexing progress payload: {e}")
                continue

            if str(data.get("collection_id")) != str(collection_id):
                continue

            logger.debug(f"CollectionIndexingSSEView live update: {data}")
            yield {"event": "indexing", "data": data}

            if data.get("collection_status") != COLLECTION_STATUS_UPLOADING:
                return

    async def get(self, request, *args, **kwargs):
        """
        SSE stream for real-time NaiveRag indexing progress of one
        SourceCollection. Returns a single "indexing" event type.
        """
        logger.info(
            f"Started collection indexing SSE for collection_id={kwargs.get('collection_id')}"
        )
        return await super().get(request, *args, **kwargs)
