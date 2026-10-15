import asyncio
import json

from fastapi import FastAPI
from fastapi.concurrency import asynccontextmanager
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger
from src.shared.models import WebhookConfigData

from app.controllers import webhook_routes
from app.core.settings import settings
from app.providers.tunnels.ngrok_working_directory import remove_stale_working_directories
from app.services.redis_service import (
    RedisService,
    close_redis_connection,
    get_redis_service,
)
from app.services.tunnel_registry import TunnelRegistry, get_tunnel_registry

# Kept short: Docker kills the container 10s after SIGTERM by default, and uvicorn drains
# connections before this budget (listener stop plus tunnel unregistering) starts.
TUNNEL_SHUTDOWN_TIMEOUT_SECONDS = 8


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

                    await tunnel_registry.register_many(webhook_config_data=webhook_config_data)
                except Exception as e:
                    logger.error(f"Error processing message: {e}")
    except asyncio.CancelledError:
        logger.info("Redis listener task was cancelled.")
        raise


@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- STARTUP ---
    logger.info("Application starting up...")

    # Before the Redis listener starts, so no tunnel of this run exists yet. Best effort:
    # leftover directories must not keep the service from starting.
    try:
        await asyncio.to_thread(remove_stale_working_directories)
    except Exception:
        logger.exception("Sweeping stale ngrok working directories failed; continuing startup.")

    redis_service = await get_redis_service()
    tunnel_registry = get_tunnel_registry(redis_service=redis_service)

    redis_listener_task = asyncio.create_task(listen_redis(redis_service, tunnel_registry))

    while True:
        n_received = await redis_service.client.publish(settings.REQUEST_WEBHOOK_UPDATE_CHANNEL, "")
        if n_received >= 1:
            break
        logger.warning("No Django instance detected, retrying in 5 seconds...")
        await asyncio.sleep(5)

    yield

    logger.info("Application shutting down...")

    # One deadline covers stopping the listener and unregistering the tunnels: a register()
    # the listener was in the middle of disconnects its new tunnel before it stops, which
    # can take as long as a tunnel disconnect. The listener stops first so it starts no
    # new registrations; all of this runs before Redis closes, because unregistering
    # deletes each tunnel URL from Redis.
    try:
        async with asyncio.timeout(TUNNEL_SHUTDOWN_TIMEOUT_SECONDS):
            redis_listener_task.cancel()
            # wait() rather than awaiting the task: the task's own CancelledError must not
            # be mistaken for this deadline or for an external cancellation.
            await asyncio.wait([redis_listener_task])
            await tunnel_registry.unregister_all()
    except TimeoutError:
        logger.warning(
            "Listener and tunnels still stopping after {}s; continuing shutdown.",
            TUNNEL_SHUTDOWN_TIMEOUT_SECONDS,
        )

    await close_redis_connection()
    logger.info("Cleanup complete.")


def create_app() -> FastAPI:
    """
    Factory function to create and configure the FastAPI app.
    """
    app = FastAPI(title="WebhookService", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins_list,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(webhook_routes.router)

    return app
