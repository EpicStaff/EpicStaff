"""Handlers for the errors this service's own code raises to a client."""

from foundation.schemas import ErrorDetailSchema, ErrorResponseSchema
from foundation.utils.litestar import error_handler
from litestar import Request, Response, status_codes

from manager.application.errors import ExecutionNotFoundError, SandboxOverloadedError
from manager.domain.errors import BadRequestError, ConflictError, NotFoundError


# Registered on the base classes: Litestar resolves a handler by walking the raised
# exception's MRO, so every error under them is covered. `ExecutionNotFoundError` is
# named too -- it stands on its own rather than under `NotFoundError`.
@error_handler.registry(NotFoundError, ExecutionNotFoundError)
def handle_not_found_error(
    request: Request, error: NotFoundError | ExecutionNotFoundError
) -> Response:
    return error_handler.create_response(
        status_code=status_codes.HTTP_404_NOT_FOUND,
        errors=[ErrorDetailSchema(code=error.code, detail=str(error))],
    )


@error_handler.registry(ConflictError)
def handle_conflict_error(request: Request, error: ConflictError) -> Response:
    return error_handler.create_response(
        status_code=status_codes.HTTP_409_CONFLICT,
        errors=[ErrorDetailSchema(code=error.code, detail=str(error))],
    )


@error_handler.registry(BadRequestError)
def handle_bad_request_error(request: Request, error: BadRequestError) -> Response:
    return error_handler.create_response(
        status_code=status_codes.HTTP_400_BAD_REQUEST,
        errors=[ErrorDetailSchema(code=error.code, detail=str(error))],
    )


@error_handler.registry(SandboxOverloadedError)
def handle_overloaded_error(request: Request, error: SandboxOverloadedError) -> Response:
    # Built directly rather than through `create_response`, which takes no headers;
    # the envelope is the same one it produces.
    return Response(
        content=ErrorResponseSchema.for_status(
            status_codes.HTTP_503_SERVICE_UNAVAILABLE,
            [ErrorDetailSchema(code=error.code, detail=str(error))],
        ),
        status_code=status_codes.HTTP_503_SERVICE_UNAVAILABLE,
        headers={"Retry-After": str(error.retry_after)},
    )
