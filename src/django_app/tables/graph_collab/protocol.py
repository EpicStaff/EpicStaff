from pydantic import BaseModel, ConfigDict, model_validator


class EditorInfo(BaseModel):
    user_id: int
    display_name: str | None
    avatar_url: str | None

    model_config = ConfigDict(from_attributes=True)


# --- Server-push messages (outbound only) ---
class GraphSavedMessage(BaseModel):
    type: str = "graph_saved"
    graph_id: int
    new_save_version: int
    saved_by: EditorInfo
    saved_at: str
    # Maps frontend temp_id strings to the real DB integer ids assigned on insert.
    # Empty for saves originating from the REST path (which has no temp ids).
    temp_id_map: dict[str, int] = {}


class GraphSaveFailedMessage(BaseModel):
    type: str = "save_failed"
    graph_id: int
    # Short category string, not a raw exception message — safe to expose to clients.
    # Values: "validation_error", "bulk_save_validation", "db_error".
    reason: str
    saved_at: str


class PresenceStateMessage(BaseModel):
    type: str = "presence_state"
    editors: list[EditorInfo]


class UserJoinedMessage(BaseModel):
    type: str = "user_joined"
    editor: EditorInfo


class UserLeftMessage(BaseModel):
    type: str = "user_left"
    user_id: int


class PresenceStateUpdatedMessage(BaseModel):
    type: str = "presence_state_updated"
    editor: EditorInfo


class ErrorMessage(BaseModel):
    type: str = "error"
    code: str
    message: str


class OpRejectedMessage(BaseModel):
    """Sent to the sender only (never relayed to peers) when a state-mutating
    op could not be applied to the live snapshot"""

    type: str = "op_rejected"
    op_type: str
    op_id: str | None = None
    list_key: str
    node_ref: dict
    # One of: "target_not_found", "no_snapshot", "unknown_list_key",
    # "missing_identity", "precondition_failed".
    reason: str
    details: dict | None = None


class NodeCreatedMessage(BaseModel):
    type: str = "node_created"
    node: dict
    # list_key identifies which <type>_node_list in the superset snapshot to target,
    # e.g. "crew_node_list". Required so apply_op can locate the right list without
    # guessing from node content.
    list_key: str
    editor: EditorInfo


class NodeUpdatedMessage(BaseModel):
    type: str = "node_updated"
    node: dict
    # list_key identifies which <type>_node_list to look up when mutating the snapshot.
    list_key: str
    editor: EditorInfo
    changed_fields: list[str] | None = None
    # Client-generated correlation id, echoed back on OpRejectedMessage so the
    # sender can match the rejection to the op it sent.
    op_id: str | None = None
    # per changed field, the value the client believes the server currently holds
    # Only meaningful alongside changed_fields
    expected: dict | None = None

    @model_validator(mode="after")
    def _changed_fields_require_identity(self) -> "NodeUpdatedMessage":
        if self.changed_fields is None:
            if self.expected is not None:
                raise ValueError("'expected' requires 'changed_fields' to be set")
            return self
        if not self.changed_fields:
            raise ValueError(
                "changed_fields must be non-empty when provided (use None for "
                "legacy full-payload semantics)"
            )
        if self.node.get("id") is None and self.node.get("temp_id") is None:
            raise ValueError(
                "A partial NodeUpdatedMessage (changed_fields set) requires "
                "'node' to carry an 'id' or 'temp_id'"
            )
        if self.expected is not None and not set(self.expected.keys()) <= set(
            self.changed_fields
        ):
            raise ValueError("'expected' keys must be a subset of 'changed_fields'")
        return self


class EntryDeleteRef(BaseModel):
    """A reference to a single node entry to remove from a list.

    Works for both node lists and connection lists.
    Exactly one of id or temp_id must be set.
    """

    list_key: str
    id: int | None = None
    temp_id: str | None = None

    @model_validator(mode="after")
    def _exactly_one_identifier(self) -> "EntryDeleteRef":
        has_id = self.id is not None
        has_temp_id = self.temp_id is not None and self.temp_id != ""
        if has_id == has_temp_id:  # both set or neither set
            raise ValueError(
                "EntryDeleteRef requires exactly one of 'id' or 'temp_id' to be set, "
                f"got id={self.id!r}, temp_id={self.temp_id!r}"
            )
        return self


class NodesDeletedMessage(BaseModel):
    type: str = "nodes_deleted"
    # Each ref carries list_key + id/temp_id so apply_op knows which list to
    # search and which deleted-ids accumulator to update.
    refs: list[EntryDeleteRef]
    editor: EditorInfo


class ConnectionCreatedMessage(BaseModel):
    type: str = "connection_created"
    connection: dict
    # "edge_list" for regular edges, "conditional_edge_list" for conditional edges.
    list_key: str
    editor: EditorInfo


class ConnectionDeletedMessage(BaseModel):
    type: str = "connection_deleted"
    connection_id: int | None = None
    temp_id: str | None = None
    # "edge_list" or "conditional_edge_list"
    list_key: str
    editor: EditorInfo


class ConnectionsDeletedMessage(BaseModel):
    type: str = "connections_deleted"
    # Each ref: {list_key, id?, temp_id?} — mixed edge/conditional_edge allowed.
    refs: list[EntryDeleteRef]
    editor: EditorInfo


class ConnectionWaypointsUpdatedMessage(BaseModel):
    type: str = "connection_waypoints_updated"
    connection_id: int | str  # real DB id or temp_id string
    waypoints: list[dict]
    # "edge_list" or "conditional_edge_list"
    list_key: str
    editor: EditorInfo


class CursorMovedMessage(BaseModel):
    type: str = "cursor_moved"
    x: float
    y: float
    editor: EditorInfo


class SelectionChangedMessage(BaseModel):
    type: str = "selection_changed"
    node_ids: list[str]
    editor: EditorInfo


class NodeLockedMessage(BaseModel):
    type: str = "node_locked"
    node_id: str
    field: str
    editor: EditorInfo


class NodeUnlockedMessage(BaseModel):
    type: str = "node_unlocked"
    node_id: str
    field: str
    editor: EditorInfo


class LockStateMessage(BaseModel):
    type: str = "lock_state"
    locks: dict[str, dict[str, EditorInfo]]


# --- Live graph state messages ---


class GraphStateMessage(BaseModel):
    """Carries the authoritative server-side superset snapshot of the graph"""

    type: str = "graph_state"
    flow: dict  # superset snapshot
    restored_by: EditorInfo | None = None
    new_save_version: int | None = None
    version_name: str | None = None


class GraphFilesChangedMessage(BaseModel):
    """Broadcast whenever a graph's storage files list changes"""

    type: str = "graph_files_changed"
    graph_id: int | None
    editor: EditorInfo | None = None
