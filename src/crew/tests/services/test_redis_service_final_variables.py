import json

import fakeredis
import pytest

from services.redis_service import RedisService
from src.shared.redis_keys import SESSION_FINAL_VARIABLES_TTL_SECONDS
from utils.singleton_meta import SingletonMeta


@pytest.fixture
def redis_service_with_fake_redis():
    SingletonMeta._instances.pop(RedisService, None)
    fake_redis = fakeredis.FakeAsyncRedis(decode_responses=True)
    redis_service = RedisService(
        host="127.0.0.1", port=6379, user="default", password="redis_password"
    )
    redis_service.aioredis_client = fake_redis
    yield redis_service, fake_redis
    SingletonMeta._instances.pop(RedisService, None)


@pytest.mark.asyncio
async def test_final_variables_are_stored_as_json_under_the_shared_key_with_ttl(
    redis_service_with_fake_redis,
):
    redis_service, fake_redis = redis_service_with_fake_redis
    variables = {"final_result": "done", "nested": {"items": [1, 2]}}

    await redis_service.aset_session_final_variables(session_id=7, variables=variables)

    # The literal key is the cross-service contract django_app reads.
    assert json.loads(await fake_redis.get("session:7:final_variables")) == variables
    ttl = await fake_redis.ttl("session:7:final_variables")
    assert 0 < ttl <= SESSION_FINAL_VARIABLES_TTL_SECONDS
    assert SESSION_FINAL_VARIABLES_TTL_SECONDS == 900
