import httpx

HEALTH_PATH = "/_epicstaff/health"
HEALTH_TIMEOUT_SECONDS = 3.0


class HealthChecker:
    """Asks a plugin process `GET /_epicstaff/health` on the node's loopback.

    `epicstaff_plugin.serve` answers it without a gateway context, ahead of the plugin's own
    app; nginx refuses `/_epicstaff/` from outside, so only the node reaches it.
    """

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None):
        self._client = httpx.AsyncClient(
            timeout=HEALTH_TIMEOUT_SECONDS,
            transport=transport,
            follow_redirects=False,
            trust_env=False,
        )

    async def is_healthy(self, port: int) -> bool:
        try:
            response = await self._client.get(f"http://127.0.0.1:{port}{HEALTH_PATH}")
        except httpx.HTTPError:
            return False
        return response.status_code == 200

    async def aclose(self) -> None:
        await self._client.aclose()
