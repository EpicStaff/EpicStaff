import os
from typing import Any, Dict

from fastapi import APIRouter, Depends, Request
from loguru import logger

from app.services.redis_service import RedisService, get_redis_service
from app.services.tunnel_registry import get_tunnel_registry, TunnelRegistry

router = APIRouter()


@router.post("/webhooks/{custom_path:path}", summary="Receives a generic webhook")
async def handle_webhook(
    request: Request,
    custom_path: str,
    payload: Dict[str, Any],
    redis: RedisService = Depends(get_redis_service),
    registry: TunnelRegistry = Depends(get_tunnel_registry),
):
    forwarded_host = (
        request.headers.get("x-forwarded-host") or request.headers.get("host") or ""
    )

    config_id = await registry.get_unique_id_by_domain(forwarded_host)

    logger.info(
        f"Webhook PATH: {custom_path} | CONFIG ID: {config_id} | DOMAIN: {forwarded_host}"
    )

    await redis.publish_webhook(path=custom_path, payload=payload, config_id=config_id)

    empty_json_paths_raw = os.environ.get("WEBHOOK_EMPTY_JSON_PATHS", "")
    empty_json_paths = {p.strip() for p in empty_json_paths_raw.split(",") if p.strip()}
    if custom_path in empty_json_paths:
        return {}

    return {"status": "success", "message": "Webhook received", "config_id": config_id}


@router.get("/")
async def index():
    """Health check route."""
    return {"message": "Webhook service is running."}
