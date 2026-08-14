from collections.abc import Callable

from domain.errors import (
    DocumentNotFoundError,
    EmbeddingConfigNotFoundError,
    GraphRagConfigNotFoundError,
    KnowledgeError,
    RagNotFoundError,
    UnsupportedError, NotRunningOperationError,
)
from litestar import Request, Response, status_codes
from loguru import logger

__all__ = ["get_error_handlers"]


_error_handlers: dict[type[Exception], Callable[[Request, Exception], Response]] = {}


def get_error_handlers() -> dict[type[Exception], Callable[[Request, Exception], Response]]:
    return _error_handlers


def create_response(request: Request, status_code: int, code: str, error: Exception) -> Response:
    return Response(
        content={
            "code": code,
            "detail": str(error),
        },
        status_code=status_code,
    )


def registry(*errors: type[Exception]):
    def decorator(fn: Callable[[Request, Exception], Response]):
        for error in errors:
            handler = _error_handlers.get(error)
            if handler is None:
                _error_handlers[error] = fn
            else:
                raise ValueError(f"'{error.__name__}' has had {handler.__name__} handler yet.")
        return fn

    return decorator


@registry(
    RagNotFoundError,
    DocumentNotFoundError,
    EmbeddingConfigNotFoundError,
    GraphRagConfigNotFoundError,
    NotRunningOperationError,
)
def handler_not_found(request: Request, error: Exception) -> Response:
    return create_response(request, status_codes.HTTP_404_NOT_FOUND, "not_found", error)


@registry(UnsupportedError)
def handler_unsupported(request, error: Exception) -> Response:
    return create_response(request, status_codes.HTTP_400_BAD_REQUEST, "unsupported", error)


@registry(KnowledgeError)
def handle_server_error(request, error: Exception) -> Response:
    logger.exception("Unhandled domain error: {}", error)
    return create_response(
        request, status_codes.HTTP_500_INTERNAL_SERVER_ERROR, "internal_error", error
    )
