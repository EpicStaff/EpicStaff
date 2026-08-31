class ClientError(Exception):
    """Base error for outbound service clients."""

    def __init__(self, detail: str):
        super().__init__(detail)
        self.detail = detail


class ClientNotAvailableError(ClientError):
    """Target service could not be reached (connection refused, DNS, network)."""


class ClientTimeoutError(ClientError):
    """Target service did not respond within the timeout."""


class ClientBadGatewayError(ClientError):
    """Target service responded with a 5xx status."""


class ClientValidationError(ClientError):
    """Target service rejected the request with a 4xx status."""
