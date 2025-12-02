import asyncio
import uvicorn
import sys
from app.core.config import settings 
from fastapi import FastAPI
from app.main import create_app
from app.providers.base import AbstractTunnelProvider
from app.providers import get_provider, ProviderNotFoundException
from app.services.webhook_service import WebhookService 
from loguru import logger
from typing import Optional



async def main():
    
    tunnel_provider: Optional[AbstractTunnelProvider] = None
    
    if settings.USE_TUNNEL:
        logger.info(f"Tunnel enabled. Attempting to use provider: '{settings.WEBHOOK_TUNNEL}'")
        try:
            tunnel_provider = get_provider(
                provider_name=settings.WEBHOOK_TUNNEL,
                port=settings.WEBHOOK_PORT,
                auth_token=settings.WEBHOOK_AUTH
            )
        except ProviderNotFoundException as e:
            logger.error(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
        except ValueError as e:
            logger.error(f"Error: Configuration error for provider '{settings.WEBHOOK_TUNNEL}'. {e}", file=sys.stderr)
            sys.exit(1)


    webhook_service = WebhookService(port=settings.WEBHOOK_PORT, tunnel_provider=tunnel_provider)
    
    app = create_app(webhook_service)
    config = uvicorn.Config(app, host="0.0.0.0", port=settings.WEBHOOK_PORT)
    server = uvicorn.Server(config)
    
    asyncio.create_task(webhook_service.run())
    logger.info("Starting Uvicorn server... (Press Ctrl+C to quit)")
    await server.serve()
    
if __name__ == "__main__":
    asyncio.run(main())

