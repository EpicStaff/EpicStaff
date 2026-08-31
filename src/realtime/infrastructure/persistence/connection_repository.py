import time
from collections import OrderedDict
from typing import Optional
from src.shared.models import RealtimeAgentChatData
from utils.singleton_meta import SingletonMeta

DEFAULT_CONNECTION_TTL_SECONDS = 300


class ConnectionRepository(metaclass=SingletonMeta):
    """Thread-safe in-memory storage for connection data.

    Entries expire after `ttl_seconds` (default 5 minutes) even if never
    consumed, and callers are expected to `delete_connection` once a
    connection_key has been used to attach a live session (single-use).
    """

    def __init__(
        self,
        max_connections: int = 50,
        ttl_seconds: int = DEFAULT_CONNECTION_TTL_SECONDS,
    ):
        self._store: OrderedDict[str, tuple[RealtimeAgentChatData, float]] = (
            OrderedDict()
        )  # Maintains insertion order
        self.max_connections = max_connections
        self.ttl_seconds = ttl_seconds

    def save_connection(self, connection_key: str, data: RealtimeAgentChatData):
        """Save connection data, remove the oldest if over capacity."""
        if len(self._store) >= self.max_connections:
            self._store.popitem(last=False)  # Remove the oldest entry
        expires_at = time.monotonic() + self.ttl_seconds
        self._store[connection_key] = (data, expires_at)

    def get_connection(self, connection_key: str) -> Optional[RealtimeAgentChatData]:
        """Retrieve connection data. Returns None (and evicts) if expired."""
        entry = self._store.get(connection_key)
        if entry is None:
            return None
        data, expires_at = entry
        if time.monotonic() >= expires_at:
            self._store.pop(connection_key, None)
            return None
        return data

    def delete_connection(self, connection_key: str):
        """Remove connection data."""
        self._store.pop(connection_key, None)

    def get_all_connections(self):
        """Retrieve all stored, non-expired connections (for debugging)."""
        now = time.monotonic()
        return [
            data for data, expires_at in self._store.values() if expires_at > now
        ]
