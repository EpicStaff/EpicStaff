"""Handlers for this service's own domain errors."""

from foundation.schemas import ErrorDetailSchema, ErrorResponseSchema
from foundation.utils.litestar import error_handler
from litestar import Request, Response, status_codes

from manager.domain import errors


# Registered on the base classes: Litestar resolves a handler by walking the raised
# exception's MRO, so every domain error under them is covered. `ExecutionNotFoundError`
# is named too -- it stands on its own rather than under `NotFoundError`.
@error_handler.registry(errors.NotFoundError, errors.ExecutionNotFoundError)
def handle_not_found_error(
    request: Request, error: errors.NotFoundError | errors.ExecutionNotFoundError
) -> Response:
    return error_handler.create_response(
        status_code=status_codes.HTTP_404_NOT_FOUND,
        errors=[ErrorDetailSchema(code="not_found", detail=str(error))],
    )


@error_handler.registry(errors.ConflictError)
def handle_conflict_error(request: Request, error: errors.ConflictError) -> Response:
    return error_handler.create_response(
        status_code=status_codes.HTTP_409_CONFLICT,
        errors=[ErrorDetailSchema(code="conflict", detail=str(error))],
    )


@error_handler.registry(errors.BadRequestError)
def handle_bad_request_error(request: Request, error: errors.BadRequestError) -> Response:
    return error_handler.create_response(
        status_code=status_codes.HTTP_400_BAD_REQUEST,
        errors=[ErrorDetailSchema(code="bad_request", detail=str(error))],
    )


@error_handler.registry(errors.SandboxOverloadedError)
def handle_overloaded_error(request: Request, error: errors.SandboxOverloadedError) -> Response:
    # Built directly rather than through `create_response`, which takes no headers;
    # the envelope is the same one it produces.
    return Response(
        content=ErrorResponseSchema.for_status(
            status_codes.HTTP_503_SERVICE_UNAVAILABLE,
            [ErrorDetailSchema(code="overloaded", detail=str(error))],
        ),
        status_code=status_codes.HTTP_503_SERVICE_UNAVAILABLE,
        headers={"Retry-After": str(error.retry_after)},
    )
