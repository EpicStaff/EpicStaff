import asyncio
import json

from app.core import settings
from app.db.opensearch_client import build_opensearch_client
from app.domains.base import IndexSpec
from app.domains.registry import DOMAINS
from loguru import logger
from opensearchpy import AsyncOpenSearch
from opensearchpy.exceptions import RequestError

_OPENSEARCH_WAIT_ATTEMPTS = 60
_OPENSEARCH_WAIT_DELAY_SECONDS = 5
_INDEX_ALREADY_EXISTS_ERROR = "resource_already_exists_exception"


async def wait_for_opensearch(client: AsyncOpenSearch) -> None:
    for attempt in range(1, _OPENSEARCH_WAIT_ATTEMPTS + 1):
        try:
            health = await client.cluster.health()
            if health.get("status") in ("green", "yellow"):
                logger.info(f"opensearch is {health['status']}, proceeding.")
                return
        except Exception as e:
            logger.info(f"Waiting for opensearch ({attempt}/{_OPENSEARCH_WAIT_ATTEMPTS}): {e}")
        await asyncio.sleep(_OPENSEARCH_WAIT_DELAY_SECONDS)

    raise RuntimeError(
        f"opensearch did not become healthy after "
        f"{_OPENSEARCH_WAIT_ATTEMPTS * _OPENSEARCH_WAIT_DELAY_SECONDS}s."
    )


async def ensure_index(client: AsyncOpenSearch, index: IndexSpec) -> None:
    """
    Creates `index` if it doesn't exist yet; safe to run on every boot.
    Replicas booting together can all pass the `exists` check before any of
    them creates the index, so losing that race (OpenSearch answers
    `resource_already_exists_exception`) is treated as success.

    Additive mapping changes on an existing index are out of scope here.
    """
    if await client.indices.exists(index=index.name):
        logger.info("Index {!r} already exists, skipping creation.", index.name)
        return

    mapping = json.loads(index.mapping_path.read_text())
    try:
        await client.indices.create(index=index.name, body=mapping)
    except RequestError as exc:
        if exc.error != _INDEX_ALREADY_EXISTS_ERROR:
            raise
        logger.info("Index {!r} was created concurrently by another replica.", index.name)
        return
    logger.info("Created index {!r}.", index.name)


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
