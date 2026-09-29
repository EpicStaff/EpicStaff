from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Generator

import pytest
import fakeredis
from unittest.mock import patch
from services.redis_service import RedisService


fakeredis_client = fakeredis.FakeStrictRedis


@pytest.fixture
def fake_redis_service() -> Generator[RedisService, None, None]:
    with patch("services.redis_service.Redis", fakeredis_client):
        service = RedisService(
            host="127.0.0.1", port=6379, user="default", password="redis_password"
        )
        yield service
