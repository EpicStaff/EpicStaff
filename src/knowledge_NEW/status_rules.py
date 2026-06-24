__all__ = [
    "ERROR_MESSAGE_MAX_LENGTH",
    "format_error_message",
]

ERROR_MESSAGE_MAX_LENGTH = 2000


def _provider_error_message(exc: BaseException) -> str | None:
    """The human-readable `message` from a provider error body, if present.

    OpenAI-style APIError exposes `exc.body == {"message": ..., "code": ...}`;
    some providers nest it under `{"error": {"message": ...}}`.
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
    """The provider's human-readable `message` when available, else
    `"TypeName: text"`. Truncated to ERROR_MESSAGE_MAX_LENGTH (with ellipsis).

    Prefers the DBAPI exception (`exc.orig`) for DB errors: SQLAlchemy's own
    str() includes the SQL + bound params, leaking document content into logs.
    """
    base = getattr(exc, "orig", None) or exc
    raw = (
        _provider_error_message(exc)
        or _provider_error_message(base)
        or f"{type(exc).__name__}: {base}"
    )
    n = ERROR_MESSAGE_MAX_LENGTH
    return raw if len(raw) <= n else raw[: n - 1] + "…"
