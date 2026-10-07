"""httpx client wrappers that raise typed errors on timeout and non-2xx.

Vendored from `foundation.base.client` (copied, not imported) so crew gains the
shared client ergonomics without taking a build-time dependency on foundation --
crew's image refuses source-only packages (UV_NO_BUILD). Keep this in sync with
the foundation original on purpose; it is a small, stable surface.
"""

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
