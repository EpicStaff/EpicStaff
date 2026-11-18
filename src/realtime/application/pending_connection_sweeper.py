import asyncio

from infrastructure.persistence.connection_repository import ConnectionRepository
from loguru import logger

from application.agent_chat_end_client import AgentChatEndClient

PENDING_END_REASON = "timeout"


class PendingConnectionSweeper:
    """Reports chats whose connection key was dropped before a client ever attached.

    The repository only expires entries lazily, and an abandoned chat otherwise ends
    silently: Django would keep its temporary storage account alive until the account's
    own TTL. Each sweep purges expired entries, then ends every chat dropped since the
    last sweep (expired or evicted) as a zero-length `timeout`. Reporting is
    best-effort and never stops the sweep.
    """

    def __init__(
        self,
        connection_repository: ConnectionRepository,
        chat_end_client: AgentChatEndClient,
        interval_seconds: float,
    ):
        self._connection_repository = connection_repository
        self._chat_end_client = chat_end_client
        self._interval_seconds = interval_seconds

    async def sweep_once(self) -> None:
        self._connection_repository.purge_expired()
        dropped_keys = self._connection_repository.take_dropped_keys()
        if dropped_keys:
            logger.info("Reporting {} realtime chats that never connected", len(dropped_keys))
        # One at a time: the sweep is off every request path, and a burst of abandoned chats
        # must not turn into as many concurrent requests to Django. The end client logs and
        # swallows its own failures, so a key it could not report is left to the account's TTL.
        for key in dropped_keys:
            await self._chat_end_client.end_chat(key, duration=0, end_reason=PENDING_END_REASON)

    async def run(self) -> None:
        while True:
            await asyncio.sleep(self._interval_seconds)
            await self.sweep_once()
