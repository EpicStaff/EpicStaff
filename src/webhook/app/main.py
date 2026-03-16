import asyncio
import json

from fastapi import Depends, FastAPI
from fastapi.concurrency import asynccontextmanager
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from app.controllers import webhook_routes
from app.core.settings import settings
from src.shared.models import WebhookConfigData
from app.services.redis_service import (
    RedisService,
    close_redis_connection,
    get_redis_service,
)
from app.services.tunnel_registry import TunnelRegistry, get_tunnel_registry


async def listen_redis(redis_service: RedisService, tunnel_registry: TunnelRegistry):
    logger.info(
        f"Subscribed to channel '{settings.REDIS_TUNNEL_CONFIG_CHANNEL}' for registering webhook tunnels."
    )

    pubsub = await redis_service.async_subscribe(settings.REDIS_TUNNEL_CONFIG_CHANNEL)

    try:
        async for message in pubsub.listen():
            if message["type"] == "message":
                try:
                    logger.debug("Received webhook message")
                    data = json.loads(message["data"])
                    webhook_config_data = WebhookConfigData(**data)

                    await tunnel_registry.register_many(
                        webhook_config_data=webhook_config_data
                    )
                except Exception as e:
                    logger.error(f"Error processing message: {e}")
    except asyncio.CancelledError:
        logger.info("Redis listener task was cancelled.")
        raise


@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- STARTUP ---
    logger.info("Application starting up...")

    redis_service = await get_redis_service()
    tunnel_registry = get_tunnel_registry(redis_service=redis_service)

    redis_listener_task = asyncio.create_task(
        listen_redis(redis_service, tunnel_registry)
    )

    while True:
        n_received = await redis_service.client.publish(
            settings.REQUEST_WEBHOOK_UPDATE_CHANNEL, ""
        )
        if n_received >= 1:
            break
        logger.warning("No Django instance detected, retrying in 5 seconds...")
        await asyncio.sleep(5)

    yield

    logger.info("Application shutting down...")

    redis_listener_task.cancel()
    try:
        await redis_listener_task
    except asyncio.CancelledError:
        pass

    await close_redis_connection()
    logger.info("Cleanup complete.")


def create_app() -> FastAPI:
    """
    Factory function to create and configure the FastAPI app.
    """
    app = FastAPI(title="WebhookService", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(webhook_routes.router)

    @app.get("/api/tunnel-url/{unique_id}")
    async def get_tunnel_url(
        unique_id: str,
        tunnel_registry: TunnelRegistry = Depends(get_tunnel_registry),
    ):
        tunnel = await tunnel_registry.get_tunnel(unique_id=unique_id)
        if tunnel is None:
            return {"status": "fail", "description": "Tunnel was not found"}

        tunnel_url = tunnel.public_url
        if tunnel_url is not None:
            return {
                "status": "success",
                "tunnel_url": tunnel_url,
            }

        return {"status": "fail", "description": "Tunnel URL not available"}

    return app
