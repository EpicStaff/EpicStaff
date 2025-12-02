import pytest
import json
from unittest.mock import patch, AsyncMock
from app.services.redis_service import RedisService
from app.request_models import WebhookEventData

@pytest.mark.asyncio
async def test_redis_publish_message():

    with patch("app.services.redis_service.aioredis.from_url") as mock_from_url:
        mock_redis_client = AsyncMock()
        mock_from_url.return_value = mock_redis_client
        
        service = RedisService(host="localhost", port=6379, webhook_channel="test_channel")
        
        test_path = "test-hook"
        test_payload = {"id": 123}
        
        await service.publish_webhook(test_path, test_payload)
        
        mock_redis_client.publish.assert_called_once()
        
        args = mock_redis_client.publish.call_args[0]
        channel = args[0]
        message_json = args[1]
        
        assert channel == "test_channel"
        
        message_data = json.loads(message_json)
        assert message_data["path"] == test_path
        assert message_data["payload"] == test_payload

@pytest.mark.asyncio
async def test_redis_close():
    with patch("app.services.redis_service.aioredis.from_url") as mock_from_url:
        mock_redis_client = AsyncMock()
        mock_from_url.return_value = mock_redis_client
        
        service = RedisService(host="localhost", port=6379, webhook_channel="test")
        
        await service.close()
        mock_redis_client.close.assert_called_once()