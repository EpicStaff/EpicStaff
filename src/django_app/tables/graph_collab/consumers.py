import asyncio
import json

import pydantic
from asgiref.sync import sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from pydantic import BaseModel

from tables.graph_collab.autosave_loop import ensure_autosave_loop_running
from tables.graph_collab.flush_service import flush_service
from tables.graph_collab.graph_state_service import graph_state_service
from tables.graph_collab.notifications import anotify_graph_saved
from tables.services.redis_service import RedisService
from tables.graph_collab.lock_service import lock_service
from tables.graph_collab.presence_service import presence_service
from tables.graph_collab.constants import (
    CURSOR_FLUSH_INTERVAL_SECONDS,
    CURSOR_REDIS_CHANNEL_PREFIX,
    _RELAY_MESSAGE_TYPES,
    _STATE_OP_TYPES,
)
from tables.graph_collab.protocol import (
    CursorMovedMessage,
    EditorInfo,
    ErrorMessage,
    GraphStateMessage,
    LockStateMessage,
    NodeLockedMessage,
    NodeUnlockedMessage,
    PresenceStateMessage,
    UserJoinedMessage,
    UserLeftMessage,
)

from utils.logger import logger


def _group_name(graph_id: int) -> str:
    return f"graph_edit_{graph_id}"


def _cursor_channel_name(graph_id: int) -> str:
    return f"{CURSOR_REDIS_CHANNEL_PREFIX}:{graph_id}"


def _lock_timeout() -> int:
    return getattr(settings, "GRAPH_LOCK_TIMEOUT_SECONDS", 300)


