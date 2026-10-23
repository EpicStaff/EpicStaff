"""Handlers for this service's own domain errors."""

from foundation.schemas import ErrorDetailSchema
from foundation.utils.litestar import error_handler
from litestar import Request, Response, status_codes

from manager.domain import errors


@error_handler.registry(errors.VenvNotFoundError, errors.ExecutionNotFoundError)
def handle_not_found_error(
    request: Request, error: errors.VenvNotFoundError | errors.ExecutionNotFoundError
) -> Response:
    return error_handler.create_response(
        status_code=status_codes.HTTP_404_NOT_FOUND,
        errors=[ErrorDetailSchema(code="not_found", detail=str(error))],
    )


@error_handler.registry(errors.SandboxOverloadedError)
def handle_overloaded_error(request: Request, error: errors.SandboxOverloadedError) -> Response:
    return error_handler.create_response(
        status_code=status_codes.HTTP_503_SERVICE_UNAVAILABLE,
        errors=[ErrorDetailSchema(code="overloaded", detail=str(error))],
        headers={"Retry-After": str(error.retry_after)},
    )
