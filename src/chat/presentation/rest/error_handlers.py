from collections.abc import Callable

from domain.errors import ChatError
from litestar import Request, Response, status_codes
from litestar.exceptions import HTTPException
from loguru import logger

__all__ = ["get_error_handlers"]


def handle_chat_error(request: Request, error: ChatError) -> Response:
    if error.status_code >= 500:
        logger.error("{} {}: {}", request.method, request.url.path, error)
    return Response(
        content={"code": error.code, "message": error.message, **error.extra},
        status_code=error.status_code,
    )


def handle_http_exception(request: Request, error: HTTPException) -> Response:
    # Litestar's own 4xx (validation, unknown route, bad method) in the public `{code, message}` shape.
    code = (
        "validation_error"
        if error.status_code == status_codes.HTTP_400_BAD_REQUEST
        else "http_error"
    )
    return Response(
        content={
            "code": code,
            "message": error.detail,
            **({"errors": error.extra} if error.extra else {}),
        },
        status_code=error.status_code,
    )


def handle_recursion_error(request: Request, error: RecursionError) -> Response:
    # The JSON decoder recurses per nesting level, so a deeply nested body ends here, not in validation.
    return Response(
        content={"code": "validation_error", "message": "The body is nested too deeply."},
        status_code=status_codes.HTTP_400_BAD_REQUEST,
    )


def handle_unexpected(request: Request, error: Exception) -> Response:
    logger.exception("Unhandled error on {} {}", request.method, request.url.path)
    return Response(
        content={"code": "internal_error", "message": "Internal error."},
        status_code=status_codes.HTTP_500_INTERNAL_SERVER_ERROR,
    )


def get_error_handlers() -> dict[type[Exception], Callable]:
    # Litestar picks the most specific class, so the catch-all only sees what the others do not.
    return {
        ChatError: handle_chat_error,
        HTTPException: handle_http_exception,
        RecursionError: handle_recursion_error,
        Exception: handle_unexpected,
    }
