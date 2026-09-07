import pytest
from unittest.mock import patch, MagicMock, ANY
from app.providers.tunnels.ngrok_tunnel import NgrokTunnel
from app.core.settings import settings


@pytest.mark.asyncio
async def test_ngrok_connect_and_disconnect():
    token = "test-token"
    port = settings.WEBHOOK_PORT
    domain = "example.ngrok.app"

    with (
        patch("app.providers.tunnels.ngrok_tunnel.ngrok") as mock_ngrok,
        patch("app.providers.tunnels.ngrok_tunnel.pyngrok.process") as mock_process,
    ):
        mock_tunnel_obj = MagicMock()
        mock_tunnel_obj.public_url = "https://real-ngrok-url.com"
        mock_ngrok.connect.return_value = mock_tunnel_obj

        provider = NgrokTunnel(port=port, auth_token=token, domain=domain)

        await provider.connect()

        mock_ngrok.connect.assert_called_once_with(
            f"localhost:{port}", "http", domain=domain, pyngrok_config=ANY
        )
        assert provider.public_url == "https://real-ngrok-url.com"

        await provider.disconnect()

        mock_ngrok.disconnect.assert_called_once_with(
            "https://real-ngrok-url.com", pyngrok_config=ANY
        )
        mock_process.kill_process.assert_called()
        assert provider.public_url is None
