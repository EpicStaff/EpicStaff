"""httpx client wrapper that raises typed errors on timeout and non-2xx.

Vendored from `foundation.base.client` (copied, not imported) so agent gains the
shared client ergonomics without a build-time dependency on foundation. Keep in
sync with the foundation original.
"""

from functools import wraps

import httpx


class ClientError(Exception):
    pass


class ClientTimeoutError(ClientError):
    pass


class ClientHTTPStatusError(ClientError):
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


class ClientConflictError(ClientHTTPStatusError):
    pass


class ClientRateLimitError(ClientHTTPStatusError):
    pass


http_status_errors: dict[int, type[ClientHTTPStatusError]] = {
    400: ClientValidationError,
    401: ClientUnauthorizedError,
    403: ClientForbiddenError,
    404: ClientNotFoundError,
    409: ClientConflictError,
    422: ClientValidationError,
    429: ClientRateLimitError,
}


class AsyncClient(httpx.AsyncClient):
    @wraps(httpx.AsyncClient.request)
    async def request(self, method: str, url: httpx.URL | str, **kwargs) -> httpx.Response:
        try:
            response = await super().request(method, url, **kwargs)
            response.raise_for_status()
            return response
        except httpx.TimeoutException as e:
            raise ClientTimeoutError from e
        except httpx.HTTPStatusError as e:
            response = e.response
            error_type = http_status_errors.get(response.status_code, ClientHTTPStatusError)
            raise error_type(response.text, response=response) from e
