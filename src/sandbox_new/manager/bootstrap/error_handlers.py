"""Handlers for this service's own domain errors."""

from foundation.schemas import ErrorDetailSchema
from foundation.utils.litestar import error_handler
from litestar import Request, Response, status_codes

from manager.domain import errors


@error_handler.registry(errors.VenvNotFoundError)
def handle_not_found_error(request: Request, error: errors.VenvNotFoundError) -> Response:
    return error_handler.create_response(
        status_code=status_codes.HTTP_404_NOT_FOUND,
        errors=[ErrorDetailSchema(code="not_found", detail=str(error))],
    )
