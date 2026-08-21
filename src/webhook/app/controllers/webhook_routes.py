import hashlib
import hmac
import os
import time
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Request
from loguru import logger
from passlib.hash import django_pbkdf2_sha256
from starlette.concurrency import run_in_threadpool

from app.services.redis_service import RedisService, get_redis_service
from app.services.tunnel_registry import (
    AmbiguousWebhookPathError,
    TunnelRegistry,
    UnregisteredWebhookPathError,
    get_tunnel_registry,
)
from src.shared.models import UNAUTHENTICATED_FALLBACK_PRINCIPAL

router = APIRouter()

# Max seconds a caller's timestamp may sit in the future relative to our
# clock.
CLOCK_SKEW_ALLOWANCE_SECONDS = 5

# Redis key prefix for the replay-protection "seen signature" markers.
REPLAY_SEEN_KEY_PREFIX = "webhook:seen"


def verify_hmac_signature(
    payload: bytes, secret: str, signature: str, timestamp: str
) -> bool:
    """Compute HMAC-SHA256 over `f"{timestamp}.{payload}"` and compare securely.

    The timestamp must be folded into the signed message (not just checked
    for freshness separately) -- otherwise a signature computed over the raw
    body alone would validate for any timestamp, and would never match a
    caller that correctly signs `f"{timestamp}.{body}"` per the documented
    algorithm implemented here and in `WebhookTriggerService.ensure_webhook_
    auth` (Django side, which mints `signing_secret`).
    """
    message = f"{timestamp}.".encode("utf-8") + payload
    expected_hmac = hmac.new(
        key=secret.encode("utf-8"), msg=message, digestmod=hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected_hmac, signature)


async def _is_replay(
    redis: RedisService, principal: str, signature: str, tolerance_seconds: int
) -> bool:
    """Atomically marks `(principal, signature)` as seen and reports whether
    it was already seen before this call.
    """
    key = f"{REPLAY_SEEN_KEY_PREFIX}:{principal}:{signature}"
    first_time_seen = await redis.client.set(key, "1", nx=True, ex=tolerance_seconds)
    return not first_time_seen


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

    # Which single node's credential matched this request, e.g.
    # "tables.webhooktriggernode:17". `None` means "no auth configured
    # anywhere on this path" (today's backward-compat unrestricted fan-out).
    matched_principal: str | None = None
    matched_index: int | None = None

    # An empty list is a deliberate fail-open: no auth has been configured
    # for any node on this path, so every request is accepted
    # unauthenticated (today's backward-compatible behavior).
    total_auths = len(config.auths)
    if not config.auths:
        logger.warning(
            f"Webhook PATH: {custom_path} | CONFIG ID: {config_id} | "
            "no auth configured for any node on this path -- accepting request "
            "unauthenticated (fail-open passthrough)."
        )
    else:
        request_authenticated = False
        raw_body = await request.body()

        for idx, auth in enumerate(config.auths, start=1):
            if not auth.enabled:
                continue

            try:
                if auth.scheme == "static_header":
                    token = request.headers.get(auth.header_name)
                    if token and auth.secret_hash:
                        # PBKDF2 verify is CPU-bound (~0.3-1s at Django's
                        # default iteration count) -- run it off the event
                        # loop so one slow verify can't stall every other
                        # in-flight request on this uvicorn worker.
                        is_valid = await run_in_threadpool(
                            django_pbkdf2_sha256.verify, token, auth.secret_hash
                        )
                        if is_valid:
                            request_authenticated = True
                            matched_principal = auth.principal
                            matched_index = idx
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
                        # One-sided freshness check: reject timestamps too far
                        # in the future and reject timestamps
                        # older than `tolerance_seconds`.
                        if ts > now + CLOCK_SKEW_ALLOWANCE_SECONDS:
                            continue
                        if ts < now - auth.tolerance_seconds:
                            continue
                    except ValueError:
                        continue

                    if not verify_hmac_signature(
                        raw_body, auth.signing_secret, signature, ts_str
                    ):
                        continue

                    # Replay protection: a captured, still-fresh, valid
                    # signature must only be accepted once per tolerance
                    # window.
                    if await _is_replay(
                        redis, auth.principal, signature, auth.tolerance_seconds
                    ):
                        logger.warning(
                            f"Webhook PATH: {custom_path} | replay detected for "
                            f"principal '{auth.principal}' -- rejecting."
                        )
                        continue

                    request_authenticated = True
                    matched_principal = auth.principal
                    matched_index = idx
                    break

            except Exception as e:
                logger.warning(
                    f"Auth check raised for scheme '{auth.scheme}' "
                    f"principal '{getattr(auth, 'principal', '?')}': "
                    f"{type(e).__name__}"
                )
                continue

        if not request_authenticated:
            if config.has_unauthenticated_node:
                # At least one node attached to this path has no enabled
                # auth of its own (it just shares a path with an
                # authenticated node, e.g. Telegram). Forward the request
                # scoped to the reserved sentinel instead of 401ing the
                # whole path -- Django restricts dispatch to only the
                # auth-free node(s) for this principal (never Telegram).
                matched_principal = UNAUTHENTICATED_FALLBACK_PRINCIPAL
                logger.info(
                    f"Webhook PATH: {custom_path} | CONFIG ID: {config_id} | "
                    "AUTH: no credential matched, but path has an "
                    "unauthenticated-eligible node -- forwarding as "
                    f"'{UNAUTHENTICATED_FALLBACK_PRINCIPAL}'."
                )
            else:
                raise HTTPException(
                    status_code=401, detail="Webhook authentication failed"
                )

    if matched_index is not None:
        logger.info(
            f"Webhook PATH: {custom_path} | CONFIG ID: {config_id} | "
            f"AUTH: matched credential {matched_index}/{total_auths} "
            f"(principal={matched_principal})"
        )
    elif matched_principal is not None:
        # Already logged above (unauthenticated-fallback forwarding).
        pass
    else:
        logger.info(
            f"Webhook PATH: {custom_path} | CONFIG ID: {config_id} | "
            "AUTH: passthrough (no auth configured)"
        )

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
