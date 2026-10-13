import asyncio
import json
import time
from dataclasses import dataclass

from asgiref.sync import sync_to_async
from django.http import JsonResponse
from drf_spectacular.utils import (
    extend_schema,
)
from rest_framework.exceptions import APIException
from rest_framework.views import APIView
from src.shared.redis_keys import (
    session_final_variables_key,
    session_messages_channel,
    session_status_channel,
)
from tables.models.graph_models import GraphSessionMessage
from tables.models.session_models import Session
from tables.services.redis_service import RedisService
from tables.services.session_access import get_accessible_session
from tables.swagger_schemas.sessions_schema import RUN_SESSION_SSE_GET
from tables.utils.base64_preview import trim_base64_file_data
from tables.utils.mixins import SerializedEvent, SSEMixin
from utils.logger import logger

redis_service = RedisService()

# Graph messages per database query: one message can be ~300 KB.
MESSAGE_PAGE_SIZE = 20

FINISHED_STATUSES = frozenset(
    {
        Session.SessionStatus.END,
        Session.SessionStatus.ERROR,
        Session.SessionStatus.STOP,
        Session.SessionStatus.EXPIRED,
    }
)
# Crew publishes the status itself, but a graph message is published only after
# Django stores it, so the last messages can arrive after the final status.
LATE_MESSAGE_SECONDS = 5.0


@dataclass(frozen=True)
class _HeldGraphMessage:
    uuid: str


class RunSessionSSEViewSwagger(APIView):
    @extend_schema(**RUN_SESSION_SSE_GET)
    def get(self, request, *args, **kwargs):
        pass  # Just for docs


