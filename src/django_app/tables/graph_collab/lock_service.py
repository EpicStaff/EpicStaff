"""
Per-graph authoritative node-field lock registry.

Keeps all active field locks in memory.  This is intentionally single-worker
only — no cross-process synchronisation — matching the same assumption used
by GraphPresenceService and GraphLiveStateService.

Structure: {graph_id: {node_id: {field: LockEntry}}}
"""

from dataclasses import dataclass

from tables.graph_collab.protocol import EditorInfo


@dataclass
class LockEntry:
    editor: EditorInfo
    channel: str


class NodeLockService:
    """In-memory authoritative registry of per-node-field edit locks."""

    def __init__(self) -> None:
        # graph_id -> {node_id -> {field -> LockEntry}}
        self._store: dict[int, dict[str, dict[str, LockEntry]]] = {}

    def try_lock(
        self,
        graph_id: int,
        node_id: str,
        field: str,
        editor: EditorInfo,
        channel: str,
    ) -> bool:
        """Attempt to acquire (or refresh) a lock on *(node_id, field)* for *channel*.

        Returns True when the lock is granted or already held by the same
        channel (re-lock by the same owner is allowed and updates the stored
        editor).  Returns False when a different channel already holds the
        *(node_id, field)* pair.
        """
        graph_locks = self._store.setdefault(graph_id, {})
        field_locks = graph_locks.setdefault(node_id, {})
        existing = field_locks.get(field)
        if existing is not None and existing.channel != channel:
            return False
        field_locks[field] = LockEntry(editor=editor, channel=channel)
        return True

    def get_holder(self, graph_id: int, node_id: str, field: str) -> LockEntry | None:
        """Return the current lock holder for *(node_id, field)*, or None if unheld."""
        return self._store.get(graph_id, {}).get(node_id, {}).get(field)

    def get_all_locks(self, graph_id: int) -> dict[str, dict[str, LockEntry]]:
        """Return a shallow copy of all locks for *graph_id* as {node_id: {field: LockEntry}}."""
        return {
            node_id: dict(fields)
            for node_id, fields in self._store.get(graph_id, {}).items()
        }

    def release(self, graph_id: int, node_id: str, field: str, channel: str) -> bool:
        """Release the lock on *(node_id, field)* if *channel* is the current holder.

        Returns True if a lock was released, False otherwise (not held or
        held by a different channel).  Cleans up empty dicts.
        """
        graph_locks = self._store.get(graph_id)
        if not graph_locks:
            return False
        field_locks = graph_locks.get(node_id)
        if not field_locks:
            return False
        existing = field_locks.get(field)
        if existing is None or existing.channel != channel:
            return False
        del field_locks[field]
        if not field_locks:
            del graph_locks[node_id]
        if not graph_locks:
            del self._store[graph_id]
        return True

    def release_all_for_channel(
        self, graph_id: int, channel: str
    ) -> list[tuple[str, str]]:
        """Release every *(node_id, field)* lock held by *channel* for *graph_id*.

        Returns the list of *(node_id, field)* tuples that were released so the
        caller can broadcast NodeUnlockedMessage for each.  Cleans up empty dicts
        at both field and node_id levels.
        """
        graph_locks = self._store.get(graph_id)
        if not graph_locks:
            return []
        released: list[tuple[str, str]] = []
        for node_id, field_locks in list(graph_locks.items()):
            for field, entry in list(field_locks.items()):
                if entry.channel == channel:
                    released.append((node_id, field))
                    del field_locks[field]
            if not field_locks:
                del graph_locks[node_id]
        if not graph_locks:
            del self._store[graph_id]
        return released

    def release_all(self, graph_id: int) -> list[tuple[str, str]]:
        """Drop every lock for *graph_id*, regardless of holder"""
        entries = self._store.pop(graph_id, None) or {}
        return [
            (node_id, field)
            for node_id, field_locks in entries.items()
            for field in field_locks
        ]


lock_service = NodeLockService()
