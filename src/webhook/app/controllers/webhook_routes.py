import hmac
import os
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Request
from loguru import logger

from app.services.redis_service import RedisService, get_redis_service
from app.services.tunnel_registry import (
    AmbiguousWebhookPathError,
    TunnelRegistry,
    UnregisteredWebhookPathError,
    get_tunnel_registry,
)

router = APIRouter()


@router.post("/webhooks/{custom_path:path}", summary="Receives a generic webhook")
async def handle_webhook(
    request: Request,
    custom_path: str,
    payload: Dict[str, Any],
    redis: RedisService = Depends(get_redis_service),
    registry: TunnelRegistry = Depends(get_tunnel_registry),
):
    try:
        config_id, config = await registry.resolve_by_path(custom_path)
    except UnregisteredWebhookPathError as e:
        logger.warning(str(e))
        raise HTTPException(
            status_code=404, detail=f"No webhook registered for path '{custom_path}'"
        )
    except AmbiguousWebhookPathError as e:
        logger.error(str(e))
        raise HTTPException(
            status_code=409,
            detail=(
                f"Path '{custom_path}' is registered by more than one tunnel "
                "config; refusing to route ambiguously."
            ),
        )

    auth = config.auth
    if auth is None:
        logger.warning(
            f"Webhook PATH: {custom_path} | CONFIG ID: {config_id} | "
            "no auth configured for this path -- rejecting (fail-closed)."
        )
        raise HTTPException(status_code=401, detail="Webhook authentication failed")

    token = request.headers.get(auth.header_name)

    authenticated = (
        bool(token)
        and bool(auth.secret)
        and hmac.compare_digest(token.encode("utf-8"), auth.secret.encode("utf-8"))
    )
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

    await redis.publish_webhook(
        path=custom_path,
        payload=payload,
        config_id=config_id,
    )

    empty_json_paths_raw = os.environ.get("WEBHOOK_EMPTY_JSON_PATHS", "")
    empty_json_paths = {p.strip() for p in empty_json_paths_raw.split(",") if p.strip()}
    if custom_path in empty_json_paths:
        return {}

    return {"status": "success", "message": "Webhook received", "config_id": config_id}


@router.get("/")
async def index():
    """Health check route."""
    return {"message": "Webhook service is running."}
