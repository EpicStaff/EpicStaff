from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from tables.graph_collab.utils import build_editor_info
from tables.graph_collab.presence_service import presence_service
from tables.graph_collab.protocol import (
    EditorInfo,
    GraphSavedMessage,
    PresenceStateUpdatedMessage,
)
from tables.graph_collab.utils import build_editor_info

from utils.logger import logger


def _group_name(graph_id: int) -> str:
    return f"graph_edit_{graph_id}"


class GraphEditNotifier:
    """
    Synchronous helpers for broadcasting graph collaboration events from
    HTTP views (which are sync). Uses async_to_sync to bridge into the
    channel layer.
    """

    @staticmethod
    def notify_graph_saved(
        graph_id: int,
        new_save_version: int,
        user,
        saved_at: str,
    ) -> None:
        editor = build_editor_info(user=user)
        message = GraphSavedMessage(
            graph_id=graph_id,
            new_save_version=new_save_version,
            saved_by=editor,
            saved_at=saved_at,
        )
        GraphEditNotifier._send(graph_id, message.model_dump())

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
            async_to_sync(layer.group_send)(_group_name(graph_id), message)
        except Exception as exc:
            logger.error("Failed to broadcast to graph {} group: {}", graph_id, exc)
