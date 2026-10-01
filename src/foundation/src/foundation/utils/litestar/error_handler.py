"""Map exception types to Litestar responses via ``@registry``."""

from collections.abc import Callable

from litestar import Request, Response

__all__ = ["create_response", "get_handlers", "registry"]


_handlers: dict[type[Exception], Callable[[Request, Exception], Response]] = {}


def get_handlers() -> dict[type[Exception], Callable[[Request, Exception], Response]]:
    """Return the mapping of exception types to their registered handlers."""
    return _handlers


def create_response(request: Request, status_code: int, code: str, error: Exception) -> Response:
    """Build a JSON error response carrying ``code`` and the error message."""
    return Response(
        content={
            "code": code,
            "detail": str(error),
        },
        status_code=status_code,
    )


def registry(*errors: type[Exception]):
    """Register the decorated function as the handler for the given exception types.

    Raises:
        ValueError: One of the exception types already has a handler.
    """

    def decorator(fn: Callable[[Request, Exception], Response]):
        for error in errors:
            handler = _handlers.get(error)
            if handler is None:
                _handlers[error] = fn
            else:
                raise ValueError(f"'{error.__name__}' has had {handler.__name__} handler yet.")
        return fn

    return decorator
