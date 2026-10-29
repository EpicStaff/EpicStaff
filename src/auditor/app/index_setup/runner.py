import asyncio

from app.core import settings
from app.db.opensearch_client import build_opensearch_client
from app.domains.base import IndexSpec
from app.domains.registry import DOMAINS
from app.index_setup.retention import ensure_index_template, ensure_ism_policies
from loguru import logger
from opensearchpy import AsyncOpenSearch
from opensearchpy.exceptions import NotFoundError

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
            logger.info(f"Waiting for opensearch ({attempt}/{_OPENSEARCH_WAIT_ATTEMPTS}): {e}")
        await asyncio.sleep(_OPENSEARCH_WAIT_DELAY_SECONDS)

    raise RuntimeError(
        f"opensearch did not become healthy after "
        f"{_OPENSEARCH_WAIT_ATTEMPTS * _OPENSEARCH_WAIT_DELAY_SECONDS}s."
    )


async def drop_legacy_index(client: AsyncOpenSearch, index: IndexSpec) -> None:
    """Delete the family's pre-tiering single index if it still exists; a no-op afterwards.

    Before tiered indices every event was written to one index named like the family
    (`index.name`). It carries no retention, so it is dropped rather than migrated. Only a
    concrete index of that name is deleted; an alias of that name is left alone, since
    deleting through it would hit whatever indices it points at.

    Another replica booting at the same time may delete the index at any point between
    these steps, so the index vanishing midway counts as success.
    """
    legacy_index = index.name
    try:
        if not await client.indices.exists(index=legacy_index):
            return
        resolved = await client.indices.get(index=legacy_index)
        if legacy_index not in resolved:
            logger.warning(
                "{!r} is an alias of {}, not the legacy audit index; leaving it in place.",
                legacy_index,
                sorted(resolved),
            )
            return

        doc_count = (await client.count(index=legacy_index))["count"]
        logger.warning(
            "Deleting legacy audit index {!r} with {} document(s): audit events now live in "
            "tiered monthly indices {!r}.",
            legacy_index,
            doc_count,
            index.read_pattern,
        )
        await client.indices.delete(index=legacy_index)
    except NotFoundError:
        logger.info("Legacy audit index {!r} was deleted by another replica.", legacy_index)


async def setup_indices(client: AsyncOpenSearch) -> None:
    """Prepare OpenSearch for audit writes, for every domain; safe to run on every boot.

    Policies go first: an ISM policy's `ism_template` attaches only to indices created
    after the policy exists, and the first write auto-creates its monthly index.
    """
    for domain in DOMAINS.values():
        await ensure_ism_policies(client, domain.index)
        await ensure_index_template(client, domain.index)
        await drop_legacy_index(client, domain.index)


async def main() -> None:
    client = build_opensearch_client(settings)
    try:
        await wait_for_opensearch(client)
        await setup_indices(client)
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
