from loguru import logger
from opensearchpy import AsyncOpenSearch

from app.core.settings import Settings


def build_opensearch_client(settings: Settings) -> AsyncOpenSearch:
    """
    Construct a new AsyncOpenSearch client from settings.

    Call this once, during app startup (lifespan) - not per-request, and not
    at import time. Ownership of the single instance for the app's lifetime
    belongs to app.state via the repository factory, not this function.
    """
    logger.info(
        f"Connecting to OpenSearch at {settings.OPENSEARCH_HOST}:{settings.OPENSEARCH_PORT}"
    )
    return AsyncOpenSearch(
        hosts=[{"host": settings.OPENSEARCH_HOST, "port": settings.OPENSEARCH_PORT}],
        http_auth=(settings.OPENSEARCH_USER, settings.OPENSEARCH_PASSWORD),
        use_ssl=True,
        verify_certs=False,
        ssl_show_warn=False,
    )
