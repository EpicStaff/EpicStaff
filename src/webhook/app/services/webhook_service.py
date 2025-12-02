import asyncio
from typing import Optional
from app.providers.base import AbstractTunnelProvider
from loguru import logger
import uvicorn


class WebhookService:
    """
    Orchestrates the web server and the tunnel provider.
    The tunnel provider is optional.
    """
    def __init__(self, port: int, tunnel_provider: Optional[AbstractTunnelProvider] = None):
        self.tunnel = tunnel_provider
        self.server: Optional[uvicorn.Server] = None
        self.port = port
    async def run(self):
        """Connect the tunnel (if provided), then start the server."""
        try:
            if self.tunnel:
                # A tunnel provider was given, so connect it.
                await self.tunnel.connect()                
                logger.info(f" ✅ Tunnel is LIVE: {self.tunnel.public_url}")
                logger.info(f" 🌐 Tunnel endpoint is: {self.tunnel.public_url}/webhooks/<path>")
            else:
                logger.info(" ✅ Running in LOCAL-ONLY mode (no tunnel).")
            logger.info(f" 🖥️  Local endpoint is: http://0.0.0.0:{self.port}/webhooks/<path>")
            while True:
                await asyncio.sleep(0.001) 
        except KeyboardInterrupt:
            logger.info("Shutting down...")
        except Exception as e:
            logger.error(f"An unexpected error occurred: {e}")
        finally:
            await self.shutdown()

    async def get_tunnel_url(self) -> str | None:
        if self.tunnel is None:
            return None
        return self.tunnel.public_url
    
    async def shutdown(self):
        """Cleanly shut down the server and the tunnel (if it exists)."""
        if self.server and self.server.started:
            logger.info("Stopping Uvicorn server...")
            self.server.should_exit = True
        
        if self.tunnel and self.tunnel.public_url:
            await self.tunnel.disconnect()
            
        logger.info("Service stopped.")