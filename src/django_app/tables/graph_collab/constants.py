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

# Seconds between each cursor-batch flush to the browser.
CURSOR_FLUSH_INTERVAL_SECONDS: float = 0.15

# Seconds between each autosave flush to the database
AUTOSAVE_FLUSH_INTERVAL_SECONDS: float = getattr(
    settings, "AUTOSAVE_FLUSH_INTERVAL_SECONDS", 20.0
)

# Redis pub/sub channel prefix for per-graph cursor traffic.
CURSOR_REDIS_CHANNEL_PREFIX: str = "cursors"

# cursor_moved is intentionally absent — it travels via Redis pub/sub, not the
# channel-layer group, so it cannot flood the per-channel mailbox (capacity 100)
# shared with critical messages.
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
