import pytest
from unittest.mock import patch, AsyncMock
from app.providers.ngrok_tunnel import NgrokTunnel

@pytest.mark.asyncio
async def test_ngrok_connect_and_disconnect():
    token = "test-token"
    port = 8000

    with patch("app.providers.ngrok_tunnel.ngrok") as mock_ngrok_lib:
        mock_tunnel_obj = AsyncMock()
        mock_tunnel_obj.public_url = "https://real-ngrok-url.com"
        mock_ngrok_lib.connect.return_value = mock_tunnel_obj

        provider = NgrokTunnel(port=port, auth_token=token)

        await provider.connect()

        mock_ngrok_lib.set_auth_token.assert_called_once_with(token)
        
        mock_ngrok_lib.connect.assert_called_once_with(port, "http") 
        
        assert provider.public_url == "https://real-ngrok-url.com"
        
        await provider.disconnect()
        mock_ngrok_lib.disconnect.assert_called()