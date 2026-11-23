import asyncio
import json
from collections.abc import Mapping
from http import HTTPStatus

from fastapi import FastAPI, Request
from fastapi.concurrency import asynccontextmanager
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from foundation.cryptographer import FernetRotatedCryptographer
from foundation.schemas import (
    INTERNAL_ERROR_DETAIL,
    UNKNOWN_ERROR_CODE,
    ErrorDetailSchema,
    ErrorResponseSchema,
)
from loguru import logger
from src.shared.models import WebhookConfigData
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.controllers import webhook_routes
from app.core.settings import settings
from app.providers.tunnels.ngrok_working_directory import remove_stale_working_directories
from app.services.redis_service import (
    RedisService,
    close_redis_connection,
    get_redis_service,
)
from app.services.tunnel_registry import TunnelRegistry

# Kept short: Docker kills the container 10s after SIGTERM by default, and uvicorn drains
# connections before this budget (listener stop plus tunnel unregistering) starts.
TUNNEL_SHUTDOWN_TIMEOUT_SECONDS = 8

# The first `loc` entry of a request validation error names the part of the request the
# value came from, not a field, so it never belongs in `attr`.
_REQUEST_PARTS = frozenset({"body", "query", "path", "header", "cookie"})


def _error_response(
    status_code: int,
    errors: list[ErrorDetailSchema],
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=ErrorResponseSchema.for_status(status_code, errors).model_dump(mode="json"),
        headers=headers,
    )


def _validation_error_attr(error: dict) -> str | None:
    # An unparseable body reports the character offset where parsing stopped; that is
    # not a field of the request.
    if error["type"] == "json_invalid":
        return None
    location = error["loc"]
    if location and location[0] in _REQUEST_PARTS:
        location = location[1:]
    return ".".join(str(part) for part in location) or None


def register_exception_handlers(app: FastAPI) -> None:
    """Answer framework refusals and any unhandled error with foundation's error envelope."""

    @app.exception_handler(Exception)
    async def _server_error_handler(request: Request, exc: Exception) -> JSONResponse:
        # The fallback for any exception no more specific handler claims. Not logged here:
        # Starlette re-raises it after this answer, and the server logs it with its traceback.
        return _error_response(
            500, [ErrorDetailSchema(code=UNKNOWN_ERROR_CODE, detail=INTERNAL_ERROR_DETAIL)]
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_exception_handler(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        code = HTTPStatus(exc.status_code).phrase.lower().replace(" ", "_")
        return _error_response(
            exc.status_code,
            [ErrorDetailSchema(code=code, detail=exc.detail)],
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def _request_validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # Built from `type`, `msg` and `loc` only: `input` would echo the sender's value.
        return _error_response(
            422,
            [
                ErrorDetailSchema(
                    code=error["type"], detail=error["msg"], attr=_validation_error_attr(error)
                )
                for error in exc.errors()
            ],
        )


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
    tunnel_registry = TunnelRegistry(app.state.cryptographer, redis_service=redis_service)
    app.state.tunnel_registry = tunnel_registry

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

    register_exception_handlers(app)

    app.include_router(webhook_routes.router)

    return app
