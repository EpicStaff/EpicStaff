import hashlib
import hmac
import os
import time
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Request
from loguru import logger
from passlib.hash import django_pbkdf2_sha256

from app.services.redis_service import RedisService, get_redis_service
from app.services.tunnel_registry import (
    TunnelRegistry,
    UnregisteredWebhookPathError,
    get_tunnel_registry,
)

router = APIRouter()


def verify_hmac_signature(
    payload: bytes, secret: str, signature: str, timestamp: str
) -> bool:
    """Compute HMAC-SHA256 over `f"{timestamp}.{payload}"` and compare securely.

    The timestamp must be folded into the signed message (not just checked
    for freshness separately) -- otherwise a signature computed over the raw
    body alone would validate for any timestamp, and would never match a
    caller that correctly signs `f"{timestamp}.{body}"` per the documented
    algorithm (mirrors `app.services.inbound_auth._compute_hmac_signature`).
    """
    message = f"{timestamp}.".encode("utf-8") + payload
    expected_hmac = hmac.new(
        key=secret.encode("utf-8"), msg=message, digestmod=hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected_hmac, signature)


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

    # Which single node's credential matched this request, e.g.
    # "tables.webhooktriggernode:17". `None` means "no auth configured
    # anywhere on this path" (today's backward-compat unrestricted fan-out).
    matched_principal: str | None = None

    if hasattr(config, "auths") and config.auths:
        request_authenticated = False
        raw_body = await request.body()

        for auth in config.auths:
            if not auth.enabled:
                continue

            try:
                if auth.scheme == "static_header":
                    token = request.headers.get(auth.header_name)
                    if (
                        token
                        and auth.secret_hash
                        and django_pbkdf2_sha256.verify(token, auth.secret_hash)
                    ):
                        request_authenticated = True
                        matched_principal = auth.principal
                        break

                elif auth.scheme == "hmac_sha256":
                    signature = request.headers.get(auth.header_name)
                    if not signature or not auth.timestamp_header_name:
                        continue

                    ts_str = request.headers.get(auth.timestamp_header_name)
                    if not ts_str:
                        continue
                    try:
                        ts = int(ts_str)
                        now = int(time.time())
                        if abs(now - ts) > auth.tolerance_seconds:
                            continue
                    except ValueError:
                        continue

                    if verify_hmac_signature(
                        raw_body, auth.signing_secret, signature, ts_str
                    ):
                        request_authenticated = True
                        matched_principal = auth.principal
                        break

            except Exception as e:
                logger.debug(f"Auth check failed for scheme {auth.scheme}: {e}")
                continue

        if not request_authenticated:
            raise HTTPException(status_code=401, detail="Webhook authentication failed")

    logger.info(f"Webhook PATH: {custom_path} | CONFIG ID: {config_id} | AUTH: Passed")

    await redis.publish_webhook(
        path=custom_path,
        payload=payload,
        config_id=config_id,
        auth_principal=matched_principal,
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
