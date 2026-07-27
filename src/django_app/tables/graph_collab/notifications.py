from datetime import datetime, timezone

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from tables.graph_collab.graph_state_service import graph_state_service
from tables.graph_collab.groups import graph_group_name, org_group_name
from tables.graph_collab.utils import build_editor_info
from tables.graph_collab.presence_service import presence_service
from tables.graph_collab.protocol import (
    EditorInfo,
    EntryDeleteRef,
    GraphFilesChangedMessage,
    GraphSaveFailedMessage,
    GraphSavedMessage,
    GraphStateMessage,
    NodesDeletedMessage,
    NodeUnlockedMessage,
    PresenceStateUpdatedMessage,
)

from utils.logger import logger

_SYSTEM_EDITOR = EditorInfo(user_id=0, display_name="Autosave", avatar_url=None)


def _build_graph_saved_message(
    graph_id: int,
    new_save_version: int,
    user,
    saved_at: str,
    avatar_url: str | None = None,
    temp_id_map: dict[str, int] | None = None,
) -> dict:
    """Build a ``GraphSavedMessage`` dict ready for channel layer group_send.

    Extracted so both the sync HTTP path and the async consumer triggers can
    reuse the same construction logic without duplicating the EditorInfo /
    GraphSavedMessage assembly.

    Pass ``user=None`` to attribute the save to the system autosave loop
    (``_SYSTEM_EDITOR``).
    """
    if user is None:
        editor = _SYSTEM_EDITOR
    else:
        editor = build_editor_info(user=user)

    message = GraphSavedMessage(
        graph_id=graph_id,
        new_save_version=new_save_version,
        saved_by=editor,
        saved_at=saved_at,
        temp_id_map=temp_id_map or {},
    )
    return message.model_dump()


class GraphEditNotifier:
    """
    Synchronous helpers for broadcasting graph collaboration events from
    HTTP views (which are sync). Uses async_to_sync to bridge into the
    channel layer.

    For async consumer triggers, use ``anotify_graph_saved`` instead — it
    awaits ``channel_layer.group_send`` directly without nesting
    ``async_to_sync`` inside a running event loop.
    """

    @staticmethod
    def notify_graph_saved(
        graph_id: int,
        new_save_version: int,
        user,
        saved_at: str,
        avatar_url: str | None = None,
        temp_id_map: dict[str, int] | None = None,
    ) -> None:
        """Broadcast graph_saved from a synchronous HTTP view.

        ``temp_id_map`` is optional and defaults to ``{}`` — existing REST
        callers that do not pass it retain identical behaviour.

        """

        # TODO need to be refactored (whole notifier), because of autosave usage
        message = _build_graph_saved_message(
            graph_id=graph_id,
            new_save_version=new_save_version,
            user=user,
            saved_at=saved_at,
            avatar_url=avatar_url,
            temp_id_map=temp_id_map,
        )
        GraphEditNotifier._send(graph_id, message)

    @staticmethod
    def notify_graph_restored(
        graph_id: int,
        flow: dict,
        new_save_version: int,
        version_name: str,
        user,
    ) -> None:
        """Broadcast a full session reset after a version restore"""

        message = GraphStateMessage(
            flow=flow,
            restored_by=build_editor_info(user),
            new_save_version=new_save_version,
            version_name=version_name,
        )
        GraphEditNotifier._send(graph_id, message.model_dump())

    @staticmethod
    def notify_nodes_unlocked(
        graph_id: int,
        released_pairs: list[tuple[str, str]],
        user,
    ) -> None:
        """Broadcast a ``node_unlocked`` message for each released lock pair"""

        if not released_pairs:
            return
        editor = build_editor_info(user)
        for node_id, field in released_pairs:
            message = NodeUnlockedMessage(
                node_id=node_id, field=field, editor=editor
            ).model_dump()
            GraphEditNotifier._send(graph_id, message)

    @staticmethod
    def broadcast_nodes_deleted(
        graph_id: int,
        node_ids: list[int],
        editor: EditorInfo | None = None,
    ) -> None:
        """Broadcast nodes_deleted for a set of ``crew_node_list`` row ids."""

        if async_to_sync(graph_state_service.get_snapshot)(graph_id) is None:
            logger.debug(
                "broadcast_nodes_deleted: no live snapshot for graph {} — skipping",
                graph_id,
            )
            return

        message = NodesDeletedMessage(
            refs=[
                EntryDeleteRef(list_key="crew_node_list", id=node_id)
                for node_id in node_ids
            ],
            editor=editor or _SYSTEM_EDITOR,
        )
        async_to_sync(graph_state_service.apply_op)(graph_id, message)
        GraphEditNotifier._send(graph_id, message.model_dump())

    @staticmethod
    def notify_schedule_node_deactivated(graph_id: int, node_id: int) -> None:
        """Notify a live collaborative session that the scheduler flipped a
        ScheduleTriggerNode's ``is_active`` to False directly in the DB.

        Gated on a live session existing at all — the common case (nobody connected) is a
        no-op.
        """
        if async_to_sync(graph_state_service.get_snapshot)(graph_id) is None:
            logger.debug(
                "notify_schedule_node_deactivated: no live snapshot for graph "
                "{} — skipping",
                graph_id,
            )
            return

        GraphEditNotifier._send(
            graph_id,
            {
                "type": "schedule_node_deactivated",
                "graph_id": graph_id,
                "node_id": node_id,
                "list_key": "schedule_trigger_node_list",
            },
        )

    @staticmethod
    def notify_graph_files_changed(graph_id: int, user=None) -> None:
        """Broadcast graph_files_changed after a graph's attached-files list
        changes
        """
        editor = (
            build_editor_info(user)
            if user is not None and user.is_authenticated
            else None
        )
        message = GraphFilesChangedMessage(graph_id=graph_id, editor=editor)
        GraphEditNotifier._send(graph_id, message.model_dump())

    @staticmethod
    def notify_org_files_changed(org_id: int) -> None:
        """Broadcast graph_files_changed org-wide after any storage-tree
        mutation, so every open "Add files" dialog in the org can live-refresh
        """
        message = GraphFilesChangedMessage(graph_id=None, editor=None)
        GraphEditNotifier._send_to_org(org_id, message.model_dump())

    @staticmethod
    def notify_profile_updated(user) -> None:
        editor = build_editor_info(user)
        affected = presence_service.update_editor_for_user(user.pk, editor)
        if not affected:
            return
        message = PresenceStateUpdatedMessage(editor=editor).model_dump()
        for graph_id in affected:
            GraphEditNotifier._send(graph_id, message)

    @staticmethod
    def _send(graph_id: int, message: dict) -> None:
        layer = get_channel_layer()
        if layer is None:
            logger.warning(
                "Channel layer is not configured — skipping broadcast for graph {}",
                graph_id,
            )
            return
        try:
            async_to_sync(layer.group_send)(graph_group_name(graph_id), message)
        except Exception as exc:
            logger.error("Failed to broadcast to graph {} group: {}", graph_id, exc)

    @staticmethod
    def _send_to_org(org_id: int, message: dict) -> None:
        layer = get_channel_layer()
        if layer is None:
            logger.warning(
                "Channel layer is not configured — skipping broadcast for org {}",
                org_id,
            )
            return
        try:
            async_to_sync(layer.group_send)(org_group_name(org_id), message)
        except Exception as exc:
            logger.error("Failed to broadcast to org {} group: {}", org_id, exc)


