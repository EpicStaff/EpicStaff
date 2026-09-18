from typing import Optional
from loguru import logger
from app.providers.tunnels.base import AbstractTunnelProvider


class LocalhostTunnel(AbstractTunnelProvider):
    def __init__(
        self,
        port: int,
        host: str = "localhost",
        domain: Optional[str] = None,
    ):
        super().__init__(port, domain=domain)
        self._host = host

    def _get_webhook_url(self):
        if self._domain:
            return f"http://{self._domain}"
        return f"http://{self._host}:{self._port}"

    async def connect(self):
        self._is_running = True
        self._public_url = self._get_webhook_url()
        logger.info(f"LocalhostTunnel active: {self._public_url}")
        if self._on_url_set:
            await self._on_url_set(self._public_url)

    async def disconnect(self):
        logger.info(f"LocalhostTunnel disconnected: {self._public_url}")
        self._is_running = False
        self._public_url = None