class RunSessionSSEView(SSEMixin):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._sent_message_uuids: set[str] = set()
        # time.monotonic() when the stream first sent a finished status.
        self._finished_at: float | None = None

    def _channel_handlers(self) -> dict:
        # Keyed by this session's own channels: whatever arrives on them belongs to it.
        session_id = self.kwargs["session_id"]
        return {
            session_status_channel(session_id): self._handle_session_statuses,
            session_messages_channel(session_id): self._handle_graph_session_messages,
        }

    def get_channels(self) -> list[str]:
        return list(self._channel_handlers())

    def hold_live_message(self, message: dict) -> None:
        # A graph message is stored before it is published, so its uuid is enough to
        # send it later; keeping its payload would move Redis's backlog into this worker.
        if message.get("channel") == session_messages_channel(self.kwargs["session_id"]):
            try:
                message_uuid = str(json.loads(message["data"])["uuid"])
            except (ValueError, TypeError, KeyError):
                # Held whole: the live handler logs what is wrong with it.
                self.held_live_messages.append(message)
                return
            self.held_live_messages.append(_HeldGraphMessage(uuid=message_uuid))
            return
        self.held_live_messages.append(message)

    def __log(self, event, state, data):
        logger.debug("{} sends event {} {} data: {}", self.__class__.__name__, event, state, data)

    async def _generate_initial_graph_session_messages(self, session_id):
        # A message is published only after it is stored, and the live channel is
        # subscribed before this runs, so the database holds everything not yet seen
        # live. A message in both is sent twice; clients drop the copy by uuid.
        # Keyset pages of plain queries: a server-side cursor is declared WITH HOLD,
        # and PostgreSQL would compute the whole history before the first row.
        last_id = 0
        while True:
            page = await sync_to_async(list)(
                GraphSessionMessage.objects.filter(session_id=session_id, id__gt=last_id)
                .order_by("id")
                .values()[:MESSAGE_PAGE_SIZE]
            )
            for message in page:
                yield message
            if len(page) < MESSAGE_PAGE_SIZE:
                return
            last_id = page[-1]["id"]

    def _messages_event(self, message: dict) -> dict:
        self._sent_message_uuids.add(str(message["uuid"]))
        message["message_data"] = trim_base64_file_data(message["message_data"])
        return {"event": "messages", "data": message}

    async def _send_held_live_messages(self):
        """Send what was published during the initial data, in the order it was published.

        A held graph message the initial data already sent is skipped; the others are
        read back from the database.
        """
        held_messages, self.held_live_messages = self.held_live_messages, []
        pending_uuids = []
        for held_message in held_messages:
            if isinstance(held_message, _HeldGraphMessage):
                if held_message.uuid not in self._sent_message_uuids:
                    pending_uuids.append(held_message.uuid)
                if len(pending_uuids) == MESSAGE_PAGE_SIZE:
                    async for item in self._send_stored_messages(pending_uuids):
                        yield item
                    pending_uuids = []
                continue
            async for item in self._send_stored_messages(pending_uuids):
                yield item
            pending_uuids = []
            async for item in self._handle_live_message(held_message):
                yield item
        async for item in self._send_stored_messages(pending_uuids):
            yield item

    async def _send_stored_messages(self, uuids: list[str]):
        if not uuids:
            return
        rows = await sync_to_async(list)(
            GraphSessionMessage.objects.filter(
                session_id=self.kwargs["session_id"], uuid__in=uuids
            ).values()
        )
        rows_by_uuid = {str(row["uuid"]): row for row in rows}
        for message_uuid in uuids:
            if message_uuid in rows_by_uuid and message_uuid not in self._sent_message_uuids:
                self.__log(event="messages", state="held", data=message_uuid)
                yield self._messages_event(rows_by_uuid[message_uuid])

    async def _handle_graph_session_messages(self, raw_data: str):
        # Only this session's channel is subscribed, so the message is the caller's.
        # Its publisher already cut the file data, so it is sent without being parsed.
        yield SerializedEvent(event="messages", data=raw_data)

    def _note_status(self, status: str) -> None:
        if status in FINISHED_STATUSES and self._finished_at is None:
            self._finished_at = time.monotonic()

    async def _handle_session_statuses(self, raw_data: str):
        data = json.loads(raw_data)
        self.__log(event="status", state="update", data=data["status"])
        self._note_status(data["status"])
        status_data = data.get("status_data", {})
        if data["status"] == Session.SessionStatus.END:
            final_variables = await self._read_final_variables(self.kwargs["session_id"])
            if final_variables is not None:
                status_data["variables"] = final_variables
        yield {
            "event": "status",
            "data": {
                "session_id": data["session_id"],
                "status": data["status"],
                "status_data": status_data,
            },
        }

    async def _read_final_variables(self, session_id) -> dict | None:
        # Crew sends `end` without variables; clients (the EpicChat widget) read
        # `status_data.variables` from this live event, so they are filled in here.
        raw_variables = await redis_service.async_redis_client.get(
            session_final_variables_key(session_id)
        )
        if raw_variables is not None:
            return json.loads(raw_variables)

        # Once the key has expired, the persisted status is the only remaining copy.
        stored_status_data = await (
            Session.objects.filter(id=session_id).values_list("status_data", flat=True).afirst()
        )
        return (stored_status_data or {}).get("variables")

    async def get_initial_data(self):
        # Graph Session Messages
        session_id = self.kwargs["session_id"]
        async for message in self._generate_initial_graph_session_messages(session_id):
            self.__log(event="messages", state="initial", data=message["uuid"])
            yield self._messages_event(message)

        # Session Statuses
        queryset = (
            Session.objects.only("id", "status", "status_data").filter(id=session_id).values()
        )
        async for session in self.async_orm_generator(queryset):
            self.__log(event="status", state="initial", data=session["status"])
            self._note_status(session["status"])
            yield {
                "event": "status",
                "data": {
                    "session_id": session["id"],
                    "status": session["status"],
                    "status_data": session.get("status_data", {}),
                },
            }

    async def get_live_updates(self, pubsub):
        async for item in self._send_held_live_messages():
            yield item
        # Sending the held messages read the database again.
        await self.release_database_connection()

        messages = redis_service.redis_get_message(channels=self.get_channels(), pubsub=pubsub)
        try:
            while (message := await self._next_live_message(messages)) is not None:
                if message.get("type") != "message":
                    continue

                async for item in self._handle_live_message(message):
                    yield item
        finally:
            await messages.aclose()

        if self._finished_at is not None:
            # Tells the client the stream ended on purpose, so it does not reconnect.
            yield {"event": "done", "data": {"session_id": self.kwargs["session_id"]}}

    async def _next_live_message(self, messages) -> dict | None:
        """Wait for the next live message; None once the session's stream is over.

        After a finished status, waits only until LATE_MESSAGE_SECONDS have passed
        since it, so a finished session's stream does not stay open until the
        client leaves.
        """
        if self._finished_at is None:
            return await anext(messages, None)
        remaining = self._finished_at + LATE_MESSAGE_SECONDS - time.monotonic()
        if remaining <= 0:
            return None
        try:
            return await asyncio.wait_for(anext(messages, None), timeout=remaining)
        except TimeoutError:
            return None

    async def _handle_live_message(self, message: dict):
        try:
            handler = self._channel_handlers().get(message.get("channel"))
            if handler is None:
                return

            async for item in handler(message["data"]):
                logger.debug("get_live_updates data: {}", item)
                yield item

        except Exception as e:
            logger.exception(f"Error processing live update: {e}")

    async def authorize(self, request, *args, **kwargs):
        """The SSE ticket only proves identity; gate the stream by the org that
        owns the session's graph (org membership + FLOWS READ). Superadmin
        passes. Returns a JSON error response on denial, else None."""
        try:
            await sync_to_async(get_accessible_session)(self.user, self.kwargs.get("session_id"))
        except APIException as exc:
            return JsonResponse(
                {
                    "status_code": exc.status_code,
                    "code": exc.default_code,
                    "message": str(exc.detail),
                },
                status=exc.status_code,
            )
        return None

    async def get(self, request, *args, **kwargs):
        """
        SSE stream for real-time run session updates.
        Returns events:
            - messages: for graph session messages
            - status: for session statuses
            - done: once the session has finished, just before the stream closes

        Append ?test=true to the URL for a finite sample response
        """
        logger.info("Started run session SSE")
        return await super().get(request, *args, **kwargs)
