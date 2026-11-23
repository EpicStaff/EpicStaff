"""Handlers for the chat service's own errors, registered with foundation's registry.

Importing this module registers them. Litestar's refusals, request validation and the 500
catch-all come from foundation, so every answer has the one shared error shape.
"""

from domain.errors import ChatError
from foundation.schemas import ErrorDetailSchema
from foundation.utils.litestar import error_handler
from litestar import Request, Response, status_codes
from loguru import logger

__all__ = ["handle_chat_error", "handle_recursion_error"]


@error_handler.registry(ChatError)
def handle_chat_error(request: Request, error: ChatError) -> Response:
    """Answer a domain error with its own status, code and message.

    The `field` an error names becomes `attr`; its other extras (a cap's `max`, a
    `retry_after`, a close reason, contract errors) become `context`.
    """
    if error.status_code >= 500:
        logger.error("{} {}: {}", request.method, request.url.path, error)
    context = dict(error.extra)
    attr = context.pop("field", None)
    return error_handler.create_response(
        status_code=error.status_code,
        errors=[
            ErrorDetailSchema(
                code=error.code, detail=error.message, attr=attr, context=context or None
            )
        ],
    )


@error_handler.registry(RecursionError)
def handle_recursion_error(request: Request, error: RecursionError) -> Response:
    # The JSON decoder recurses per nesting level, so a deeply nested body ends here, not in validation.
    return error_handler.create_response(
        status_code=status_codes.HTTP_400_BAD_REQUEST,
        errors=[
            ErrorDetailSchema(code="validation_error", detail="The body is nested too deeply.")
        ],
    )
