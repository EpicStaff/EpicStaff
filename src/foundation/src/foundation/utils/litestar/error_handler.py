"""Map exception types to Litestar responses via ``@registry``, in one error shape.

Importing this module registers the handlers every Litestar service needs regardless of
what it does: a payload that fails model validation, and the catch-all that turns
anything unhandled into a 500. A service adds handlers for its own domain errors and
nothing else.

They are prefixed ``foundation_`` so that a service writing `handle_not_found` of its
own cannot shadow one by accident, and so that the duplicate-registration error names
which of the two it already had.
"""

from collections.abc import Callable

import pydantic
from litestar import Request, Response, status_codes

from foundation.schemas import ErrorDetailSchema, ErrorResponseSchema

__all__ = [
    "create_response",
    "foundation_handle_payload_validation_error",
    "foundation_handle_server_error",
    "get_handlers",
    "registry",
]


_handlers: dict[type[Exception], Callable[[Request, Exception], Response]] = {}


def get_handlers() -> dict[type[Exception], Callable[[Request, Exception], Response]]:
    """Return the mapping of exception types to their registered handlers."""
    return _handlers


def create_response(
    status_code: int, errors: list[ErrorDetailSchema]
) -> Response[ErrorResponseSchema]:
    """Wrap the shared error envelope in a Litestar response."""
    return Response(
        content=ErrorResponseSchema.for_status(status_code, errors),
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


@registry(pydantic.ValidationError)
def foundation_handle_payload_validation_error(
    request: Request, error: pydantic.ValidationError
) -> Response:
    """A payload that parsed but broke an invariant of the model it was turned into.

    `loc` is empty for a rule that spans fields, which leaves `attr` null -- the error
    belongs to the model, not to any one of its fields.
    """
    return create_response(
        status_code=status_codes.HTTP_400_BAD_REQUEST,
        errors=[
            ErrorDetailSchema(
                code=entry["type"],
                detail=entry["msg"],
                attr=".".join(str(part) for part in entry["loc"]) or None,
            )
            for entry in error.errors()
        ],
    )


@registry(Exception)
def foundation_handle_server_error(request: Request, error: Exception) -> Response:
    """Anything no other handler claimed. Registered last so it stays the fallback."""
    return create_response(
        status_code=status_codes.HTTP_500_INTERNAL_SERVER_ERROR,
        errors=[ErrorDetailSchema(code="unknown", detail=str(error))],
    )
