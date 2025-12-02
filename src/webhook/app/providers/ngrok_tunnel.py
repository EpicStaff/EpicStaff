import asyncio
from pyngrok import ngrok
from app.providers.base import AbstractTunnelProvider
from typing import Optional

class NgrokTunnel(AbstractTunnelProvider):
    """
    The ngrok-specific implementation of abstract tunnel.
    """
    def __init__(self, port: int, auth_token: Optional[str] = None):
        """
        Initialize the ngrok tunnel.
        """
        super().__init__(port, auth_token)
        self._tunnel = None
        
        if not self._auth_token:
            raise ValueError("NgrokTunnel requires an auth_token.")
        
        ngrok.set_auth_token(self._auth_token)

    async def connect(self):
        print(f"Starting ngrok tunnel for localhost:{self._port}...")
        self._tunnel = await asyncio.to_thread(ngrok.connect, self._port, "http")
        self._public_url = self._tunnel.public_url

    async def disconnect(self):
        if self._tunnel:
            print("Closing ngrok tunnel...")
            await asyncio.to_thread(ngrok.disconnect, self._tunnel.public_url)
        self._public_url = None
