import hashlib
import json
from datetime import UTC, datetime

from enums import DocumentErrorCode

__all__ = [
    "ERROR_MESSAGE_MAX_LENGTH",
    "format_error_message",
    "hash_dict",
    "http_status",
    "error_details",
    "utcnow",
]

ERROR_MESSAGE_MAX_LENGTH = 2000


def utcnow() -> datetime:
    return datetime.now(UTC)


def hash_dict(dictionary: dict) -> str:
    return hashlib.sha256(json.dumps(dictionary, sort_keys=True).encode()).hexdigest()


def extract_provider_message(exc: BaseException) -> str | None:
    """The human-readable `message` carried in an exception's error body, if present.

    Some clients attach a structured `body` to the exception — e.g. OpenAI-style
    APIError with `exc.body == {"message": ..., "code": ...}`; some nest it under
    `{"error": {"message": ...}}`.
    """
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        msg = body.get("message")
        if not msg and isinstance(body.get("error"), dict):
            msg = body["error"].get("message")
        if msg:
            return str(msg)
    return None


def http_status(exc: BaseException) -> int | None:
    """The HTTP status code carried by a provider exception, if any.

    Different SDKs expose it under different attributes, so several are tried.
    `bool` is skipped: it is an `int` subclass but never a real status code.
    """
    for attr in ("status_code", "http_status", "status", "code"):
        value = getattr(exc, attr, None)
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            return value
    return None


def format_error_message(exc: BaseException) -> str:
    """The human-readable `message` from the exception's error body when available,
    else `"TypeName: text"`. Truncated to ERROR_MESSAGE_MAX_LENGTH (with ellipsis).

    Prefers the DBAPI exception (`exc.orig`) for DB errors: SQLAlchemy's own
    str() includes the SQL + bound params, leaking document content into logs.
    """
    base = getattr(exc, "orig", None) or exc
    raw = (
        extract_provider_message(exc)
        or extract_provider_message(base)
        or f"{type(exc).__name__}: {base}"
    )
    n = ERROR_MESSAGE_MAX_LENGTH
    return raw if len(raw) <= n else raw[: n - 1] + "…"


def error_details(exc: BaseException) -> tuple[DocumentErrorCode, str]:
    """The `(error_code, error_message)` to persist for a failed operation.

    Domain errors carry their own `error_code`; any other exception is treated
    as `UNKNOWN`. Replaces the old exception-type classifier: the code is read
    straight off the error instead of being guessed after the fact.
    """
    error_code = getattr(exc, "error_code", DocumentErrorCode.UNKNOWN)
    return error_code, format_error_message(exc)