async def anotify_graph_saved(
    graph_id: int,
    new_save_version: int,
    saved_at: str,
    user=None,
    avatar_url: str | None = None,
    temp_id_map: dict[str, int] | None = None,
) -> None:
    """Broadcast graph_saved from an async context (e.g. WebSocket consumer).

    Preferred over ``GraphEditNotifier.notify_graph_saved`` when already inside
    an async event loop — avoids nesting ``async_to_sync`` which raises a
    ``RuntimeError`` when called from a running loop.

    ``temp_id_map`` carries the frontend-temp-id → real-DB-id mapping produced
    by a flush so connected editors can reconcile their local node references.

    Pass ``user=None`` (the default) when called from the global autosave loop,
    which has no acting user — the save will be attributed to ``_SYSTEM_EDITOR``.
    """
    layer = get_channel_layer()
    if layer is None:
        logger.warning(
            "Channel layer is not configured — skipping async broadcast for graph {}",
            graph_id,
        )
        return
    message = _build_graph_saved_message(
        graph_id=graph_id,
        new_save_version=new_save_version,
        user=user,
        saved_at=saved_at,
        avatar_url=avatar_url,
        temp_id_map=temp_id_map,
    )
    try:
        await layer.group_send(graph_group_name(graph_id), message)
    except Exception as exc:
        logger.error("Failed to async broadcast to graph {} group: {}", graph_id, exc)


async def anotify_save_failed(
    graph_id: int,
    reason: str,
    saved_at: str | None = None,
) -> None:
    """Broadcast save_failed to all editors of *graph_id*.

    Called by the global autosave loop when a persistent (non-transient) flush
    error occurs — e.g. validation failure or BulkSaveValidationError.
    Version conflicts are transient and must NOT trigger this broadcast.

    ``reason`` should be a short category string safe to expose to clients:
    ``"validation_error"``, ``"bulk_save_validation"``, or ``"db_error"``.
    """
    if saved_at is None:
        saved_at = datetime.now(tz=timezone.utc).isoformat()
    layer = get_channel_layer()
    if layer is None:
        logger.warning(
            "Channel layer is not configured — skipping save_failed broadcast for graph {}",
            graph_id,
        )
        return
    message = GraphSaveFailedMessage(
        graph_id=graph_id,
        reason=reason,
        saved_at=saved_at,
    ).model_dump()
    try:
        await layer.group_send(graph_group_name(graph_id), message)
    except Exception as exc:
        logger.error(
            "Failed to async broadcast save_failed to graph {} group: {}", graph_id, exc
        )
