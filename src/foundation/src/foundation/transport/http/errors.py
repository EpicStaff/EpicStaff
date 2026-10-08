import httpx

__all__ = [
    "ERROR_BY_STATUS",
    "ClientBadGatewayError",
    "ClientConflictError",
    "ClientError",
    "ClientForbiddenError",
    "ClientGatewayTimeoutError",
    "ClientHTTPStatusError",
    "ClientMethodNotAllowedError",
    "ClientNotFoundError",
    "ClientNotImplementedError",
    "ClientRateLimitError",
    "ClientServerError",
    "ClientTimeoutError",
    "ClientUnauthorizedError",
    "ClientUnavailableError",
    "ClientValidationError",
]


class ClientError(Exception):
    """Base class for every error raised by this transport."""


class ClientTimeoutError(ClientError):
    """Raised when the request times out before a response arrives."""


class ClientHTTPStatusError(ClientError):
    """Raised for a non-2xx response; carries the offending `httpx.Response`.

    Concrete subclasses map to specific status codes via `http_status_errors`;
    catch this base to handle any HTTP status failure regardless of code.
    """

    def __init__(self, message: str, *, response: httpx.Response):
        self.response = response
        super().__init__(message)


class ClientValidationError(ClientHTTPStatusError):
    pass


class ClientUnauthorizedError(ClientHTTPStatusError):
    pass


class ClientForbiddenError(ClientHTTPStatusError):
    pass


class ClientNotFoundError(ClientHTTPStatusError):
    pass


class ClientMethodNotAllowedError(ClientHTTPStatusError):
    pass


class ClientConflictError(ClientHTTPStatusError):
    pass


class ClientRateLimitError(ClientHTTPStatusError):
    pass


class ClientServerError(ClientHTTPStatusError):
    pass


class ClientNotImplementedError(ClientHTTPStatusError):
    pass


class ClientBadGatewayError(ClientHTTPStatusError):
    pass


class ClientUnavailableError(ClientHTTPStatusError):
    pass


class ClientGatewayTimeoutError(ClientHTTPStatusError):
    pass


ERROR_BY_STATUS: dict[int, type[ClientHTTPStatusError]] = {
    400: ClientValidationError,
    401: ClientUnauthorizedError,
    403: ClientForbiddenError,
    404: ClientNotFoundError,
    405: ClientMethodNotAllowedError,
    409: ClientConflictError,
    422: ClientValidationError,
    429: ClientRateLimitError,
    500: ClientServerError,
    501: ClientNotImplementedError,
    502: ClientBadGatewayError,
    503: ClientUnavailableError,
    504: ClientGatewayTimeoutError,
}
