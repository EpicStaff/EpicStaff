import asyncio
import json
from pathlib import Path

from loguru import logger
from opensearchpy import AsyncOpenSearch

from app.core.settings import settings
from app.db.opensearch_client import build_opensearch_client
from app.repositories.opensearch_repository import SESSION_AUDIT_EVENTS_INDEX

MAPPING_PATH = Path(__file__).parent / "0001_create_audit_events_index.json"


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
        await ensure_session_audit_index(client)
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
