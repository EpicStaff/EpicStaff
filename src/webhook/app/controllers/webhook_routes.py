import hmac
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from foundation.cryptographer import CryptographerError
from loguru import logger

from app.core.settings import settings
from app.services.redis_service import (
    RedisService,
    WebhookDeliveryUnavailableError,
    get_redis_service,
)
from app.services.tunnel_config_listener import (
    TunnelConfigListener,
    get_tunnel_config_listener,
)
from app.services.tunnel_registry import (
    AmbiguousWebhookPathError,
    TunnelRegistry,
    UnavailableWebhookPathError,
    UnregisteredWebhookPathError,
    get_tunnel_registry,
)

router = APIRouter()

# Sent with every 503 a sender should retry; senders such as Telegram redeliver only after
# a non-2xx.
RETRY_AFTER_SECONDS = "30"


@router.post("/webhooks/{custom_path:path}", summary="Receives a generic webhook")
async def handle_webhook(
    request: Request,
    custom_path: str,
    payload: dict[str, Any],
    redis: RedisService = Depends(get_redis_service),
    registry: TunnelRegistry = Depends(get_tunnel_registry),
):
    if not registry.has_full_config_set():
        logger.warning(
            "Webhook PATH: {} | webhook configs not synced with Django yet.", custom_path
        )
        # Not 404: until the first sync the path may well exist, and senders treat a 404
        # as a wrong URL rather than retrying.
        raise HTTPException(
            status_code=503,
            detail="Webhook configs are not synced with Django yet",
            headers={"Retry-After": RETRY_AFTER_SECONDS},
        )

    try:
        config_id, config = await registry.resolve_by_path(custom_path)
    except UnregisteredWebhookPathError as e:
        logger.warning(str(e))
        raise HTTPException(
            status_code=404, detail=f"No webhook registered for path '{custom_path}'"
        ) from e
    except UnavailableWebhookPathError as e:
        logger.warning(str(e))
        # Not 404 for the same reason as before the first sync: the path exists in Django.
        raise HTTPException(
            status_code=503,
            detail="Webhook is temporarily unavailable",
            headers={"Retry-After": RETRY_AFTER_SECONDS},
        ) from e
    except AmbiguousWebhookPathError as e:
        logger.error(str(e))
        raise HTTPException(
            status_code=409,
            detail=(
                f"Path '{custom_path}' is registered by more than one tunnel "
                "config; refusing to route ambiguously."
            ),
        ) from e

    auth = config.auth
    if auth is None:
        logger.warning(
            f"Webhook PATH: {custom_path} | CONFIG ID: {config_id} | "
            "no auth configured for this path -- rejecting (fail-closed)."
        )
        raise HTTPException(status_code=401, detail="Webhook authentication failed")

    token = request.headers.get(auth.header_name)

    authenticated = False
    if token and auth.secret:
        try:
            # The secret arrives sealed for transport; an unopenable one fails closed.
            secret = request.app.state.cryptographer.decrypt(auth.secret)
        except CryptographerError:
            logger.warning(
                "Webhook PATH: {} | CONFIG ID: {} | AUTH: '{}' secret could not be decrypted.",
                custom_path,
                config_id,
                auth.kind,
            )
        else:
            authenticated = hmac.compare_digest(token.encode("utf-8"), secret.encode("utf-8"))
    if not authenticated:
        logger.warning(
            f"Webhook PATH: {custom_path} | CONFIG ID: {config_id} | "
            f"AUTH: '{auth.kind}' strategy rejected the request."
        )
        raise HTTPException(status_code=401, detail="Webhook authentication failed")
    logger.info(
        f"Webhook PATH: {custom_path} | CONFIG ID: {config_id} | "
        f"AUTH: '{auth.kind}' strategy matched."
    )

    try:
        await redis.publish_webhook(
            path=custom_path,
            payload=payload,
            config_id=config_id,
        )
    except WebhookDeliveryUnavailableError as e:
        logger.warning("Webhook PATH: {} | CONFIG ID: {} | {}", custom_path, config_id, str(e))
        # A 200 here would acknowledge an event nobody received: no listener was
        # subscribed, or Redis itself failed or timed out.
        raise HTTPException(
            status_code=503,
            detail="Webhook receiver is temporarily unavailable",
            headers={"Retry-After": RETRY_AFTER_SECONDS},
        ) from e

    if custom_path in settings.webhook_empty_json_paths_set:
        return {}

    return {"status": "success", "message": "Webhook received", "config_id": config_id}


@router.get("/")
async def index(listener: TunnelConfigListener = Depends(get_tunnel_config_listener)):
    """Health check route.

    Fails once the tunnel config listener has gone too long without applying a config set
    from Django over Redis: the registry then no longer follows Django, so rotated secrets
    and deleted webhooks keep working and new webhooks are unknown. Configs of an applied
    set that failed to register do not fail it: their paths answer 503 on their own, and
    one organization's broken config must not mark the whole service unhealthy.
    """
    if not listener.is_healthy():
        raise HTTPException(
            status_code=503,
            detail="No webhook config set from Django was applied over Redis for too long.",
        )
    return {"message": "Webhook service is running."}
