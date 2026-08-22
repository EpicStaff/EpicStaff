import pytest
import pytest_asyncio
import os

pytest_plugins = ["mcp_fixture"]

from loguru import logger

from utils.knowledge_utils import (
    get_embedder_model,
    get_or_create_embedder_config,
    create_source_collection,
    check_statuses_for_embedding_creation,
    knowledge_clean_up,
)
from services.redis_service import RedisService

# Constants
REDIS_HOST = os.getenv("REDIS_HOST", "127.0.0.1")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD")


# Fixture for embedder configuration
@pytest.fixture
def embedder_config_id():
    """Set up embedder model and config."""
    embedder_model_id = get_embedder_model(name="text-embedding-3-small")
    config_id = get_or_create_embedder_config(embedder_model_id=embedder_model_id)
    return config_id


# Fixture for source collection
@pytest.fixture
def collection_id(embedder_config_id):
    """Create a source collection for testing."""
    collection_id = create_source_collection(embedder_config_id=embedder_config_id)
    logger.info(f"Knowledge collection created ID: {collection_id}")

    check_statuses_for_embedding_creation(collection_id=collection_id, max_timeout=25)
    logger.success(f"Knowledge collection embedded ID: {collection_id}")

    # Return the collection ID for the test to use
    yield collection_id

    # Cleanup after the test
    try:
        knowledge_clean_up(collection_id)
        logger.info(f"Knowledge collection deleted ID: {collection_id}")

    except Exception as e:
        logger.warning(f"Warning: Cleanup failed: {e}")


@pytest_asyncio.fixture
async def redis_service():
    """Create and connect Redis service."""
    service = RedisService(host=REDIS_HOST, port=REDIS_PORT, password=REDIS_PASSWORD)
    await service.connect()
    yield service
    if service.aioredis_client:
        await service.aioredis_client.aclose()
