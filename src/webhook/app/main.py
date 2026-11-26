import asyncio

from fastapi import FastAPI
from fastapi.concurrency import asynccontextmanager
from fastapi.middleware.cors import CORSMiddleware
from foundation.cryptographer import FernetRotatedCryptographer
from loguru import logger

from app.controllers import webhook_routes
from app.core.settings import settings
from app.providers.tunnels.ngrok_working_directory import remove_stale_working_directories
from app.services.redis_service import close_redis_connection, get_redis_service
from app.services.tunnel_config_listener import TunnelConfigListener
from app.services.tunnel_registry import TunnelRegistry

# Kept short: Docker kills the container 10s after SIGTERM by default, and uvicorn drains
# connections before this budget (listener stop plus tunnel unregistering) starts.
TUNNEL_SHUTDOWN_TIMEOUT_SECONDS = 8


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
    tunnel_registry = TunnelRegistry(app.state.cryptographer, redis_service=redis_service)
    app.state.tunnel_registry = tunnel_registry

    # The listener requests the initial config set itself, and again after every reconnect.
    tunnel_config_listener = TunnelConfigListener(redis_service, tunnel_registry)
    app.state.tunnel_config_listener = tunnel_config_listener
    redis_listener_task = asyncio.create_task(tunnel_config_listener.run())

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
    # The one cryptographer for transport-sealed secrets: the webhook route reads it from
    # here, and the startup hands it to the tunnel registry.
    app.state.cryptographer = FernetRotatedCryptographer(
        settings.SECRETS_TRANSPORT_KEY,
        settings.SECRETS_TRANSPORT_PREVIOUS_KEYS,
        hkdf_info=settings.SECRETS_TRANSPORT_HKDF_INFO.encode(),
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins_list,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(webhook_routes.router)

    return app
