import pydantic
from foundation.utils.litestar import error_handler
from litestar import Request, Response, status_codes

from manager.domain import errors


@error_handler.registry(pydantic.ValidationError)
def handle_validation_error(request: Request, error: Exception) -> Response:
    return error_handler.create_response(
        request=request,
        status_code=status_codes.HTTP_400_BAD_REQUEST,
        code="invalid_data",
        error=error,
    )


@error_handler.registry(errors.VenvNotFoundError)
def handle_not_found_error(request: Request, error: Exception) -> Response:
    return error_handler.create_response(
        request=request,
        status_code=status_codes.HTTP_404_NOT_FOUND,
        code="not_found",
        error=error,
    )


@error_handler.registry(Exception)
def handle_server_error(request: Request, error: Exception) -> Response:
    return error_handler.create_response(
        request=request,
        status_code=status_codes.HTTP_500_INTERNAL_SERVER_ERROR,
        code="server",
        error=error,
    )
