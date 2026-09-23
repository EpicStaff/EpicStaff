import asyncio
import json

from loguru import logger
from opensearchpy import AsyncOpenSearch

from app.core import settings
from app.db.opensearch_client import build_opensearch_client
from app.domains.base import IndexSpec
from app.domains.registry import DOMAINS


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


async def ensure_index(client: AsyncOpenSearch, index: IndexSpec) -> None:
    """
    Idempotent: creates `index` if it doesn't exist yet. Safe to run on
    every boot - creating an already-existing index is a no-op, so no
    advisory-lock/race concern even with multiple replicas.

    Additive mapping changes (PUT new fields onto an existing index,
    hard-fail on type drift) are explicitly out of scope here - deferred to
    its own follow-up piece of work, not part of this idempotent
    create-if-absent behavior.
    """
    if await client.indices.exists(index=index.name):
        logger.info(f"Index '{index.name}' already exists, skipping creation.")
        return

    mapping = json.loads(index.mapping_path.read_text())
    await client.indices.create(index=index.name, body=mapping)
    logger.info(f"Created index '{index.name}'.")


async def main() -> None:
    client = build_opensearch_client(settings)
    try:
        await wait_for_opensearch(client)
        for domain in DOMAINS.values():
            await ensure_index(client, domain.index)
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
