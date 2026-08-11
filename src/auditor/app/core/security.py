import secrets

from fastapi import HTTPException, Security
from fastapi.security import APIKeyHeader

from app.core.settings import settings

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_ingest_api_key(api_key: str | None = Security(_api_key_header)) -> None:
    """
    FastAPI dependency gating the ingest endpoint. Compares the presented
    X-API-Key against AUDITOR_INGEST_API_KEY using a constant-time
    comparison to avoid a timing side-channel on the check itself.
    """
    if api_key is None or not secrets.compare_digest(api_key, settings.AUDITOR_INGEST_API_KEY):
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
