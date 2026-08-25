from django.conf import settings
from pydantic import BaseModel

from tables.graph_collab.protocol import (
    ConnectionCreatedMessage,
    ConnectionDeletedMessage,
    ConnectionsDeletedMessage,
    ConnectionWaypointsUpdatedMessage,
    NodeCreatedMessage,
    NodeUpdatedMessage,
    NodesDeletedMessage,
    SelectionChangedMessage,
)

from tables.services.graph_bulk_save_service.registry import NODE_TYPE_REGISTRY

# -------------------------------------------------------------------
# Global real-time collaboration — flush/broadcast timing and channel naming,
# consumed by consumers.py and autosave_loop.py
# -------------------------------------------------------------------

# Seconds between each cursor-batch flush to the browser.
CURSOR_FLUSH_INTERVAL_SECONDS: float = 0.15

# Seconds between each autosave flush to the database
AUTOSAVE_FLUSH_INTERVAL_SECONDS: float = getattr(
    settings, "AUTOSAVE_FLUSH_INTERVAL_SECONDS", 20.0
)

# Redis pub/sub channel prefix for per-graph cursor traffic.
CURSOR_REDIS_CHANNEL_PREFIX: str = "cursors"

# Seconds between each periodic backstop re-check of the connected user's
# org edit permission (catches revocations missed by the event-driven
# permission_changed broadcast — e.g. a group_send dropped by an infra hiccup).
PERMISSION_RECHECK_INTERVAL_SECONDS: float = getattr(
    settings, "PERMISSION_RECHECK_INTERVAL_SECONDS", 45.0
)

# -------------------------------------------------------------------
# Consumer — WS message-type dispatch tables, consumed by consumers.py
# -------------------------------------------------------------------

# cursor_moved is intentionally absent — it travels via Redis pub/sub
_RELAY_MESSAGE_TYPES: dict[str, type[BaseModel]] = {
    "node_created": NodeCreatedMessage,
    "node_updated": NodeUpdatedMessage,
    "nodes_deleted": NodesDeletedMessage,
    "connection_created": ConnectionCreatedMessage,
    "connection_deleted": ConnectionDeletedMessage,
    "connections_deleted": ConnectionsDeletedMessage,
    "connection_waypoints_updated": ConnectionWaypointsUpdatedMessage,
    "selection_changed": SelectionChangedMessage,
}

# Op types that mutate the live graph snapshot — must be applied via apply_op.
_STATE_OP_TYPES: frozenset[str] = frozenset(
    {
        "node_created",
        "node_updated",
        "nodes_deleted",
        "connection_created",
        "connection_deleted",
        "connections_deleted",
        "connection_waypoints_updated",
    }
)

# -------------------------------------------------------------------
# GraphStateService — list-key tables describing every node/edge list in a
# graph snapshot, consumed by graph_state_service.py, flush_service.py, and
# snapshot_normalize.py
# -------------------------------------------------------------------

_EDGE_ENDPOINT_TEMP_FIELDS: dict[str, tuple[tuple[str, str], ...]] = {
    "edge_list": (("start_temp_id", "start_node_id"), ("end_temp_id", "end_node_id")),
    "conditional_edge_list": (("source_temp_id", "source_node_id"),),
}

# Maps list_key to the corresponding deleted-accumulator key. Covers every
# list type: node lists use the <type>_node_ids pattern; edge lists use
# edge_ids / conditional_edge_ids.
_LIST_KEY_TO_DELETE_KEY: dict[str, str] = {
    "crew_node_list": "crew_node_ids",
    "task_node_list": "task_node_ids",
    "agent_node_list": "agent_node_ids",
    "python_node_list": "python_node_ids",
    "file_extractor_node_list": "file_extractor_node_ids",
    "audio_transcription_node_list": "audio_transcription_node_ids",
    "start_node_list": "start_node_ids",
    "end_node_list": "end_node_ids",
    "subgraph_node_list": "subgraph_node_ids",
    "decision_table_node_list": "decision_table_node_ids",
    "graph_note_list": "graph_note_ids",
    "webhook_trigger_node_list": "webhook_trigger_node_ids",
    "telegram_trigger_node_list": "telegram_trigger_node_ids",
    "schedule_trigger_node_list": "schedule_trigger_node_ids",
    "code_agent_node_list": "code_agent_node_ids",
    "classification_decision_table_node_list": "classification_decision_table_node_ids",
    "edge_list": "edge_ids",
    "conditional_edge_list": "conditional_edge_ids",
}

_ALL_LIST_KEYS: frozenset[str] = frozenset(_LIST_KEY_TO_DELETE_KEY.keys())

# Node-ref fields on each edge list that must be checked when cascading a
# node delete — edge_list has two endpoints, conditional_edge_list has one
# (conditional edges have no target_node_id field).
_EDGE_NODE_REF_FIELDS: dict[str, tuple[str, ...]] = {
    "edge_list": ("start_node_id", "end_node_id"),
    "conditional_edge_list": ("source_node_id",),
}

# Decision-table-like list keys whose entries carry routing refs to other
# nodes (default_next_node_id / next_error_node_id / condition_groups[].next_node_id).
_DECISION_TABLE_LIST_KEYS: tuple[str, ...] = (
    "decision_table_node_list",
    "classification_decision_table_node_list",
)


_SINGLETON_LIST_KEYS: frozenset[str] = frozenset(
    config.list_key for config in NODE_TYPE_REGISTRY if config.is_singleton
)

# (list_key, nested object key) -> superadmin-only fields inside that object.
# apply_op pins these to their currently-stored value for non-superadmins
# before any snapshot mutation — see _pin_privileged_fields.
PRIVILEGED_NESTED_FIELDS: dict[str, dict[str, frozenset[str]]] = {
    "webhook_trigger_node_list": {
        "webhook_trigger": frozenset({"ngrok_webhook_config"})
    },
    "telegram_trigger_node_list": {
        "webhook_trigger": frozenset({"ngrok_webhook_config"})
    },
}