class GraphEditConsumer(AsyncJsonWebsocketConsumer):
    """
    WebSocket consumer for graph co-editing events.

    Clients connect to /ws/graphs/{graph_id}/edit/?ticket=<token>.
    After connect they can send canvas-edit messages which are relayed
    to all other consumers for the same graph. graph_saved events are pushed
    from HTTP views via GraphEditNotifier.
    """

    async def connect(self):
        user = self.scope.get("user")
        if not user or isinstance(user, AnonymousUser):
            await self.close(code=4401)
            return

        graph_id_str = self.scope["url_route"]["kwargs"]["graph_id"]
        try:
            self.graph_id = int(graph_id_str)
        except (ValueError, TypeError):
            await self.close(code=4400)
            return

        exists = await sync_to_async(self._graph_exists)(self.graph_id)
        if not exists:
            await self.close(code=4404)
            return

        self.group = _group_name(self.graph_id)

        # Per-field asyncio timer handles; keyed by "{node_id}:{field}".
        self._lock_timers: dict[str, asyncio.Task] = {}

        # Latest cursor position per remote user_id (echo-suppressed).
        self._pending_cursors: dict[int, dict] = {}

        # Dedicated Redis pubsub connection for this consumer (lossy cursor channel).
        self._cursor_pubsub = None
        self._cursor_reader_task: asyncio.Task | None = None
        self._cursor_flush_task: asyncio.Task | None = None

        await self.channel_layer.group_add(self.group, self.channel_name)
        await self.accept()
        logger.info(
            "User {} connected to graph {} edit channel", user.pk, self.graph_id
        )

        editor = self._build_editor_info(user)
        presence_service.add(self.graph_id, self.channel_name, editor)

        await self.send_json(
            PresenceStateMessage(
                editors=presence_service.get_editors(self.graph_id),
            ).model_dump()
        )

        await self.channel_layer.group_send(
            self.group,
            UserJoinedMessage(editor=editor).model_dump(),
        )

        # If no snapshot is cached yet (first connector or post-clear), seed from the DB now.
        snapshot = await graph_state_service.get_snapshot(self.graph_id)
        if snapshot is None:
            seeded = await graph_state_service.seed_from_db(self.graph_id)
            if not seeded:
                # Graph was deleted between the existence check and seed — close cleanly.
                logger.warning(
                    "Graph {} disappeared before snapshot could be seeded — closing connection",
                    self.graph_id,
                )
                await self.close(code=4404)
                return
            snapshot = await graph_state_service.get_snapshot(self.graph_id)
        await self.send_json(GraphStateMessage(flow=snapshot).model_dump())

        active_locks = lock_service.get_all_locks(self.graph_id)
        if active_locks:
            await self.send_json(
                LockStateMessage(
                    locks={
                        node_id: {
                            field: entry.editor for field, entry in fields.items()
                        }
                        for node_id, fields in active_locks.items()
                    }
                ).model_dump()
            )

        # Start cursor pub/sub reader and flush tasks.
        await self._start_cursor_tasks()

        # Ensure the global autosave loop is running (idempotent — no-op if already alive).
        ensure_autosave_loop_running()

    async def disconnect(self, code):
        # Cancel cursor background tasks before doing anything else.
        await self._stop_cursor_tasks()

        group = getattr(self, "group", None)
        if group:
            graph_id = getattr(self, "graph_id", None)
            user = self.scope.get("user")
            if graph_id is not None:
                # Cancel all pending lock timers before releasing locks.
                for timer in getattr(self, "_lock_timers", {}).values():
                    timer.cancel()

                # Release all locks held by this channel and broadcast unlocks.
                released_pairs = lock_service.release_all_for_channel(
                    graph_id, self.channel_name
                )
                if released_pairs and user and not isinstance(user, AnonymousUser):
                    editor = self._build_editor_info(user)
                    for node_id, field in released_pairs:
                        event = NodeUnlockedMessage(
                            node_id=node_id, field=field, editor=editor
                        ).model_dump()
                        event["sender_channel"] = self.channel_name
                        await self.channel_layer.group_send(self.group, event)

                presence_service.remove(graph_id, self.channel_name)
                if user and not isinstance(user, AnonymousUser):
                    await self.channel_layer.group_send(
                        group,
                        UserLeftMessage(user_id=user.pk).model_dump(),
                    )

                # Flush to DB and then clear the live snapshot once the last editor leaves
                if presence_service.count_editors(graph_id) == 0:
                    try:
                        outcome = await flush_service.flush_if_dirty(graph_id)
                        if outcome.saved:
                            editor_user = (
                                user
                                if user and not isinstance(user, AnonymousUser)
                                else None
                            )
                            await anotify_graph_saved(
                                graph_id=graph_id,
                                new_save_version=outcome.result.new_save_version,
                                saved_at=outcome.result.saved_at,
                                user=editor_user,
                                temp_id_map=outcome.result.temp_id_map,
                            )
                        if outcome.safe_to_clear:
                            await graph_state_service.clear(graph_id)
                        else:
                            logger.error(
                                "Last-leave: final flush FAILED for graph {} — "
                                "snapshot retained via TTL for recovery",
                                graph_id,
                            )
                    except Exception as exc:
                        logger.error(
                            "Last-leave flush failed for graph {}: {}", graph_id, exc
                        )
            await self.channel_layer.group_discard(group, self.channel_name)

    async def receive_json(self, content, **kwargs):
        message_type = content.get("type")

        # Cursor messages travel via Redis pub/sub (lossy), not the channel layer.
        if message_type == "cursor_moved":
            await self._handle_cursor_moved(content)
            return

        # TODO DEPRECATED: Client→Server graph_state seed (old clients only).
        # The server now seeds from DB on connect (seed_from_db) and does not
        # need the client to push state.
        if message_type == "graph_state":
            logger.debug(
                "Received deprecated client-side graph_state seed from graph {} — ignoring",
                self.graph_id,
            )
            return

        # Handle lock claim — arbitrated through lock_service, not blindly relayed.
        if message_type == "node_locked":
            await self._handle_node_locked(content)
            return

        # Handle lock release — arbitrated through lock_service.
        if message_type == "node_unlocked":
            await self._handle_node_unlocked(content)
            return

        model_class = _RELAY_MESSAGE_TYPES.get(message_type)
        if model_class is not None:
            await self._handle_relay(content, model_class)
        else:
            await self.send_json(
                ErrorMessage(
                    code="unknown_message_type",
                    message=f"Unknown message type: {message_type!r}",
                ).model_dump()
            )

    async def _handle_node_locked(self, content: dict) -> None:
        try:
            message = NodeLockedMessage.model_validate(content)
        except pydantic.ValidationError as exc:
            await self.send_json(
                ErrorMessage(code="invalid_payload", message=str(exc)).model_dump()
            )
            return

        # Override editor server-side — never trust the client-sent identity.
        editor = self._build_editor_info(self.scope["user"])
        message.editor = editor

        granted = lock_service.try_lock(
            self.graph_id,
            message.node_id,
            message.field,
            editor,
            self.channel_name,
        )

        if granted:
            self._schedule_lock_timer(message.node_id, message.field, editor)
            event = message.model_dump()
            event["sender_channel"] = self.channel_name
            await self.channel_layer.group_send(self.group, event)
        else:
            # Send corrective signal to the loser — describes the current holder.
            holder = lock_service.get_holder(
                self.graph_id, message.node_id, message.field
            )
            if holder is None:
                # Holder vanished between try_lock and get_holder — harmless, skip.
                return
            await self.send_json(
                NodeLockedMessage(
                    node_id=message.node_id,
                    field=message.field,
                    editor=holder.editor,
                ).model_dump()
            )

    async def _handle_node_unlocked(self, content: dict) -> None:
        try:
            message = NodeUnlockedMessage.model_validate(content)
        except pydantic.ValidationError as exc:
            await self.send_json(
                ErrorMessage(code="invalid_payload", message=str(exc)).model_dump()
            )
            return

        released = lock_service.release(
            self.graph_id, message.node_id, message.field, self.channel_name
        )
        if not released:
            # Non-owner or already released — silently discard; no broadcast.
            return

        self._cancel_lock_timer(message.node_id, message.field)

        # Override editor server-side before relaying.
        message.editor = self._build_editor_info(self.scope["user"])
        event = message.model_dump()
        event["sender_channel"] = self.channel_name
        await self.channel_layer.group_send(self.group, event)

    # --- Backstop inactivity timer ---

    def _schedule_lock_timer(
        self, node_id: str, field: str, editor: EditorInfo
    ) -> None:
        """Schedule (or reset) a backstop timer that auto-releases *node_id*/*field* after
        GRAPH_LOCK_TIMEOUT_SECONDS.  The timer lives on the consumer instance so
        that asyncio event-loop concerns stay out of the pure-registry lock_service.
        """
        self._cancel_lock_timer(node_id, field)
        timeout = _lock_timeout()
        timer_key = f"{node_id}:{field}"
        self._lock_timers[timer_key] = asyncio.ensure_future(
            self._backstop_release(node_id, field, editor, timeout)
        )

    def _cancel_lock_timer(self, node_id: str, field: str) -> None:
        timer_key = f"{node_id}:{field}"
        timer = self._lock_timers.pop(timer_key, None)
        if timer is not None:
            timer.cancel()

    async def _backstop_release(
        self, node_id: str, field: str, editor: EditorInfo, timeout: int
    ) -> None:
        await asyncio.sleep(timeout)
        released = lock_service.release(
            self.graph_id, node_id, field, self.channel_name
        )
        if not released:
            return

        logger.info(
            "Lock backstop: auto-released node {} field {} on graph {} for channel {}",
            node_id,
            field,
            self.graph_id,
            self.channel_name,
        )
        event = NodeUnlockedMessage(
            node_id=node_id, field=field, editor=editor
        ).model_dump()
        event["sender_channel"] = self.channel_name
        await self.channel_layer.group_send(self.group, event)

    async def _handle_relay(self, content: dict, model_class: type[BaseModel]) -> None:
        try:
            message = model_class.model_validate(content)
        except pydantic.ValidationError as exc:
            await self.send_json(
                ErrorMessage(
                    code="invalid_payload",
                    message=str(exc),
                ).model_dump()
            )
            return

        # Override editor server-side — never trust the client-sent identity.
        message.editor = self._build_editor_info(self.scope["user"])

        # Apply state-mutating ops to the live snapshot before relaying.
        if message.type in _STATE_OP_TYPES:
            await graph_state_service.apply_op(self.graph_id, message)

        event = message.model_dump()
        event["sender_channel"] = self.channel_name
        await self.channel_layer.group_send(self.group, event)

    async def _relay(self, event: dict) -> None:
        """Forward a channel-layer event to the WebSocket, suppressing echo to sender."""
        if event.get("sender_channel") == self.channel_name:
            return
        payload = {
            key: value for key, value in event.items() if key != "sender_channel"
        }
        await self.send_json(payload)

    # --- Channel layer handlers: relay ---

    async def node_created(self, event):
        await self._relay(event)

    async def node_updated(self, event):
        await self._relay(event)

    async def nodes_deleted(self, event):
        await self._relay(event)

    async def connection_created(self, event):
        await self._relay(event)

    async def connection_deleted(self, event):
        await self._relay(event)

    async def connections_deleted(self, event):
        await self._relay(event)

    async def connection_waypoints_updated(self, event):
        await self._relay(event)

    async def selection_changed(self, event):
        await self._relay(event)

    async def node_locked(self, event):
        await self._relay(event)

    async def node_unlocked(self, event):
        await self._relay(event)

    # --- Channel layer handlers: presence + notifications ---

    async def graph_saved(self, event):
        await self.send_json(event)

    async def save_failed(self, event):
        await self.send_json(event)

    async def user_joined(self, event):
        await self.send_json(event)

    async def user_left(self, event):
        await self.send_json(event)

    async def presence_state(self, event):
        await self.send_json(event)

    # --- Cursor pub/sub (Redis, lossy) ---

    async def _handle_cursor_moved(self, content: dict) -> None:
        """Publish cursor position to the per-graph Redis channel (fire-and-forget).

        The server overrides editor identity so clients cannot spoof who they are.
        The payload includes the sender's user_id so all subscribers can suppress echo.
        """
        try:
            message = CursorMovedMessage.model_validate(content)
        except pydantic.ValidationError as exc:
            await self.send_json(
                ErrorMessage(code="invalid_payload", message=str(exc)).model_dump()
            )
            return

        user = self.scope["user"]
        message.editor = self._build_editor_info(user)

        payload = {
            "sender_user_id": user.pk,
            "x": message.x,
            "y": message.y,
            "editor": message.editor.model_dump(),
        }

        redis_client = RedisService().async_redis_client
        channel = _cursor_channel_name(self.graph_id)
        await redis_client.publish(channel, json.dumps(payload))

    async def _start_cursor_tasks(self) -> None:
        """Subscribe to the cursor Redis channel and start reader + flush tasks."""
        redis_client = RedisService().async_redis_client
        self._cursor_pubsub = redis_client.pubsub()
        channel = _cursor_channel_name(self.graph_id)
        await self._cursor_pubsub.subscribe(channel)

        self._cursor_reader_task = asyncio.ensure_future(self._cursor_reader_loop())
        self._cursor_flush_task = asyncio.ensure_future(self._cursor_flush_loop())
        logger.debug(
            "Cursor pub/sub started for user {} on graph {}",
            self.scope["user"].pk,
            self.graph_id,
        )

    async def _stop_cursor_tasks(self) -> None:
        """Cancel cursor tasks and close the Redis pubsub connection cleanly."""
        for task in (
            getattr(self, "_cursor_reader_task", None),
            getattr(self, "_cursor_flush_task", None),
        ):
            if task is not None:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        pubsub = getattr(self, "_cursor_pubsub", None)
        if pubsub is not None:
            try:
                channel = _cursor_channel_name(getattr(self, "graph_id", 0))
                await pubsub.unsubscribe(channel)
                await pubsub.aclose()
            except Exception as exc:
                logger.warning("Error closing cursor pubsub: {}", exc)

    async def _cursor_reader_loop(self) -> None:
        """Read cursor messages from Redis and write latest position per user.

        Overwrites any previous position for the same user_id (coalescing).
        Skips messages from this consumer's own user (echo suppression).
        """
        own_user_id: int = self.scope["user"].pk
        try:
            async for message in self._cursor_pubsub.listen():
                if message["type"] != "message":
                    continue
                try:
                    data = json.loads(message["data"])
                except (json.JSONDecodeError, TypeError) as exc:
                    logger.warning("Cursor reader: invalid JSON payload: {}", exc)
                    continue

                sender_user_id = data.get("sender_user_id")
                if sender_user_id == own_user_id:
                    # Echo suppression — a user must not see their own cursor.
                    continue

                editor = data.get("editor")
                if editor is None or "x" not in data or "y" not in data:
                    logger.warning(
                        "Cursor reader: malformed payload, missing fields: {}", data
                    )
                    continue

                self._pending_cursors[sender_user_id] = {
                    "x": data["x"],
                    "y": data["y"],
                    "editor": editor,
                }
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error(
                "Cursor reader loop error for graph {}: {}", self.graph_id, exc
            )

    async def _cursor_flush_loop(self) -> None:
        """Periodically send one batched cursor message to this consumer's browser.

        Sends only when there is at least one pending cursor update.
        """
        try:
            while True:
                await asyncio.sleep(CURSOR_FLUSH_INTERVAL_SECONDS)
                if not self._pending_cursors:
                    continue
                batch = list(self._pending_cursors.values())
                self._pending_cursors.clear()
                await self.send_json({"type": "cursor_batch", "cursors": batch})
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("Cursor flush loop error for graph {}: {}", self.graph_id, exc)

    # --- Helpers ---

    @staticmethod
    def _build_editor_info(user) -> EditorInfo:
        avatar_url: str | None = None
        avatar = getattr(user, "avatar", None)
        if avatar and avatar.name:
            try:
                avatar_url = avatar.url
            except ValueError:
                avatar_url = None
        return EditorInfo(
            user_id=user.pk,
            display_name=getattr(user, "display_name", None)
            or getattr(user, "email", None),
            avatar_url=avatar_url,
        )

    @staticmethod
    def _graph_exists(graph_id: int) -> bool:
        from tables.models import Graph

        return Graph.objects.filter(pk=graph_id).exists()
