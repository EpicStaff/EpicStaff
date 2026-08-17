from datetime import datetime, timezone
import base64
import json
from typing import Any

from loguru import logger
from opensearchpy import AsyncOpenSearch
from opensearchpy.helpers import async_bulk

from app.repositories.base import SessionAuditRepository
from src.shared.models import SessionAuditEvent

SESSION_AUDIT_EVENTS_INDEX = "audit_events"


def _encode_cursor(sort_values: list) -> str:
    return base64.urlsafe_b64encode(json.dumps(sort_values).encode()).decode()


def _decode_cursor(cursor: str) -> list:
    return json.loads(base64.urlsafe_b64decode(cursor.encode()))


class OpenSearchSessionAuditRepository(SessionAuditRepository):
    """SessionAuditRepository implementation backed by OpenSearch."""

    def __init__(self, client: AsyncOpenSearch):
        self._client = client

    async def write_batch(self, events: list[SessionAuditEvent]) -> None:
        if not events:
            return

        record_time = datetime.now(timezone.utc)
        actions = (
            {
                "_op_type": "index",
                "_index": SESSION_AUDIT_EVENTS_INDEX,
                "_id": event.id,
                "_source": event.model_copy(
                    update={"record_time": record_time}
                ).model_dump(mode="json"),
            }
            for event in events
        )

        success_count, errors = await async_bulk(
            self._client, actions, raise_on_error=False
        )

        if errors:
            logger.warning(
                f"OpenSearch bulk write had {len(errors)} error(s): {errors}"
            )
        logger.info(
            f"OpenSearch bulk write: {success_count}/{len(events)} event(s) indexed "
            f"into {SESSION_AUDIT_EVENTS_INDEX}"
        )

    async def query(
        self,
        filters: dict[str, Any],
        cursor: str | None = None,
        size: int = 50,
    ) -> tuple[list[SessionAuditEvent], str | None]:
        """
        filters keys: org_id (required - always scoped to the caller's org),
        kind (optional), session_id (optional, for tree expansion),
        retention_days (optional, 0/absent = unlimited), search (optional
        free-text term over name/node_type/flow_name).
        """
        must: list[dict] = [{"term": {"org_id": filters["org_id"]}}]

        if filters.get("kind"):
            must.append({"term": {"kind": filters["kind"]}})
        if filters.get("session_id") is not None:
            must.append({"term": {"session_id": filters["session_id"]}})

        retention_days = filters.get("retention_days") or 0
        if retention_days > 0:
            must.append({"range": {"event_time": {"gte": f"now-{retention_days}d"}}})

        if filters.get("search"):
            term = filters["search"]
            must.append(
                {
                    "bool": {
                        "should": [
                            {
                                "wildcard": {
                                    field: {
                                        "value": f"*{term}*",
                                        "case_insensitive": True,
                                    }
                                }
                            }
                            for field in ("name", "node_type", "flow_name")
                        ]
                        + [
                            {
                                "query_string": {
                                    "query": term,
                                    "fields": ["input.*", "output.*", "details.*"],
                                    "default_operator": "AND",
                                    "lenient": True,
                                }
                            }
                        ],
                        "minimum_should_match": 1,
                    }
                }
            )

        return await self._execute({"bool": {"must": must}}, cursor=cursor, size=size)

    async def query_ast(
        self,
        query: dict[str, Any],
        cursor: str | None = None,
        size: int = 50,
    ) -> tuple[list[SessionAuditEvent], str | None]:
        """`query` is a fully-compiled OpenSearch query clause (see
        opensearch_query_compiler.py) - org_id/retention_days/the AST are
        already baked in. Shares _execute() with `query()` so the fixed sort
        order (event_time desc, id desc) stays enforced in exactly one place."""
        return await self._execute(query, cursor=cursor, size=size)

    async def _execute(
        self, query: dict[str, Any], *, cursor: str | None, size: int
    ) -> tuple[list[SessionAuditEvent], str | None]:
        body: dict[str, Any] = {
            "query": query,
            "sort": [{"event_time": "desc"}, {"id": "desc"}],
            "size": size,
        }
        if cursor:
            body["search_after"] = _decode_cursor(cursor)

        response = await self._client.search(
            index=SESSION_AUDIT_EVENTS_INDEX, body=body
        )
        hits = response["hits"]["hits"]
        logger.info(f"Audit query -> {len(hits)} hit(s)")

        events = [SessionAuditEvent.model_validate(hit["_source"]) for hit in hits]
        next_cursor = _encode_cursor(hits[-1]["sort"]) if len(hits) == size else None

        return events, next_cursor

    async def close(self) -> None:
        await self._client.close()
