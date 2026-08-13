class ClientError(Exception):
    """Base error for outbound service clients."""

    status_code = 502

    def __init__(self, detail: str):
        super().__init__(detail)
        self.detail = detail


class ClientNotAvailableError(ClientError):
    """Target service could not be reached (connection refused, DNS, network)."""

    status_code = 503


class ClientTimeoutError(ClientError):
    """Target service did not respond within the timeout."""

    status_code = 504


class ClientBadGatewayError(ClientError):
    """Target service responded with a 5xx status."""

    status_code = 502


class ClientValidationError(ClientError):
    """Target service rejected the request with a 4xx status."""

    status_code = 400
