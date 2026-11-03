import time
from collections import OrderedDict

from loguru import logger
from src.shared.models import RealtimeAgentChatData
from utils.singleton_meta import SingletonMeta

DEFAULT_CONNECTION_TTL_SECONDS = 300
DEFAULT_MAX_CONNECTIONS_PER_ORG = 50
# A memory guard only: the per-organization cap is what normally bounds the store.
DEFAULT_MAX_CONNECTIONS = 2000


class ConnectionRepository(metaclass=SingletonMeta):
    """In-memory store of pending session snapshots, keyed by single-use connection_key.

    Entries expire after `ttl_seconds` even if never consumed, and callers are
    expected to `delete_connection` once a connection_key has been used to attach a
    live session.

    Capacity is enforced per organization, so one organization opening sessions in
    a burst evicts only its own oldest pending entry, never another organization's.
    `max_connections` is a global hard cap behind it, reached only when many
    organizations together fill the store. Expired entries are purged before
    anything live is evicted.

    Used from a single event loop; it does no locking.
    """

    def __init__(
        self,
        max_connections_per_org: int = DEFAULT_MAX_CONNECTIONS_PER_ORG,
        max_connections: int = DEFAULT_MAX_CONNECTIONS,
        ttl_seconds: int = DEFAULT_CONNECTION_TTL_SECONDS,
    ):
        # Oldest first. Every save moves its key to the end and all entries share one
        # TTL, so this is also expiry order: expired entries are always at the front.
        # Each entry keeps the org_id it was counted under at save time, so removal
        # never depends on the payload, which callers can still mutate.
        self._store: OrderedDict[str, tuple[RealtimeAgentChatData, float, int]] = OrderedDict()
        # Same order, per organization; the values are unused.
        self._keys_by_org: dict[int, OrderedDict[str, None]] = {}
        self.max_connections_per_org = max_connections_per_org
        self.max_connections = max_connections
        self.ttl_seconds = ttl_seconds

    def save_connection(self, connection_key: str, data: RealtimeAgentChatData):
        """Save connection data, making room in its organization's share first."""
        self._remove(connection_key)
        self._purge_expired()

        org_id = data.org_id
        org_keys = self._keys_by_org.get(org_id)
        if org_keys is not None and len(org_keys) >= self.max_connections_per_org:
            logger.warning(
                "Pending realtime sessions of org {} at capacity ({}), evicting its oldest",
                org_id,
                self.max_connections_per_org,
            )
            self._remove(next(iter(org_keys)))

        if len(self._store) >= self.max_connections:
            logger.warning(
                "Pending realtime sessions at the global capacity ({}), evicting the oldest",
                self.max_connections,
            )
            self._remove(next(iter(self._store)))

        self._store[connection_key] = (data, time.monotonic() + self.ttl_seconds, org_id)
        self._keys_by_org.setdefault(org_id, OrderedDict())[connection_key] = None

    def get_connection(self, connection_key: str) -> RealtimeAgentChatData | None:
        """Retrieve connection data. Returns None (and evicts) if expired."""
        entry = self._store.get(connection_key)
        if entry is None:
            return None
        data, expires_at, _ = entry
        if time.monotonic() >= expires_at:
            self._remove(connection_key)
            return None
        return data

    def delete_connection(self, connection_key: str):
        """Remove connection data."""
        self._remove(connection_key)

    def get_all_connections(self):
        """Retrieve all stored, non-expired connections (for debugging)."""
        now = time.monotonic()
        return [data for data, expires_at, _ in self._store.values() if expires_at > now]

    def _purge_expired(self) -> None:
        now = time.monotonic()
        while self._store:
            oldest_key, (_, expires_at, _) = next(iter(self._store.items()))
            if expires_at > now:
                return
            self._remove(oldest_key)

    def _remove(self, connection_key: str) -> None:
        entry = self._store.pop(connection_key, None)
        if entry is None:
            return
        _, _, org_id = entry
        org_keys = self._keys_by_org[org_id]
        del org_keys[connection_key]
        if not org_keys:
            del self._keys_by_org[org_id]
