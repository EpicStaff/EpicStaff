import requests
from loguru import logger

from core.config import settings


_api_key_validated = False


def validate_api_key() -> bool:
    global _api_key_validated
    if _api_key_validated:
        return True
    try:
        resp = requests.get(
            f"{settings.DJANGO_AUTH_URL}/api/auth/api-key/validate/",
            headers={"X-API-Key": settings.DJANGO_API_KEY},
            timeout=settings.DJANGO_AUTH_TIMEOUT,
        )
    except Exception:
        logger.warning("API key validation request failed")
        return False

    if resp.status_code != 200:
        logger.warning(f"API key validation failed with status {resp.status_code}")
        return False

    data = resp.json()
    if not data.get("active"):
        logger.warning("API key validation returned inactive")
        return False

    _api_key_validated = True
    return True


def introspect_token(token: str) -> dict | None:
    if not validate_api_key():
        return None
    try:
        resp = requests.post(
            f"{settings.DJANGO_AUTH_URL}/api/auth/introspect/",
            json={"token": token},
            headers={"X-API-Key": settings.DJANGO_API_KEY},
            timeout=settings.DJANGO_AUTH_TIMEOUT,
        )
    except Exception:
        logger.warning("Token introspection request failed")
        return None

    if resp.status_code != 200:
        logger.warning(f"Token introspection failed with status {resp.status_code}")
        return None

    data = resp.json()
    if not data.get("active"):
        logger.warning("Token introspection returned inactive")
        return None
    return data
