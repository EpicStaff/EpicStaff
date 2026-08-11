from datetime import datetime, timezone
from typing import Any

from loguru import logger
from opensearchpy import AsyncOpenSearch
from opensearchpy.helpers import async_bulk

from app.repositories.base import SessionAuditRepository
from src.shared.models import SessionAuditEvent

SESSION_AUDIT_EVENTS_INDEX = "audit_events"


class OpenSearchSessionAuditRepository(SessionAuditRepository):
    """SessionAuditRepository implementation backed by OpenSearch."""

    def __init__(self, client: AsyncOpenSearch):
        self._client = client

    async def write_batch(self, events: list[SessionAuditEvent]) -> None:
        if not events:
            return

        record_time = datetime.now(timezone.utc).isoformat()

        actions = (
            {
                "_op_type": "index",
                "_index": SESSION_AUDIT_EVENTS_INDEX,
                "_id": event.id,
                "_source": {
                    **event.model_dump(mode="json"),
                    "record_time": record_time,
                },
            }
            for event in events
        )

        _, errors = await async_bulk(self._client, actions, raise_on_error=False)

        if errors:
            logger.warning(f"OpenSearch bulk write had {len(errors)} error(s): {errors}")

    async def query(
        self,
        filters: dict[str, Any],
        cursor: str | None = None,
        size: int = 50,
    ) -> tuple[list[SessionAuditEvent], str | None]:
        raise NotImplementedError("Query routes land in a later step (plan §9).")

    async def close(self) -> None:
        await self._client.close()
