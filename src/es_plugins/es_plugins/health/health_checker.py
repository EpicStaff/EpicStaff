import asyncio

import httpx

HEALTH_PATH = "/_epicstaff/health"
HEALTH_TIMEOUT_SECONDS = 3.0


class HealthChecker:
    """Asks a plugin process `GET /_epicstaff/health` on the node's loopback.

    `epicstaff_plugin.serve` answers it without a gateway context, ahead of the plugin's own
    app; nginx refuses `/_epicstaff/` from outside, so only the node reaches it.

    Only the status line counts, and the body is never read: a plugin that answers with an
    endless or slow body costs the agent no memory. One deadline, `HEALTH_TIMEOUT_SECONDS`,
    covers the whole exchange, as the hook calls' does.
    """

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None):
        # No timeout of httpx's own: the deadline below covers connecting and the answer.
        self._client = httpx.AsyncClient(
            timeout=None,
            transport=transport,
            follow_redirects=False,
            trust_env=False,
        )

    async def is_healthy(self, port: int) -> bool:
        try:
            async with asyncio.timeout(HEALTH_TIMEOUT_SECONDS):
                async with self._client.stream(
                    "GET", f"http://127.0.0.1:{port}{HEALTH_PATH}"
                ) as response:
                    # Leaving the block closes the connection with the body unread.
                    return response.status_code == 200
        except (TimeoutError, httpx.HTTPError):
            return False

    async def aclose(self) -> None:
        await self._client.aclose()
