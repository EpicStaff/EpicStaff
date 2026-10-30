class ClientError(Exception):
    """Base error for outbound service clients."""

    status_code = 502
    # What an API client is told. `detail` can hold the upstream response
    # body, which describes the upstream service, not the caller's request.
    public_detail = "An upstream service failed to handle the request."
    code = "upstream_service_error"

    def __init__(self, detail: str):
        super().__init__(detail)
        self.detail = detail


class ClientNotAvailableError(ClientError):
    """Target service could not be reached (connection refused, DNS, network)."""

    status_code = 503
    public_detail = "An upstream service is unreachable."
    code = "upstream_service_unreachable"


class ClientTimeoutError(ClientError):
    """Target service did not respond within the timeout."""

    status_code = 504
    public_detail = "An upstream service timed out."
    code = "upstream_service_timeout"


class ClientBadGatewayError(ClientError):
    """Target service responded with a 5xx status."""

    status_code = 502


class ClientValidationError(ClientError):
    """Target service rejected the request with a 4xx status."""

    status_code = 400
    public_detail = "An upstream service rejected the request."
    code = "upstream_service_rejected"


class ClientResourceNotFoundError(ClientError):
    """Target service responded 404 — the referenced resource or operation does not exist."""

    status_code = 404
    public_detail = "The upstream resource was not found."
    code = "upstream_resource_not_found"
