"""Shared HTTP transport for EpicStaff services."""

import httpx

from foundation.transport.http import errors

__all__ = [
    "AsyncClient",
    "Client",
]

_UNREACHABLE = "The service could not be reached."


class Client(httpx.Client):
    """Synchronous httpx client that raises typed `ClientError`s on failure."""

    def request(self, method: str, url: httpx.URL | str, **kwargs) -> httpx.Response:
        """Send a request and return the response, raising on a failure to get a 2xx.

        Raises:
            ClientTimeoutError: The request timed out before a response arrived.
            ClientConnectionError: The service could not be reached at all.
            ClientHTTPStatusError: The response status was non-2xx; the concrete
                subclass matches the status code (see `ERROR_BY_STATUS`).
        """
        try:
            response = super().request(method, url, **kwargs)
            response.raise_for_status()
            return response
        except httpx.TimeoutException as e:
            raise errors.ClientTimeoutError from e
        except httpx.RequestError as e:
            raise errors.ClientConnectionError(_UNREACHABLE) from e
        except httpx.HTTPStatusError as e:
            response = e.response
            error_type = errors.ERROR_BY_STATUS.get(
                response.status_code, errors.ClientHTTPStatusError
            )
            raise error_type(response.text, response=response) from e


class AsyncClient(httpx.AsyncClient):
    """Asynchronous counterpart of `Client` with the same error translation."""

    async def request(self, method: str, url: httpx.URL | str, **kwargs) -> httpx.Response:
        """Send a request and return the response, raising on a failure to get a 2xx.

        Raises:
            ClientTimeoutError: The request timed out before a response arrived.
            ClientConnectionError: The service could not be reached at all.
            ClientHTTPStatusError: The response status was non-2xx; the concrete
                subclass matches the status code (see `ERROR_BY_STATUS`).
        """
        try:
            response = await super().request(method, url, **kwargs)
            response.raise_for_status()
            return response
        except httpx.TimeoutException as e:
            raise errors.ClientTimeoutError from e
        except httpx.RequestError as e:
            raise errors.ClientConnectionError(_UNREACHABLE) from e
        except httpx.HTTPStatusError as e:
            response = e.response
            error_type = errors.ERROR_BY_STATUS.get(
                response.status_code, errors.ClientHTTPStatusError
            )
            raise error_type(response.text, response=response) from e
