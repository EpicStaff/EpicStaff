import json
import uuid
from fastapi import WebSocket
from loguru import logger

from infrastructure.persistence.presence_repository import PresenceRepository


class PresenceService:
    """Manages per-flow WebSocket presence.

    Maintains an in-process registry of live sockets for fan-out broadcast
    (single-worker deployment — no cross-worker pub/sub needed).

    Redis presence SET (``presence:flow:{flow_id}``) is the durable count
    store so that the count survives across service restarts and reflects
    exactly the connections registered in this process.
    """

    def __init__(self, repository: PresenceRepository) -> None:
        self._repository = repository
        # flow_id -> set of live WebSocket objects
        self._sockets: dict[int, set[WebSocket]] = {}

    async def join(self, flow_id: int, websocket: WebSocket) -> str:
        """Register a new connection for flow_id.

        Returns the opaque member_id (uuid4 hex) assigned to this connection.
        Broadcasts the updated count to all connections on the flow.
        """
        member_id = uuid.uuid4().hex

        # Redis write first: if it fails, the socket is never registered locally
        # so there is no local/Redis count mismatch.
        await self._repository.add_member(flow_id, member_id)

        if flow_id not in self._sockets:
            self._sockets[flow_id] = set()
        self._sockets[flow_id].add(websocket)

        await self._broadcast(flow_id)

        logger.info("presence JOIN flow={} member={}", flow_id, member_id)
        return member_id

    async def leave(self, flow_id: int, websocket: WebSocket, member_id: str) -> None:
        """Deregister a connection for flow_id.

        Broadcasts the decremented count to all remaining connections.
        Safe to call even if the socket was already removed.
        """
        flow_sockets = self._sockets.get(flow_id)
        if flow_sockets is not None:
            flow_sockets.discard(websocket)
            if not flow_sockets:
                del self._sockets[flow_id]

        await self._repository.remove_member(flow_id, member_id)
        await self._broadcast(flow_id)

        logger.info("presence LEAVE flow={} member={}", flow_id, member_id)

    async def _broadcast(self, flow_id: int) -> None:
        """SCARD the flow's Redis set and fan-out to all live sockets.

        Dead sockets are silently dropped from the registry.
        """
        count = await self._repository.count(flow_id)
        message = json.dumps({"type": "presence", "flow_id": flow_id, "count": count})

        flow_sockets = list(self._sockets.get(flow_id, set()))
        dead: list[WebSocket] = []

        for ws in flow_sockets:
            try:
                await ws.send_text(message)
            except Exception:
                # Socket is no longer alive; mark for removal, do not crash.
                logger.warning(
                    "presence broadcast: dead socket on flow={}, removing", flow_id
                )
                dead.append(ws)

        if dead:
            surviving = self._sockets.get(flow_id)
            if surviving is not None:
                for ws in dead:
                    surviving.discard(ws)
                if not surviving:
                    del self._sockets[flow_id]
