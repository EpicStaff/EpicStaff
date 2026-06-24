__all__ = [
    "ERROR_MESSAGE_MAX_LENGTH",
    "format_error_message",
]

ERROR_MESSAGE_MAX_LENGTH = 2000


def _error_body_message(exc: BaseException) -> str | None:
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


def format_error_message(exc: BaseException) -> str:
    """The human-readable `message` from the exception's error body when available,
    else `"TypeName: text"`. Truncated to ERROR_MESSAGE_MAX_LENGTH (with ellipsis).

    Prefers the DBAPI exception (`exc.orig`) for DB errors: SQLAlchemy's own
    str() includes the SQL + bound params, leaking document content into logs.
    """
    base = getattr(exc, "orig", None) or exc
    raw = (
        _error_body_message(exc)
        or _error_body_message(base)
        or f"{type(exc).__name__}: {base}"
    )
    n = ERROR_MESSAGE_MAX_LENGTH
    return raw if len(raw) <= n else raw[: n - 1] + "…"
