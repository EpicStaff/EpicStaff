import asyncio
import json
from pathlib import Path

from loguru import logger
from opensearchpy import AsyncOpenSearch

from app.core.settings import settings
from app.db.opensearch_client import build_opensearch_client
from app.repositories.opensearch_repository import SESSION_AUDIT_EVENTS_INDEX

MAPPING_PATH = Path(__file__).parent / "0001_create_audit_events_index.json"


_OPENSEARCH_WAIT_ATTEMPTS = 60
_OPENSEARCH_WAIT_DELAY_SECONDS = 5


async def wait_for_opensearch(client: AsyncOpenSearch) -> None:
    for attempt in range(1, _OPENSEARCH_WAIT_ATTEMPTS + 1):
        try:
            health = await client.cluster.health()
            if health.get("status") in ("green", "yellow"):
                logger.info(f"opensearch is {health['status']}, proceeding.")
                return
        except Exception as e:
            logger.info(
                f"Waiting for opensearch ({attempt}/{_OPENSEARCH_WAIT_ATTEMPTS}): {e}"
            )
        await asyncio.sleep(_OPENSEARCH_WAIT_DELAY_SECONDS)

    raise RuntimeError(
        f"opensearch did not become healthy after "
        f"{_OPENSEARCH_WAIT_ATTEMPTS * _OPENSEARCH_WAIT_DELAY_SECONDS}s."
    )


async def ensure_session_audit_index(client: AsyncOpenSearch) -> None:
    """
    Idempotent: creates the session-audit index if it doesn't exist yet.
    Safe to run on every boot - creating an already-existing index is a
    no-op, so no advisory-lock/race concern even with multiple replicas.
    """
    if await client.indices.exists(index=SESSION_AUDIT_EVENTS_INDEX):
        logger.info(
            f"Index '{SESSION_AUDIT_EVENTS_INDEX}' already exists, skipping creation."
        )
        return

    mapping = json.loads(MAPPING_PATH.read_text())
    await client.indices.create(index=SESSION_AUDIT_EVENTS_INDEX, body=mapping)
    logger.info(f"Created index '{SESSION_AUDIT_EVENTS_INDEX}'.")


async def main() -> None:
    client = build_opensearch_client(settings)
    try:
        await wait_for_opensearch(client)
        await ensure_session_audit_index(client)
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
