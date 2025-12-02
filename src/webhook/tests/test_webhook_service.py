import pytest
import asyncio
from unittest.mock import patch, AsyncMock, MagicMock
from app.services.webhook_service import WebhookService

@pytest.mark.asyncio
async def test_webhook_service_run_flow(mock_tunnel_provider):
    port = 8009
    service = WebhookService(port=port, tunnel_provider=mock_tunnel_provider)


    with patch("uvicorn.Server") as mock_server_cls:
        mock_server_instance = MagicMock()
        mock_server_instance.serve = AsyncMock(side_effect=lambda: asyncio.sleep(0.001))
        mock_server_cls.return_value = mock_server_instance
        
        run_task = asyncio.create_task(service.run())
        await asyncio.sleep(0.01)
        

        mock_tunnel_provider.connect.assert_called_once()
        
        run_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await run_task

        mock_tunnel_provider.disconnect.assert_called_once()

@pytest.mark.asyncio
async def test_webhook_service_local_mode():
    service = WebhookService(port=8009, tunnel_provider=None)
    
    run_task = asyncio.create_task(service.run())
    await asyncio.sleep(0.01)
    
    assert await service.get_tunnel_url() is None
    
    run_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await run_task