from collections import OrderedDict
from typing import Optional
from src.shared.models import RealtimeAgentChatData
from utils.singleton_meta import SingletonMeta


class ConnectionRepository(metaclass=SingletonMeta):
    """Thread-safe in-memory storage for connection data."""

    def __init__(self, max_connections: int = 50):
        self._store = OrderedDict()  # Maintains insertion order
        self.max_connections = max_connections

    def save_connection(self, connection_key: str, data: RealtimeAgentChatData):
        """Save connection data, remove the oldest if over capacity."""
        if len(self._store) >= self.max_connections:
            self._store.popitem(last=False)  # Remove the oldest entry
        self._store[connection_key] = data

    def get_connection(self, connection_key: str) -> Optional[RealtimeAgentChatData]:
        """Retrieve connection data."""
        return self._store.get(connection_key)

    def delete_connection(self, connection_key: str):
        """Remove connection data."""
        self._store.pop(connection_key, None)

    def get_all_connections(self):
        """Retrieve all stored connections (for debugging)."""
        return list(self._store.values())
