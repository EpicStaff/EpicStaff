import secrets

from fastapi import Header, HTTPException, status
from loguru import logger

from app.core.settings import settings


async def verify_webhook_auth(x_webhook_auth: str | None = Header(default=None)) -> None:
    # Both failure modes below return the exact same 401 response, so an
    # unauthenticated caller can't distinguish "WEBHOOK_AUTH unconfigured"
    # from "wrong secret" and use that to fingerprint the deployment.
    if not settings.WEBHOOK_AUTH:
        logger.error("WEBHOOK_AUTH is not configured; rejecting tunnel-url request")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")

    if not x_webhook_auth or not secrets.compare_digest(x_webhook_auth, settings.WEBHOOK_AUTH):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
