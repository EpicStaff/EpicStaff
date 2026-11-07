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
    """Target service responded with a 5xx status, or with an error its API does not send."""


class ClientValidationError(ClientError):
    """Target service rejected the request with a 4xx status."""


class ClientRefusedError(ClientError):
    """Target service refused the caller rather than the request's content (e.g. 401, 403, 429).

    Its message is about crew's credentials, permissions or rate limit, which the user of a
    flow can't act on, so it is not shown to them.
    """
