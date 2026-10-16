import base64
import binascii
import json
from datetime import UTC, datetime
from typing import Any

from app.domains.base import IndexSpec
from app.filtering.ast import FilterError
from app.repositories.base import AuditRepository, T
from loguru import logger
from opensearchpy import AsyncOpenSearch
from opensearchpy.helpers import async_bulk
from pydantic import ValidationError


def _encode_cursor(sort_values: list) -> str:
    return base64.urlsafe_b64encode(json.dumps(sort_values).encode()).decode()


def _decode_cursor(cursor: str) -> list:
    try:
        return json.loads(base64.urlsafe_b64decode(cursor.encode()))
    except (binascii.Error, ValueError, UnicodeDecodeError) as exc:
        raise FilterError("invalid or malformed cursor") from exc


class OpenSearchAuditRepository(AuditRepository[T]):
    """AuditRepository implementation backed by OpenSearch."""

    def __init__(self, client: AsyncOpenSearch, index: IndexSpec, model: type[T]):
        self._client = client
        self._index = index
        self._model = model

    async def write_batch(self, events: list[T]) -> list[dict] | None:
        if not events:
            return

        record_time = datetime.now(UTC)
        actions = (
            {
                "_op_type": "index",
                "_index": self._index.name,
                "_id": event.id,
                "_source": event.model_copy(update={"record_time": record_time}).model_dump(
                    mode="json"
                ),
            }
            for event in events
        )

        success_count, errors = await async_bulk(self._client, actions, raise_on_error=False)

        if errors:
            logger.warning(f"OpenSearch bulk write had {len(errors)} error(s): {errors}")
            return errors

        logger.info(
            f"OpenSearch bulk write: {success_count}/{len(events)} event(s) indexed "
            f"into {self._index.name}"
        )
        return

    async def query(
        self,
        query: dict[str, Any],
        cursor: str | None = None,
        size: int = 50,
    ) -> tuple[list[T], str | None]:
        """`query` is a fully-compiled OpenSearch query clause (see
        compiler.py) - org_id/retention_days/the AST are already baked in.
        The sort order always comes from the domain's IndexSpec.sort_keys."""
        return await self._execute(query, cursor=cursor, size=size)

    async def _execute(
        self, query: dict[str, Any], *, cursor: str | None, size: int
    ) -> tuple[list[T], str | None]:
        body: dict[str, Any] = {
            "query": query,
            "sort": [{field: direction} for field, direction in self._index.sort_keys],
            "size": size,
            # Pagination here is search_after/next_cursor-based, and no search
            # response surfaces a hit count - so there is no reason to pay for
            # an exact match count on every query.
            "track_total_hits": False,
        }
        if cursor:
            body["search_after"] = _decode_cursor(cursor)

        response = await self._client.search(index=self._index.name, body=body)
        hits = response["hits"]["hits"]
        logger.info(f"Audit query -> {len(hits)} hit(s)")

        events = []
        for hit in hits:
            try:
                events.append(self._model.model_validate(hit["_source"]))
            except ValidationError as exc:
                logger.warning(
                    "Skipping malformed {index} document id={doc_id!r}: {exc}",
                    index=self._index.name,
                    doc_id=hit.get("_id"),
                    exc=exc,
                )

        next_cursor = _encode_cursor(hits[-1]["sort"]) if hits and len(hits) == size else None

        return events, next_cursor

    async def close(self) -> None:
        await self._client.close()
